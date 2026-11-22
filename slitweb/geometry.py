from .intervals import union


def map_defect(defect, cut, length):
    x0,x1 = max(defect['x0'],cut['a']), min(defect['x1'],cut['b'])
    if x0 >= x1:
        return None
    y0,y1 = defect['y0'], defect['y1']
    if cut['winding'] == 'reverse':
        x0,x1 = cut['b']-x1, cut['b']-x0
        y0,y1 = length-y1,length-y0
    else:
        x0,x1 = x0-cut['a'],x1-cut['a']
    return dict(id=f"{cut['id']}/{defect['id']}", child=cut['id'], evidence=defect['id'],
                x0=x0,x1=x1,y0=y0,y1=y1,state=defect['grade'])


def overlap(first, second):
    return (max(first['x0'], second['x0']) < min(first['x1'], second['x1']) and
            max(first['y0'], second['y0']) < min(first['y1'], second['y1']))


def union_area(rectangles):
    edges = sorted({r[key] for r in rectangles for key in ('x0', 'x1')})
    return sum((b - a) * sum(d - c for c, d in union([
        (r['y0'], r['y1']) for r in rectangles if r['x0'] <= a and b <= r['x1']
    ])) for a, b in zip(edges, edges[1:]))
