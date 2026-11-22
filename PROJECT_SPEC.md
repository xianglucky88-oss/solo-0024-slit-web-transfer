# 分切疵点转印台：数据规格

## 使用者和目标

分切线质量工程师提交母卷实际幅宽及长度、验布疵点矩形、刀位、子卷绕向、局部复检区域和封样条件，得到子卷坐标疵点表、分切损耗证据和按已检范围生成的封样判定。服务在回环地址启动，仅供本机处理。无需登录，不控制真实设备或放行生产数据。

## 数据合同

长度和幅向坐标使用毫米，面积使用平方毫米；坐标窗为左闭右开。反绕同时镜像横向与走卷向。重大转印疵点阻断整卷封样；复检窗按并集扣除盲区。修剪建议排除重大疵点、预留边距和未复检范围，选最长连续区间，等长取较早者。 在重大疵点安全边距和复检缺口的边界上拆分走卷轴；同一段可同时受两者约束，只将可保段用于连续修剪。复核可附 `batch_orders` 联合配料单：允许子卷、件长、需求量、每刀余量与优先级档（档值小者优先，1 为最高档）。

`examples/sample.json` 是字段及合法取值示例。`alternate.json` 是同一对象的另一有效输入，`reject.json` 是应被阻止的输入。对象在输入顶层以 `id` 标识；归约行使用原始身份或来源组件组合作为标识。缺测映射为 `null` 或待定状态，不当成数值零。接口接受不超过 512 KiB 的 UTF-8 JSON 对象；重复字段、非法数值或域内冲突返回 400。

成果保存数据合同版本、原始包、各阶段输出、输入摘要和整包摘要。SQLite 通过唯一摘要让同一个有效产物只存一次，错误输入不落库；版本比对只允许同一对象和同一合同版本。校验摘要用于本地内容完整性，不是签名。

## 生产工作流

| 工作流 | 公开入口 | 主要样例观测 |
|---|---|---|
| 刀位核账 | `POST /slitweb/api/evaluate 的 outputs.layout` | 甲卷 的 宽度 为 43 |
| 疵点转印 | `POST /slitweb/api/evaluate 的 outputs.transfer` | 乙卷/亮线 的 走卷起点 为 750 |
| 边料追踪 | `POST /slitweb/api/evaluate 的 outputs.scrap` | edge-1 的 来源证据 为 ["边刺"] |
| 复检覆盖 | `POST /slitweb/api/evaluate 的 outputs.coverage` | 乙卷 的 缺口 为 [[740, 900]] |
| 幅面封样 | `POST /slitweb/api/evaluate 的 outputs.release` | 乙卷 的 状态 为 "blocked" |
| 修剪提议 | `POST /slitweb/api/evaluate 的 outputs.trim` | 乙卷 的 终点 为 740 |
| 沿卷回查 | `POST /slitweb/api/evaluate 的 outputs.trace` | 乙卷 的 起点 为 185 |
| 禁保区间 | `POST /slitweb/api/evaluate 的 outputs.exclusion` | 乙卷/2 的 状态 为 "mixed" |
| 跨版本比较 | `POST /slitweb/api/compare` | 异版产生差异，同版无差异，跨对象拒绝 |
| 封存版本 | `POST /slitweb/api/seal` | 同输入仅写入一次，旧版不随对照改变 |
| 导出交接 | `GET /slitweb/api/export/<摘要>` | 下载头有效且内容完整保留历史快照 |

## 职责

- `slitweb/contract.py`：JSON 与领域字段边界。
- `slitweb/domain.py`：解析领域单位与归约事实。
- `slitweb/rules.py`：消费归约证据和约束，产生业务判定。
- `slitweb/artifacts.py`：成果规范编码、摘要与差分。
- `slitweb/archive.py`：SQLite 历史版本与原子封存。
- `slitweb/service.py`：串联归约、比对和历史读取。
- `slitweb/server.py`：本机 HTTP 及静态界面入口。
- `web/ui.js`：归约阶段、图形、归档与交互。
- `slitweb/reconcile.py`：联合原始归约事实与业务判定，推导禁保区间。
- `slitweb/batching.py`：联合配料逐档优化、下刀区间与余料留存核对。

浏览器显示来源和判定结果；发布决定由服务端归约。自动化测试套件留置。每条工作流的有界核对命令见 `.project-runtime.json`。

## 扩展复核

顶层可选 `review`；省略时基础包与旧版逐字段一致。启用时增加下列结果，与原数据共同封存，旧版与增强版可按阶段比对。`examples/review-sample.json` 给出有效输入结构。

- `face` 幅面复检：实际检验矩形做并集，和走卷长度覆盖分开。
- `defect_review` 疵点复核：转印范围与同卷复检窗取交；标记优先，完全覆盖才可判为未复现。
- `origin` 复检反查：宽向和纵向同时还原到母卷并回查疵点。
- `shared` 母卷疵点分摊：核对子卷与边料共同保留的原始疵点宽度。
- `runs` 连续可利用段：合并相邻可保段但不跨禁保区，记录母卷纵向范围。
- `yield_plan` 短卷产量：各连续段独立容纳定尺与段内切口留量，绝不跨段拼接。
- `batch` 联合配料：同一连续段不重复承诺给两个订单；逐档最大化同档完成件数，高档结果优先；各档件数相同再优先保留最长的一块连续余料；逐规格报价与各订单缺件并列对照。
- `batch_cuts` 下刀区间：成品不跨禁保段，同段相邻两件只留一次刀口并取两件余量中较大值；每件可按走卷与母卷坐标回查，余料逐段留存。
- `losses` 分因长度核账：重大、缺检、双因三类长度互斥，同可保长度核对整卷。
