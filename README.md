# 分切疵点转印台

分切线质量工程师使用浏览器处理母卷实际幅宽及长度、验布疵点矩形、刀位、子卷绕向、局部复检区域和封样条件，交付子卷坐标疵点表、分切损耗证据和按已检范围生成的封样判定。全部内置数据为合成样例，不连接生产设备或在线服务。

## 本机运行

Python 3.11 或以上（含标准库 SQLite），不需要下载包。现代浏览器负责界面；Node.js 仅用于构建时检查 JavaScript 语法。

```sh
python3 -m slitweb.server
```

访问 `http://127.0.0.1:8861`。默认把封存成果写入 `.local/slitweb.sqlite`；可传 `--port`、`--db` 覆盖。界面先显示合成首例；可切换对照、导入 JSON、查看证据明细、封存成果、比较同对象版本或下载指定版本。

## 手动核对

```sh
python3 -m slitweb.check_flow layout
python3 -m slitweb.check_flow exclusion
python3 -m slitweb.check_flow export
```

这些命令在临时成果库和临时回环端口运行实际 HTTP 接口，分别核对样例、对照和拒绝路径。`examples` 保存业务示例及可人工核算的观测点。完整命令见 `.project-runtime.json`；自动化测试套件留置，不包含私有验收测试、缺陷任务或参考解答。

### 扩展复核

使用「复核样例」，随后在「扩展复核」切换各项结果。有效输入见 `examples/review-sample.json` 与 `examples/review-alternate.json`。例如运行 `python3 -m slitweb.check_flow face` 可核对派生结果、拒绝非法复核和基础版本兼容性。

## 离线刀位试算

工艺员遇到必须保留原净幅的订单时，在「离线刀位试算」面板录入可用刀位格（`slots`）、禁刀区间（`forbidden`）、品种净幅与最少条数（`order`）、实际转印与两端预留（`trial`）和疵点矩形，调用 `POST /slitweb/api/knife-plan`：

- 枚举能装上现有刀架的全部刀位序列，每条带都不窄于净幅，下刀点避开禁刀区间；可按 `ranking=length`（保住长段）或 `trim`（减少幅宽边料）择优。
- 被重大疵点穿过的条带仍可试切，走卷方向损失按「实际转印预留 + 两端预留」扩张后的并集核算，重叠疵点不重复计长；轻微疵点只登记不封锁。
- 等宽带宽序列相同的布局会两两对照，用命中疵点、净长损失、最短板可保长段和边料说明为何不等价。
- 找不到布局时返回 `infeasible` 和可复核的约束诊断，而不是空结果。所有备选都是 `trial` 试算状态，没有复检结论，不构成放行依据；试算请求不写入成果库。

```sh
python3 -m slitweb.check_planning
```

该命令在临时库和临时回环端口核对枚举择优、多疵点纵向重叠的并集核算、等宽布局不等价、无解约束说明与非法输入拒绝。样例见 `examples/planning-sample.json`、`planning-infeasible.json` 与 `planning-reject.json`。
