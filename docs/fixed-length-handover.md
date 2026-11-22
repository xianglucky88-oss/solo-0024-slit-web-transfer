# 定尺报价交接说明

本文只解释**既有输出**，供采购、裁剪和车间在抄同一张短卷结果时对齐口径。字段名、计算方式、成果摘要和报价规则都不变；不新增排产、择优或互斥分配能力，也不产生单价、金额或成品逐件坐标。

本项目的字段合同里没有单价、金额或折扣字段。“定尺报价”所依据的现有数值只有 `yield_plan` 的 `count`、`length`、`used`、`remainder`：报价用 `count × length`（净长），车间领料用 `used`（含件间刀口），两者核对用 `remainder`。本文不定义、不修改任何价格规则。

- 接口：`POST /slitweb/api/evaluate` → `outputs.yield_plan`，上游为 `outputs.runs`、`outputs.exclusion`。
- 业务样例：`examples/review-sample.json`（规格 `乙定尺`）。
- 可验算的最小材料：`examples/handover-minimal.json`（下称“最小卷”）。
- 实现位置：`slitweb/salvage.py:19`（可利用段）、`slitweb/salvage.py:33`（单段可容件数）、`slitweb/salvage.py:39`（按规格汇总）。

## 1. 六条结论

1. **每个规格行都是一次独立试算。** 同一子卷的同一段料会被多个规格行分别计数，行与行之间没有互斥分配，也没有先后顺序。
2. **`used` 含件间刀口，`length` 是净定尺。** 一段内切 `n` 件要计 `n−1` 个切口留量；段两端和跨段都不计。
3. **`remainder` 是整行算术余量，不是可整段复用的余料。** 它由各段段尾碎料拼成，可能分处禁保区两侧；既不能跨行相加，也不能当库存。
4. **`yield_plan.evidence` 的键是可利用段的编号，不是成品标签。** 段编号来自 `runs.id`/`exclusion.id`；成品件只以 `count` 计数，没有逐件编号。
5. **下载文件可自证并回到源段。** 摘要 → `outputs.yield_plan[].evidence` → `outputs.runs[]` → `outputs.exclusion[]` → `source`。
6. **净长相同的规格也会因件间刀口不同而给出不同的 `count`/`used`/`remainder`。** 最小卷中三行净长都是 200，留量 0/10/30 分别得到 4/3/2 件。

## 2. 字段

### 2.1 输入：`source.review.orders[]`

| 字段 | 含义 | 单位/取值 |
|---|---|---|
| `id` | 规格行标识；`yield_plan.id` 原样引用 | 字符串 |
| `child` | 试算所用子卷 | 必须是 `cuts[].id` |
| `length` | 定尺净长 `L` | mm，`0.001 ≤ L ≤` 母卷长度 |
| `allowance` | 每两个相邻件之间的切口留量 `A` | mm，`0 ≤ A ≤` 母卷长度 |

`allowance` **不会在 `yield_plan` 行里回显**。看到 `count`/`used` 后要复算时，必须按同一 `id` 回到 `source.review.orders` 取 `A`。

### 2.2 输出：`outputs.yield_plan[]`

列定义见 `workbench.json` 的 `yield_plan` 操作；行内另有 `evidence`。

| 字段 | 列名 | 含义 | 单位/取值 |
|---|---|---|---|
| `id` | 标识 | 规格行标识，等于输入 `orders[].id` | 字符串 |
| `child` | 子卷 | 本行试算的子卷 | 字符串 |
| `length` | 长度 | 净定尺 `L`，等于输入 | mm |
| `count` | 数量 | 该子卷所有可利用段按本行 `L`/`A` 可容纳的件数之和 | 整数 ≥ 0 |
| `used` | 占用长度 | 计入件间刀口后的耗料长度 | mm |
| `remainder` | 余量 | 该子卷可利用段总长减去 `used` 的算术余量 | mm |
| `state` | 状态 | `count > 0` 为 `fits`（有产量），否则 `blocked`（阻断） | 枚举 |
| `evidence` | 来源证据 | `{可利用段编号: 该段件数}`；**包含件数为 0 的候选段** | 对象 |

### 2.3 上游：`outputs.runs[]`（连续可利用段）

| 字段 | 含义 |
|---|---|
| `id` | 段编号；等于该段所对应的 `exclusion` 可保行编号（若合并多行则取首行） |
| `child` | 子卷 |
| `start`、`end` | 子卷走卷轴上的左闭右开区间，`length = end − start` |
| `origin` | 母卷纵向区间；正绕为 `[start, end]`，反绕为 `[母卷长度−end, 母卷长度−start]` |
| `evidence` | 组成该段的 `exclusion` 行编号列表 |
| `state` | 固定为 `eligible`（可保留） |

