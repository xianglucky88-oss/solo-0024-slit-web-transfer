"""绕向翻转回归夹具：同一块实物材料的正绕版与反绕版输入。

设计约束（见 tests/REGRESSION.md）：

* 两版输入描述同一块实物材料，母卷幅宽/长度、刀位、疵点矩形、
  实物复检范围、回查实物范围全部一致，仅子卷绕向字段及由其换算的
  子卷坐标不同；两版对象标识相同，可直接进入跨版本比较。
* 疵点全部采用非对称形状，并让「跨刀疵」同时落入两个刀位，
  仅翻横轴或仅翻纵轴都无法与另一版的实物不变量对齐。
* 两处恰贴边不相交区域：回查窗与乙内疵在走卷向 520 处两维贴边，
  复检「贴边窗」与跨刀疵在走卷向 270 处贴边，「贴边疵」在幅向 68 处
  贴乙卷边沿；若实现把贴边误算成交集（用 <= 代替 <），归属断言会失败。
"""

WIDTH = 120
LENGTH = 1000
MARGIN = 10
SUBJECT = "回归材料-绕向翻转"

CUTS_PHYSICAL = (
    ("甲卷", 30, 56),
    ("乙卷", 68, 100),
    ("丙卷", 108, 118),
)

# 实物疵点（母卷坐标，毫米，左闭右开）。
# 跨刀疵：横跨两个刀位之间的 56..68 废料带，且在两刀位内的宽度与
# 走卷长度都不对称（6 x 70 与 2 x 70），用于区分单轴翻转错误。
DEFECT_CROSS = dict(id="跨刀疵", x0=50, x1=70, y0=200, y1=270, grade="major")
# 甲卷内部的非对称小疵点（6 x 18）。
DEFECT_A_LOCAL = dict(id="甲内疵", x0=34, x1=40, y0=400, y1=418, grade="minor")
# 乙卷内部的非对称疵点（8 x 25），与回查实物窗 460..520 恰在 520 贴边。
DEFECT_B_LOCAL = dict(id="乙内疵", x0=90, x1=98, y0=520, y1=545, grade="minor")
# 落在 edge-2（56..68）内、恰在 68 处与乙卷贴边的疵点：
# 左闭右开下乙卷不收，只属于 edge-2；map_defect 门限放宽会把它错转印。
DEFECT_EDGE = dict(id="贴边疵", x0=64, x1=68, y0=800, y1=812, grade="minor")
DEFECTS = [DEFECT_CROSS, DEFECT_A_LOCAL, DEFECT_EDGE, DEFECT_B_LOCAL]

# 实物复检范围（母卷走卷坐标），用同一批物理窗按绕向换算成子卷坐标。
CHECKS_PHYSICAL = {
    "甲卷": [("复检甲", 100, 900)],
    "乙卷": [("复检乙前", 0, 400), ("复检乙后", 520, 1000)],
}

# 回查实物窗（母卷坐标）：与跨刀疵相交；与乙内疵在两维投影上都贴合
# （幅向完全落入其幅向区间、走卷向仅在 520 边界相接），左闭右开下不算交集。
QUERY_PHYSICAL = ("乙卷", 240, 520)
# 回查窗在母卷上的幅向范围（服务按刀位判幅向，这里独立用于贴边断言）：
# 与跨刀疵（50..70）相交，且完全落入乙内疵幅向区间（90..98）。
QUERY_X0, QUERY_X1 = 55, 96

# 幅面复检实物矩形（母卷坐标），同样按绕向换算到子卷坐标。
# 覆盖窗：在乙卷内完整包住跨刀疵的乙卷部分（68..70 x 200..270），result=marked。
INSPECT_HIT_PHYSICAL = dict(id="覆盖窗", child="乙卷",
                            x0=68, x1=78, y0=200, y1=270, result="marked")
