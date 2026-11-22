"""按母卷实物位置对照两版禁保区间与长度损失账。

子卷坐标随绕向变化，段号也随边界变化，按记录标识逐段相减会把同一条实物
区段误报成“消失 + 新增”。跨版本核账先把每段禁保区间还原到母卷纵向坐标，
再在刀带公共幅域上比较；两版幅域不重合、或结论由越出公共幅域的疵点引起时，
只记为幅域差异，不当成原地修复或新增疵点。
"""


def _span(row, cut, length):
    """把子卷走卷区间还原为母卷实物纵向区间。"""
    if cut['winding'] == 'reverse':
        return length - row['end'], length - row['start']
    return row['start'], row['end']


def ledger(packet):
    """把一个成果包归约成母卷坐标下的逐段禁保账。"""
    source = packet['source']
    length = source['length']
    rows = packet['outputs'].get('exclusion')
    if not isinstance(rows, list):
        return None
    defects = {item['id']: (item['x0'], item['x1']) for item in source.get('defects', [])}
    children = {}
    for cut in source.get('cuts', []):
        spans = []
        for row in rows:
            if row.get('child') != cut['id']:
                continue
            start, end = _span(row, cut, length)
            spans.append(dict(start=start, end=end, state=row['state'],
                              major=sorted(set(row.get('evidence') or []))))
        spans.sort(key=lambda item: item['start'])
        children[cut['id']] = dict(id=cut['id'], a=cut['a'], b=cut['b'],
                                   winding=cut['winding'], spans=spans)
    return dict(length=length, width=source['width'], defects=defects, children=children)


def _at(spans, point):
    for span in spans:
        if span['start'] <= point < span['end']:
            return span
    return None


def _verdict(span):
    if span is None:
        return None, dict(major=[], blind=False)
    return span['state'], dict(major=list(span['major']),
                               blind=span['state'] in ('blind', 'mixed'))


def _cause(before, after):
    major = before['major'] != after['major']
    blind = before['blind'] != after['blind']
    if major and blind:
        return 'both'
    if major:
        return 'defect'
    if blind:
        return 'gap'
    return None


def _transition(before, after, cause):
    if before == 'eligible' and after == 'eligible':
        return 'retained'
    if before == 'eligible':
        return 'restricted'
    if after == 'eligible':
        return 'released'
    return 'shifted' if cause else 'held'


def _clip(defects, key, cut):
    """疵点矩形落在某一版刀带内的横向片段；缺失记录按空片段处理。"""
    span = defects.get(key)
    if span is None or cut is None:
        return None
    lo, hi = max(span[0], cut['a']), min(span[1], cut['b'])
    return (lo, hi) if lo < hi else None


def _attributable(left, right, before_cut, after_cut, keys, common):
    """结论变化是否可在相同实物幅域内归因。

    两版刀带相同则直接可比；刀带移动时，只有引起变化的疵点在两版中被
    同一段实物幅域切到时才可比，否则差异来自幅域本身。
    """
    if [before_cut['a'], before_cut['b']] == [after_cut['a'], after_cut['b']]:
        return True
    if common is None:
        return False
    for key in keys:
        if _clip(left['defects'], key, before_cut) != _clip(right['defects'], key, after_cut):
            return False
    return True


def _strips(before, after, common):
    if common is None:
        strips = []
        if before is not None:
            strips.append(dict(state='dropped', x0=before['a'], x1=before['b'],
                               width=before['b'] - before['a']))
        if after is not None:
            strips.append(dict(state='gained', x0=after['a'], x1=after['b'],
                               width=after['b'] - after['a']))
        return strips
    strips = []
    lo, hi = common
    if before is not None and before['a'] < lo:
        strips.append(dict(state='dropped', x0=before['a'], x1=lo, width=lo - before['a']))
    if after is not None and after['a'] < lo:
        strips.append(dict(state='gained', x0=after['a'], x1=lo, width=lo - after['a']))
    if before is not None and before['b'] > hi:
        strips.append(dict(state='dropped', x0=hi, x1=before['b'], width=before['b'] - hi))
    if after is not None and after['b'] > hi:
        strips.append(dict(state='gained', x0=hi, x1=after['b'], width=after['b'] - hi))
    return strips


