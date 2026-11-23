"""离线刀位试算的有界核对。

与 slitweb.check_flow 同风格：在临时库和临时回环端口上跑实际 HTTP 接口，
另用纯函数断言核对多疵点纵向重叠、等宽布局不等价和无解约束说明。
运行：python3 -m slitweb.check_planning
"""

import json
from math import isclose
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Thread

from . import planning
from .server import PREFIX, ROOT, serve
from .check_flow import request

EXAMPLE = ROOT / 'examples'


def load(name):
    return json.loads((EXAMPLE / name).read_text(encoding='utf8'))


def close(a, b):
    return isclose(a, b, abs_tol=1e-8)


def audit_core():
    sample = load('planning-sample.json')
    result = planning.plan(sample)
    assert result['state'] == 'feasible', '样例应能找到布局'
    assert result['candidate_count'] > 0
    assert all(row['state'] == 'trial' for row in result['layouts']), '备选只能是试算状态'
    assert all('不得放行' in row['release'] for row in result['layouts'])
    assert '不得放行' in result['notice']

    layouts = result['layouts']
    for layout in layouts:
        assert layout['strip_count'] >= sample['order']['minimum_strips']
        assert len(layout['knife_positions']) == layout['knife_count']
        assert layout['knife_positions'] == sorted(layout['knife_positions'])
        for strip in layout['strips']:
            assert strip['width'] >= sample['order']['net_width'] - 1e-9
        # 禁刀区间内不应出现任何下刀点
        for a, b in result['constraints']['forbidden']:
            assert all(not (a < pos < b) for pos in layout['knife_positions'])
        # 幅宽守恒：两边边料 + 各带宽度 = 母卷宽
        total = layout['outer_left'] + layout['outer_right'] + sum(s['width'] for s in layout['strips'])
        assert close(total, sample['width']), f"{layout['id']} 幅宽不守恒：{total}"
        # 宽度废料口径：边料 + 带内富余
        assert close(layout['width_waste'],
                     layout['edge_waste'] + layout['trim_waste'])
        assert close(layout['trim_waste'],
                     sum(s['excess'] for s in layout['strips']))

    # 择优口径：length 模式按最短板可保长段降序
    for earlier, later in zip(layouts, layouts[1:]):
        assert earlier['longest_run'] >= later['longest_run'] - 1e-9

    # trim 模式按幅宽边料升序
    trim_result = planning.plan(dict(sample, ranking='trim'))
    for earlier, later in zip(trim_result['layouts'], trim_result['layouts'][1:]):
        assert earlier['width_waste'] <= later['width_waste'] + 1e-9

    audit_overlapping_defects(sample, result)
    audit_equal_width(sample, result)


def audit_overlapping_defects(sample, result):
    """三个重大疵点在走卷方向纵向重叠，且只跨一部分候选刀位。"""
    defects = {row['id']: row for row in sample['defects'] if row['grade'] == 'major'}
    # 甲 [40,120]、乙 [90,180]、丙 [150,230]：纵向 y 区间 [200,400] 重叠
    assert max(defects['重叠疵点甲']['y0'], defects['重叠疵点乙']['y0'],
               defects['重叠疵点丙']['y0']) < min(defects['重叠疵点甲']['y1'],
               defects['重叠疵点乙']['y1'], defects['重叠疵点丙']['y1'])

    # 找一个包含刀位 60 与 112（甲乙都跨）和一个把它们分开的布局，验证分摊差异
    layout_hit = next(row for row in result['layouts']
                      if {'重叠疵点甲', '重叠疵点乙'}.issubset(set(row['major_hits'])))
    strip_between = next(s for s in layout_hit['strips']
                         if s['start'] <= 60 and s['end'] >= 112)
    assert {'重叠疵点甲', '重叠疵点乙'}.issubset(set(strip_between['major']))
    # 甲、乙在该带内的纵向封锁区间重叠，损失必须按并集而不是相加
    union_loss = strip_between['loss']
    separate = ((defects['重叠疵点甲']['y1'] + 5 + 10) -
                (defects['重叠疵点甲']['y0'] - 5 - 10)) + \
               ((defects['重叠疵点乙']['y1'] + 5 + 10) -
                (defects['重叠疵点乙']['y0'] - 5 - 10))
    assert union_loss < separate, '重叠疵点损失按并集核算，不能重复计长'
    # 手工复算该带封锁并集：甲 [185,335]、乙 [245,415] → 并集 [185,415]，长 230
    assert close(union_loss, 230), f'重叠封锁并集应为 230，实际 {union_loss}'

    # 远端疵点只影响靠右侧的带：验证"只有一部分跨候选刀位"
    right_layout = next(row for row in result['layouts'] if '远端疵点' in row['major_hits'])
    left_layout = next(row for row in result['layouts'] if '远端疵点' not in row['major_hits'])
    assert right_layout['total_loss'] != left_layout['total_loss'] or right_layout['id'] != left_layout['id']