### 2.4 上游：`outputs.exclusion[]`（禁保区间）

`yield_plan` 只使用其中 `state = eligible` 的行。段编号 `child/n` 是按该子卷的边界顺序编的，输入变化会重新编号。

| 字段 | 含义 |
|---|---|
| `id` | `子卷/序号`，如 `乙卷/1` |
| `start`、`end`、`length` | 子卷走卷轴上的左闭右开区间及长度 |
| `state` | `eligible`（可保留）、`blocked`（重大疵点）、`blind`（缺检）、`mixed`（缺检且有重大疵点） |
| `evidence` | 造成禁保的原始疵点编号；`eligible` 行为空 |

## 3. 计算口径

对某个规格行，记净长 `L`、切口留量 `A`，该子卷的可利用段为 `r = 1..m`，第 `r` 段长度 `span_r`。

1. **单段件数**（`slitweb/salvage.py:33`）：

   ```text
   n_r = floor((span_r + A) / (L + A))
   ```

   若商恰好为整数（容差 `1e-12`）则取该整数。它等价于不等式 `n·L + (n−1)·A ≤ span_r` 的最大整数 `n`：一段内 `n` 件之间需要 `n−1` 个刀口。段只有一件时不计留量；段两端不计留量。
2. **件数**：`count = Σ n_r`。
3. **占用长度**：`used = Σ (n_r·L + max(0, n_r−1)·A)`。
4. **余量**：`remainder = max(0, Σ span_r − used)`。
5. **状态**：`count > 0` → `fits`，否则 `blocked`。
6. **证据**：`evidence = {r: n_r}`，所有候选段都列出，没取到件的段写 `0`。

由此每行恒有：

```text
used + remainder = Σ span_r = 该子卷可保总长
```

这个等式只对**单独一行**成立；不同行不能相加。

## 4. 最小卷：可逐项核对的材料

输入 `examples/handover-minimal.json`：母卷 200×1000 mm，一个正绕子卷 `短卷甲`（刀带 0–100），无疵点；复检窗为 0–420 和 600–1000，因此 420–600 缺检。

### 4.1 走卷分段与可利用段

下表的 `state` 来自 `outputs.exclusion`；`outputs.runs` 只收 `eligible` 的两段。

| 段（`exclusion.id`） | 区间（子卷轴） | 长度 | 状态 | 在 `runs` 中 | `origin`（母卷轴） |
|---|---|---|---:|---|---|
| `短卷甲/1` | 0–420 | 420 | eligible | 是 | `[0, 420]` |
| `短卷甲/2` | 420–600 | 180 | blind | 否 | — |
| `短卷甲/3` | 600–1000 | 400 | eligible | 是 | `[600, 1000]` |

`outputs.runs` 只有 `短卷甲/1` 与 `短卷甲/3`，两者合计可保 **820 mm**；中间 180 mm 缺检不可用。`losses` 同时给出 `eligible=820`、`blind=180`。

### 4.2 五个规格行

| 行（`id`） | `L` | `A` | `短卷甲/1` 件数 | `短卷甲/3` 件数 | `count` | `used` | `remainder` | `state` |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| `甲-净200-留0` | 200 | 0 | 2 | 2 | 4 | 800 | 20 | `fits` |
| `甲-净200-留10` | 200 | 10 | 2 | 1 | 3 | 610 | 210 | `fits` |
| `甲-净200-留30` | 200 | 30 | 1 | 1 | 2 | 400 | 420 | `fits` |
| `甲-净400-留0` | 400 | 0 | 1 | 1 | 2 | 800 | 20 | `fits` |
| `甲-净500-留0` | 500 | 0 | 0 | 0 | 0 | 0 | 820 | `blocked` |

逐段复算（段长 420 与 400）：

- `甲-净200-留0`：`floor(420/200)=2`、`floor(400/200)=2`；占用 `2×200 + 2×200 = 800`，余量 `820−800=20`。
- `甲-净200-留10`：`floor(430/210)=2`、`floor(410/210)=1`；占用 `(2×200+1×10) + 200 = 610`，余量 `820−610=210`。
- `甲-净200-留30`：`floor(450/230)=1`、`floor(430/230)=1`；占用 `200+200=400`，余量 `820−400=420`。
- `甲-净400-留0`：`floor(420/400)=1`、`floor(400/400)=1`；占用 `400+400=800`，余量 `20`。
- `甲-净500-留0`：两段分别只有 420、400，商为 `420/500=0.84`、`400/500=0.8`，件数均为 0；整行 `blocked`，余量 820。

