"""离线返检资料包的不变量校验（独立于构建器读取成品文件）。

核对任务的四条硬约束：
1. 同一母卷疵点的跨子卷分片不会被当成两个优先工单（按母卷疵点去重）。
2. 「只差复检的盲域」与「复检也无解的重大/双因禁保域」严格互斥、不混类。
3. 每张工单都带证据出处；每个放弃件都带放弃理由。
4. manifest 的摘要与成品文件实际摘要一致；packets 摘要可被 artifacts 复核。

运行：python3 -I tools/handoff/verify_handoff.py
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from slitweb.artifacts import digest, verify_packet  # noqa: E402

KIT = ROOT / "handoff-kit"
failures = []


def check(condition, message):
    if not condition:
        failures.append(message)


def load(name):
    return json.loads((KIT / name).read_text(encoding="utf8"))


def main():
    ledger = load("01-origin-defect-ledger.json")
    exclusion = load("03-exclusion-classification.json")
    orders = load("06-recheck-work-orders.json")["orders"]
    manifest = load("manifest.json")

    origin_ids = [r["origin_defect_id"] for r in ledger["rows"]]
    check(len(origin_ids) == len(set(origin_ids)), "母卷疵点台账存在重复疵点")

    # 约束 1：每个母卷疵点最多一张活跃疵点工单；分片只出现在该工单的 targets 内。
    active_defect_orders = [o for o in orders
                            if o["kind"] == "origin_defect_recheck"
                            and o.get("disposition") != "abandoned"]
    seen = [o["origin_defect_id"] for o in active_defect_orders]
    check(len(seen) == len(set(seen)), "同一母卷疵点被派成了多个优先工单")
    for o in active_defect_orders:
        frags = o["recheck_targets"]
        # 所有 target 必须溯源到同一个母卷疵点（transfer_id 形如 子卷/母卷疵点）
        check(all(t["transfer_id"].split("/", 1)[1] == o["origin_defect_id"]
                  for t in frags), f"{o['order_id']} 混入了其他母卷疵点的分片")
        check(len(frags) == len({t["transfer_id"] for t in frags}),
              f"{o['order_id']} 分片重复")

    # 约束 2：可挽救盲域与不可解禁保域互斥，按 exclusion 段号不重叠。
    recover = {(s["child"], s["start"], s["end"])
               for s in exclusion["recoverable_by_recheck"]}
    irreparable = {(s["child"], s["start"], s["end"])
                   for s in exclusion["irreparable_major"]}
    check(recover.isdisjoint(irreparable), "盲域与重大/双因禁保域出现重叠混类")
    # 可挽救段必须确实无重大疵点证据
    check(all(not s["major_evidence"] for s in exclusion["recoverable_by_recheck"]),
          "可挽救盲域内混入了重大疵点证据")
    # 不可解段必须有重大疵点证据
    check(all(s["major_evidence"] for s in exclusion["irreparable_major"]),
          "存在无重大疵点证据却被标为不可解的禁保段")
    # 三类长度互斥且与各子卷总长守恒（与 losses 口径一致）
    packets = {p["file"].split("/")[1].split(".")[0]:
               json.loads((KIT / p["file"]).read_text(encoding="utf8"))
               for p in manifest["files"] if p["file"].startswith("packets/")}
    base = next(p for n, p in packets.items() if n == manifest["baseline_input"])
    losses = {r["id"]: r for r in base["outputs"]["losses"]}
    for child in {c for c, _, _ in recover | irreparable}:
        rows = [s for s in exclusion["recoverable_by_recheck"]
                + exclusion["irreparable_major"]
                + exclusion["eligible"] if s["child"] == child]
        total = sum(s["length"] for s in rows)
        check(total == base["source"]["length"],
              f"{child} 禁保分类长度不守恒：{total} != {base['source']['length']}")
        lr = losses[child]
        check(lr["blind"] == sum(s["length"] for s in exclusion["recoverable_by_recheck"]
                                 if s["child"] == child), f"{child} 盲域长度与 losses 不符")
        check(lr["blocked"] + lr["mixed"] ==
              sum(s["length"] for s in exclusion["irreparable_major"]
                  if s["child"] == child), f"{child} 重大/双因长度与 losses 不符")

    # 约束 3：每张工单都有证据；每个放弃件都有放弃理由。
    for o in orders:
        check(o.get("evidence_sources"), f"{o['order_id']} 缺少证据出处")
        if o.get("disposition") == "abandoned":
            check(o.get("abandon_or_limit_reasons"), f"{o['order_id']} 放弃但无放弃理由")
        else:
            check(o.get("execution_rank") is not None, f"{o['order_id']} 活跃但无执行顺位")

    # 活跃工单按优先级单调不增
    actives = [o for o in orders if o.get("disposition") != "abandoned"]
    scores = [o["priority_score"] for o in actives]
    check(scores == sorted(scores, reverse=True), "活跃工单未按优先级降序")

    # 约束 4：manifest 摘要与文件一致；packet 可被 verify_packet 复核。
    for entry in manifest["files"]:
        raw = (KIT / entry["file"]).read_bytes()
        if entry["file"].startswith("packets/"):
            packet = json.loads(raw)
            verify_packet(packet)  # 抛错即失败
            check(packet["digest"] == entry["sha256"], f"{entry['file']} 摘要不符")
        else:
            check(digest(json.loads(raw)) == entry["sha256"],
                  f"{entry['file']} manifest 摘要不符")

    # 备选交接：三种定位条件都覆盖了全部活跃工单
    contingency = load("07-contingency-handoff.json")
    active_ids = {o["order_id"] for o in actives}
    for plan in ("plan_a_child_local", "plan_b_master_ledger", "plan_c_linear_only"):
        covered = {s["order_id"] for s in contingency[plan]["steps"]}
        check(active_ids <= covered, f"{plan} 未覆盖全部活跃工单：{active_ids - covered}")

    if failures:
        print("校验失败：")
        for f in failures:
            print(" -", f)
        sys.exit(1)
    print(f"全部不变量通过：{len(active_defect_orders)} 张活跃疵点工单、"
          f"{len(exclusion['recoverable_by_recheck'])} 段可挽救盲域、"
          f"{len(exclusion['irreparable_major'])} 段不可解禁保、"
          f"{sum(1 for o in orders if o.get('disposition')=='abandoned')} 个放弃件均有理由。")


if __name__ == "__main__":
    main()