def compare_physical(left_packet, right_packet):
    """按母卷实物位置给出继续可保、转为禁保、解除禁保与幅域差异。"""
    left = ledger(left_packet)
    right = ledger(right_packet)
    empty = dict(regions=[], domains=[], totals={})
    if left is None or right is None:
        return dict(comparable=False, reason='缺少禁保区间记录，无法按实物位置对照',
                    length=None, width=None, **empty)
    if (left['length'], left['width']) != (right['length'], right['width']):
        return dict(comparable=False, reason='两版母卷规格不同，不能按实物位置对照',
                    length=None, width=None, **empty)

    length = left['length']
    regions, domains = [], []
    for child_id in sorted(set(left['children']) | set(right['children'])):
        before_cut, after_cut = left['children'].get(child_id), right['children'].get(child_id)
        common = None
        if before_cut and after_cut:
            lo, hi = max(before_cut['a'], after_cut['a']), min(before_cut['b'], after_cut['b'])
            common = [lo, hi] if lo < hi else None
        if common is None:
            if before_cut is None:
                state = 'band_added'
            elif after_cut is None:
                state = 'band_withdrawn'
            else:
                state = 'disjoint'
            domains.append(dict(
                id=child_id, child=child_id, state=state, common=None,
                before=[before_cut['a'], before_cut['b']] if before_cut else None,
                after=[after_cut['a'], after_cut['b']] if after_cut else None,
                before_winding=before_cut['winding'] if before_cut else None,
                after_winding=after_cut['winding'] if after_cut else None,
                strips=_strips(before_cut, after_cut, None)))
            continue
        before_domain = [before_cut['a'], before_cut['b']]
        after_domain = [after_cut['a'], after_cut['b']]
        rewound = before_cut['winding'] != after_cut['winding']
        if before_domain != after_domain or rewound:
            domains.append(dict(
                id=child_id, child=child_id,
                state='moved' if before_domain != after_domain else 'rewound',
                common=common, before=before_domain, after=after_domain,
                before_winding=before_cut['winding'], after_winding=after_cut['winding'],
                strips=_strips(before_cut, after_cut, common)))

        before_spans, after_spans = before_cut['spans'], after_cut['spans']
        edges = sorted({0, length}
                       | {value for span in before_spans for value in (span['start'], span['end'])}
                       | {value for span in after_spans for value in (span['start'], span['end'])})
        for start, end in zip(edges, edges[1:]):
            if start == end:
                continue
            point = (start + end) / 2
            before_span, after_span = _at(before_spans, point), _at(after_spans, point)
            if before_span is None and after_span is None:
                continue
            before_label, before_evidence = _verdict(before_span)
            after_label, after_evidence = _verdict(after_span)
            changed = sorted(set(before_evidence['major']) ^ set(after_evidence['major']))
            attributable = _attributable(left, right, before_cut, after_cut, changed, common)
            if not attributable:
                state, cause = 'domain', 'domain'
            else:
                cause = _cause(before_evidence, after_evidence)
                state = _transition(before_label, after_label, cause)
            regions.append(dict(
                id=f'{child_id}@{start}-{end}', child=child_id,
                start=start, end=end, length=end - start,
                x0=common[0], x1=common[1],
                state=state, cause=cause,
                before=before_label, after=after_label,
                before_winding=before_cut['winding'], after_winding=after_cut['winding'],
                evidence=dict(before=before_evidence, after=after_evidence)))

    def total(predicate):
        return sum(region['length'] for region in regions if predicate(region))

    def measured(predicate):
        """只把能在公共幅域内归因的区段计入损失账；幅域差异单列。"""
        return sum(region['length'] for region in regions
                   if predicate(region) and region['state'] != 'domain')

    loss_before = measured(lambda region: region['before'] not in (None, 'eligible'))
    loss_after = measured(lambda region: region['after'] not in (None, 'eligible'))

    def lost(kind, when):
        return measured(lambda region: region['evidence'][when]['blind'] if kind == 'gap'
                        else bool(region['evidence'][when]['major']))

    totals = dict(
        evaluated=total(lambda region: True),
        loss_before=loss_before, loss_after=loss_after, delta=loss_after - loss_before,
        gap_before=lost('gap', 'before'), gap_after=lost('gap', 'after'),
        defect_before=lost('defect', 'before'), defect_after=lost('defect', 'after'),
        retained=total(lambda region: region['state'] == 'retained'),
        restricted=total(lambda region: region['state'] == 'restricted'),
        released=total(lambda region: region['state'] == 'released'),
        held=total(lambda region: region['state'] == 'held'),
        shifted=total(lambda region: region['state'] == 'shifted'),
        domain=total(lambda region: region['state'] == 'domain'))
    return dict(comparable=True, reason=None, length=length, width=left['width'],
                regions=regions, domains=domains, totals=totals)
