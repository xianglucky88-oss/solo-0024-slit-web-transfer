from .contract import enum, ident, interval, invariant, num, obj, records
from .geometry import map_defect
from .intervals import gaps


def parse(source):
    width = num(source.get('width'), '母卷宽度', 1)
    length = num(source.get('length'), '母卷长度', 1)
    cuts = []
    for item in records(source.get('cuts'), '刀带', count=36, minimum=1):
        a, b = interval(item.get('a'), item.get('b'), '刀带', width)
        cuts.append(dict(id=item['id'], a=a, b=b,
                         winding=enum(item.get('winding'), ('forward','reverse'), '子卷绕向')))
    cuts.sort(key=lambda item: item['a'])
    invariant(all(first['b'] <= second['a'] for first,second in zip(cuts,cuts[1:])), '刀带不可重叠')
    lengths = {item['id']: length for item in cuts}
    defects = []
    for item in records(source.get('defects'), '疵点', count=240):
        x0,x1 = interval(item.get('x0'),item.get('x1'),'疵点幅向区间',width)
        y0,y1 = interval(item.get('y0'),item.get('y1'),'疵点走卷区间',length)
        defects.append(dict(id=item['id'], x0=x0,x1=x1,y0=y0,y1=y1,
                            grade=enum(item.get('grade'), ('minor','major'), '疵点级别')))
    checks = []
    for item in records(source.get('checks'), '复检窗', count=240):
        child = ident(item.get('child'), '复检子卷')
        invariant(child in lengths,'复检引用未知子卷')
        start,end = interval(item.get('start'),item.get('end'),'复检窗',length)
        checks.append(dict(id=item['id'],child=child,start=start,end=end))
    query = obj(source.get('query'), '回查区间')
    child = ident(query.get('child'), '回查子卷')
    invariant(child in lengths,'回查引用未知子卷')
    start,end = interval(query.get('start'),query.get('end'),'回查区间',length)
    return dict(width=width, length=length,cuts=cuts,defects=defects,checks=checks,
                query=(child,start,end), margin=num(source.get('margin'),'修剪预留',0,length))


def evaluate(model):
    cuts = model['cuts']
    waste = gaps([(cut['a'],cut['b']) for cut in cuts], model['width'])
    mapped = [row for cut in cuts for defect in model['defects']
              if (row := map_defect(defect,cut,model['length'])) is not None]
    scrap = []
    for i,(a,b) in enumerate(waste,1):
        ids = [d['id'] for d in model['defects'] if max(a,d['x0']) < min(b,d['x1'])]
        scrap.append(dict(id=f'edge-{i}',start=a,end=b,area=(b-a)*model['length'],evidence=ids,
                          state='marked' if ids else 'clear'))
    coverage = []
    for cut in cuts:
        relevant = [r for r in model['checks'] if r['child']==cut['id']]
        missing = gaps([(r['start'],r['end']) for r in relevant],model['length'])
        remain = sum(b-a for a,b in missing)
        coverage.append(dict(id=cut['id'],observed=model['length']-remain,missing=missing,
                             evidence=[r['id'] for r in relevant],state='blind' if missing else 'covered'))
    return dict(layout=[dict(id=cut['id'],start=cut['a'],end=cut['b'],width=cut['b']-cut['a'],state=cut['winding']) for cut in cuts],
                transfer=mapped,scrap=scrap,coverage=coverage)