每条 `used + remainder` 都等于 820：`800+20`、`610+210`、`400+420`、`800+20`、`0+820`。

### 4.3 500 mm 为何被阻断

两段合计 820 mm，但没有任何一段能独立容纳 500 mm。`yield_plan` **不跨段拼接**，所以不能把 420 与 400 接起来凑 500。这正是“各段独立、规格独立”的直接证据。

## 5. 净长相同、件间刀口不同

三行净长都是 200 mm，只有切口留量不同：

| `A` | 每段可容件数 | `count` | `used` | `remainder` | 与净长合计的差 |
|---:|---|---:|---:|---:|---:|
| 0 | 420→2，400→2 | 4 | 800 | 20 | `4×200=800`，差 0 |
| 10 | 420→2，400→1 | 3 | 610 | 210 | `3×200=600`，差 10 |
| 30 | 420→1，400→1 | 2 | 400 | 420 | `2×200=400`，差 0 |

- `A=10` 时，`短卷甲/1` 内两件之间切一刀，耗料 `2×200+1×10=410`；`短卷甲/3` 只有一件，不计刀口，耗料 200；合计 610。成品净长只有 `3×200=600`，差的 10 mm 就是段内那一个刀口。
- `A=30` 时，`短卷甲/1` 容不下两件（需 `2×200+1×30=430 > 420`），只能取一件，因此 `used` 反而降到 400，`remainder` 升到 420。
- `A=0` 与 `A=30` 时净长都是 200 mm，但件数和耗料完全不同；所以**不能只看净长推件数或耗料**。
- 跨段不计刀口：`甲-净400-留0` 在两段各取一件，每段都没有件间切口，`used` 正好 `2×400=800`。

## 6. 各规格相互独立

`order_yield` 对每个规格行单独遍历该子卷的全部可利用段（`slitweb/salvage.py:39`），不扣除其他规格行已占用的部分，也不排序、不择优。因此：

- 同一个 `短卷甲/1` 在五行里分别被计为 2、2、1、1、0 件；同一段料被反复试算，而不是被切成五份。
- 五行的 `used` 合计是 `800+610+400+800+0=2610`，`remainder` 合计是 `20+210+420+20+820=1490`，都远大于可保总长 820。**这些合计没有物理意义。**
- 每行自身满足 `used+remainder=820`，才是可用的一致性检查。
- 不同 `child` 的行更不能相加：它们对应母卷上不同刀带，根本不是同一块料。
- `evidence` 中的 `0` 只表示“该候选段参与了试算但没有取件”，不是用料，也不表示该段被占用。样例 `乙定尺` 的 `乙卷/4: 0` 就是这种情况。

## 7. 车间为什么不能把各行的剩余料直接相加

以最小卷 `甲-净200-留10` 为例，`remainder=210` 的实际构成是：

| 段 | 段长 | 取件占用 | 段尾剩余 |
|---|---:|---:|---:|
| `短卷甲/1` | 420 | `2×200+1×10=410` | 10 |
| `短卷甲/3` | 400 | `1×200=200` | 200 |
| 合计 | 820 | 610 | 210 |

这 210 mm 分成两处：段 1 尾部的 10 mm 和段 3 尾部的 200 mm，中间隔着 180 mm 缺检禁保区。它们不能拼成一段 210 mm 的料；也不能原地续切一件 200 mm 的定尺——段 1 只剩 10 mm，段 3 的 200 mm 再接一件还要再加 10 mm 刀口，共需 210 mm。所以：

1. **跨行不能加。** 每行的 `remainder` 都是对同一批可保段的独立试算结果；五行相加等于把同一块料算了五遍。
2. **行内也不能当作一整块。** `remainder` 只是算术差，没有记录段尾位置、形状和可用性；它由多个段的尾部剩余拼成，可能被禁保区隔开。
3. **不能倒推为库存。** 若用 `820 − count×L` 算剩余，会漏掉刀口：`甲-净200-留10` 会得到 220，而真实 `remainder` 是 210，差的 10 mm 正是件间刀口。
4. **不能跨段续切。** `甲-净500-留0` 已说明：总长 820 仍可能一件都取不到；剩余料的存在不等于可容纳下一件。

