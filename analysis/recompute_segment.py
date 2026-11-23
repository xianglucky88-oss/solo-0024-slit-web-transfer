"""Recompute the segment-handover review example from existing outputs only.

This is an audit script, not a product feature.  It runs the unchanged
service pipeline over ``examples/segment-sample.json`` and derives, with plain
interval arithmetic, the two handover readings discussed in
``analysis/segment-handover-review.md``:

1. full-width, longitudinally bounded segment: the longest continuous
   eligible run at the child's full width;
2. width-restricted band: a lateral band that clears the major defect, whose
   longitudinal coverage is rebuilt from outputs that already exist —
   the complement of ``outputs.coverage.missing`` plus the inspection
   rectangles in ``outputs.origin``.

Every printed number is an existing packet row or a union of existing
rectangles, so the memo's figures can be re-derived after any input change.

Run with the interpreter isolated from the working directory::

    python3 -I analysis/recompute_segment.py
    python3 -I analysis/recompute_segment.py path/to/input.json

The numeric assertions pin the shipped example.  For another input, adapt the
constants and assertions first; otherwise the script stops on the first
mismatch.
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from slitweb.intervals import gaps, union  # noqa: E402
from slitweb.server import CONFIG  # noqa: E402
from slitweb.service import Workbench  # noqa: E402

CHILD = '乙卷'
DEFECT = '窄脉'
# Declared handover policy, deliberately *not* part of the archived source:
# the contract's ``margin`` is longitudinal only.  The memo treats a recorded
# lateral margin as a precondition for band delivery, so it lives here rather
# than being smuggled into the input as if the schema supported it.
LATERAL_MARGIN = 5.0
BASE_STAGES = ('layout', 'transfer', 'scrap', 'coverage', 'release', 'trim',
               'trace', 'exclusion')


def load(path):
    with open(path, encoding='utf-8') as handle:
        return json.load(handle)


def child_rows(outputs, key):
    return [row for row in outputs[key] if row.get('child') == CHILD]


def child_covered(coverage, length):
    """Complement of the longitudinal blind gaps in child coordinates."""
    return [list(span) for span in gaps([tuple(pair) for pair in coverage['missing']], length)]


def to_mother_y(cut, span, length):
    a, b = span
    if cut['winding'] == 'reverse':
        return (length - b, length - a)
    return (a, b)


def band_to_mother(cut, band):
    """Map a child-coordinate x band to a mother-coordinate x range."""
    a, b = band
    if cut['winding'] == 'reverse':
        return (cut['b'] - b, cut['b'] - a)
    return (cut['a'] + a, cut['a'] + b)


def band_spans(covered_child, origin_rows, band, cut, length):
    """Union of mother-y spans covering ``band``.

    Full-width re-inspection (the complement of ``coverage.missing``) applies
    to every band; a local face inspection only counts where its mother x
    rectangle overlaps the band.  This is the band-level reading of the same
    evidence, not a new computation on the source.
    """
    spans = [to_mother_y(cut, span, length) for span in covered_child]
    for row in origin_rows:
        if max(row['x0'], band[0]) < min(row['x1'], band[1]):
            spans.append((row['y0'], row['y1']))
    return [list(span) for span in union(spans)], gaps(spans, length)


def main():
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / 'examples' / 'segment-sample.json'
    source = load(path)
    packet = Workbench(None, CONFIG).analyze(source)
    outputs = packet['outputs']

    cuts = {cut['id']: cut for cut in source['cuts']}
    cut = cuts[CHILD]
    width, length = cut['b'] - cut['a'], source['length']
    margin = source.get('margin', 0)

    transfer = child_rows(outputs, 'transfer')
    coverage = next(row for row in outputs['coverage'] if row['id'] == CHILD)
    release = next(row for row in outputs['release'] if row['id'] == CHILD)
    trim = next(row for row in outputs['trim'] if row['id'] == CHILD)
    losses = next(row for row in outputs['losses'] if row['id'] == CHILD)
    face = next(row for row in outputs['face'] if row['id'] == CHILD)
    review = next(row for row in outputs['defect_review'] if row['id'] == f'{CHILD}/{DEFECT}')
    shared = next(row for row in outputs['shared'] if row['id'] == DEFECT)
    trace = next(row for row in outputs['trace'] if row['id'] == CHILD)
    excluded = child_rows(outputs, 'exclusion')
    runs = child_rows(outputs, 'runs')
    origin_rows = child_rows(outputs, 'origin')
    orders = {row['id']: row for row in outputs['yield_plan'] if row['child'] == CHILD}
    requested = {row['id']: row for row in source['review']['orders']}

    major = next(row for row in transfer if row['state'] == 'major')
    reserved = (max(0, major['y0'] - margin), min(length, major['y1'] + margin))
    gap = coverage['missing'][0] if coverage['missing'] else None
    overlap = None if gap is None else max(0, min(gap[1], reserved[1]) - max(gap[0], reserved[0]))

    # --- the example's defining shape -------------------------------------
    assert major['x1'] - major['x0'] == 3, 'major defect should occupy 3 mm of width'
    assert reserved == (560, 610), f'unexpected reserved range: {reserved}'
    assert gap == [600, 640], f'unexpected longitudinal gap: {gap}'
    assert overlap == 10, f'gap should overlap the reserve by 10 mm: {overlap}'
    assert release['state'] == 'blocked' and release['count'] == 1
    assert review['state'] == 'blind', 'no inspection reaches the defect rectangle'
    assert shared['kept'] == 3 and shared['state'] == 'kept'
    assert trace['evidence'] == [DEFECT]

    # --- reading 1: full-width, longitudinally bounded segment ------------
    segment_area = trim['length'] * width
    excluded_length = sum(row['length'] for row in excluded if row['state'] != 'eligible')
    excluded_area = excluded_length * width
    assert excluded_length == gap[1] - reserved[0] == 80
    assert (trim['start'], trim['end'], trim['length']) == (0, 560, 560)
    assert trim['length'] == max(row['length'] for row in runs)
    assert losses['blocked'] == gap[0] - reserved[0] == 40
    assert losses['mixed'] == overlap == 10
    assert losses['blind'] == gap[1] - reserved[1] == 30
    assert losses['eligible'] == trim['length'] + 360 == 920
    assert sum(losses[state] for state in ('eligible', 'blocked', 'blind', 'mixed')) == length
    short = orders['乙整幅定尺']
    segment_order = orders['乙整段定尺']
    long_order = orders['乙整长定尺']
    assert (short['length'], short['count'], short['used']) == (200, 3, 610)
    assert requested['乙整幅定尺']['allowance'] == 10
    assert (segment_order['length'], segment_order['count'], segment_order['used']) == (560, 1, 560)
    assert long_order['count'] == 0
    # Old reports stay quotable: removing the optional review block leaves all
    # base stages byte-identical.
    plain = Workbench(None, CONFIG).analyze({key: value for key, value in source.items() if key != 'review'})
    assert all(plain['outputs'][stage] == outputs[stage] for stage in BASE_STAGES)
    assert not set(BASE_STAGES) & (set(outputs) - set(plain['outputs']))

    # --- reading 2: width-restricted band ---------------------------------
    low_band = (0.0, major['x0'] - LATERAL_MARGIN)
    high_band = (major['x1'] + LATERAL_MARGIN, width)
    band = max((low_band, high_band), key=lambda pair: pair[1] - pair[0])
    band_width = band[1] - band[0]
    assert band == (0.0, 14.0), band
    assert major['x0'] - band[1] == LATERAL_MARGIN

    covered_child = child_covered(coverage, length)
    mother_band = band_to_mother(cut, band)
    covered, band_missing = band_spans(covered_child, origin_rows, mother_band, cut, length)
    assert band_missing == [], f'low band is blind somewhere: {band_missing}'
    assert covered == [[0, length]], covered
    source_defect = next(d for d in source['defects'] if d['id'] == DEFECT)
    assert not [row for row in origin_rows
                if max(row['x0'], mother_band[0]) < min(row['x1'], mother_band[1])
                and max(row['x0'], source_defect['x0']) < min(row['x1'], source_defect['x1'])
                and max(row['y0'], source_defect['y0']) < min(row['y1'], source_defect['y1'])], 'band window re-covers the defect'

    other_mother = band_to_mother(cut, high_band)
    other_covered, other_missing = band_spans(covered_child, origin_rows, other_mother, cut, length)
    other_width = high_band[1] - high_band[0]
    other_net = sum(hi - lo for lo, hi in other_covered) * other_width
    assert other_missing == [[to_mother_y(cut, gap, length)[0], to_mother_y(cut, gap, length)[1]]] == [[360, 400]]

    # Counterfactual: child-level check windows alone (what ``coverage`` knows)
    # leave the low band blind over the same 40 mm the child-level gap names.
    _, no_local_missing = band_spans(covered_child, [], mother_band, cut, length)
    assert no_local_missing == [[360, 400]], no_local_missing

    # Winding hazard: ignoring reverse winding maps the band onto the mirror
    # strip.  ``origin`` handles the mirroring; a hand-computed band may not.
    naive_mother = (cut['a'] + band[0], cut['a'] + band[1])
    _, naive_missing = band_spans(covered_child, origin_rows, naive_mother, cut, length)
    assert naive_mother == (50.0, 64.0)
    assert naive_missing == [[360, 400]], naive_missing

    # Verified lateral clearance: the only window that re-covers the band at
    # the check gap reaches child x=17, i.e. 3 mm past the band edge, not the
    # declared 5 mm.
    gap_span = to_mother_y(cut, gap, length)
    local = [row for row in origin_rows
             if max(row['y0'], gap_span[0]) < min(row['y1'], gap_span[1])
             and max(row['x0'], mother_band[0]) < min(row['x1'], mother_band[1])]
    assert len(local) == 1, local
    inspected_edge = cut['b'] - local[0]['x0']   # child x reached by the window
    verified_clearance = inspected_edge - band[1]
    assert (inspected_edge, verified_clearance) == (17.0, 3.0), (inspected_edge, verified_clearance)
    shortfall = LATERAL_MARGIN - verified_clearance
    assert shortfall == 2.0, shortfall

    band_defects = [d['id'] for d in source['defects']
                    if d['grade'] == 'major'
                    and max(d['x0'], mother_band[0]) < min(d['x1'], mother_band[1])]
    assert band_defects == [], band_defects
    band_area = band_width * length
    overlap_area = band_width * trim['length']
    # Existing yield rows cannot see the band: every eligible run is split at
    # the child-level gap, so a full-length order is refused.
    assert sum(row['length'] for row in runs if row['length'] >= long_order['length']) == 0

    print(f'输入：{path}')
    print(f"包摘要：{packet['digest'][:16]}")
    print()
    print(f"{CHILD}：母卷 x[{cut['a']},{cut['b']}]，绕向 {cut['winding']}，"
          f"幅宽 {width}，长度 {length}，纵向预留 {margin}")
    print(f'重大疵点：子卷 x[{major["x0"]},{major["x1"]}] y[{major["y0"]},{major["y1"]}]，'
          f'占幅 {major["x1"] - major["x0"]} mm（子卷幅宽的 '
          f'{(major["x1"] - major["x0"]) / width:.1%}）')
    print(f'复检缺口：y{gap}；预留段 y{list(reserved)}；重叠 {overlap} mm；'
          f'defect_review={review["state"]}，shared.kept={shared["kept"]}，trace={trace["state"]}')
    print(f'整卷签封：release={release["state"]}，trim=[{trim["start"]},{trim["end"]}]，'
          f'losses.blind={losses["blind"]}')
    print()
    print('【读法一】整幅定尺交付')
    print(f'  可交段：y[{trim["start"]},{trim["end"]}] × 全幅 {width} mm '
          f'= {segment_area} mm²（占整卷 {segment_area / (width * length):.0%}）')
    print(f'  该段之外：blocked {losses["blocked"]} + mixed {losses["mixed"]} '
          f'+ blind {losses["blind"]} = {excluded_length} mm × {width} = {excluded_area} mm²')
    print(f'  定尺 {short["length"]} mm、留量 {requested["乙整幅定尺"]["allowance"]} mm：'
          f'{short["count"]} 段（占用 {short["used"]} mm，余量 {short["remainder"]} mm）')
    print(f'  定尺 {segment_order["length"]} mm、留量 {requested["乙整段定尺"]["allowance"]} mm：'
          f'{segment_order["count"]} 段（正好用掉可交段）')
    print(f'  定尺 {long_order["length"]} mm、留量 {requested["乙整长定尺"]["allowance"]} mm：'
          f'{long_order["count"]} 段（整幅无 1000 mm 连续段）')
    print(f'  返回母卷：runs.origin={[r["origin"] for r in runs]}')
    print(f'  支撑：transfer[{major["id"]}]、coverage.missing、release、exclusion '
          f'{[r["id"] + ":" + r["state"] for r in excluded]}、trim、runs、losses')
    print()
    print('【读法二】限定幅域取料')
    print(f'  子卷幅域 x[{band[0]:g},{band[1]:g}]（{band_width:g} mm，占幅 {band_width / width:.0%}）'
          f' → 母卷幅域 x[{mother_band[0]:g},{mother_band[1]:g}]')
    print(f'  带内纵向覆盖 {covered}（盲区 {band_missing}），取料面积 {band_area:g} mm²')
    print(f'  距疵点 {LATERAL_MARGIN:g} mm，横向让出 {width - band_width:g} mm；'
          f'face={face["state"]} {face["area"]:g}/{face["total"]:g} mm²（无法定位到带）')
    print(f'  镜像侧 x[{high_band[0]:g},{high_band[1]:g}] → 母卷 x[{other_mother[0]:g},{other_mother[1]:g}]：'
          f'盲区 {other_missing}（{other_missing[0][1] - other_missing[0][0]:g} mm），'
          f'净面积 {other_net:g} mm²')
    print(f'  同一 gap 在低带为 0、在镜像带为 {other_missing[0][1] - other_missing[0][0]:g} mm：'
          f'带级覆盖不是子卷级 missing 的简单缩放')
    print(f'  该带可容 {long_order["length"]} mm 整长 1 段；现有 yield_plan 仍报 '
          f'{long_order["count"]} 段（看不见带宽）')
    print(f'  与读法一重叠：带 x[{band[0]:g},{band[1]:g}] × y[{trim["start"]},{trim["end"]}] '
          f'= {overlap_area:g} mm²，两种交接同时签发会重复计量')
    print(f'  反事实：只看子卷级复检窗，低带在 y[360,400] 仍盲 {no_local_missing[0][1] - no_local_missing[0][0]:g} mm；'
          f'正是本地窗把这一段补上')
    print(f'  绕向陷阱：若忽略 reverse 直接把子卷 x[{band[0]:g},{band[1]:g}] 当母卷 x，'
          f'会落到 x[{naive_mother[0]:g},{naive_mother[1]:g}]，同样报盲 '
          f'{naive_missing[0][1] - naive_missing[0][0]:g} mm')
    print(f'  横向证据：唯一覆盖缺口段的本地窗止于子卷 x={inspected_edge:g}，'
          f'只把带外 {verified_clearance:g} mm 认证为 clear；声明 {LATERAL_MARGIN:g} mm 还差 {shortfall:g} mm，'
          f'这 {shortfall:g} mm 落在窗边与测得疵点边 x={major["x0"]:g} 之间，只有疵点矩形作依据')
    print(f'  支撑：origin（唯一同时含母卷 x、y 的现有输出）、coverage.missing（整幅）、'
          f'face.evidence={face["evidence"]}、transfer 子卷坐标、layout.state 绕向')
    print()
    print('现有输出明确不承载的：')
    print('  · release/trim/runs/yield_plan/losses 只有纵向，没有横向子区间；')
    print('  · coverage.missing 是整幅口径：对本例低带偏保守（带已全覆盖），对镜像带恰好相同；')
    print('  · 合同 margin 只定义纵向安全边距；横向 %g mm 无字段、不进摘要；' % LATERAL_MARGIN)
    print('  · face 只有窗口并集面积，不能说明哪一条带完整；')
    print('  · defect_review 对疵点本身为 blind：3 mm 宽度只有一次测量，未被复检佐证；')
    print('  · shared.kept 说的是“留在子卷里”，不是“留在交付带上”；')
    print('  · trim 是“最长可用段”提议，不是该段或该带的签封行。')
    print()
    print('核对通过：示例由现有管线重算，两种读法的数值均可复现；'
          '去掉 review 后基础阶段逐字段不变。')


if __name__ == '__main__':
    main()
