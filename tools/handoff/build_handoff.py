"""离线返检资料包构建器。

职责边界：
- 只读取 examples/ 下已有的复核输入（不可信数据），调用仓库自带、已被 check_flow
  覆盖的归约管线（domain/rules/reconcile/review），不复制任何领域算法。
- 在归约成果之上做「交接编排」：按母卷原始疵点合并子卷分片、按母卷疵点分组的
  矛盾排序、把「只差复检的盲域」与「复检也无法解除的重大疵点禁保域」分开，
  并为每张工单保留证据出处与放弃理由。
- 仅写本地资料文件，不注册任何 HTTP 路由、不改工作台界面或服务代码。

运行：python3 -I tools/handoff/build_handoff.py
输出：handoff-kit/
"""
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from slitweb.archive import Archive  # noqa: E402
from slitweb.artifacts import digest  # noqa: E402
from slitweb.server import CONFIG  # noqa: E402
from slitweb.service import Workbench  # noqa: E402

KIT = ROOT / "handoff-kit"
PACKETS = KIT / "packets"
# 基线场景（当前班实际封存口径）与对照场景（另一操作者/另一刀位的冲突快照）。
BASELINE = "review-sample"
CONFLICT = "review-alternate"
ALL_INPUTS = ["sample", BASELINE, CONFLICT]

# 状态/枚举的现场术语，复用工作台同一套中文值，避免另造口径。
ZH = dict(CONFIG["values"])
ZH.setdefault("partial", "部分幅面复检")


def zh(value):
    return ZH.get(value, value)


def load(wb, name):
    source = json.loads((ROOT / "examples" / f"{name}.json").read_text(encoding="utf8"))
    packet = wb.analyze(source)
    return source, packet


def index(rows, key="id"):
    return {row[key]: row for row in rows}


def overlap_1d(a0, a1, b0, b1):
    return max(a0, b0) < min(a1, b1)


def build_origin_defects(source, packet):
    """原始疵点台账：每个母卷疵点一行，挂上其全部子卷分片与边料去向。

    关键去重：同一母卷疵点在多个子卷/边料中的分片在此处合并成一条，
    下游工单以母卷疵点为单位，绝不把分片当成两个优先件。
    """
    transfer = packet["outputs"]["transfer"]
    shared = index(packet["outputs"]["shared"])
    scrap = packet["outputs"]["scrap"]
    rows = []
    for defect in source["defects"]:
        did = defect["id"]
        fragments = [t for t in transfer if t["evidence"] == did]
        scrap_hits = [s["id"] for s in scrap if did in s["evidence"]]
        share = shared.get(did, {})
        rows.append({
            "origin_defect_id": did,
            "grade": defect["grade"],
            "grade_label": zh(defect["grade"]),
            "master_rect": {"x0": defect["x0"], "x1": defect["x1"],
                            "y0": defect["y0"], "y1": defect["y1"]},
            "spread_state": share.get("state"),
            "spread_label": zh(share.get("state")),
            "width": share.get("width"),
            "kept_width": share.get("kept"),
            "lost_width": share.get("lost"),
            "child_fragments": [
                {"transfer_id": f["id"], "child": f["child"],
                 "child_rect": {"x0": f["x0"], "x1": f["x1"],
                                "y0": f["y0"], "y1": f["y1"]},
                 "grade": f["state"], "grade_label": zh(f["state"])}
                for f in fragments],
            "scrap_destinations": scrap_hits,
            "evidence_sources": {
                "input_defect": did,
                "transfer_rows": [f["id"] for f in fragments],
                "shared_row": f"shared/{did}",
                "scrap_rows": [f"scrap/{s}" for s in scrap_hits]},
        })
    return rows