车间要复用余料，必须重新把具体段和新的 `L`/`A` 交给下一次试算，而不是对 `remainder` 做加法。本文不提供这种重排能力。

## 8. 编号是可利用段，不是成品标签

- `yield_plan.evidence` 的键是 `runs.id`，也就是 `exclusion` 中对应可保行的编号，例如 `短卷甲/1`。它表示子卷 0–420 mm 这一**纵向可利用段**，不是“第 1 件成品”，也不是“第 1 卷”。
- `count` 才是件数，但件没有编号，也没有逐件位置；成果里不存在“成品 1/2/3”的记录。任何“第几件”的叫法都是外部叫法，无法从成果回溯。
- `短卷甲/2` 是缺检段，不是成品；样例 `乙卷/4` 只有 100 mm 且取件数为 0，更能说明段编号不是产量编号。
- 段编号按边界顺序生成，输入一变就会重排；不要把它当作长期产品序列号。需要跨版本指认时，用“成果摘要 + 段编号 + `origin`”三者一起。
- 合并相邻可保段时，`runs.evidence` 会列出全部组成段，而 `runs.id` 取其中第一段。当前口径下可保段之间必有禁保段，故每个 `run` 的 `evidence` 只含一个编号；读取时仍应按列表处理。
- 反绕子卷的 `start`/`end` 是子卷轴坐标，`origin` 才是母卷纵向坐标，两者数值通常不同。样例 `乙卷` 为反绕：

  | 段 | `start`–`end`（子卷轴） | `origin`（母卷轴） |
  |---|---|---|
  | `乙卷/1` | 0–740 | `[260, 1000]` |
  | `乙卷/4` | 900–1000 | `[0, 100]` |

  因此 `乙卷/1` 不能读成“母卷 0–740”；要落到母卷，必须看 `origin`。

## 9. 从下载追到源段

### 9.1 取得下载文件

```sh
python3 -m slitweb.server --port 8861   # 前台运行，另开一个终端执行下面的命令

curl -s -X POST -H 'Content-Type: application/json' \
  --data @examples/handover-minimal.json \
  http://127.0.0.1:8861/slitweb/api/seal
# {"created":true,"digest":"d699c4687a8e518bfd6ac07e834da7a8372a5b79832f6b26de35a9acf18cce8f","sequence":1}

curl -OJ http://127.0.0.1:8861/slitweb/api/export/d699c4687a8e518bfd6ac07e834da7a8372a5b79832f6b26de35a9acf18cce8f
# 下载为 slitweb-d699c4687a8e518b.json，响应头：
# Content-Disposition: attachment; filename="slitweb-d699c4687a8e518b.json"
```

下载内容是封存版本的完整包，与 `GET /slitweb/api/packet/<摘要>` 逐字节一致；不是当前页面尚未封存的状态。未知摘要返回 404。上例的 `sequence` 只在空成果库时为 1，随库内已有版本递增；`digest` 只由内容决定，换库不变。

### 9.2 包内追溯链

```text
下载文件
├─ digest            整包摘要（去掉 digest 字段后的规范 JSON 的 SHA-256）
├─ source_digest     原始输入摘要
├─ source            原始输入（cuts / checks / defects / review.orders）
└─ outputs
   ├─ yield_plan[id=甲-净200-留10]
   │    count=3, used=610, remainder=210
   │    evidence = {"短卷甲/1": 2, "短卷甲/3": 1}
   ├─ runs[id=短卷甲/1]
   │    start=0, end=420, length=420, origin=[0,420]
   │    evidence=["短卷甲/1"]
   ├─ exclusion[id=短卷甲/1]
   │    start=0, end=420, state="eligible"
   └─ source.checks: 全检一 0–420、全检二 600–1000
```

具体走法：

1. 在下载文件中找到 `outputs.yield_plan` 的目标行（例如 `甲-净200-留10`）。
2. 取 `evidence` 的键 `短卷甲/1`、`短卷甲/3`；这些是段编号，不是成品编号。
3. 在 `outputs.runs` 中按同一 `id` 找到段，得到子卷轴 `start`/`end`、母卷轴 `origin` 和组成行列表 `evidence`。
4. 在 `outputs.exclusion` 中按同一 `id` 找到可保行，确认 `state="eligible"` 及其区间。
5. 回到 `source`：`checks` 给出该段的复检覆盖，`cuts` 给出刀带与绕向，`review.orders` 按 `id` 给出该行的 `length`/`allowance`。

由此，`610` 这个数可以完整复算为：段 420 取 2 件（`2×200+1×10`）加段 400 取 1 件（`200`），而不是来自任何界面标签。

