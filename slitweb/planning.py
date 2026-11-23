"""离线刀位试算：在现有刀架的可用刀位格上枚举能保住订单净幅的拼刀布局。

试算只消费工艺员录入的刀位格、禁刀区间、订单净幅/条数和疵点矩形，
不连接设备、不写成果库，也不把任何备选称为可放行。所有长度与幅向坐标
使用毫米，坐标窗左闭右开，与主数据合同保持同一口径。
"""

from .contract import ContractError, enum, ident, invariant, num, obj, records
from .intervals import gaps, union

ENUM_LIMIT = 20000          # 枚举布局的硬上限，防止组合爆炸占满本机
REPORT_LIMIT = 50           # 每种排序最多带回的备选数量
EQUAL_PAIR_LIMIT = 60       # 等宽布局对照的最多条数


def _slots(source, width):
    raw = records(source.get('slots'), '可用刀位格', count=256, minimum=2)
    positions = []
    seen = set()
    for item in raw:
        pos = num(item.get('position'), '刀位格坐标', 0, width)
        invariant(pos not in seen, f'刀位格坐标重复：{pos}')
        seen.add(pos)
        positions.append(dict(id=ident(item.get('id'), '刀位格标识'), position=pos))
    positions.sort(key=lambda row: row['position'])
    return positions


def _forbidden(source, width):
    zones = []
    for item in records(source.get('forbidden'), '禁刀区间', count=128):
        a, b = num(item.get('a'), '禁刀区间起点', 0, width), num(item.get('b'), '禁刀区间终点', 0, width)
        invariant(a < b, '禁刀区间终点必须大于起点')
        zones.append((a, b))
    return union(zones)


def _order(source, width):
    order = obj(source.get('order'), '订单要求')
    net = num(order.get('net_width'), '品种所需净幅', 0.001, width)
    minimum = num(order.get('minimum_strips'), '最少条数', 2, 256)
    invariant(float(minimum).is_integer(), '最少条数应为整数')
    return dict(net=net, minimum=int(minimum))


def _defects(source, width, length):
    defects = []
    for item in records(source.get('defects'), '试算疵点', count=240):
        x0, x1 = num(item.get('x0'), '疵点幅向起点', 0, width), num(item.get('x1'), '疵点幅向终点', 0, width)
        y0, y1 = num(item.get('y0'), '疵点走卷起点', 0, length), num(item.get('y1'), '疵点走卷终点', 0, length)
        invariant(x0 < x1 and y0 < y1, '疵点矩形必须有正面积')
        defects.append(dict(id=ident(item.get('id'), '疵点标识'), x0=x0, x1=x1, y0=y0, y1=y1,
                            grade=enum(item.get('grade'), ('minor', 'major'), '疵点级别')))
    return defects


def parse_request(source):
    source = obj(source, '刀位试算请求')
    ident(source.get('id'), '试算对象标识')
    width = num(source.get('width'), '母卷宽度', 1)
    length = num(source.get('length'), '母卷长度', 1)
    slots = _slots(source, width)
    forbidden = _forbidden(source, width)
    order = _order(source, width)
    trial = obj(source.get('trial') or {}, '试算口径')
    transfer = num(trial.get('transfer_margin', 0), '实际转印预留', 0, length)
    reserve = num(trial.get('reserve_margin', 0), '两端预留', 0, length)
    defects = _defects(source, width, length)
    mode = enum(source.get('ranking', 'length'), ('length', 'trim'), '择优口径')
    for row in slots:
        blocked = any(a < row['position'] < b for a, b in forbidden)
        invariant(not blocked, f"刀位格 {row['id']} 落在禁刀区间内，不能下刀")
    need_knives = order['minimum'] + 1
    invariant(len(slots) >= need_knives,
              f'可用刀位格只有 {len(slots)} 个，{order["minimum"]} 条带至少需要 {need_knives} 把刀')
    invariant(order['net'] * order['minimum'] <= width + 1e-9,
              f'净幅 {order["net"]} × {order["minimum"]} 条已超过母卷宽度 {width}')
    return dict(id=source['id'], width=width, length=length, slots=slots, forbidden=forbidden,
                order=order, transfer=transfer, reserve=reserve, defects=defects, mode=mode)


def _enumerate(model):
    slots, net, minimum = model['slots'], model['order']['net'], model['order']['minimum']
    positions = [row['position'] for row in slots]
    width = model['width']
    layouts, truncated = [], False

    def search(start, chosen):
        nonlocal truncated
        if len(chosen) >= minimum + 1:
            layouts.append(list(chosen))
            if len(layouts) >= ENUM_LIMIT:
                return True
        last = positions[chosen[-1]]
        for j in range(start, len(positions)):
            if positions[j] - last < net - 1e-9:
                continue
            chosen.append(j)
            if search(j + 1, chosen):
                return True
            chosen.pop()
        return False

    for first in range(len(positions)):
        truncated = search(first + 1, [first]) or truncated
        if truncated:
            break
    invariant(layouts, '没有任何刀位序列能让每条带都达到净幅要求')
    return layouts, truncated