def build_scanned_regions(source, packet):
    """实际扫描/复检过的区域台账：走卷长度覆盖与幅面 2D 复检分开登记。"""
    coverage = index(packet["outputs"]["coverage"])
    face = index(packet["outputs"].get("face", []))
    checks_by_child = {}
    for chk in source["checks"]:
        checks_by_child.setdefault(chk["child"], []).append(chk)
    insp_by_child = {}
    for insp in source.get("review", {}).get("inspections", []):
        insp_by_child.setdefault(insp["child"], []).append(insp)

    rows = []
    for cut in source["cuts"]:
        cid = cut["id"]
        cov = coverage[cid]
        length_windows = [
            {"check_id": c["id"], "child": cid, "start": c["start"], "end": c["end"]}
            for c in checks_by_child.get(cid, [])]
        face_windows = [
            {"inspection_id": i["id"], "child": cid,
             "rect": {"x0": i["x0"], "x1": i["x1"], "y0": i["y0"], "y1": i["y1"]},
             "result": i["result"], "result_label": zh(i["result"])}
            for i in insp_by_child.get(cid, [])]
        f = face.get(cid, {})
        rows.append({
            "child": cid,
            "winding": cut["winding"],
            "winding_label": zh(cut["winding"]),
            "length_observed": cov["observed"],
            "length_total": source["length"],
            "length_gaps": cov["missing"],
            "length_state": cov["state"],
            "length_state_label": zh(cov["state"]),
            "length_check_windows": length_windows,
            "face_covered_area": f.get("area", 0),
            "face_total_area": f.get("total"),
            "face_state": f.get("state", "blind"),
            "face_state_label": zh(f.get("state", "blind")),
            "face_inspection_windows": face_windows,
            "evidence_sources": {
                "coverage_row": f"coverage/{cid}",
                "checks": [c["id"] for c in checks_by_child.get(cid, [])],
                "face_row": f"face/{cid}" if f else None,
                "inspections": [i["id"] for i in insp_by_child.get(cid, [])]},
        })
    return rows


def build_exclusion_classes(packet):
    """把禁保区间按「复检能否解除」分成互斥两类，这是任务的硬约束。

    - blind（缺检）：只差复检，补检且无重大疵点即可转可保。
    - blocked（重大疵点）：即使复检仍禁保，复检不能抵消重大疵点。
    - mixed（同段双因）：复检只能消掉其中的缺检因，重大疵点因仍在，整段仍禁保。
    - eligible：可保，无需返检。
    """
    classes = {"recoverable_by_recheck": [], "irreparable_major": [], "eligible": []}
    for seg in packet["outputs"]["exclusion"]:
        item = {"segment_id": seg["id"], "child": seg["child"],
                "start": seg["start"], "end": seg["end"], "length": seg["length"],
                "state": seg["state"], "state_label": zh(seg["state"]),
                "major_evidence": seg["evidence"],
                "evidence_sources": {"exclusion_row": f"exclusion/{seg['id']}",
                                     "losses_row": f"losses/{seg['child']}"}}
        if seg["state"] == "blind":
            item["reason"] = "仅缺检：该段无重大疵点证据，补检覆盖且未见重大疵点即可转可保。"
            classes["recoverable_by_recheck"].append(item)
        elif seg["state"] == "blocked":
            item["reason"] = ("重大疵点禁保：该段由重大疵点安全边距锁定，"
                              "复检无论结论如何都不能解除，只能修剪/降级处理。")
            classes["irreparable_major"].append(item)
        elif seg["state"] == "mixed":
            item["reason"] = ("双因段：同时落在重大疵点安全边距与缺检窗口内。"
                              "复检最多消除缺检因，重大疵点因仍在，整段依旧禁保；"
                              "不得与纯盲域混为同一类返检目标。")
            classes["irreparable_major"].append(item)
        else:
            classes["eligible"].append(item)
    return classes


