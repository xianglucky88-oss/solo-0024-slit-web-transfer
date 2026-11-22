from .intervals import gaps


def decide(model, facts):
    verdicts, trim = [], []
    length,margin = model['length'],model['margin']
    for coverage in facts['coverage']:
        child = coverage['id']
        bad = [row for row in facts['transfer'] if row['child']==child and row['state']=='major']
        evidence = [r['evidence'] for r in bad]
        state = 'blocked' if bad else 'pending' if coverage['missing'] else 'ready'
        verdicts.append(dict(id=child, state=state, count=len(bad), missing=coverage['missing'], evidence=evidence))
        rejected = [(max(0,row['y0']-margin),min(length,row['y1']+margin)) for row in bad] + [tuple(x) for x in coverage['missing']]
        usable = gaps(rejected,length)
        a,b = max(usable,key=lambda p: (p[1]-p[0],-p[0])) if usable else (None,None)
        trim.append(dict(id=child,state='proposed' if usable else 'blocked',start=a,end=b,
                         length=b-a if usable else 0,evidence=evidence,missing=coverage['missing']))
    child,start,end = model['query']
    cut = next(c for c in model['cuts'] if c['id']==child)
    a,b = (model['length']-end,model['length']-start) if cut['winding']=='reverse' else (start,end)
    matched = [d['id'] for d in model['defects'] if max(a,d['y0'])<min(b,d['y1']) and max(cut['a'],d['x0'])<min(cut['b'],d['x1'])]
    query = [dict(id=child,start=a,end=b,evidence=matched,state='marked' if matched else 'clear')]
    return dict(facts,release=verdicts,trim=trim,trace=query)
