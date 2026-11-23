import argparse
import json
from math import isclose
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Thread
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from .server import CONFIG, PREFIX, ROOT, serve


def request(port, route, body=None, status=200):
    url = f'http://127.0.0.1:{port}{PREFIX}{route}'
    opts = {} if body is None else dict(data=json.dumps(body).encode(), headers={'Content-Type': 'application/json'})
    response = None
    try:
        response = urlopen(Request(url, **opts), timeout=5)
    except HTTPError as failure:
        response = failure
    with response:
        if response.status != status:
            raise ValueError(f'{route}：状态码 {response.status}，预期 {status}；{response.read(300)!r}')
        return json.load(response), response.headers


def observe(rows, row_id, field, target):
    result = next((row for row in rows if row['id'] == row_id), None)
    if field is None:
        if result is not None:
            raise ValueError(f'{row_id} 不应出现在结果中')
        return
    actual = result.get(field) if result is not None else None
    ok = isclose(actual, target, abs_tol=1e-8) if type(target) is float and type(actual) in (int,float) else actual == target
    if not ok or result is None or field not in result:
        raise ValueError(f'{row_id}.{field} 为 {actual!r}，应为 {target!r}')


def audit(port, flow):
    review = any(op['id'] == flow and op.get('optional') for op in CONFIG['operations'])
    prefix = 'review-' if review else ''
    data = request(port, prefix+'sample')[0]
    alt = request(port, prefix+'alternate')[0]
    bad = json.loads((ROOT/'examples'/(prefix+'reject.json')).read_text(encoding='utf8'))
    original = request(port,'evaluate',data)[0]
    alternate = request(port,'evaluate',alt)[0]
    request(port,'evaluate',bad,status=400)
    if review:
        request(port, 'seal', bad, status=400)
        baselines = [request(port, 'evaluate', request(port, name)[0])[0] for name in ('sample', 'alternate')]
        for baseline, enhanced in zip(baselines, (original, alternate), strict=True):
            if flow in baseline['outputs'] or any(enhanced['outputs'][k] != v for k,v in baseline['outputs'].items()):
                raise ValueError('复核改变了基础口径')
    if flow in original['outputs']:
        cases = json.loads((ROOT/'examples'/(prefix+'observations.json')).read_text(encoding='utf8'))
        row, key, value, alt_row, alt_key, alt_value = cases[flow]
        observe(original['outputs'][flow],row,key,value)
        observe(alternate['outputs'][flow],alt_row,alt_key,alt_value)
        return
    request(port,'seal',bad,status=400)
    left = request(port,'seal',data)[0]
    again = request(port,'seal',data)[0]
    right = request(port,'seal',alt)[0]
    if not left['created'] or again['created'] or again['sequence'] != left['sequence'] or not right['created']:
        raise ValueError('版本去重或首写失败')
    if len(request(port,'revisions')[0]) != 2:
        raise ValueError('无效及重复记录不应该入库')
    if flow == 'seal':
        observed = request(port,f"packet/{left['digest']}")[0]
        if observed != original:
            raise ValueError('较新的归约改变了历史成果')
    elif flow == 'compare':
        versions = dict(left=left['digest'],right=right['digest'])
        changes = request(port,'compare',versions)[0]
        if not changes['rows'] or request(port,'compare',dict(left=left['digest'],right=left['digest']))[0]['rows']:
            raise ValueError('版本比对没有区分同版及异版')
        other = request(port,'seal',dict(alt,id='不同对象'))[0]
        request(port,'compare',dict(left=left['digest'],right=other['digest']),status=409)
        base = request(port, 'seal', request(port, 'review-sample')[0])[0]
        mixed = request(port, 'compare', dict(left=left['digest'], right=base['digest']))[0]
        stages = {op['label'] for op in CONFIG['operations'] if op.get('optional')}
        if not mixed['rows'] or any(row['stage'] not in stages or row['state'] != 'added' for row in mixed['rows']):
            raise ValueError('旧版比对只应报告新增的复核结果')
        if request(port, f"export/{base['digest']}")[0] != request(port, f"packet/{base['digest']}")[0]:
            raise ValueError('复核信息未完整保存')
    elif flow == 'export':
        payload, headers = request(port,f"export/{left['digest']}")
        if payload != original or 'attachment;' not in headers.get('Content-Disposition',''):
            raise ValueError('导出没有保留原版本或下载头')
        request(port,'export/' + '0'*64,status=404)
    elif flow == 'reuse':
        origin = json.loads((ROOT/'examples'/'reuse-origin.json').read_text(encoding='utf8'))
        plan = json.loads((ROOT/'examples'/'reuse-plan.json').read_text(encoding='utf8'))
        old = request(port,'seal',origin)[0]
        new = request(port,'seal',plan)[0]
        if not old['created'] or not new['created']:
            raise ValueError('转用试算材料封存失败')
        segment = dict(start=120,end=880)
        result = request(port,'reuse',dict(left=old['digest'],right=new['digest'],**segment))[0]
        if result['subject'] != origin['id'] or result['segment'] != [120,880]:
            raise ValueError('转用试算应回显同一母卷与目标段')
        expected = {
            '丙卷': dict(winding='reverse',clean=8220,marked=0,conflict=0,lacking=33580,target=41800,
                         state='partial',evidence=['乙跨窗','甲净窗']),
            '丁卷': dict(winding='forward',clean=2650,marked=950,conflict=1050,lacking=21950,target=26600,
                         state='conflict',evidence=['乙净窗','乙标窗','乙跨窗']),
        }
        rows = {row['id']: row for row in result['rows']}
        if set(rows) != set(expected):
            raise ValueError('转用试算应覆盖新方案全部刀带')
        for child, want in expected.items():
            row = rows[child]
            for key, value in want.items():
                actual = row.get(key)
                ok = isclose(actual,value,abs_tol=1e-8) if type(value) in (int,float) else actual == value
                if not ok:
                    raise ValueError(f'{child}.{key} 为 {actual!r}，应为 {value!r}')
            if not isclose(row['clean']+row['marked']+row['conflict']+row['lacking'],row['target'],abs_tol=1e-8):
                raise ValueError('四类幅面应不重不漏拼成目标幅面')
        if '乙跨窗' not in rows['丙卷']['evidence'] or '乙跨窗' not in rows['丁卷']['evidence']:
            raise ValueError('一处旧区域应分给跨缝的两条新刀带')
        flat = request(port,'reuse',dict(left=left['digest'],right=new['digest'],**segment))[0]
        if any(row['clean'] or row['marked'] or row['conflict'] or row['state'] != 'blind'
               or not isclose(row['lacking'],row['target'],abs_tol=1e-8) for row in flat['rows']):
            raise ValueError('只有纵向检查窗的旧档不能充当二维证据')
        other = request(port,'seal',dict(plan,id='另一母卷'))[0]
        request(port,'reuse',dict(left=old['digest'],right=other['digest'],**segment),status=409)
        wider = request(port,'seal',dict(plan,width=120))[0]
        request(port,'reuse',dict(left=old['digest'],right=wider['digest'],**segment),status=409)
        request(port,'reuse',dict(left=old['digest'],right=new['digest'],start=880,end=120),status=400)
        request(port,'reuse',dict(left=old['digest'],right=new['digest'],start=0,end=1200),status=400)
        request(port,'reuse',dict(left=old['digest'],right=new['digest'],start=120),status=400)
        request(port,'reuse',dict(left='0'*64,right=new['digest'],**segment),status=404)
        if request(port,f"packet/{old['digest']}")[0] != request(port,'evaluate',origin)[0]:
            raise ValueError('转用试算改写了已封存旧档')
        if len(request(port,'revisions')[0]) != 6:
            raise ValueError('转用试算不应写入成果库或替新方案签封')
    else:
        raise ValueError(f'未知工作流：{flow}')


def main():
    parser = argparse.ArgumentParser(description='运行有界的生产工作流检查')
    parser.add_argument('flow', choices=[op['id'] for op in CONFIG['operations']]+['seal','compare','export','reuse'])
    args = parser.parse_args()
    with TemporaryDirectory(prefix=CONFIG['namespace']+'-') as directory:
        with serve(Path(directory)/'observations.sqlite', 0) as server:
            thread = Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                audit(server.server_port,args.flow)
            finally:
                server.shutdown()
                thread.join()
    print(f'{args.flow}：样例、对照与合法拒绝均已核对')


if __name__ == '__main__':
    main()
