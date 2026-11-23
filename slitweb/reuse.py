from .contract import ContractError, invariant, num
from .geometry import union_area


def clip(rect, a, b, y0, y1):
    x0, x1 = max(rect['x0'], a), min(rect['x1'], b)
    lo, hi = max(rect['y0'], y0), min(rect['y1'], y1)
    if x0 >= x1 or lo >= hi:
        return None
    return dict(x0=x0, x1=x1, y0=lo, y1=hi)


def snap(value, tolerance):
    return 0 if abs(value) <= tolerance else value


def band_row(band, origins, y0, y1):
    a, b = band['start'], band['end']
    target = (b - a) * (y1 - y0)
    clips = [dict(piece, state=rect['state'], id=rect['id'])
             for rect in origins if (piece := clip(rect, a, b, y0, y1)) is not None]
    clear = union_area([piece for piece in clips if piece['state'] == 'clear'])
    marked = union_area([piece for piece in clips if piece['state'] == 'marked'])
    both = union_area(clips)
    tolerance = max(target, 1.0) * 1e-9
    conflict = snap(clear + marked - both, tolerance)
    lacking = snap(target - both, tolerance)
    clean = snap(both - marked, tolerance)
    flagged = snap(both - clear, tolerance)
    if conflict:
        state = 'conflict'
    elif not clips:
        state = 'blind'
    elif lacking:
        state = 'partial'
    else:
        state = 'covered'
    return dict(id=band['id'], winding=band['state'], clean=clean, marked=flagged,
                conflict=conflict, lacking=lacking, target=target, state=state,
                evidence=sorted({piece['id'] for piece in clips}))


def transfer_reuse(left, right, body):
    if left['subject'] != right['subject']:
        raise ContractError('两份成果不属于同一母卷，不能转用试算', 409)
    if left['schema'] != right['schema']:
        raise ContractError('两份成果的口径版本不一致', 409)
    old, new = left['source'], right['source']
    if old['width'] != new['width'] or old['length'] != new['length']:
        raise ContractError('两份成果的母卷幅面不一致，不能转用试算', 409)
    length = new['length']
    y0 = num(body.get('start'), '目标段起点', 0, length)
    y1 = num(body.get('end'), '目标段终点', 0, length)
    invariant(y0 < y1, '目标段终点必须大于起点')
    origins = left['outputs'].get('origin', [])
    layout = right['outputs']['layout']
    rows = [band_row(band, origins, y0, y1) for band in layout]
    return dict(subject=left['subject'], left=left['digest'], right=right['digest'],
                segment=[y0, y1], rows=rows)