# 贴边窗：幅向投影落入跨刀疵在乙卷的幅向片段内，走卷向仅在 y=270 相接，
# 左闭右开下不相交；实现若把 < 放宽成 <= 就会误判命中。
INSPECT_TOUCH_PHYSICAL = dict(id="贴边窗", child="乙卷",
                              x0=68, x1=70, y0=270, y1=330, result="clear")

ORDER_PHYSICAL = dict(id="乙定尺", child="乙卷", length=200, allowance=10)


def _mirror_y(start, end):
    """实物走卷窗到反绕子卷走卷坐标的换算（独立重算，不调用被测代码）。"""
    return LENGTH - end, LENGTH - start


def _checks_for(winding):
    rows = []
    for child, windows in CHECKS_PHYSICAL.items():
        for cid, start, end in windows:
            if winding == "reverse":
                start, end = _mirror_y(start, end)
            rows.append(dict(id=cid, child=child, start=start, end=end))
    return rows


def _inspections_for(winding):
    rows = []
    for spec in (INSPECT_HIT_PHYSICAL, INSPECT_TOUCH_PHYSICAL):
        child = spec["child"]
        cut_a, cut_b = next((a, b) for cid, a, b in CUTS_PHYSICAL if cid == child)
        width = cut_b - cut_a
        x0, x1, y0, y1 = spec["x0"], spec["x1"], spec["y0"], spec["y1"]
        if winding == "reverse":
            x0, x1 = width - (x1 - cut_a), width - (x0 - cut_a)
            y0, y1 = _mirror_y(y0, y1)
        else:
            x0, x1 = x0 - cut_a, x1 - cut_a
        rows.append(dict(id=spec["id"], child=child, x0=x0, x1=x1,
                         y0=y0, y1=y1, result=spec["result"]))
    return rows


def build_package(winding):
    """返回正绕（forward）或反绕（reverse）的完整输入包。"""
    if winding not in ("forward", "reverse"):
        raise ValueError(winding)
    child, q_start, q_end = QUERY_PHYSICAL
    if winding == "reverse":
        q_start, q_end = _mirror_y(q_start, q_end)
    return dict(
        id=SUBJECT,
        width=WIDTH,
        length=LENGTH,
        margin=MARGIN,
        cuts=[dict(id=cid, a=a, b=b, winding=winding)
              for cid, a, b in CUTS_PHYSICAL],
        defects=[dict(d) for d in DEFECTS],
        checks=_checks_for(winding),
        query=dict(child=child, start=q_start, end=q_end),
        review=dict(inspections=_inspections_for(winding),
                    orders=[dict(ORDER_PHYSICAL)]),
    )


# --- 独立重算的期望值 ----------------------------------------------------
# 以下数值由夹具几何手算得到，供测试与服务输出逐字段核对；
# 不允许从被测实现反推。

# 转印行：id -> (x0, x1, y0, y1)，正绕 / 反绕两版。
EXPECTED_TRANSFER = {
    "forward": {
        "甲卷/跨刀疵": (20, 26, 200, 270),
        "甲卷/甲内疵": (4, 10, 400, 418),
        "乙卷/跨刀疵": (0, 2, 200, 270),
        "乙卷/乙内疵": (22, 30, 520, 545),
    },
    "reverse": {
        "甲卷/跨刀疵": (0, 6, 730, 800),
        "甲卷/甲内疵": (16, 22, 582, 600),
        "乙卷/跨刀疵": (30, 32, 730, 800),
        "乙卷/乙内疵": (2, 10, 455, 480),
    },
}

# 每条转印疵点的实物面积（跨轴镜像不变量），以及所属子卷。
TRANSFER_AREAS = {
    "甲卷/跨刀疵": (6 * 70, "甲卷"),
    "甲卷/甲内疵": (6 * 18, "甲卷"),
    "乙卷/跨刀疵": (2 * 70, "乙卷"),
    "乙卷/乙内疵": (8 * 25, "乙卷"),
}