def build_position_cards(source, packet):
    """同一物理位置的两套现场定位坐标：子卷本地坐标 ↔ 母卷坐标。

    反绕子卷需要两轴镜像，正绕子卷仅平移；全部数值取自 trace/origin/transfer
    归约结果，构建器不自行推导镜像公式。
    """
    cuts = {c["id"]: c for c in source["cuts"]}
    cards = []
    # 母卷回查（query）卡：子卷窗口 -> 母卷窗口
    trace = packet["outputs"]["trace"][0]
    q = source["query"]
    cards.append({
        "card": "query_trace",
        "child": q["child"],
        "winding": cuts[q["child"]]["winding"],
        "child_window": {"start": q["start"], "end": q["end"]},
        "master_window": {"start": trace["start"], "end": trace["end"]},
        "matched_origin_defects": trace["evidence"],
        "state": trace["state"],
        "evidence_sources": {"trace_row": "trace/乙卷", "input_query": "query"},
    })
    # 每个幅面复检窗：子卷矩形 -> 母卷矩形（origin 已做反绕还原）
    for org in packet["outputs"].get("origin", []):
        cards.append({
            "card": f"inspection_origin/{org['id']}",
            "child": org["child"],
            "winding": cuts[org["child"]]["winding"],
            "inspection_id": org["id"],
            "master_rect": {"x0": org["x0"], "x1": org["x1"],
                            "y0": org["y0"], "y1": org["y1"]},
            "inspection_result": org["state"],
            "inspection_result_label": zh(org["state"]),
            "matched_origin_defects": org["evidence"],
            "evidence_sources": {"origin_row": f"origin/{org['id']}"},
        })
    # 每个子卷疵点分片 -> 母卷原疵点矩形（用于现场按本地坐标找点）
    for tr in packet["outputs"]["transfer"]:
        origin_defect = next(d for d in source["defects"] if d["id"] == tr["evidence"])
        cards.append({
            "card": f"fragment_locate/{tr['id']}",
            "child": tr["child"],
            "winding": cuts[tr["child"]]["winding"],
            "origin_defect_id": tr["evidence"],
            "child_rect": {"x0": tr["x0"], "x1": tr["x1"], "y0": tr["y0"], "y1": tr["y1"]},
            "master_rect": {"x0": origin_defect["x0"], "x1": origin_defect["x1"],
                            "y0": origin_defect["y0"], "y1": origin_defect["y1"]},
            "grade": tr["state"],
            "evidence_sources": {"transfer_row": f"transfer/{tr['id']}",
                                 "input_defect": tr["evidence"]},
        })
    return cards


def contradiction_note(base_packet, conflict_packet, origin_defects):
    """两版快照之间、影响本次返检的现存矛盾，逐条列出并指认母卷疵点。"""
    base_dr = index(base_packet["outputs"]["defect_review"])
    conf_dr = index(conflict_packet["outputs"]["defect_review"])
    notes = []
    for od in origin_defects:
        for frag in od["child_fragments"]:
            tid = frag["transfer_id"]
            b, c = base_dr.get(tid), conf_dr.get(tid)
            if b and c and b["state"] != c["state"]:
                notes.append({
                    "origin_defect_id": od["origin_defect_id"],
                    "transfer_id": tid,
                    "child": frag["child"],
                    "baseline_state": b["state"],
                    "baseline_label": zh(b["state"]),
                    "conflict_state": c["state"],
                    "conflict_label": zh(c["state"]),
                    "baseline_grade": b["grade"],
                    "conflict_grade": c["grade"],
                    "contradiction": (
                        f"同一母卷疵点「{od['origin_defect_id']}」在 {frag['child']} 的分片，"
                        f"基线快照复核为「{zh(b['state'])}」，对照快照复核为「{zh(c['state'])}」；"
                        "且两版疵点分级不同，需一次返检统一结论。"),
                    "evidence_sources": {
                        "baseline_defect_review": f"defect_review/{tid}",
                        "conflict_defect_review": f"defect_review/{tid}",
                        "baseline_packet": base_packet["digest"],
                        "conflict_packet": conflict_packet["digest"]},
                })
    # 覆盖口径矛盾：基线乙卷有盲域，对照无盲域
    base_cov = index(base_packet["outputs"]["coverage"])
    conf_cov = index(conflict_packet["outputs"]["coverage"])
    for cid, b in base_cov.items():
        c = conf_cov[cid]
        if b["state"] != c["state"] or b["missing"] != c["missing"]:
            notes.append({
                "origin_defect_id": None,
                "transfer_id": None,
                "child": cid,
                "baseline_state": b["state"],
                "conflict_state": c["state"],
                "contradiction": (
                    f"子卷「{cid}」走卷覆盖口径不一致：基线缺口 {b['missing']}（{zh(b['state'])}），"
                    f"对照缺口 {c['missing']}（{zh(c['state'])}）。盲域是否仍存在需现场确认。"),
                "evidence_sources": {
                    "baseline_coverage": f"coverage/{cid}",
                    "conflict_coverage": f"coverage/{cid}"},
            })
    return notes