def audit_equal_width(sample, result):
    pairs = result['equal_width_pairs']
    assert pairs, '样例应能产出等宽布局对照'
    for pair in pairs:
        left = next(row for row in result['layouts'] if row['id'] == pair['left'])
        right = next(row for row in result['layouts'] if row['id'] == pair['right'])
        assert left['width_signature'] == right['width_signature']
        # 等宽但刀位整体平移后，命中疵点不同，必须能说明不等价
        if pair['equivalent']:
            assert close(left['total_loss'], right['total_loss'])
            assert close(left['longest_run'], right['longest_run'])
            assert set(left['major_hits']) == set(right['major_hits'])
        else:
            assert pair['reasons'], '不等价的等宽布局必须给出可复核理由'
            metrics = {reason['metric'] for reason in pair['reasons']}
            assert metrics & {'total_loss', 'longest_run', 'major_hits'}
    # 至少有一对等宽布局因疵点分摊不同而不等价
    assert any(not pair['equivalent'] and
               any(reason['metric'] in ('major_hits', 'total_loss') for reason in pair['reasons'])
               for pair in pairs), '缺少疵点导致的等宽不等价证据'


def audit_infeasible():
    result = planning.plan(load('planning-infeasible.json'))
    assert result['state'] == 'infeasible'
    assert result['layouts'] == [] and result['candidate_count'] == 0
    codes = {note['code'] for note in result['diagnosis']}
    assert 'longest_feasible_chain' in codes and 'net_capacity' in codes
    chain = next(note for note in result['diagnosis'] if note['code'] == 'longest_feasible_chain')
    # 0-30、30-58 都不足 50，58-120、120-320 可行，最长链 2 条带 < 4
    assert '2 条带' in chain['detail']


def audit_reject(port):
    bad = load('planning-reject.json')
    request(port, 'knife-plan', bad, status=400)
    # 刀位格落在禁刀区间也应拒绝
    sample = load('planning-sample.json')
    blocked = dict(sample, forbidden=[dict(id='封格', a=56, b=64)])
    request(port, 'knife-plan', blocked, status=400)
    # 净幅超出母卷宽度
    oversized = dict(sample, order=dict(net_width=200, minimum_strips=4))
    request(port, 'knife-plan', oversized, status=400)


def audit_http(port):
    sample = load('planning-sample.json')
    payload, _ = request(port, 'knife-plan', sample)
    assert payload['kind'] == 'knife_trial' and payload['state'] == 'feasible'
    infeasible, _ = request(port, 'knife-plan', load('planning-infeasible.json'))
    assert infeasible['state'] == 'infeasible'
    # 试算入口不写成果库
    revisions, _ = request(port, 'revisions')
    assert revisions == []


def main():
    audit_core()
    audit_infeasible()
    with TemporaryDirectory(prefix='slitweb-planning-') as directory:
        with serve(Path(directory) / 'planning.sqlite', 0) as server:
            thread = Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                port = server.server_port
                audit_http(port)
                audit_reject(port)
            finally:
                server.shutdown()
                thread.join()
    print('刀位试算：枚举择优、重叠疵点并集、等宽不等价、无解约束说明与非法拒绝均已核对')


if __name__ == '__main__':
    main()
