from .geometry import overlap, part_ref
from .intervals import measure


def inspection_origin(model, inspections):
    cuts = {cut['id']: cut for cut in model['cuts']}
    result = []
    for row in inspections:
        cut = cuts[row['child']]
        width = cut['b'] - cut['a']
        a, b = (row['x0'], row['x1']) if cut['winding'] == 'forward' else (width-row['x1'], width-row['x0'])
        y0, y1 = (row['y0'], row['y1']) if cut['winding'] == 'forward' else (model['length']-row['y1'], model['length']-row['y0'])
        rect = dict(x0=cut['a']+a, x1=cut['a']+b, y0=y0, y1=y1)
        hit, parts = [], []
        for d in model['defects']:
            ns = [n for n, p in enumerate(d['parts'], 1) if overlap(p, rect)]
            if ns:
                hit.append(d['id'])
                parts += [part_ref(d, n) for n in ns if len(d['parts']) > 1]
        origin = dict(id=row['id'], **rect, child=row['child'], state=row['state'], evidence=hit)
        if parts:
            origin['parts'] = parts
        result.append(origin)
    return result


def shared_origins(model, transfer, scrap):
    result = []
    for defect in model['defects']:
        transfers = [r for r in transfer if r['evidence'] == defect['id']]
        waste = [r for r in scrap if defect['id'] in r['evidence']]
        span = measure([(p['x0'], p['x1']) for p in defect['parts']])
        kept = measure([(max(p['x0'], cut['a']), min(p['x1'], cut['b']))
                        for p in defect['parts'] for cut in model['cuts']
                        if max(p['x0'], cut['a']) < min(p['x1'], cut['b'])])
        bands = {r['child'] for r in transfers} | {r['id'] for r in waste}
        state = 'split' if len(bands) > 1 else 'kept' if transfers else 'scrap'
        result.append(dict(id=defect['id'], width=span, kept=kept, lost=span-kept, state=state,
                           evidence={'transfer': [r['id'] for r in transfers], 'scrap': [r['id'] for r in waste]}))
    return result