def build_work_orders(source, packet, origin_defects, exclusion_classes, contradictions):
    """生成返检工单。

    排序目标：让有限的一次返检澄清最多现存矛盾。
    去重规则：以母卷原始疵点为一个工单，跨子卷分片只做证据，不重复派单。
    分类规则：纯盲域（可被复检挽救）与重大疵点禁保域（复检也无解）严格分开。
    """
    transfer = packet["outputs"]["transfer"]
    defect_review = index(packet["outputs"]["defect_review"])
    coverage = index(packet["outputs"]["coverage"])
    orders = []
    order_seq = 1

    # 第一类：可被一次返检澄清的母卷疵点（按其能澄清的矛盾数排序）。
    contradiction_by_origin = {}
    for n in contradictions:
        if n["origin_defect_id"]:
            contradiction_by_origin.setdefault(n["origin_defect_id"], []).append(n)

    for od in origin_defects:
        did = od["origin_defect_id"]
        fragments = od["child_fragments"]
        dr_states = {f["transfer_id"]: defect_review.get(f["transfer_id"], {}).get("state")
                     for f in fragments}
        has_major = any(f["grade"] == "major" for f in fragments)
        in_blind = any(
            overlap_1d(f["child_rect"]["y0"], f["child_rect"]["y1"],
                       g0, g1)
            for f in fragments
            for g0, g1 in coverage[f["child"]]["missing"])
        contrad = contradiction_by_origin.get(did, [])

        # 决策：是否值得派返检，以及放弃理由。
        abandon_reasons = []
        recheck_targets = []
        priority = None

        if od["spread_state"] == "scrap" and not fragments:
            abandon_reasons.append(
                f"母卷疵点「{did}」整体落入边料（{', '.join(od['scrap_destinations'])}），"
                "不进入任何保留子卷，无返检价值，放弃派单。")
        elif not has_major and not in_blind and not contrad:
            # 走卷长度窗已无缺口（in_blind 为假）；幅面 2D 是否复检需另行说明，
            # 不能把「长度已覆盖」与「幅面已复检」混为一谈。
            face_unreviewed = [f["transfer_id"] for f in fragments
                               if dr_states.get(f["transfer_id"]) == "blind"]
            reason = (
                f"母卷疵点「{did}」为轻微疵点，其保留分片的走卷长度窗均无缺检缺口、"
                "也无跨快照矛盾，一次返检无法澄清任何现存矛盾，放弃派单。")
            if face_unreviewed:
                reason += (
                    " 说明：这些分片尚未做幅面 2D 复检（defect_review=blind），"
                    "但其走卷向已在复检窗内且为轻微疵点，不构成本次有限返检的优先目标；"
                    "如后续升级为重大或出现异议，再凭母卷坐标补 2D 复检。")
            abandon_reasons.append(reason)
        else:
            # 有返检价值：要么分级/结论矛盾，要么分片落在盲域。
            for f in fragments:
                child = f["child"]
                gaps = coverage[child]["missing"]
                hit_gaps = [[g0, g1] for g0, g1 in gaps
                            if overlap_1d(f["child_rect"]["y0"], f["child_rect"]["y1"], g0, g1)]
                recheck_targets.append({
                    "child": child,
                    "transfer_id": f["transfer_id"],
                    "child_rect": f["child_rect"],
                    "grade": f["grade"],
                    "current_review_state": dr_states.get(f["transfer_id"]),
                    "current_review_label": zh(dr_states.get(f["transfer_id"])),
                    "blind_gaps_on_this_fragment": hit_gaps,
                })
            # 重大疵点即使复检也不能解封，明确标注，避免现场误以为可改判。
            if has_major:
                abandon_reasons.append(
                    f"注意：母卷疵点「{did}」含重大(major)分片，复检结论不能解除其封样阻断；"
                    "本工单的返检目的仅限于澄清分级/复现矛盾与补齐盲域，不改变禁保事实。")
            score = len(contrad) + (1 if in_blind else 0) + (1 if has_major else 0)
            priority = score

        if recheck_targets:
            orders.append({
                "order_id": f"WO-{order_seq:02d}",
                "kind": "origin_defect_recheck",
                "origin_defect_id": did,
                "priority_score": priority,
                "priority_basis": {
                    "contradictions_clarified": len(contrad),
                    "touches_blind_gap": in_blind,
                    "has_major_fragment": has_major},
                "master_rect": od["master_rect"],
                "spread_state": od["spread_state"],
                "recheck_targets": recheck_targets,
                "contradictions": contrad,
                "expected_clarification": (
                    f"一次返检统一「{did}」在所有子卷分片的复现/分级结论，"
                    "并覆盖其落在盲域内的部分，消除跨快照矛盾。"),
                "abandon_or_limit_reasons": abandon_reasons,
                "evidence_sources": od["evidence_sources"],
            })
            order_seq += 1
        else:
            orders.append({
                "order_id": f"WO-{order_seq:02d}",
                "kind": "origin_defect_recheck",
                "origin_defect_id": did,
                "priority_score": 0,
                "disposition": "abandoned",
                "master_rect": od["master_rect"],
                "abandon_or_limit_reasons": abandon_reasons,
                "evidence_sources": od["evidence_sources"],
            })
            order_seq += 1

    # 第二类：纯盲域补检（不含重大疵点），这是「只差复检」的可挽救长度。
    for seg in exclusion_classes["recoverable_by_recheck"]:
        orders.append({
            "order_id": f"WO-{order_seq:02d}",
            "kind": "blind_gap_coverage",
            "priority_score": 2,
            "child": seg["child"],
            "target_segment": {"start": seg["start"], "end": seg["end"]},
            "length": seg["length"],
            "priority_basis": {"recoverable": True, "contains_major": False},
            "expected_clarification": (
                f"补检 {seg['child']} 走卷 {seg['start']}–{seg['end']}（长 {seg['length']}），"
                "该段无重大疵点证据，覆盖且未见重大疵点即可由盲域转可保。"),
            "abandon_or_limit_reasons": [],
            "evidence_sources": seg["evidence_sources"],
        })
        order_seq += 1

    # 第三类：复检也无解的重大/双因禁保段，登记为「不派返检」并写明放弃理由。
    for seg in exclusion_classes["irreparable_major"]:
        orders.append({
            "order_id": f"WO-{order_seq:02d}",
            "kind": "excluded_no_recheck",
            "priority_score": 0,
            "disposition": "abandoned",
            "child": seg["child"],
            "target_segment": {"start": seg["start"], "end": seg["end"]},
            "length": seg["length"],
            "state": seg["state"],
            "abandon_or_limit_reasons": [seg["reason"]],
            "evidence_sources": seg["evidence_sources"],
        })
        order_seq += 1

    # 排序：有派单的按 priority_score 降序、同序按工单序号；放弃件沉底。
    def sort_key(o):
        active = 0 if o.get("disposition") != "abandoned" else 1
        return (active, -o.get("priority_score", 0), o["order_id"])

    orders.sort(key=sort_key)
    # 重排名次（保留 order_id 作为稳定溯源号，另给执行顺位）。
    for rank, o in enumerate(orders, 1):
        o["execution_rank"] = rank if o.get("disposition") != "abandoned" else None
    return orders


