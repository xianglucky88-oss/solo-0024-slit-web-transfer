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

## 定尺交接

采购、裁剪与车间对同一张短卷结果抄数的口径说明见 `docs/fixed-length-handover.md`，附带可逐项验算的最小输入 `examples/handover-minimal.json`。说明只解释现有 `yield_plan`/`runs`/`exclusion` 字段与下载追溯，不新增排产或标价规则。
