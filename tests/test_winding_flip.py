"""绕向翻转端到端回归：从 HTTP 输入一直走到封存与导出下载。

同一实物材料（tests/winding_fixture.py）提交正绕、反绕两版，断言：

1. 母卷回查（trace）与复检反查（origin）在两版里都指向同一个疵点，
   贴边区域严格不算交集；
2. 走卷标签（layout.state）与转印坐标确实随反绕换位；
3. 面积、分摊、封样判定、分因长度等实物不变量两版完全一致；
4. 封存按摘要去重、导出内容与下载头保留完整历史快照；
5. compare 只允许白名单字段变化，其余阶段零差异。

不修改任何生产判定代码；全部期望由夹具几何独立重算。
"""

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Thread
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from slitweb.server import CONFIG, PREFIX, serve

from . import winding_fixture as fx
from .invariants import (assert_layout_label_swapped, assert_transfer_invariants,
                         mirror_child_y, strict_overlap)


def call(port, route, body=None, status=200):
    url = f"http://127.0.0.1:{port}{PREFIX}{route}"
    opts = {} if body is None else dict(
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"})
    try:
        response = urlopen(Request(url, **opts), timeout=8)
    except HTTPError as failure:
        response = failure
    with response:
        payload = response.read()
        if response.status != status:
            raise AssertionError(
                f"{route} 状态码 {response.status}，预期 {status}：{payload[:300]!r}")
        return (json.loads(payload) if payload else None,
                response.headers, payload)


def rows_by_id(rows):
    return {row["id"]: row for row in rows}


class WindingFlipRegression(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tempdir = TemporaryDirectory(prefix="slitweb-regression-")
        db = Path(cls.tempdir.name) / "regression.sqlite"
        cls.server = serve(db, 0)
        cls.thread = Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.port = cls.server.server_port
        cls.forward_input = fx.build_package("forward")
        cls.reverse_input = fx.build_package("reverse")
        cls.forward = call(cls.port, "evaluate", cls.forward_input)[0]
        cls.reverse = call(cls.port, "evaluate", cls.reverse_input)[0]

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.thread.join()
        cls.server.server_close()
        cls.tempdir.cleanup()

    def test_01_inputs_describe_same_physical_material(self):
        """两版输入只有绕向与由其换算的子卷坐标不同。"""
        before, after = self.forward_input, self.reverse_input
        self.assertEqual(before["id"], after["id"])
        for field in ("width", "length", "margin"):
            self.assertEqual(before[field], after[field])
        self.assertEqual(before["defects"], after["defects"])
        self.assertEqual([(c["id"], c["a"], c["b"]) for c in before["cuts"]],
                         [(c["id"], c["a"], c["b"]) for c in after["cuts"]])
        self.assertEqual({c["winding"] for c in before["cuts"]}, {"forward"})
        self.assertEqual({c["winding"] for c in after["cuts"]}, {"reverse"})
        # 反绕复检窗必须是实物窗的走卷镜像（测试侧独立换算）。
        for child, windows in fx.CHECKS_PHYSICAL.items():
            for cid, start, end in windows:
                r_start, r_end = mirror_child_y(start, end)
                row = next(c for c in after["checks"] if c["id"] == cid)
                self.assertEqual((row["start"], row["end"]), (r_start, r_end))
                f_row = next(c for c in before["checks"] if c["id"] == cid)
                self.assertEqual((f_row["start"], f_row["end"]), (start, end))

    def test_02_transfer_coordinates_and_physical_invariants(self):
        """非对称跨刀疵：逐字段核对两版坐标、面积与母卷还原。"""
        assert_transfer_invariants(self, self.forward, "forward")
        assert_transfer_invariants(self, self.reverse, "reverse")
        # 两版同一疵点的子卷坐标必须不同，且恰好是镜像关系。
        f_rows, r_rows = (rows_by_id(self.forward["outputs"]["transfer"]),
                          rows_by_id(self.reverse["outputs"]["transfer"]))
        for row_id in f_rows:
            f_row, r_row = f_rows[row_id], r_rows[row_id]
            self.assertNotEqual((f_row["x0"], f_row["x1"], f_row["y0"], f_row["y1"]),
                                (r_row["x0"], r_row["x1"], r_row["y0"], r_row["y1"]),
                                f"{row_id} 反绕后坐标没有换位")
            self.assertEqual((f_row["x1"] - f_row["x0"], f_row["y1"] - f_row["y0"]),
                             (r_row["x1"] - r_row["x0"], r_row["y1"] - r_row["y0"]),
                             f"{row_id} 幅向/走卷跨度不是实物不变量")

    def test_03_layout_label_actually_swapped(self):
        """走卷标签确实换了位置，刀位几何保持不动。"""
        assert_layout_label_swapped(self, self.forward, self.reverse)

    def test_04_trace_points_to_same_defect_in_both_windings(self):
        """母卷回查：两版都还原到同一实物窗，且只命中跨刀疵。"""
        for packet in (self.forward, self.reverse):
            trace = packet["outputs"]["trace"]
            self.assertEqual(len(trace), 1)
            row = trace[0]
            self.assertEqual({k: row[k] for k in ("id", "start", "end",
                                                  "evidence", "state")},
                             fx.EXPECTED_TRACE)
        # 贴边断言：乙内疵与实物窗在幅向包含、走卷向仅在 y=520 相接，
        # 严格相交必须为空；放宽成 <= 会把乙内疵误计入证据。
        child, start, end = fx.QUERY_PHYSICAL
        window = dict(x0=fx.QUERY_X0, x1=fx.QUERY_X1, y0=start, y1=end)
        self.assertTrue(strict_overlap(window, fx.DEFECT_CROSS))
        self.assertFalse(strict_overlap(window, fx.DEFECT_B_LOCAL),
                         "乙内疵只在 520 贴边，不应算入回查证据")
        self.assertNotIn("乙内疵", self.forward["outputs"]["trace"][0]["evidence"])
        self.assertNotIn("乙内疵", self.reverse["outputs"]["trace"][0]["evidence"])

    def test_05_inspection_origin_and_edge_touch_not_intersection(self):
        """复检反查：两版还原成同一母卷矩形；贴边窗证据必须为空。"""
        for packet in (self.forward, self.reverse):
            origin = rows_by_id(packet["outputs"]["origin"])
            for row_id, expected in fx.EXPECTED_ORIGIN.items():
                row = origin[row_id]
                for field, value in expected.items():
                    self.assertEqual(row[field], value,
                                     f"{row_id}.{field} 两版实物反查不一致")
        # 贴边窗与跨刀疵幅向投影重合、走卷向只在 270 边界相接，
        # 严格相交为假；<= 实现会误判成命中。
        touch = dict(x0=68, x1=70, y0=270, y1=330)
        self.assertFalse(strict_overlap(touch, fx.DEFECT_CROSS))
        for packet in (self.forward, self.reverse):
            self.assertEqual(rows_by_id(packet["outputs"]["origin"])
                             ["贴边窗"]["evidence"], [])

    def test_06_defect_review_and_face_invariants(self):
        """疵点复核与幅面复检：两版逐行一致，贴边不贡献覆盖面积。"""
        for packet in (self.forward, self.reverse):
            review = rows_by_id(packet["outputs"]["defect_review"])
            for row_id, expected in fx.EXPECTED_DEFECT_REVIEW.items():
                for field, value in expected.items():
                    self.assertEqual(review[row_id][field], value,
                                     f"{row_id}.{field} 复核口径随绕向漂移")
            face = rows_by_id(packet["outputs"]["face"])
            for child, expected in fx.EXPECTED_FACE.items():
                for field, value in expected.items():
                    self.assertEqual(face[child][field], value,
                                     f"幅面复检 {child}.{field} 不是实物不变量")

    def test_07_coverage_release_and_trim_judgments_unchanged(self):
        """生产判定不迁就测试：封样状态/证据两版相同，仅坐标字段允许变化。"""
        for winding, packet in (("forward", self.forward),
                                ("reverse", self.reverse)):
            coverage = rows_by_id(packet["outputs"]["coverage"])
            for child, expected in fx.EXPECTED_COVERAGE[winding].items():
                for field, value in expected.items():
                    self.assertEqual(coverage[child][field], value)
            release = rows_by_id(packet["outputs"]["release"])
            for child, expected in fx.EXPECTED_RELEASE[winding].items():
                for field, value in expected.items():
                    self.assertEqual(release[child][field], value,
                                     f"封样判定 {child}.{field} 随绕向改变")
            trim = rows_by_id(packet["outputs"]["trim"])
            for child, expected in fx.EXPECTED_TRIM[winding].items():
                for field, value in expected.items():
                    self.assertEqual(trim[child][field], value)
            # 修剪段映射回母卷后，两版必须是同一实物区间。
            for child, (p_start, p_end) in fx.EXPECTED_TRIM_PHYSICAL.items():
                row = trim[child]
                if winding == "reverse":
                    physical = tuple(mirror_child_y(row["start"], row["end"]))
                else:
                    physical = (row["start"], row["end"])
                self.assertEqual(physical, (p_start, p_end),
                                 f"{child} 修剪段不是同一实物区间")
            # 禁保区间：按子卷坐标逐段核对边界、状态与证据。
            actual = {}
            for row in packet["outputs"]["exclusion"]:
                actual.setdefault(row["child"], []).append(
                    (row["start"], row["end"], row["state"], tuple(row["evidence"])))
            for child, expected in fx.EXPECTED_EXCLUSION[winding].items():
                self.assertEqual(sorted(actual[child]), sorted(expected),
                                 f"{child} 禁保区间与独立重算不一致")

    def test_08_scrap_shared_losses_and_runs_origin_invariants(self):
        """边料、分摊、分因长度与连续段母卷区间：全部实物不变量。"""
        for packet in (self.forward, self.reverse):
            outputs = packet["outputs"]
            scrap = rows_by_id(outputs["scrap"])
            for edge_id, expected in fx.EXPECTED_SCRAP.items():
                for field, value in expected.items():
                    self.assertEqual(scrap[edge_id][field], value)
            # 贴边疵只在 edge-2：其他边料带把贴边算成交集都会在这里暴露。
            for edge_id in fx.EXPECTED_SCRAP:
                present = "贴边疵" in scrap[edge_id]["evidence"]
                self.assertEqual(present, edge_id == "edge-2",
                                 f"贴边疵对 {edge_id} 的边料归属错误")
            self.assertFalse(
                any(row["evidence"] == "贴边疵" for row in outputs["transfer"]),
                "贴边疵不得转印进任何子卷")
            shared = rows_by_id(outputs["shared"])
            for defect_id, expected in fx.EXPECTED_SHARED.items():
                for field, value in expected.items():
                    self.assertEqual(shared[defect_id][field], value,
                                     f"分摊 {defect_id}.{field} 随绕向改变")
            losses = rows_by_id(outputs["losses"])
            for child, expected in fx.EXPECTED_LOSSES.items():
                for field, value in expected.items():
                    self.assertEqual(losses[child][field], value)
            # runs 的母卷纵向区间集合两版完全相同（排序后比较）。
            origins = sorted(row["origin"] for row in outputs["runs"]
                             if row["child"] == "乙卷")
            self.assertEqual(origins, fx.EXPECTED_RUN_ORIGINS["乙卷"])
            origins_a = sorted(row["origin"] for row in outputs["runs"]
                               if row["child"] == "甲卷")
            self.assertEqual(origins_a, fx.EXPECTED_RUN_ORIGINS["甲卷"])
            plan = rows_by_id(outputs["yield_plan"])["乙定尺"]
            for field, value in fx.EXPECTED_YIELD.items():
                self.assertEqual(plan[field], value)

    def test_09_compare_only_whitelisted_fields_change(self):
        """跨版本比较：不变量阶段零差异，变化字段全部落在白名单内。"""
        left = call(self.port, "seal", self.forward_input)[0]
        right = call(self.port, "seal", self.reverse_input)[0]
        diff = call(self.port, "compare",
                       dict(left=left["digest"], right=right["digest"]))[0]
        label_to_id = {op["label"]: op["id"] for op in CONFIG["operations"]}
        invariant_labels = {next(op["label"] for op in CONFIG["operations"]
                                 if op["id"] == stage)
                            for stage in fx.INVARIANT_STAGES}
        stages_seen = {row["stage"] for row in diff["rows"]}
        self.assertTrue(stages_seen.isdisjoint(invariant_labels),
                        f"实物不变量阶段出现了绕向差异：{stages_seen & invariant_labels}")
        self.assertTrue(diff["rows"], "绕向翻转应当产生可解释的差异行")
        for row in diff["rows"]:
            stage_id = label_to_id[row["stage"]]
            self.assertIn(stage_id, fx.ALLOWED_CHANGES,
                          f"阶段 {row['stage']} 不应随绕向变化")
            unexpected = {key for key in set(row["before"]) | set(row["after"])
                          if row["before"].get(key) != row["after"].get(key)}
            self.assertTrue(unexpected <= fx.ALLOWED_CHANGES[stage_id],
                            f"{row['id']} 出现白名单外变化：{unexpected}")

    def test_10_seal_dedup_revisions_and_export_download(self):
        """封存去重、历史快照与导出下载头端到端核对。"""
        # 同一输入重复封存：唯一摘要保证同一产物只存一次，
        # 两次返回同一 sequence（谁先跑由测试顺序决定，不断言 created 归属）。
        first = call(self.port, "seal", self.forward_input)[0]
        again = call(self.port, "seal", self.forward_input)[0]
        self.assertEqual(first["digest"], again["digest"])
        self.assertEqual(first["sequence"], again["sequence"])
        reverse_seal = call(self.port, "seal", self.reverse_input)[0]
        self.assertNotEqual(first["digest"], reverse_seal["digest"])
        revisions = call(self.port, "revisions")[0]
        self.assertEqual(len(revisions), 2)
        self.assertEqual({row["digest"] for row in revisions},
                         {first["digest"], reverse_seal["digest"]})
        # packet 与 export 内容一致，export 带附件下载头且为完整快照。
        packet, headers, raw = call(self.port, f"export/{first['digest']}")
        via_packet, _, _ = call(self.port, f"packet/{first['digest']}")
        self.assertEqual(packet, via_packet)
        self.assertEqual(packet, self.forward)
        self.assertIn("attachment;", headers.get("Content-Disposition", ""))
        self.assertIn(first["digest"][:16], headers["Content-Disposition"])
        self.assertEqual(headers.get("Content-Type"), "application/json; charset=utf-8")
        self.assertEqual(headers.get("Cache-Control"), "no-store")
        # 导出字节重新解码后摘要仍可独立复算，证明快照未被重写。
        from slitweb.artifacts import digest
        rehashed = digest({k: v for k, v in packet.items() if k != "digest"})
        self.assertEqual(rehashed, first["digest"])
        self.assertEqual(packet["digest"], first["digest"])
        self.assertEqual(raw, json.dumps(packet, ensure_ascii=False,
                                         sort_keys=True, separators=(",", ":")).encode())
        # 未知摘要返回 404；错误输入不落库。
        call(self.port, "export/" + "0" * 64, status=404)
        bad = dict(self.forward_input, cuts=[
                   dict(c, winding="sideways") for c in self.forward_input["cuts"]])
        call(self.port, "seal", bad, status=400)
        revisions_after = call(self.port, "revisions")[0]
        self.assertEqual(len(revisions_after), 2, "错误输入不应落入封存库")


if __name__ == "__main__":
    unittest.main(verbosity=2)
