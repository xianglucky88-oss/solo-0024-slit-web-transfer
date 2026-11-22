from functools import lru_cache
from math import inf, isclose

from .contract import ident, invariant, num, records
from .salvage import fit_count

EPS = 1e-9
STATE_LIMIT = 262144
RUN_LIMIT = 256
BRUTE_LIMIT = 2000000


def read_batch_orders(review, model):
    cuts = {row['id'] for row in model['cuts']}
    orders = []
    for row in records(review.get('batch_orders', []), '联合配料单', 36):
        children = row.get('children')
        invariant(isinstance(children, list) and 1 <= len(children) <= 36, '允许子卷应为 1 至 36 条')
        seen = set()
        for child in children:
            ident(child, '子卷')
            invariant(child in cuts, '联合配料引用未知子卷')
            invariant(child not in seen, '允许子卷存在重复')
            seen.add(child)
        demand, priority = row.get('demand'), row.get('priority')
        invariant(type(demand) is int and demand >= 1, '需求量应为正整数')
        invariant(type(priority) is int and priority >= 1, '优先级档应为正整数，1 为最高档')
        orders.append(dict(id=row['id'], children=list(children),
                           length=num(row.get('length'), '件长', 0.001, model['length']),
                           allowance=num(row.get('allowance'), '每刀余量', 0, model['length']),
                           demand=demand, priority=priority))
    return orders


def standalone_quote(order, runs):
    return sum(fit_count(run['length'], order['length'], order['allowance'])
               for run in runs if run['child'] in order['children'])


def load_options(segment, orders, caps):
    allowed = [i for i, order in enumerate(orders) if segment['child'] in order['children']]
    options, counts = [], [0] * len(orders)

    def visit(slot, stretch, lowest):
        if slot == len(allowed):
            used = stretch - lowest if stretch else 0.0
            options.append((tuple(counts), round(segment['length'] - used, 9)))
            return
        index = allowed[slot]
        order = orders[index]
        top = min(caps[index], fit_count(segment['length'], order['length'], order['allowance']))
        for n in range(top + 1):
            total = stretch + n * (order['length'] + order['allowance'])
            floor = min(lowest, order['allowance']) if n else lowest
            if total - (floor if total else 0.0) > segment['length'] + EPS:
                break
            counts[index] = n
            visit(slot + 1, total, floor)
        counts[index] = 0

    visit(0, 0.0, inf)
    return options


def joint_layout(orders, runs):
    invariant(len(runs) <= RUN_LIMIT, '联合配料规模超出本机核算上限')
    tiers = sorted({order['priority'] for order in orders})
    rank = {tier: key for key, tier in enumerate(tiers)}
    caps = [min(order['demand'], standalone_quote(order, runs)) for order in orders]
    space = 1
    for cap in caps:
        space *= cap + 1
    invariant(space <= STATE_LIMIT, '联合配料规模超出本机核算上限')
    options = [load_options(run, orders, caps) for run in runs]

    def tier_row(counts):
        return tuple(sum(n for i, n in enumerate(counts) if rank[orders[i]['priority']] == key)
                     for key in range(len(tiers)))

    scored = [[(counts, remnant, tier_row(counts)) for counts, remnant in slot] for slot in options]
    choice = {}

    @lru_cache(maxsize=None)
    def best(slot, remaining):
        if slot == len(runs):
            return tuple(0 for _ in tiers), ()
        top = None
        for counts, remnant, gained in scored[slot]:
            if any(n > left for n, left in zip(counts, remaining)):
                continue
            rest = tuple(left - n for n, left in zip(counts, remaining))
            sub_tiers, sub_remnants = best(slot + 1, rest)
            value = (tuple(a + b for a, b in zip(gained, sub_tiers)),
                     tuple(sorted(sub_remnants + (remnant,), reverse=True)))
            if top is None or value > top[0]:
                top = value, counts
        choice[slot, remaining] = top[1]
        return top[0]

    remaining = tuple(caps)
    best(0, remaining)
    loads = []
    for slot in range(len(runs)):
        counts = choice[slot, remaining]
        loads.append(counts)
        remaining = tuple(left - n for n, left in zip(counts, remaining))
    return loads