# 回查（trace）：两版都还原到同一母卷实物窗，证据只含跨刀疵；
# 乙内疵在 520 处贴边，必须被排除。
EXPECTED_TRACE = dict(id="乙卷", start=240, end=520,
                      evidence=["跨刀疵"], state="marked")

# 复检反查（origin）：两版都还原为同一母卷矩形；
# 覆盖窗命中跨刀疵，贴边窗证据为空（贴边不算交集）。
EXPECTED_ORIGIN = {
    "覆盖窗": dict(x0=68, x1=78, y0=200, y1=270, evidence=["跨刀疵"], state="marked"),
    "贴边窗": dict(x0=68, x1=70, y0=270, y1=330, evidence=[], state="clear"),
}

# 幅面复检（face）。覆盖窗 10*70=700，贴边窗 2*60=120，两窗不相交。
EXPECTED_FACE = {
    "甲卷": dict(area=0, total=26 * LENGTH, state="blind"),
    "乙卷": dict(area=700 + 120, total=32 * LENGTH, state="partial"),
    "丙卷": dict(area=0, total=10 * LENGTH, state="blind"),
}

# 复检覆盖（coverage）：observed/state 为实物不变量；缺口按子卷坐标表达，
# 反绕版应是实物缺口 [400,520] 的镜像 [480,600]。
EXPECTED_COVERAGE = {
    "forward": {
        "甲卷": dict(observed=800, missing=[[0, 100], [900, 1000]], state="blind"),
        "乙卷": dict(observed=880, missing=[[400, 520]], state="blind"),
        "丙卷": dict(observed=0, missing=[[0, 1000]], state="blind"),
    },
    "reverse": {
        "甲卷": dict(observed=800, missing=[[0, 100], [900, 1000]], state="blind"),
        "乙卷": dict(observed=880, missing=[[480, 600]], state="blind"),
        "丙卷": dict(observed=0, missing=[[0, 1000]], state="blind"),
    },
}

# 封样判定（release）：跨刀疵是 major，甲乙两卷阻断；丙卷无疵点但全盲，待定。
EXPECTED_RELEASE = {
    "forward": {
        "甲卷": dict(state="blocked", count=1, missing=[[0, 100], [900, 1000]],
                     evidence=["跨刀疵"]),
        "乙卷": dict(state="blocked", count=1, missing=[[400, 520]],
                     evidence=["跨刀疵"]),
        "丙卷": dict(state="pending", count=0, missing=[[0, 1000]], evidence=[]),
    },
    "reverse": {
        "甲卷": dict(state="blocked", count=1, missing=[[0, 100], [900, 1000]],
                     evidence=["跨刀疵"]),
        "乙卷": dict(state="blocked", count=1, missing=[[480, 600]],
                     evidence=["跨刀疵"]),
        "丙卷": dict(state="pending", count=0, missing=[[0, 1000]], evidence=[]),
    },
}

# 边料（scrap）：贴边疵在 68 处与乙卷严格贴边，左闭右开下只属于 edge-2；
# 跨刀疵横跨 edge-2。贴边疵不得出现在任何子卷转印里。
EXPECTED_SCRAP = {
    "edge-1": dict(start=0, end=30, evidence=[]),
    "edge-2": dict(start=56, end=68, evidence=["跨刀疵", "贴边疵"]),
    "edge-3": dict(start=100, end=108, evidence=[]),
    "edge-4": dict(start=118, end=120, evidence=[]),
}

# 母卷疵点分摊（shared）。
EXPECTED_SHARED = {
    "跨刀疵": dict(width=20, kept=8, lost=12, state="split"),
    "甲内疵": dict(width=6, kept=6, lost=0, state="kept"),
    "贴边疵": dict(width=4, kept=0, lost=4, state="scrap"),
    "乙内疵": dict(width=8, kept=8, lost=0, state="kept"),
}