def build_contingencies(source, packet, work_orders):
    """按不同现场定位条件都能执行的备选交接安排。"""
    cuts = {c["id"]: c for c in source["cuts"]}
    active = [o for o in work_orders if o.get("disposition") != "abandoned"]

    plan_a_local = []
    plan_b_master = []
    for o in active:
        if o["kind"] == "blind_gap_coverage":
            child = o["child"]
            winding = cuts[child]["winding"]
            s, e = o["target_segment"]["start"], o["target_segment"]["end"]
            length = source["length"]
            # 反绕子卷：本地走卷段映射回母卷纵向（与 salvage.reusable_runs 的 origin 同口径）。
            if winding == "reverse":
                master = [length - e, length - s]
            else:
                master = [s, e]
            plan_a_local.append({
                "order_id": o["order_id"], "child": child,
                "locate_by": "子卷本地走卷刻度",
                "child_window": [s, e],
                "note": "按子卷自身计米器/刻度定位，无需母卷台账。"})
            plan_b_master.append({
                "order_id": o["order_id"], "child": child,
                "locate_by": "母卷纵向坐标",
                "master_window": master,
                "winding": winding,
                "note": "在母卷台账按纵向区间定位，再依绕向还原到该子卷。"})
        else:
            for t in o["recheck_targets"]:
                child = t["child"]
                winding = cuts[child]["winding"]
                r = t["child_rect"]
                origin_defect = next(d for d in source["defects"]
                                     if d["id"] == o["origin_defect_id"])
                plan_a_local.append({
                    "order_id": o["order_id"], "child": child,
                    "origin_defect_id": o["origin_defect_id"],
                    "locate_by": "子卷本地坐标(幅向x,走卷y)",
                    "child_rect": r,
                    "note": "用子卷本地矩形找点，适合只能在子卷工位操作的现场。"})
                plan_b_master.append({
                    "order_id": o["order_id"], "child": child,
                    "origin_defect_id": o["origin_defect_id"],
                    "locate_by": "母卷坐标(幅向x,走卷y)",
                    "master_rect": {"x0": origin_defect["x0"], "x1": origin_defect["x1"],
                                    "y0": origin_defect["y0"], "y1": origin_defect["y1"]},
                    "winding": winding,
                    "note": "在母卷台账按原疵点矩形找点，反绕子卷需两轴镜像还原。"})

    # 方案 C：只能做走卷一维扫查、无法做幅面 2D 复检时的降级安排。
    plan_c_linear = []
    for o in active:
        if o["kind"] == "blind_gap_coverage":
            plan_c_linear.append({
                "order_id": o["order_id"], "child": o["child"],
                "linear_window": [o["target_segment"]["start"], o["target_segment"]["end"]],
                "capability": "一维走卷复检",
                "note": "仅确认该走卷段是否覆盖；不能判定幅向 2D 位置，结论保守。"})
        else:
            # 不同子卷是独立物理卷、绕向可能相反，一维窗必须按子卷分别给出，
            # 不能跨子卷合并走卷区间。
            for t in o["recheck_targets"]:
                r = t["child_rect"]
                plan_c_linear.append({
                    "order_id": o["order_id"], "child": t["child"],
                    "origin_defect_id": o["origin_defect_id"],
                    "linear_window": [r["y0"], r["y1"]],
                    "winding": cuts[t["child"]]["winding"],
                    "capability": "一维走卷复检",
                    "note": "只能在该子卷走卷向上定位母卷疵点带，幅向归属需回工位后补 2D 复检。"})

    return {
        "plan_a_child_local": {
            "condition": "现场可在子卷工位按子卷本地坐标/计米刻度定位。",
            "steps": plan_a_local},
        "plan_b_master_ledger": {
            "condition": "现场可查母卷台账、按母卷坐标定位（反绕子卷需镜像还原）。",
            "steps": plan_b_master},
        "plan_c_linear_only": {
            "condition": "扫描设备只能做走卷一维扫查、无幅面 2D 复检能力。",
            "steps": plan_c_linear},
    }