def place_pieces(orders, runs, loads, model):
    cuts = {row['id']: row for row in model['cuts']}
    rows, sequences = [], {}

    def coordinates(cut, start, end):
        origin = [start, end] if cut['winding'] == 'forward' else [model['length'] - end, model['length'] - start]
        return origin, [cut['a'], cut['b']]

    for run, counts in zip(runs, loads):
        cut = cuts[run['child']]
        pieces = sorted((i for i, n in enumerate(counts) for _ in range(n)),
                        key=lambda i: (-orders[i]['allowance'], orders[i]['id']))
        cursor = run['start']
        for slot, index in enumerate(pieces):
            order = orders[index]
            sequences[order['id']] = sequences.get(order['id'], 0) + 1
            start, end = cursor, cursor + order['length']
            origin, span = coordinates(cut, start, end)
            rows.append(dict(id=f"{order['id']}/{sequences[order['id']]}", child=run['child'],
                             start=start, end=end, length=order['length'], origin=origin, span=span,
                             segment=run['id'], state='cut', evidence=[run['id'], order['id']]))
            cursor = end + (order['allowance'] if slot + 1 < len(pieces) else 0)
        if run['end'] - cursor > EPS:
            origin, span = coordinates(cut, cursor, run['end'])
            rows.append(dict(id=f"{run['id']}/余料", child=run['child'], start=cursor, end=run['end'],
                             length=run['end'] - cursor, origin=origin, span=span,
                             segment=run['id'], state='remnant', evidence=[run['id']]))
    return rows


def batch_plan(orders, runs, model):
    if not orders:
        return [], []
    loads = joint_layout(orders, runs)
    cuts = place_pieces(orders, runs, loads, model)
    made = {order['id']: 0 for order in orders}
    evidence = {order['id']: {} for order in orders}
    for run, counts in zip(runs, loads):
        for index, n in enumerate(counts):
            if n:
                order = orders[index]
                made[order['id']] += n
                evidence[order['id']][run['id']] = n
    rows = []
    for order in sorted(orders, key=lambda item: (item['priority'], item['id'])):
        count = made[order['id']]
        rows.append(dict(id=order['id'], children=order['children'], priority=order['priority'],
                         demand=order['demand'], quoted=standalone_quote(order, runs), count=count,
                         shortage=order['demand'] - count,
                         state='met' if count == order['demand'] else 'blocked' if count == 0 else 'short',
                         evidence=evidence[order['id']]))
    return rows, cuts


def exhaustive(orders, runs, limit=BRUTE_LIMIT):
    tiers = sorted({order['priority'] for order in orders})
    rank = {tier: key for key, tier in enumerate(tiers)}
    caps = [min(order['demand'], standalone_quote(order, runs)) for order in orders]
    options = [load_options(run, orders, caps) for run in runs]
    total = 1
    for slot in options:
        total *= len(slot)
    if total > limit:
        return None

    def tier_row(counts):
        return tuple(sum(n for i, n in enumerate(counts) if rank[orders[i]['priority']] == key)
                     for key in range(len(tiers)))

    def visit(slot, remaining, gained, remnants, sink):
        if slot == len(runs):
            sink((gained, tuple(sorted(remnants, reverse=True))))
            return
        for counts, remnant in options[slot]:
            if any(n > left for n, left in zip(counts, remaining)):
                continue
            visit(slot + 1, tuple(left - n for n, left in zip(counts, remaining)),
                  tuple(a + b for a, b in zip(gained, tier_row(counts))), remnants + (remnant,), sink)

    best = None

    def keep(value):
        nonlocal best
        if best is None or value > best:
            best = value

    start = tuple(caps)
    visit(0, start, tuple(0 for _ in tiers), (), keep)
    longest = set()

    def scan(value):
        if value[0] == best[0]:
            longest.add(max(value[1]) if value[1] else 0)

    visit(0, start, tuple(0 for _ in tiers), (), scan)
    return dict(tiers=best[0], remnants=best[1], longest=longest)


