from .contract import enum, ident, interval, invariant, records
from .geometry import overlap, union_area


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
        row = dict(id=defect['id'], area=area, total=total, grade=defect['state'],
                   state='marked' if marked else 'clear' if abs(area-total) <= total*1e-12 else 'partial' if rows else 'blind',
                   evidence={'origin': defect['evidence'], 'inspections': [r['id'] for r in rows]})
        if 'part' in defect:
            row['part'] = defect['part']
        result.append(row)
    return result