def _major_loss(model, a, b):
    """一条候选带在走卷方向上因重大疵点损失的净长（按实际转印与两端预留核算）。"""
    length, transfer, reserve = model['length'], model['transfer'], model['reserve']
    spans, minor = [], []
    for defect in model['defects']:
        if max(a, defect['x0']) >= min(b, defect['x1']):
            continue
        if defect['grade'] == 'minor':
            minor.append(defect['id'])
            continue
        lo = max(0, defect['y0'] - transfer - reserve)
        hi = min(length, defect['y1'] + transfer + reserve)
        spans.append((lo, hi))
    blocked = union(spans)
    runs = gaps(blocked, length)
    return dict(loss=sum(hi - lo for lo, hi in blocked),
                longest=max((hi - lo for lo, hi in runs), default=0),
                usable=sum(hi - lo for lo, hi in runs),
                blocked=blocked, minor=minor,
                major=[d['id'] for d in model['defects']
                       if d['grade'] == 'major' and max(a, d['x0']) < min(b, d['x1'])])


def _build_layout(model, indexes, serial):
    slots, width, length, net = model['slots'], model['width'], model['length'], model['order']['net']
    knives = [slots[i] for i in indexes]
    strips, losses, longest_runs, major_hits = [], [], [], []
    for n, (left, right) in enumerate(zip(knives, knives[1:]), 1):
        a, b = left['position'], right['position']
        account = _major_loss(model, a, b)
        strip = dict(id=f'带{n}', start=a, end=b, width=b - a, excess=(b - a) - net,
                     loss=round(account['loss'], 9), longest=round(account['longest'], 9),
                     usable=round(account['usable'], 9),
                     major=account['major'], minor=account['minor'],
                     blocked=[[lo, hi] for lo, hi in account['blocked']])
        strips.append(strip)
        losses.append(account['loss'])
        longest_runs.append(account['longest'])
        major_hits.extend(account['major'])
    outer_left = knives[0]['position']
    outer_right = width - knives[-1]['position']
    edge = outer_left + outer_right
    trim = sum(row['excess'] for row in strips)
    return dict(id=f'布局{serial}', knife_count=len(knives), strip_count=len(strips),
                knife_ids=[row['id'] for row in knives],
                knife_positions=[row['position'] for row in knives],
                outer_left=outer_left, outer_right=outer_right, edge_waste=edge,
                trim_waste=round(trim, 9), width_waste=round(edge + trim, 9),
                width_signature=tuple(round(row['width'], 9) for row in strips),
                longest_run=round(min(longest_runs), 9),
                total_loss=round(sum(losses), 9),
                total_usable=round(sum(row['usable'] for row in strips), 9),
                major_hits=sorted(set(major_hits)), strips=strips,
                state='trial', release='试算备选，未经复检不得放行')


def _rank(layouts, mode):
    if mode == 'length':
        return sorted(layouts, key=lambda row: (-row['longest_run'], row['total_loss'],
                                                row['width_waste'], row['knife_positions']))
    return sorted(layouts, key=lambda row: (row['width_waste'], -row['strip_count'],
                                            -row['longest_run'], row['total_loss'],
                                            row['knife_positions']))


