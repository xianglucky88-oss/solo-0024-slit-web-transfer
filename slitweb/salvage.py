from math import floor, isclose

from .contract import ident, invariant, num, records
from .intervals import union


def read_orders(review, model):
    cuts = {r['id'] for r in model['cuts']}
    orders = []
    for row in records(review.get('orders', []), '短卷规格', 36):
        child = ident(row.get('child'), '子卷')
        invariant(child in cuts, '短卷规格引用未知子卷')
        orders.append(dict(id=row['id'], child=child,
                           length=num(row.get('length'), '定尺长度', 0.001, model['length']),
                           allowance=num(row.get('allowance'), '切口留量', 0, model['length'])))
    return orders


def reusable_runs(model, exclusion):
    result = []
    for cut in model['cuts']:
        child = cut['id']
        safe = [r for r in exclusion if r['child'] == child and r['state'] == 'eligible']
        for a, b in union([(r['start'], r['end']) for r in safe]):
            length = model['length']
            origin = [a, b] if cut['winding'] == 'forward' else [length-b, length-a]
            evidence = [r['id'] for r in safe if a <= r['start'] < b]
            result.append(dict(id=evidence[0], child=child, start=a, end=b, length=b-a,
                               state='eligible', origin=origin, evidence=evidence))
    return result


def fit_count(span, length, allowance):
    quotient = (span + allowance) / (length + allowance)
    nearest = round(quotient)
    return nearest if isclose(quotient, nearest, rel_tol=0, abs_tol=1e-12) else floor(quotient)


def order_yield(orders, runs):
    result = []
    for order in orders:
        length, allowance = order['length'], order['allowance']
        candidates = [r for r in runs if r['child'] == order['child']]
        counts = [(r, fit_count(r['length'], length, allowance)) for r in candidates]
        n = sum(count for _, count in counts)
        occupied = sum(count * length + max(0, count-1) * allowance for _, count in counts)
        result.append(dict(id=order['id'], child=order['child'], count=n, length=length, used=occupied,
                           remainder=max(0, sum(r['length'] for r in candidates)-occupied),
                           state='fits' if n else 'blocked',
                           evidence={r['id']: count for r, count in counts}))
    return result


def length_losses(model, exclusion):
    result = []
    for cut in model['cuts']:
        child = cut['id']
        rows = [r for r in exclusion if r['child'] == child]
        totals = {state: sum(r['length'] for r in rows if r['state'] == state)
                  for state in ('eligible', 'blocked', 'blind', 'mixed')}
        result.append(dict(id=child, **totals, state='blocked' if totals['eligible'] == 0 else 'partial' if
                           totals['eligible'] < model['length'] else 'covered',
                           evidence={r['id']: r['state'] for r in rows}))
    return result
