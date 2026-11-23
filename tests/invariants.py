"""独立于被测实现的实物不变量与绕向换算核对。

这里的镜像换算、面积计算和区间相交都在测试侧重新实现，
只依赖夹具里的实物定义，不 import slitweb 的领域代码，
避免与被测实现共用同一处错误。
"""

from . import winding_fixture as fx


def mirror_child_y(start, end):
    """走卷向镜像：母卷/实物坐标 -> 反绕子卷坐标。"""
    return fx.LENGTH - end, fx.LENGTH - start


def mirror_child_x(cut_a, cut_b, x0, x1):
    """幅向镜像：母卷实物矩形 -> 反绕子卷坐标。"""
    width = cut_b - cut_a
    return width - (x1 - cut_a), width - (x0 - cut_a)


def rectangle_area(rect):
    return (rect["x1"] - rect["x0"]) * (rect["y1"] - rect["y0"])


def strict_overlap(a, b):
    """左闭右开窗的严格相交：贴边（仅边界相接）不算交集。"""
    return (max(a["x0"], b["x0"]) < min(a["x1"], b["x1"]) and
            max(a["y0"], b["y0"]) < min(a["y1"], b["y1"]))


def transfer_invariants(outputs):
    """从转印结果独立重算跨绕向实物不变量，返回断言用描述表。"""
    rows = {}
    for row in outputs["transfer"]:
        area = rectangle_area(row)
        width = row["x1"] - row["x0"]
        length = row["y1"] - row["y0"]
        rows[row["id"]] = dict(area=area, width=width, length=length,
                               child=row["child"], evidence=row["evidence"],
                               state=row["state"])
    return rows


def physical_rect_from_transfer(row, cut):
    """把子卷转印矩形独立还原为母卷实物矩形。"""
    if cut["winding"] == "reverse":
        width = cut["b"] - cut["a"]
        x0 = cut["a"] + (width - row["x1"])
        x1 = cut["a"] + (width - row["x0"])
        y0, y1 = mirror_child_y(row["y0"], row["y1"])
    else:
        x0 = cut["a"] + row["x0"]
        x1 = cut["a"] + row["x1"]
        y0, y1 = row["y0"], row["y1"]
    return dict(x0=x0, x1=x1, y0=y0, y1=y1)


def assert_transfer_invariants(testcase, packet, winding):
    """逐行核对转印：期望坐标、面积不变量、还原回母卷后等于原疵点。"""
    outputs = packet["outputs"]
    cuts = {cid: dict(id=cid, a=a, b=b, winding=winding)
            for cid, a, b in fx.CUTS_PHYSICAL}
    defects = {d["id"]: d for d in fx.DEFECTS}
    expected = fx.EXPECTED_TRANSFER[winding]
    actual = {row["id"]: row for row in outputs["transfer"]}
    testcase.assertEqual(set(actual), set(expected), "转印行集合与夹具不一致")
    for row_id, (ex0, ex1, ey0, ey1) in expected.items():
        row = actual[row_id]
        testcase.assertEqual((row["x0"], row["x1"], row["y0"], row["y1"]),
                             (ex0, ex1, ey0, ey1), f"{row_id} 坐标换算错误")
        area, child = fx.TRANSFER_AREAS[row_id]
        testcase.assertEqual(rectangle_area(row), area, f"{row_id} 面积不是实物不变量")
        testcase.assertEqual(row["child"], child)
        # 独立还原回母卷，必须与原疵点在该刀位内的实物片段逐边重合。
        restored = physical_rect_from_transfer(row, cuts[child])
        origin = defects[row["evidence"]]
        clipped = dict(x0=max(origin["x0"], cuts[child]["a"]),
                       x1=min(origin["x1"], cuts[child]["b"]),
                       y0=origin["y0"], y1=origin["y1"])
        testcase.assertEqual((restored["x0"], restored["x1"],
                              restored["y0"], restored["y1"]),
                             (clipped["x0"], clipped["x1"],
                              clipped["y0"], clipped["y1"]),
                             f"{row_id} 还原母卷后偏离原疵点的刀位片段")


def assert_layout_label_swapped(testcase, forward_packet, reverse_packet):
    """走卷标签必须换位置：刀位几何不变，state 正绕->反绕。"""
    f_rows = {r["id"]: r for r in forward_packet["outputs"]["layout"]}
    r_rows = {r["id"]: r for r in reverse_packet["outputs"]["layout"]}
    testcase.assertEqual(set(f_rows), set(r_rows))
    for child in f_rows:
        before, after = f_rows[child], r_rows[child]
        for field in ("start", "end", "width"):
            testcase.assertEqual(before[field], after[field],
                                 f"{child} 的刀位几何不应随绕向改变")
        testcase.assertEqual((before["state"], after["state"]),
                             ("forward", "reverse"),
                                 f"{child} 走卷标签没有随反绕换位")