def _equal_width_pairs(layouts):
    groups = {}
    for layout in layouts:
        groups.setdefault(layout['width_signature'], []).append(layout)
    pairs = []
    for signature, members in groups.items():
        if len(members) < 2:
            continue
        members = sorted(members, key=lambda row: row['id'])
        for earlier, later in zip(members, members[1:]):
            reasons = []
            if not _close(earlier['total_loss'], later['total_loss']):
                reasons.append(dict(metric='total_loss',
                                    detail=f"走卷净长损失 {earlier['total_loss']} ≠ {later['total_loss']}",
                                    left=earlier['total_loss'], right=later['total_loss']))
            if not _close(earlier['longest_run'], later['longest_run']):
                reasons.append(dict(metric='longest_run',
                                    detail=f"最短板可保长段 {earlier['longest_run']} ≠ {later['longest_run']}",
                                    left=earlier['longest_run'], right=later['longest_run']))
            if set(earlier['major_hits']) != set(later['major_hits']):
                reasons.append(dict(metric='major_hits',
                                    detail=f"命中的重大疵点 {earlier['major_hits']} ≠ {later['major_hits']}",
                                    left=earlier['major_hits'], right=later['major_hits']))
            if not _close(earlier['edge_waste'], later['edge_waste']):
                reasons.append(dict(metric='edge_waste',
                                    detail=f"两侧边料合计 {earlier['edge_waste']} ≠ {later['edge_waste']}",
                                    left=earlier['edge_waste'], right=later['edge_waste']))
            if not _close(earlier['trim_waste'], later['trim_waste']):
                reasons.append(dict(metric='trim_waste',
                                    detail=f"带内富余合计 {earlier['trim_waste']} ≠ {later['trim_waste']}",
                                    left=earlier['trim_waste'], right=later['trim_waste']))
            per_strip = []
            for left_strip, right_strip in zip(earlier['strips'], later['strips']):
                if (set(left_strip['major']) != set(right_strip['major']) or
                        not _close(left_strip['loss'], right_strip['loss'])):
                    per_strip.append(dict(strip=left_strip['id'],
                                          left_major=left_strip['major'], right_major=right_strip['major'],
                                          left_loss=left_strip['loss'], right_loss=right_strip['loss']))
            pairs.append(dict(id=f"{earlier['id']}|{later['id']}", width_signature=list(signature),
                              left=earlier['id'], right=later['id'],
                              equivalent=not reasons, reasons=reasons, strip_evidence=per_strip))
            if len(pairs) >= EQUAL_PAIR_LIMIT:
                return pairs, True
    return pairs, False


def _close(a, b):
    return abs(a - b) <= 1e-7


def _diagnose(model):
    """枚举失败时给出可复核的约束说明，而不是空结果。"""
    slots, net, minimum = model['slots'], model['order']['net'], model['order']['minimum']
    width = model['width']
    notes = [dict(code='net_capacity',
                  detail=f'净幅 {net} × 最少 {minimum} 条 = {round(net * minimum, 6)}，母卷宽 {width}')]
    chain, best = [], 1
    run = 1
    for left, right in zip(slots, slots[1:]):
        if right['position'] - left['position'] >= net - 1e-9:
            run += 1
            best = max(best, run)
        else:
            run = 1
    notes.append(dict(code='longest_feasible_chain',
                      detail=f'相邻刀位格都能容纳净幅的最长链只能拼出 {best - 1} 条带，要求 {minimum} 条'))
    if net * minimum > width + 1e-9:
        notes.append(dict(code='insufficient_width', detail='母卷幅宽本身装不下最少条数的净幅'))
    return notes


def plan(source):
    try:
        model = parse_request(source)
    except ContractError:
        raise
    try:
        indexes_list, truncated = _enumerate(model)
    except ContractError as exc:
        return dict(project='slitweb', kind='knife_trial', id=model['id'],
                    state='infeasible', ranking=model['mode'],
                    constraints=dict(width=model['width'], length=model['length'],
                                     net_width=model['order']['net'],
                                     minimum_strips=model['order']['minimum'],
                                     transfer_margin=model['transfer'],
                                     reserve_margin=model['reserve'],
                                     slot_count=len(model['slots']),
                                     forbidden=[[a, b] for a, b in model['forbidden']]),
                    candidate_count=0, truncated=False,
                    reason=str(exc), diagnosis=_diagnose(model),
                    layouts=[], equal_width_pairs=[],
                    notice='试算阶段没有复检结论，以下口径只用于找备选，不构成放行依据')
    layouts = [_build_layout(model, indexes, serial) for serial, indexes in enumerate(indexes_list, 1)]
    ranked = _rank(layouts, model['mode'])[:REPORT_LIMIT]
    pairs, pair_truncated = _equal_width_pairs(ranked)
    return dict(project='slitweb', kind='knife_trial', id=model['id'], state='feasible',
                ranking=model['mode'],
                constraints=dict(width=model['width'], length=model['length'],
                                 net_width=model['order']['net'],
                                 minimum_strips=model['order']['minimum'],
                                 transfer_margin=model['transfer'],
                                 reserve_margin=model['reserve'],
                                 slot_count=len(model['slots']),
                                 forbidden=[[a, b] for a, b in model['forbidden']]),
                candidate_count=len(layouts),
                truncated=truncated, truncated_at=ENUM_LIMIT if truncated else None,
                equal_width_truncated=pair_truncated,
                layouts=[_public(layout) for layout in ranked],
                equal_width_pairs=pairs,
                notice='试算阶段没有复检结论，备选只用于试切排刀，未经复检不得放行')


def _public(layout):
    row = dict(layout)
    row['width_signature'] = list(row['width_signature'])
    return row
