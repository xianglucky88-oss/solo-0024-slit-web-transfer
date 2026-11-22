from .intervals import union


def summarize(model, facts, outputs):
    result = []
    for coverage in facts['coverage']:
        child = coverage['id']
        length, margin = model['length'], model['margin']
        defects = [(max(0, row['y0']-margin), min(length, row['y1']+margin), row['evidence'])
                   for row in facts['transfer'] if row['child'] == child and row['state'] == 'major']
        missing = coverage['missing']
        boundaries = sorted({0, length} | {x for a,b,_ in defects for x in (a,b)} | {x for ab in missing for x in ab})
        kept = []
        for n,(a,b) in enumerate(zip(boundaries,boundaries[1:]), 1):
            sources = sorted({key for lo,hi,key in defects if lo <= a < hi})
            blind = any(lo <= a < hi for lo,hi in missing)
            state = 'mixed' if blind and sources else 'blocked' if sources else 'blind' if blind else 'eligible'
            result.append(dict(id=f'{child}/{n}', child=child, start=a, end=b, length=b-a, state=state, evidence=sources))
            if state == 'eligible':
                kept.append((a,b))
        longest = max((b-a for a,b in union(kept)), default=0)
        trim = next(row for row in outputs['trim'] if row['id'] == child)
        if longest != trim['length']:
            raise RuntimeError('区间账与连续修剪长度不一致')
    return result
