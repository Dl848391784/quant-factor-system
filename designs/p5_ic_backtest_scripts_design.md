# P5 新因子 IC 脚本 + 分层回测脚本 Design

> 遵循 designs/strategy_systemic_overhaul.md §2.5 P5（批次5已完成因子计算函数）
> 本 design 覆盖：为5个预计算因子创建 IC 脚本 + 分层回测脚本

## 1. 背景

P5 批次5已在 factor_generator.py 注册5个新因子的计算函数：
- rsi_slope_3d (momentum): RSI 3日斜率
- ma5_slope (momentum): MA5 3日斜率
- lower_shadow_ratio (price_position): 下影线比
- volume_shrink_rate (volume): 缩量率
- price_volume_divergence (volume): 价跌量缩背离

这5个因子是**预计算因子**（已在 factor_ic_data.json.gz 中），不需要自定义计算函数。

## 2. 规范引用

| 规范 | 来源 | 要求 |
|------|------|------|
| M2 | factor_ic/MODULE.md L286 | 公共模块强制复用，禁止手写三模式分支 |
| M3.3 | factor_ic/MODULE.md L550 | FactorSpec 声明式注册 + run_factor_ic 统一入口 |
| M3.4 | factor_ic/MODULE.md L619 | 禁止 sys.path.insert，仅 import |
| H12 | PROJECT.md | 退出码 0/1/3/4/5 |
| R17/R18/R19 | factor_ic/MODULE.md | SummaryLogError=3, DataSchemaError=4, FactorCalcError=5 |
| M5 | backtest/MODULE.md L273 | Config 类 ClassVar 薄声明 |
| M8 | backtest/MODULE.md L359 | factor_cli_main 是 CLI 入口标准 |

## 3. 实施计划

### 批次A: 3个 IC 脚本（rsi_slope_3d + ma5_slope + lower_shadow_ratio）
### 批次B: 2个 IC 脚本（volume_shrink_rate + price_volume_divergence）
### 批次C: 3个回测脚本（rsi_slope_3d + ma5_slope + lower_shadow_ratio）
### 批次D: 2个回测脚本（volume_shrink_rate + price_volume_divergence）

每批 ≤3 文件，遵循 ruff → pytest → commit。

## 4. IC 脚本模板（遵循 ic_industry_roe_trend_1d.py v1.3 模式）

关键点：
- FactorSpec: 预计算因子省略 calculation 参数，required_columns 省略（公共模块自动派生）
- 异常处理: SpecRegistrationError → raise; DataSchemaError → exit 4; SummaryLogError → exit 3; FactorCalcError → exit 5
- main(args=None): 支持 args=None 库函数调用
- log_factor_summary: 摘要日志
- 禁止 sys.path.insert

## 5. 回测脚本模板（遵循 layered_backtest_rsi_1d.py 模式）

关键点：
- LayerConfigBase 子类: ClassVar factor_name + layer_names
- factor_cli_main(config_cls=..., factor_calculator=None): 预计算因子传 None
- layer_names: 5层 percentile

## 6. 验证标准

- ruff check 全通过
- python -m factor_ic.ic_xxx_1d --help 正常输出
- grep "sys.path.insert" factor_ic/ic_*_slope*.py 等零命中
- 回测脚本 import 成功
