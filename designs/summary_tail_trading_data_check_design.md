# summary_tail_trading_data_check_design

> 日期: 2026-06-17
> 范围: summary 基础数据源完整性检查补充 tail_trading_data

## 背景

`fetch_tail_trading.py` 已输出 `data_fetchers/result/tail_trading_data.json.gz`，且尾盘因子 IC/回测已进入 summary 正文；但 `summary/generate_factor_summary_report.py` 的 `DATA_CHECK_SOURCES` 只检查 `factor_ic_data`、`factor_data`、`turnover_data`，报告第零部分无法展示尾盘原始数据是否更新。

## 触及规范

- `PROJECT.md` 行 22-24：涉及跨模块数据契约/2+ 文件改动，需要 Design-First。
- `summary/MODULE.md` 行 100-110：基础数据源检查由 `DATA_CHECK_SOURCES` 定义。
- `summary/MODULE.md` 行 158-168：状态判定需复用既有 ok/warning/error 规则。

## 方案

1. 在 `DATA_CHECK_SOURCES` 增加 `tail_trading_data`：
   - path: `data_fetchers/result/tail_trading_data.json.gz`
   - description: `尾盘5分钟K线数据`
   - date_field: `meta.date_range.end`
   - format: `full_json`
   - is_gzip: `True`
2. 增加回归测试，验证 `tail_trading_data` 完整 JSON 格式可被 `check_data_freshness()` 解析为正常状态。
3. 同步 `summary/MODULE.md` 与 `summary/docs/generate_factor_summary_report_flow.md` 的基础数据源表。
4. 不修改 `paths.py`、schema、上游 fetch 脚本，不重跑完整 pipeline。

## 验证

- `pytest summary/test_cases/test_generate_factor_summary_report.py::TestDataFreshnessCheck -q`
- `pytest summary/test_cases/test_generate_factor_summary_report.py -q`
- `ruff check --fix ... && ruff format ... && ruff check ...`
- 真实产物调用 `check_data_freshness('2026-06-17')`，应看到 `tail_trading_data actual_date=2026-06-16 status=ok`。