def verify(orders, runs, model, batch_rows, cut_rows):
    problems = []
    by_id = {order['id']: order for order in orders}
    run_by_id = {run['id']: run for run in runs}
    pieces = {run['id']: [] for run in runs}
    remnants = {run['id']: [] for run in runs}
    for row in cut_rows:
        run = run_by_id.get(row.get('segment'))
        if run is None or run['child'] != row.get('child'):
            problems.append(f"{row.get('id')}：可保段回查失败")
            continue
        target = remnants if row.get('state') == 'remnant' else pieces
        target[run['id']].append(row)
    made = {order['id']: 0 for order in orders}
    evidence = {order['id']: {} for order in orders}
    for run in runs:
        rows = sorted(pieces[run['id']], key=lambda row: row['start'])
        previous = None
        for row in rows:
            order = by_id.get(row['id'].rsplit('/', 1)[0])
            if order is None or run['child'] not in order['children']:
                problems.append(f"{row['id']}：订单或允许子卷不符")
                continue
            if not isclose(row['end'] - row['start'], order['length'], abs_tol=1e-6):
                problems.append(f"{row['id']}：件长不符")
            if previous is None:
                if not isclose(row['start'], run['start'], abs_tol=1e-6):
                    problems.append(f"{row['id']}：段首未对齐")
            else:
                gap = row['start'] - previous['end']
                expect = max(order['allowance'], by_id[previous['id'].rsplit('/', 1)[0]]['allowance'])
                if not isclose(gap, expect, abs_tol=1e-6):
                    problems.append(f"{row['id']}：刀口留量不符")
            if row['start'] < run['start'] - 1e-6 or row['end'] > run['end'] + 1e-6:
                problems.append(f"{row['id']}：成品跨出可保段")
            made[order['id']] += 1
            evidence[order['id']][run['id']] = evidence[order['id']].get(run['id'], 0) + 1
            previous = row
        tail = remnants[run['id']]
        expect = run['end'] - (previous['end'] if previous else run['start'])
        if expect > 1e-6:
            if (len(tail) != 1 or not isclose(tail[0]['start'], run['end'] - expect, abs_tol=1e-6)
                    or not isclose(tail[0]['end'], run['end'], abs_tol=1e-6)):
                problems.append(f"{run['id']}：余料区间不符")
        elif tail:
            problems.append(f"{run['id']}：不应有余料区间")
    cuts = {row['id']: row for row in model['cuts']}
    for row in cut_rows:
        cut = cuts[row['child']]
        origin = ([row['start'], row['end']] if cut['winding'] == 'forward'
                  else [model['length'] - row['end'], model['length'] - row['start']])
        if (not all(isclose(a, b, abs_tol=1e-6) for a, b in zip(row['origin'], origin))
                or not all(isclose(a, b, abs_tol=1e-6) for a, b in zip(row['span'], [cut['a'], cut['b']]))):
            problems.append(f"{row['id']}：母卷坐标不符")
    for row in batch_rows:
        order = by_id.get(row['id'])
        if order is None:
            problems.append(f"{row['id']}：未知订单")
            continue
        if row['quoted'] != standalone_quote(order, runs):
            problems.append(f"{row['id']}：逐规格报价不符")
        if (row['count'] != made[row['id']] or row['shortage'] != row['demand'] - made[row['id']]
                or row['demand'] != order['demand'] or row['evidence'] != evidence[row['id']]):
            problems.append(f"{row['id']}：缺件账不平")
    tiers = sorted({order['priority'] for order in orders})
    plan_tiers = tuple(sum(made[order['id']] for order in orders if order['priority'] == tier)
                       for tier in tiers)
    plan_remnants = tuple(sorted((run['end'] - max((row['end'] for row in pieces[run['id']]),
                                                   default=run['start']) for run in runs), reverse=True))
    outcome = exhaustive(orders, runs)
    longest_options = []
    if outcome is None:
        problems.append('规模超出核对上限')
    else:
        if plan_tiers != outcome['tiers']:
            problems.append('逐档完成件数不是最优')
        if (tuple(round(x, 6) for x in plan_remnants)
                != tuple(round(x, 6) for x in outcome['remnants'])):
            problems.append('同档余料留存不是最优')
        longest_options = sorted(outcome['longest'])
    return dict(ok=not problems, problems=problems, tiers=plan_tiers,
                longest=max(plan_remnants) if plan_remnants else 0,
                longest_options=longest_options)