### 9.3 自证完整性

`digest` 与 `source_digest` 是本地内容完整性校验，不是签名。规范 JSON 为 UTF-8、键排序、分隔符 `,` 与 `:`、不转义非 ASCII（序列化函数见 `slitweb/contract.py:32` 的 `canonical`，摘要算法见 `slitweb/artifacts.py:8` 的 `digest`）。可用下面的脚本核对下载包：

```python
import hashlib, json

with open('slitweb-d699c4687a8e518b.json', encoding='utf-8') as f:
    packet = json.load(f)

claimed = packet.pop('digest')
body = json.dumps(packet, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()
assert hashlib.sha256(body).hexdigest() == claimed

source = json.dumps(packet['source'], ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()
assert hashlib.sha256(source).hexdigest() == packet['source_digest']
print('完整性核对通过', packet['subject'], packet['source']['review']['orders'][1])
```

在本基线上，最小卷的整包摘要为 `d699c468…cce8f`，原始输入摘要为 `1b510390…0fbaf`。摘要按解析后的数据以键排序重新序列化，改动任何字段值或条目都会改变对应摘要，仅调整 JSON 空白或键顺序不会。

## 10. 抄数对照

同一张结果里，采购和裁剪抄的不是同一个字段，差值是刀口，不应互相改数：

| 角色 | 应抄字段 | 样例 `乙定尺`（`review-sample`） | 含义 | 不能拿去做什么 |
|---|---|---|---|---|
| 采购/报价 | `count` × `length` | 3 × 200 = 600 mm | 成品净长 | 不等于耗料，不能当库存 |
| 裁剪/车间 | `used` | 620 mm | 含 2 个件间刀口的耗料 | 不等于净长，不能跨行累加 |
| 两者核对 | `remainder` | 220 mm（段尾 120 + 100） | 该行算术余量 | 不能跨行相加，不能当整段余料 |
| 追溯 | `evidence` | `{"乙卷/1":3, "乙卷/4":0}` | 每段取件数 | `0` 不是用料；键不是成品号 |

`乙定尺` 的 620 可复算为：`乙卷/1` 段长 740，`floor(750/210)=3`，占用 `3×200+2×10=620`；`乙卷/4` 段长 100，`floor(110/210)=0`。余量 `(740+100)−620=220`。采购抄的 600 与裁剪抄的 620 相差 20 mm，正好是 3 件之间的 2 个刀口。

对号之前先对摘要：

- `review-sample` 中 `乙定尺` 的 `count=3`（可保 840 mm）；`review-alternate` 中同一 `乙定尺` 的 `count=4`（可保 1000 mm）。两者对象 `id` 相同但输入不同，摘要不同，数字不同是正常的。
- 只有 `subject` 相同且 `digest` 相同的包才能逐字段比较；界面上的未封存试算不是下载版本。
- 发现两个数不一致时，先确认是否同一 `digest`，再确认是否分别抄了 `count×length` 与 `used`，最后按第 3 节复算，而不是直接改其中一个数。

## 11. 复算清单

```sh
# 既有工作流检查：样例、对照、非法输入
python3 -m slitweb.check_flow yield_plan
python3 -m slitweb.check_flow runs
python3 -m slitweb.check_flow losses
python3 -m slitweb.check_flow export
```

不启动服务也可直接复算最小卷：

```python
import json
from slitweb import domain, rules, reconcile
from slitweb.review import analyze_review

source = json.load(open('examples/handover-minimal.json', encoding='utf-8'))
model = domain.parse(source)
facts = domain.evaluate(model)
outputs = rules.decide(model, facts)
outputs['exclusion'] = reconcile.summarize(model, facts, outputs)
outputs.update(analyze_review(source['review'], model, facts, outputs))

expected = {
    '甲-净200-留0': (4, 800, 20),
    '甲-净200-留10': (3, 610, 210),
    '甲-净200-留30': (2, 400, 420),
    '甲-净400-留0': (2, 800, 20),
    '甲-净500-留0': (0, 0, 820),
}
for row in outputs['yield_plan']:
    assert (row['count'], row['used'], row['remainder']) == expected[row['id']], row
    assert row['used'] + row['remainder'] == 820, row
    print(row['id'], row['count'], row['used'], row['remainder'], row['evidence'])
```

预期输出与第 4.2 节表格一致；每行均应满足 `used + remainder == 820`。

本文所述均可在当前基线由上述样例与命令复现；不涉及新增排产、分配或标价逻辑。
