#!/usr/bin/env python3
"""复算“月报口径”对照材料。

只读取正式输入并调用现有归约（slitweb.service.Workbench.analyze），
打印面积分摊与走卷长度账的对照表；不写回成果，不改变任何统计输出。
用法：python3 -I docs/metrics-audit/recompute.py
"""

import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from slitweb.contract import canonical, decode  # noqa: E402
from slitweb.geometry import union_area  # noqa: E402
from slitweb.intervals import gaps, union  # noqa: E402
from slitweb.server import CONFIG  # noqa: E402
from slitweb.service import Workbench  # noqa: E402


def analyze(source):
    # 与 HTTP 入口同一路径：合同解码 + 正式归约。
    return Workbench(None, CONFIG).analyze(decode(canonical(source)))['outputs']


def table(headers, rows):
    print('| ' + ' | '.join(headers) + ' |')
    print('|' + '|'.join('---' for _ in headers) + '|')
    for row in rows:
        print('| ' + ' | '.join(str(cell) for cell in row) + ' |')


def span(defect):
    return defect['y1'] - defect['y0']


def band_width(defect, cut):
    return max(0, min(cut['b'], defect['x1']) - max(cut['a'], defect['x0']))


def edge_width(defect, waste):
    return sum(max(0, min(b, defect['x1']) - max(a, defect['x0'])) for a, b in waste)


def defect_rect(defect):
    return dict(x0=defect['x0'], x1=defect['x1'], y0=defect['y0'], y1=defect['y1'])


def child_span(defect, cut, length):
    y0, y1 = defect['y0'], defect['y1']
    if cut['winding'] == 'reverse':
        y0, y1 = length - y1, length - y0
    return y0, y1


def expanded_span(defect, cut, length, margin):
    y0, y1 = child_span(defect, cut, length)
    return max(0, y0 - margin), min(length, y1 + margin)


def longest_run(outputs, child):
    return max((row['length'] for row in outputs['runs'] if row['child'] == child), default=0)


def yield_count(outputs, child):
    row = next((item for item in outputs['yield_plan'] if item['child'] == child), None)
    return None if row is None else row['count']


def loss_row(outputs, child):
    return next(row for row in outputs['losses'] if row['id'] == child)


def margin_sensitivity(source, base):
    zero = copy.deepcopy(source)
    zero['margin'] = 0
    other = analyze(zero)
    rows = []
    for cut in source['cuts']:
        child = cut['id']
        now, then = loss_row(base, child), loss_row(other, child)
        rows.append([child, source['margin'], now['eligible'], now['blocked'], now['mixed'], now['blind'],
                     then['eligible'], then['blocked'], then['mixed'], then['blind']])
    table(['子卷', '边距', '可保', '重大', '双因', '缺检', '可保(m=0)', '重大(m=0)', '双因(m=0)', '缺检(m=0)'], rows)


STATE = {'blocked': '阻断', 'pending': '待确定', 'ready': '已符合'}


def ablate(base, label):
    """把“刀位”和“等级”分开改，看两种指标各自跟随哪一个。"""
    print(f'\n## 刀位与等级的分离对照（以 {label} 为底）\n')
    print('四个变体只改一个因素。刀位移到 55 时子卷宽 40，复核窗右界随之从 43 收到 40；'
          '复检窗本身（乙卷 740–900 未检）保持不变，所以缺检长度与判定不受变体干扰。\n')
    variants = []
    for name, knife, grade in [('原状（刀位 52）', 52, 'major'),
                               ('只移刀位到 55', 55, 'major'),
                               ('只把亮线降为 minor', 52, 'minor'),
                               ('两项同时（刀位 55 + minor）', 55, 'minor')]:
        source = copy.deepcopy(base)
        source['cuts'][1]['a'] = knife
        next(row for row in source['defects'] if row['id'] == '亮线')['grade'] = grade
        width_limit = source['cuts'][1]['b'] - source['cuts'][1]['a']
        for window in source['review']['inspections']:
            window['x1'] = min(window['x1'], width_limit)
        variants.append((name, source))
    rows = []
    for name, source in variants:
        out = analyze(source)
        shared = next(row for row in out['shared'] if row['id'] == '亮线')
        rows.append([name, f"{shared['kept']}/{shared['lost']}",
                     f"{shared['kept'] * 70}/{shared['lost'] * 70}",
                     *[f"{loss_row(out, child)['eligible']}/{loss_row(out, child)['blocked']}"
                       f"/{loss_row(out, child)['mixed']}/{loss_row(out, child)['blind']}" for child in ('甲卷', '乙卷')],
                     *[STATE[next(row for row in out['release'] if row['id'] == child)['state']]
                       for child in ('甲卷', '乙卷')],
                     '/'.join(str(sum(b - a for a, b in next(row for row in out['coverage'] if row['id'] == child)['missing']))
                              for child in ('甲卷', '乙卷'))])
    table(['变体', '亮线 保留/边料宽', '亮线 保留/边料面积', '甲卷 可保/重大/双因/缺检',
           '乙卷 可保/重大/双因/缺检', '甲卷 判定', '乙卷 判定', '甲/乙 缺检原长'], rows)
    print('\n刀位只改幅向分摊（保留/边料宽及其面积），等级只改走卷长度账与封样判定；'
          '刀位动而等级不动时，长度账与判定一格不变。\n')


