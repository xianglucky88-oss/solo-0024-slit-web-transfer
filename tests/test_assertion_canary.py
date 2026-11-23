"""断言强度金丝雀：证明回归断言真的抓得住错误实现。

对反绕结果做受控变异，模拟三类典型缺陷，断言测试侧的实物核对必然失败：

* 仅翻纵轴（漏翻横轴）；
* 仅翻横轴（漏翻纵轴）；
* 把贴边当成交集（< 改成 <=）；
并单独演示「只核对两版总面积相同」为何不足：
面积可以保持不变而坐标已经错放。
"""

import copy
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from slitweb.archive import Archive
from slitweb.server import CONFIG
from slitweb.service import Workbench

from . import winding_fixture as fx
from .invariants import assert_transfer_invariants, strict_overlap


def workbench():
    tmp = TemporaryDirectory(prefix="slitweb-canary-")
    return Workbench(Archive(Path(tmp.name) / "canary.sqlite"), CONFIG), tmp


class AssertionStrengthCanary(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.wb, cls.tmp = workbench()
        cls.good_reverse = cls.wb.analyze(fx.build_package("reverse"))
        cls.good_forward = cls.wb.analyze(fx.build_package("forward"))

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_good_packet_passes_invariants(self):
        """未变异的反绕结果必须通过，避免断言本身写错。"""
        assert_transfer_invariants(self, self.good_reverse, "reverse")

    def test_x_only_flip_is_caught(self):
        """仅翻纵轴：保留正确的 y 镜像，把 x 退回正绕坐标。"""
        mutant = copy.deepcopy(self.good_reverse)
        forward_rows = {r["id"]: r for r in self.good_forward["outputs"]["transfer"]}
        for row in mutant["outputs"]["transfer"]:
            row["x0"], row["x1"] = forward_rows[row["id"]]["x0"], forward_rows[row["id"]]["x1"]
        with self.assertRaises(AssertionError):
            assert_transfer_invariants(self, mutant, "reverse")

    def test_y_only_flip_is_caught(self):
        """仅翻横轴：保留正确的 x 镜像，把 y 退回正绕坐标。"""
        mutant = copy.deepcopy(self.good_reverse)
        forward_rows = {r["id"]: r for r in self.good_forward["outputs"]["transfer"]}
        for row in mutant["outputs"]["transfer"]:
            row["y0"], row["y1"] = forward_rows[row["id"]]["y0"], forward_rows[row["id"]]["y1"]
        with self.assertRaises(AssertionError):
            assert_transfer_invariants(self, mutant, "reverse")

    def test_edge_touch_counted_as_intersection_is_caught(self):
        """<= 缺陷：贴边窗被误判命中跨刀疵，origin 证据必须暴露它。"""
        mutant = copy.deepcopy(self.good_reverse)
        for row in mutant["outputs"]["origin"]:
            if row["id"] == "贴边窗":
                row["evidence"] = ["跨刀疵"]
        expected = fx.EXPECTED_ORIGIN["贴边窗"]["evidence"]
        actual = next(r for r in mutant["outputs"]["origin"]
                      if r["id"] == "贴边窗")["evidence"]
        self.assertNotEqual(actual, expected)
        # 同一套严格相交规则在测试侧也应判定贴边不相交。
        touch = dict(x0=68, x1=70, y0=270, y1=330)
        self.assertFalse(strict_overlap(touch, fx.DEFECT_CROSS))

    def test_trace_edge_touch_caught_via_strict_overlap(self):
        """回查窗与乙内疵贴边：若放宽成 <=，证据集合就会多出乙内疵。"""
        child, start, end = fx.QUERY_PHYSICAL
        window = dict(x0=fx.QUERY_X0, x1=fx.QUERY_X1, y0=start, y1=end)
        self.assertFalse(strict_overlap(window, fx.DEFECT_B_LOCAL))
        trace_evidence = self.good_reverse["outputs"]["trace"][0]["evidence"]
        self.assertEqual(trace_evidence, fx.EXPECTED_TRACE["evidence"])
        self.assertNotIn("乙内疵", trace_evidence)

    def test_total_area_alone_is_not_enough(self):
        """面积不变但坐标错放：面积断言放行，位置与母卷还原断言拦截。"""
        mutant = copy.deepcopy(self.good_reverse)
        row = next(r for r in mutant["outputs"]["transfer"]
                   if r["id"] == "乙卷/跨刀疵")
        # 同一条矩形整体平移 6mm：自身面积与跨度完全不变，
        # 但还原回母卷后已偏离原疵点，且不再贴合刀位。
        row["x0"], row["x1"] = row["x0"] + 6, row["x1"] + 6
        from .invariants import rectangle_area
        for row_id, (area, _child) in fx.TRANSFER_AREAS.items():
            current = next(r for r in mutant["outputs"]["transfer"]
                           if r["id"] == row_id)
            self.assertEqual(rectangle_area(current), area)
        # 但逐字段坐标与母卷还原断言必须失败。
        with self.assertRaises(AssertionError):
            assert_transfer_invariants(self, mutant, "reverse")


class SealFirstWriteCanary(unittest.TestCase):
    """在全新成果库上验证首写 created=True、重复封存 created=False。"""

    def test_first_write_then_dedup(self):
        wb, tmp = workbench()
        try:
            packet = wb.analyze(fx.build_package("forward"))
            first = wb.archive.seal(packet)
            second = wb.archive.seal(packet)
            self.assertTrue(first["created"])
            self.assertFalse(second["created"])
            self.assertEqual(first["sequence"], second["sequence"])
            self.assertEqual(len(wb.archive.list()), 1)
        finally:
            tmp.cleanup()


if __name__ == "__main__":
    unittest.main(verbosity=2)