# 禁保区间（exclusion）：按子卷坐标的 (start, end, state, evidence) 多重集。
EXPECTED_EXCLUSION = {
    "forward": {
        "甲卷": [
            (0, 100, "blind", ()),
            (100, 190, "eligible", ()),
            (190, 280, "blocked", ("跨刀疵",)),
            (280, 900, "eligible", ()),
            (900, 1000, "blind", ()),
        ],
        "乙卷": [
            (0, 190, "eligible", ()),
            (190, 280, "blocked", ("跨刀疵",)),
            (280, 400, "eligible", ()),
            (400, 520, "blind", ()),
            (520, 1000, "eligible", ()),
        ],
    },
    "reverse": {
        "甲卷": [
            (0, 100, "blind", ()),
            (100, 720, "eligible", ()),
            (720, 810, "blocked", ("跨刀疵",)),
            (810, 900, "eligible", ()),
            (900, 1000, "blind", ()),
        ],
        "乙卷": [
            (0, 480, "eligible", ()),
            (480, 600, "blind", ()),
            (600, 720, "eligible", ()),
            (720, 810, "blocked", ("跨刀疵",)),
            (810, 1000, "eligible", ()),
        ],
    },
}

# 连续可利用段（runs）：母卷纵向区间 origin 两版必须完全相同。
EXPECTED_RUN_ORIGINS = {
    "甲卷": [[100, 190], [280, 900]],
    "乙卷": [[0, 190], [280, 400], [520, 1000]],
}

# 短卷产量（yield_plan）：实物可保长度相同，定尺容纳数相同。
EXPECTED_YIELD = dict(id="乙定尺", count=2, length=200, used=410,
                      remainder=380, state="fits")

# 分因长度核账（losses）：各状态长度（实物不变量）。
EXPECTED_LOSSES = {
    "甲卷": dict(eligible=710, blocked=90, blind=200, mixed=0, state="partial"),
    "乙卷": dict(eligible=790, blocked=90, blind=120, mixed=0, state="partial"),
    "丙卷": dict(eligible=0, blocked=0, blind=1000, mixed=0, state="blocked"),
}

# 疵点复核（defect_review）：跨刀疵在乙卷内的部分被覆盖窗完整覆盖。
EXPECTED_DEFECT_REVIEW = {
    "乙卷/跨刀疵": dict(area=2 * 70, total=2 * 70, grade="major", state="marked"),
    "乙卷/乙内疵": dict(area=0, total=8 * 25, grade="minor", state="blind"),
}
# 连续修剪（trim）：最长可保段长度两版相同（实物不变量），坐标随绕向变化；
# 反绕段映射回母卷后必须与正绕段是同一实物区间。
EXPECTED_TRIM = {
    "forward": {
        "甲卷": dict(start=280, end=900, length=620),
        "乙卷": dict(start=520, end=1000, length=480),
    },
    "reverse": {
        "甲卷": dict(start=100, end=720, length=620),
        "乙卷": dict(start=0, end=480, length=480),
    },
}
# 修剪段对应的母卷实物区间（两版必须一致）。
EXPECTED_TRIM_PHYSICAL = {
    "甲卷": (280, 900),
    "乙卷": (520, 1000),
}

# 允许随绕向变化的字段（compare 差异行白名单），键为归约阶段。
ALLOWED_CHANGES = {
    "layout": {"state"},
    "transfer": {"x0", "x1", "y0", "y1"},
    "coverage": {"missing"},
    "release": {"missing"},
    "trim": {"start", "end", "missing"},
    "exclusion": {"id", "start", "end", "length", "state", "evidence"},
    # runs 按序号对齐，绕向翻转后同序号对应不同实物段，故 origin 也会变；
    # 母卷区间集合的两版一致性在端到端测试里单独按集合断言。
    "runs": {"id", "start", "end", "length", "state", "evidence", "origin"},
    "yield_plan": {"evidence"},
    "losses": {"evidence"},
}

# 实物不变量阶段：两版逐行必须完全相同，compare 不得报告任何差异。
INVARIANT_STAGES = ("scrap", "trace", "face", "defect_review", "origin", "shared")