def report(source, label):
    out = analyze(source)
    length, margin, width = source['length'], source['margin'], source['width']
    cuts = sorted(source['cuts'], key=lambda row: row['a'])
    waste = [tuple(item) for item in gaps([(cut['a'], cut['b']) for cut in cuts], width)]
    defects = source['defects']
    children = [cut['id'] for cut in cuts]

    print(f'\n## {label}（{source["id"]}）\n')
    print(f'母卷 {width}×{length}，修剪预留 {margin}，刀带 {children}，边料 {waste}。\n')

    print('### 1. 原疵点的幅向分摊与面积可加性\n')
    rows = []
    for defect in defects:
        shared = next(row for row in out['shared'] if row['id'] == defect['id'])
        cells = []
        for cut in cuts:
            w = band_width(defect, cut)
            cells.append(f'{w}/{w * span(defect)}' if w else '—')
        edge = edge_width(defect, waste)
        rows.append([defect['id'], defect['grade'], f"{defect['x0']}–{defect['x1']}",
                     f"{defect['y0']}–{defect['y1']}", span(defect) * (defect['x1'] - defect['x0']),
                     *cells, f'{edge}/{edge * span(defect)}' if edge else '—',
                     f"{shared['kept']}/{shared['lost']}", shared['state']])
    table(['原疵点', '级别', '幅向 x', '走卷 y', '原面积', *[f'{child} 宽/面积' for child in children],
           '边料 宽/面积', '保留/边料宽', '状态'], rows)

    mother_union = union_area([defect_rect(defect) for defect in defects])
    mother_sum = sum(span(defect) * (defect['x1'] - defect['x0']) for defect in defects)
    # 子卷内坐标互不相通，必须逐卷求并集再相加，不能把所有子卷的行混在一起做并集。
    child_union = 0
    child_sum = 0
    for cut in cuts:
        rows = [row for row in out['transfer'] if row['child'] == cut['id']]
        child_union += union_area(rows)
        child_sum += sum((row['x1'] - row['x0']) * (row['y1'] - row['y0']) for row in rows)
    edge_rects = [dict(x0=max(a, defect['x0']), x1=min(b, defect['x1']),
                       y0=defect['y0'], y1=defect['y1'])
                  for defect in defects for a, b in waste
                  if min(b, defect['x1']) > max(a, defect['x0'])]
    edge_union = union_area(edge_rects)
    overlap_note = '疵点互相重合' if mother_sum > mother_union else '无重合，可直接相加'
    child_note = '同一子卷内两条转印重合' if child_sum > child_union else '无重合，可直接相加'
    print(f'- 原疵点逐条相加 {mother_sum}；母卷坐标并集 {mother_union}；差 {mother_sum - mother_union}（{overlap_note}）。')
    print(f'- 子卷转印行相加 {child_sum}；子卷内并集 {child_union}；差 {child_sum - child_union}（{child_note}）。')
    print(f'- 边料内疵点并集 {edge_union}；子卷并集 + 边料并集 = {child_union + edge_union}；母卷并集 = {mother_union}。')
    if child_union + edge_union != mother_union:
        raise SystemExit('分区并集与母卷并集不闭合')

    for defect in defects:
        pieces = sum(band_width(defect, cut) * span(defect) for cut in cuts)
        pieces += edge_width(defect, waste) * span(defect)
        if pieces != span(defect) * (defect['x1'] - defect['x0']):
            raise SystemExit(f"{defect['id']} 的分区面积不闭合")

    print('\n### 2. 各条成品的走卷长度账\n')
    rows = []
    for cut in cuts:
        child = cut['id']
        loss = loss_row(out, child)
        coverage = next(row for row in out['coverage'] if row['id'] == child)
        missing = sum(b - a for a, b in coverage['missing'])
        count = yield_count(out, child)
        rows.append([child, cut['winding'], loss['eligible'], loss['blocked'], loss['mixed'], loss['blind'],
                     missing, f"{loss['eligible'] + loss['blocked'] + loss['mixed'] + loss['blind']}/{length}",
                     longest_run(out, child), '—' if count is None else count])
        if loss['eligible'] + loss['blocked'] + loss['mixed'] + loss['blind'] != length:
            raise SystemExit(f'{child} 长度账不闭合')
    table(['子卷', '绕向', '可保', '重大(已检)', '双因(缺检∩重大)', '缺检', '缺检原长', '合计', '最长连续段', '定尺件数'], rows)

    print('\n### 3. 禁保分段（互斥归因）\n')
    table(['段', '区间', '长度', '状态', '来源疵点'],
          [[row['id'], f"{row['start']}–{row['end']}", row['length'], row['state'],
            '、'.join(row['evidence']) or '—'] for row in out['exclusion']])

    print('\n### 4. 面积、缺陷体长度、含边距禁保与边际效果\n')
    print('“缺陷体长度”是疵点自身走卷区间在该子卷上的长度；“含边距”再向两侧各加预留；'
          '“边际”是逐条移除该疵点后重新归约的差。三者都不是面积。\n')
    rows = []
    for defect in defects:
        reduced = dict(source, defects=[row for row in defects if row['id'] != defect['id']])
        other = analyze(reduced)
        for cut in cuts:
            child = cut['id']
            if not band_width(defect, cut):
                continue
            body = span(defect)
            if defect['grade'] == 'major':
                a, b = expanded_span(defect, cut, length, margin)
                nominal, reserved = b - a, b - a - body
            else:
                nominal, reserved = '—', '—'
            now, then = loss_row(out, child), loss_row(other, child)
            before, after = yield_count(out, child), yield_count(other, child)
            rows.append([defect['id'], defect['grade'], span(defect) * (defect['x1'] - defect['x0']),
                         f"{band_width(defect, cut)}/{body}", nominal, reserved,
                         then['eligible'] - now['eligible'],
                         f'{before}→{after}' if before is not None else '—',
                         longest_run(other, child) - longest_run(out, child)])
    table(['原疵点', '级别', '原面积', '幅向宽/缺陷体长', '含边距禁保', '其中边距', '边际可保增加', '定尺件数', '最长段增加'], rows)

    print('\n#### 4b. 同一批疵点按两种指标排序\n')
    ranking = []
    for defect in defects:
        reduced = dict(source, defects=[row for row in defects if row['id'] != defect['id']])
        other = analyze(reduced)
        nominal = 0
        gain = 0
        pieces = 0
        for cut in cuts:
            if not band_width(defect, cut):
                continue
            if defect['grade'] == 'major':
                a, b = expanded_span(defect, cut, length, margin)
                nominal += b - a
                before, after = yield_count(out, cut['id']), yield_count(other, cut['id'])
                pieces += (after or 0) - (before or 0)
            now, then = loss_row(out, cut['id']), loss_row(other, cut['id'])
            gain += then['eligible'] - now['eligible']
        ranking.append([defect['id'], span(defect) * (defect['x1'] - defect['x0']), span(defect), nominal, gain, pieces])
    by_area = {row[0]: rank for rank, row in enumerate(sorted(ranking, key=lambda item: (-item[1], item[0])), 1)}
    by_body = {row[0]: rank for rank, row in enumerate(sorted(ranking, key=lambda item: (-item[2], item[0])), 1)}
    by_len = {row[0]: rank for rank, row in enumerate(sorted(ranking, key=lambda item: (-item[3], item[0])), 1)}
    by_gain = {row[0]: rank for rank, row in enumerate(sorted(ranking, key=lambda item: (-item[4], item[0])), 1)}
    table(['原疵点', '原面积', '面积名次', '缺陷体走卷长', '长度名次', '含边距合计', '含边距名次',
           '边际可保合计', '边际名次', '定尺件数变化'],
          [[row[0], row[1], by_area[row[0]], row[2], by_body[row[0]], row[3], by_len[row[0]],
            row[4], by_gain[row[0]], row[5]] for row in ranking])
    print('\n结论：逐条边际值不可相加。重合的亮线 × 横贯痕同时移除得 150，大于两条各自边际之和 120——'
          '重合段要等两条都解除才放开；其余组合两者相等。\n')

    major = [defect for defect in defects if defect['grade'] == 'major']
    pairs = [(a, b) for i, a in enumerate(major) for b in major[i + 1:]]
    if pairs:
        print('#### 4c. 同时移除两条疵点，检验可加性\n')
        rows = []
        for first, second in pairs:
            reduced = dict(source, defects=[row for row in defects if row['id'] not in (first['id'], second['id'])])
            other = analyze(reduced)
            singles = 0
            for defect in (first, second):
                partly = dict(source, defects=[row for row in defects if row['id'] != defect['id']])
                alone = analyze(partly)
                singles += sum(loss_row(alone, child)['eligible'] - loss_row(out, child)['eligible']
                               for child in children)
            both = sum(loss_row(other, child)['eligible'] - loss_row(out, child)['eligible'] for child in children)
            rows.append([f"{first['id']} × {second['id']}", singles, both, both - singles])
        table(['疵点对', '两条各自边际之和', '同时移除的增益', '重合带来的一次性释放'], rows)
        print('\n“重合带来的一次性释放”为正：只有两条同时解除，重合段才变成可保；'
              '逐条相加会低估一对重合疵点的总收益，不能当作月报总额相加。\n')

    print('### 5. 长度口径的逐条相加 vs 禁保并集\n')
    rows = []
    for cut in cuts:
        child = cut['id']
        spans = [expanded_span(defect, cut, length, margin) for defect in defects
                 if defect['grade'] == 'major' and band_width(defect, cut)]
        loss = loss_row(out, child)
        rows.append([child, sum(b - a for a, b in spans),
                     sum(b - a for a, b in union(spans)), loss['blocked'] + loss['mixed'], loss['eligible']])
    table(['子卷', '逐条含边距之和', '禁保并集', '实际禁保（重大+双因）', '可保'], rows)
    print('\n逐条相加与并集的差就是被两条疵点共同占用的段（如甲卷/3、乙卷/3）；'
          '并集才是长度账，`exclusion.evidence` 条数不能用来累加长度。\n')

    print('### 6. 预留变化（只是情景复算，不写入成果）\n')
    margin_sensitivity(source, out)

    print('\n### 7. 缺检的构成\n')
    rows = []
    for cut in cuts:
        child = cut['id']
        coverage = next(row for row in out['coverage'] if row['id'] == child)
        loss = loss_row(out, child)
        rows.append([child, coverage['missing'] or '—',
                     sum(b - a for a, b in coverage['missing']), loss['blind'], loss['mixed']])
    table(['子卷', '缺检窗', '缺检原长', '纯缺检', '缺检∩重大(双因)'], rows)
    print('\n缺检是“未观测”，不是 0，也不是已确认损失；双因段同时受重大疵点与缺检约束，不能在两栏各算一次。\n')


def main():
    base = json.loads((ROOT / 'examples/review-sample.json').read_text(encoding='utf8'))
    for name, label in [('examples/review-sample.json', '现有样例'),
                        ('docs/metrics-audit/contrast-roll.json', '口径对照例')]:
        report(json.loads((ROOT / name).read_text(encoding='utf8')), label)
    ablate(base, '现有样例')


if __name__ == '__main__':
    main()
