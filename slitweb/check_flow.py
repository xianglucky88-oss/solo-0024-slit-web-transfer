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


def control(port):
    before_sample = request(port, 'migration-before')[0]
    after_sample = request(port, 'migration-after')[0]
    left = request(port, 'seal', before_sample)[0]
    right = request(port, 'seal', after_sample)[0]
    left_packet = request(port, f"packet/{left['digest']}")[0]
    right_packet = request(port, f"packet/{right['digest']}")[0]

    def need(condition, message):
        if not condition:
            raise ValueError(message)

    def amounts(packet):
        rows = packet['outputs']['exclusion']
        return {state: sum(row['length'] for row in rows if row['state'] == state)
                for state in ('blocked', 'blind', 'mixed', 'eligible')}

    need(amounts(left_packet) == amounts(right_packet) ==
         dict(blocked=60, blind=80, mixed=0, eligible=860), '两版分因损失长度应各自持平')

    comparison = request(port, 'compare', dict(left=left['digest'], right=right['digest']))[0]
    result = comparison['physical']
    observed = json.loads((ROOT/'examples'/'migration-observations.json').read_text(encoding='utf8'))
    need(result['comparable'], '同母卷应可按实物位置对照')
    need(result['totals']['delta'] == 0, '改绕向并调整缺检后损失总长应恰好抵消')
    need((result['totals']['gap_before'], result['totals']['gap_after']) == (80, 80) and
         (result['totals']['defect_before'], result['totals']['defect_after']) == (60, 60),
         '两版缺检与重大损失分项应各自持平')
    need(result['totals']['released'] == 80 and result['totals']['restricted'] == 80,
         '应各有一段解除禁保与转为禁保的实物区段')
    need(all(result['totals'][key] == value for key, value in observed['totals'].items()),
         '长度合计与样例观测不一致')
    for name in ('released', 'restricted'):
        row, key, value, key2, value2 = observed[name]
        observe(result['regions'], row, key, value)
        observe(result['regions'], row, key2, value2)
    domain_row, domain_key, domain_value, key2, value2 = observed['domain']
    observe(result['domains'], domain_row, domain_key, domain_value)
    observe(result['domains'], domain_row, key2, value2)
    need(any(row['state'] == 'rewound' for row in result['domains']), '应报告绕向改变')
    need(request(port, 'compare', dict(left=left['digest'], right=left['digest']))[0]['rows'] == [],
         '同版按记录比对仍应无差异')

    moved = request(port, 'seal', request(port, 'sample')[0])[0]
    shifted = request(port, 'seal', request(port, 'alternate')[0])[0]
    domain = request(port, 'compare', dict(left=moved['digest'], right=shifted['digest']))[0]['physical']
    need(domain['totals']['domain'] > 0, '两版幅域不同处应记为幅域差异')
    need(all(row['cause'] != 'gap' for row in domain['regions'] if row['state'] == 'domain'),
         '幅域差异不应被当作缺检原地修复')

    other = request(port, 'seal', dict(after_sample, id='不同对象'))[0]
    request(port, 'compare', dict(left=left['digest'], right=other['digest']), status=409)
    need(request(port, f"packet/{left['digest']}")[0] == left_packet, '旧封存结果不应随对照改变')

    need(comparison['rows'], '按记录比对旧版能力仍应可用')


def audit(port, flow):
    if flow == 'migration':
        control(port)
        return
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
        if flow in cases:
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
    else:
        raise ValueError(f'未知工作流：{flow}')


def main():
    parser = argparse.ArgumentParser(description='运行有界的生产工作流检查')
    parser.add_argument('flow', choices=[op['id'] for op in CONFIG['operations']]+['seal','compare','export','migration'])
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