def write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf8")


def main():
    wb = Workbench(Archive(":memory:"), CONFIG)
    loaded = {name: load(wb, name) for name in ALL_INPUTS}
    base_source, base_packet = loaded[BASELINE]
    _, conflict_packet = loaded[CONFLICT]

    for name, (_src, packet) in loaded.items():
        write_json(PACKETS / f"{name}.packet.json", packet)

    origin_defects = build_origin_defects(base_source, base_packet)
    scanned = build_scanned_regions(base_source, base_packet)
    exclusion_classes = build_exclusion_classes(base_packet)
    position_cards = build_position_cards(base_source, base_packet)
    contradictions = contradiction_note(base_packet, conflict_packet, origin_defects)
    work_orders = build_work_orders(base_source, base_packet, origin_defects,
                                    exclusion_classes, contradictions)
    contingencies = build_contingencies(base_source, base_packet, work_orders)

    write_json(KIT / "01-origin-defect-ledger.json",
               {"subject": base_source["id"], "generated_from": BASELINE,
                "dedup_rule": "按母卷原始疵点合并所有子卷/边料分片，每疵点仅一条。",
                "rows": origin_defects})
    write_json(KIT / "02-scanned-regions.json",
               {"subject": base_source["id"],
                "note": "走卷长度覆盖与幅面2D复检分开登记；重复窗按并集只计一次。",
                "rows": scanned})
    write_json(KIT / "03-exclusion-classification.json",
               {"subject": base_source["id"], **exclusion_classes})
    write_json(KIT / "04-position-cards.json",
               {"subject": base_source["id"],
                "note": "同一物理位置的子卷本地坐标与母卷坐标对照，反绕已镜像还原。",
                "cards": position_cards})
    write_json(KIT / "05-contradictions.json",
               {"subject": base_source["id"],
                "baseline_packet": base_packet["digest"],
                "conflict_packet": conflict_packet["digest"],
                "rows": contradictions})
    write_json(KIT / "06-recheck-work-orders.json",
               {"subject": base_source["id"],
                "single_pass_goal": "一次返检澄清最多现存矛盾；按母卷疵点去重；盲域与重大禁保域分开。",
                "orders": work_orders})
    write_json(KIT / "07-contingency-handoff.json",
               {"subject": base_source["id"], **contingencies})

    manifest = {
        "kit": "离线返检资料包",
        "subject": base_source["id"],
        "built_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "build_date": date.today().isoformat(),
        "baseline_input": BASELINE,
        "conflict_input": CONFLICT,
        "baseline_packet_digest": base_packet["digest"],
        "conflict_packet_digest": conflict_packet["digest"],
        "files": [],
    }
    deliverables = [
        "01-origin-defect-ledger.json", "02-scanned-regions.json",
        "03-exclusion-classification.json", "04-position-cards.json",
        "05-contradictions.json", "06-recheck-work-orders.json",
        "07-contingency-handoff.json"]
    for name in deliverables:
        raw = (KIT / name).read_bytes()
        manifest["files"].append({"file": name, "sha256": digest(json.loads(raw))})
    for name in ALL_INPUTS:
        packet = loaded[name][1]
        manifest["files"].append({"file": f"packets/{name}.packet.json",
                                  "sha256": packet["digest"],
                                  "source_digest": packet["source_digest"]})
    write_json(KIT / "manifest.json", manifest)
    print("资料包已生成：", KIT)
    print("基线成果摘要：", base_packet["digest"][:16])
    print("工单总数：", len(work_orders),
          " 活跃：", sum(1 for o in work_orders if o.get("disposition") != "abandoned"),
          " 放弃：", sum(1 for o in work_orders if o.get("disposition") == "abandoned"))


if __name__ == "__main__":
    main()
