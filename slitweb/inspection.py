from .contract import enum, ident, interval, invariant, records
from .geometry import overlap, union_area
from .intervals import gaps, union


def read_inspections(review, model):
    cuts = {cut['id']: cut for cut in model['cuts']}
    result = []
    for row in records(review.get('inspections', []), '幅面复检', 64):
        child = ident(row.get('child'), '子卷')
        invariant(child in cuts, '幅面复检引用未知子卷')
        cut = cuts[child]
        x0, x1 = interval(row.get('x0'), row.get('x1'), '子卷横幅', cut['b'] - cut['a'])
        y0, y1 = interval(row.get('y0'), row.get('y1'), '子卷长度', model['length'])
        result.append(dict(id=row['id'], child=child, x0=x0, x1=x1, y0=y0, y1=y1,
                           state=enum(row.get('result'), ('clear', 'marked'), '复检结论')))
    return result


def face_coverage(model, inspections, coverage):
    result = []
    covered_length = {r['id']: r['observed'] for r in coverage}
    for cut in model['cuts']:
        child = cut['id']
        rows = [r for r in inspections if r['child'] == child]
        area = union_area(rows)
        total = (cut['b'] - cut['a']) * model['length']
        result.append(dict(id=child, area=area, total=total, observed=covered_length[child],
                           state='covered' if abs(area-total) <= total*1e-12 else 'partial' if rows else 'blind',
                           evidence=[r['id'] for r in rows]))
    return result


def defect_review(inspections, transfer):
    result = []
    for defect in transfer:
        rows = [r for r in inspections if r['child'] == defect['child'] and overlap(r, defect)]
        clips = [{key: f(r[key], defect[key]) for key, f in
                  [('x0', max), ('x1', min), ('y0', max), ('y1', min)]} for r in rows]
        area = union_area(clips)
        total = (defect['x1'] - defect['x0']) * (defect['y1'] - defect['y0'])
        marked = any(r['state'] == 'marked' for r in rows)
        result.append(dict(id=defect['id'], area=area, total=total, grade=defect['state'],
                           state='marked' if marked else 'clear' if abs(area-total) <= total*1e-12 else 'partial' if rows else 'blind',
                           evidence={'origin': defect['evidence'], 'inspections': [r['id'] for r in rows]}))
    return result


def fullwidth_segments(model, inspections, transfer):
    result = []
    length, margin = model['length'], model['margin']
    for cut in model['cuts']:
        child = cut['id']
        width = cut['b'] - cut['a']
        rows = [r for r in inspections if r['child'] == child]
        reserved = [(max(0, r['y0']-margin), min(length, r['y1']+margin), r['evidence'])
                    for r in transfer if r['child'] == child and r['state'] == 'major']
        bounds = sorted({0, length} | {y for r in rows for y in (r['y0'], r['y1'])}
                        | {y for a, b, _ in reserved for y in (a, b)})
        merged = []
        for a, b in zip(bounds, bounds[1:]):
            covered = union([(r['x0'], r['x1']) for r in rows if r['y0'] <= a and b <= r['y1']])
            uncovered = gaps(covered, width)
            sources = sorted({key for lo, hi, key in reserved if lo <= a < hi})
            state = ('mixed' if uncovered and sources else 'blocked' if sources
                     else 'blind' if uncovered else 'eligible')
            if merged and merged[-1]['state'] == state and merged[-1]['evidence'] == sources \
                    and merged[-1]['uncovered'] == uncovered:
                merged[-1].update(end=b, length=b-merged[-1]['start'])
            else:
                merged.append(dict(child=child, start=a, end=b, length=b-a, state=state,
                                   uncovered=uncovered, evidence=sources))
        result.extend(dict(id=f'{child}/{n}', **row) for n, row in enumerate(merged, 1))
    return result
