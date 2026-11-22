from .geometry import overlap


def inspection_origin(model, inspections):
    cuts = {cut['id']: cut for cut in model['cuts']}
    result = []
    for row in inspections:
        cut = cuts[row['child']]
        width = cut['b'] - cut['a']
        a, b = (row['x0'], row['x1']) if cut['winding'] == 'forward' else (width-row['x1'], width-row['x0'])
        y0, y1 = (row['y0'], row['y1']) if cut['winding'] == 'forward' else (model['length']-row['y1'], model['length']-row['y0'])
        rect = dict(x0=cut['a']+a, x1=cut['a']+b, y0=y0, y1=y1)
        hit = [r['id'] for r in model['defects'] if overlap(r, rect)]
        result.append(dict(id=row['id'], **rect, child=row['child'], state=row['state'], evidence=hit))
    return result


def shared_origins(model, transfer, scrap):
    result = []
    for defect in model['defects']:
        transfers = [r for r in transfer if r['evidence'] == defect['id']]
        waste = [r for r in scrap if defect['id'] in r['evidence']]
        kept = sum(r['x1'] - r['x0'] for r in transfers)
        span = defect['x1'] - defect['x0']
        result.append(dict(id=defect['id'], width=span, kept=kept, lost=span-kept,
                           state='split' if len(transfers) + len(waste) > 1 else 'kept' if transfers else 'scrap',
                           evidence={'transfer': [r['id'] for r in transfers], 'scrap': [r['id'] for r in waste]}))
    return result
