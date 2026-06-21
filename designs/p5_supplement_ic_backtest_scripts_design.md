# P5-补充: 6个二阶导数企稳信号因子 IC + 回测脚本设计

> 遵循 AGENTS.md Design-First（H8: 涉及 2+ 文件改动，必须先提交 design.md）

## §1 背景

从第一性原理推导"企稳"的物理定义：**价格下跌速度在放缓**（二阶导数为正），而非一阶导数（价格方向）。

现有5个确认因子（rsi_slope_3d/ma5_slope/lower_shadow_ratio/volume_shrink_rate/price_volume_divergence）测的是一阶量或弱信号，4个IC为负。新增6个因子从3个维度测量二阶导数企稳信号：

| 维度 | 因子 | 公式 | 物理含义 |
|------|------|------|---------|
| 价格加速度 | return_acceleration_5d | return_5d(t) - return_5d(t-5) | 5日收益率加速度 |
| 价格加速度 | downside_deceleration | max(0, return_5d(t) - return_5d(t-5))，仅当 return_5d(t-5)<0 | 下跌股票跌幅收窄幅度 |
| 波动收敛 | amplitude_compression | mean(amplitude,5d) / mean(amplitude,10d) | 振幅收敛（<1=收敛） |
| 波动收敛 | range_compression | (rolling_high_5d - rolling_low_5d) / (rolling_high_10d - rolling_low_10d) | 价格区间收敛（<1=收敛） |
| 量能衰竭 | volume_decay_rate | volume_ma5 / volume_ma10 | 量能衰减（<1=衰减） |
| 量能衰竭 | turnover_decay_rate | turnover_rate / turnover_rate_ma5 | 换手率衰减（<1=衰减） |

## §2 规范引用

IC脚本遵循：
- M2（公共模块强制复用）：run_factor_ic() + FactorSpec
- M3.3（FactorSpec 声明式注册）
- M3.4（CLI 调用 `python -m`）
- R17-R19（退出码语义：0/1/3/4/5）
- H12（main() 体内禁 sys.exit）

回测脚本遵循：
- M5（ClassVar 薄声明，不用 @dataclass）
- M6（layer_names 用 Sequence）
- M8（factor_cli_main 是 CLI 入口标准）
- M53（预计算因子不传 factor_calculator）

## §3 批次拆分（遵循 H9: ≤3文件 ≤200行）

| 批次 | 文件 | 行数估计 | 内容 |
|------|------|---------|------|
| A | ic_return_acceleration_5d_1d.py | ~180 | IC脚本：价格加速度 |
| B | ic_downside_deceleration_1d.py, ic_amplitude_compression_1d.py | ~360 | IC脚本：下跌减速+振幅收敛 |
| C | ic_range_compression_1d.py, ic_volume_decay_rate_1d.py, ic_turnover_decay_rate_1d.py | ~540 | IC脚本：区间收敛+量能衰减+换手率衰减 |
| D | layered_backtest_return_acceleration_5d_1d.py, layered_backtest_downside_deceleration_1d.py | ~104 | 回测脚本：价格加速度+下跌减速 |
| E | layered_backtest_amplitude_compression_1d.py, layered_backtest_range_compression_1d.py, layered_backtest_volume_decay_rate_1d.py | ~156 | 回测脚本：波动收敛+量能衰竭 |
| F | layered_backtest_turnover_decay_rate_1d.py, run_pipeline.py | ~55+26 | 回测脚本+pipeline注册 |

每批完成后执行：ruff check → ruff format → pytest → git commit

## §4 模板来源

IC脚本模板：`factor_ic/ic_rsi_slope_3d_1d.py`（已验证合规）
回测脚本模板：`backtest/layered_backtest_rsi_slope_3d_1d.py`（已验证合规）

## §5 关键约束

1. IC脚本传 `calculation=calculate_xxx` 让 FactorSpec 自动派生 required_columns
2. 回测脚本不传 factor_calculator（因子已在 factor_ic_data.json.gz 预计算）
3. 脚本启动方式与 run_pipeline 一致：`python3 <脚本路径> <args>` + `PYTHONPATH=项目根`
