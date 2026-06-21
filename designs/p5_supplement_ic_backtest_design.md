# P5-补充: 6个二阶导数企稳信号因子 IC + 回测脚本

> v2.35 | 2026-06-21

## 1. 背景

现有5个确认信号因子（rsi_slope_3d, ma5_slope, lower_shadow_ratio, volume_shrink_rate, price_volume_divergence）4个IC为负、1个为弱正。从第一性原理分析：它们测的是一阶导数（动量方向），不是二阶导数（企稳状态）。

新增6个因子从3维度推导真正的"企稳信号"：
- 维度1（价格加速度）：return_acceleration_5d, downside_deceleration
- 维度2（波动收敛）：amplitude_compression, range_compression
- 维度3（量能衰竭）：volume_decay_rate, turnover_decay_rate

6个因子的计算函数已实现并提交（commit 2905060），factor_generator 已重跑完成。

## 2. 实施计划

按 H9（≤3文件 ≤200行）分4批，每批 ruff + pytest + commit。

### 批次A：3个 IC 脚本（return_acceleration_5d / downside_deceleration / amplitude_compression）

| 文件 | 规范 | 行数预估 |
|------|------|---------|
| `factor_ic/ic_return_acceleration_5d_1d.py` | M2 FactorSpec + M3.4 禁 sys.path | 170 |
| `factor_ic/ic_downside_deceleration_1d.py` | M2 FactorSpec + M3.4 | 170 |
| `factor_ic/ic_amplitude_compression_1d.py` | M2 FactorSpec + M3.4 | 170 |

关键签名（codegraph 确认）：
- `run_factor_ic(spec, *, return_period, min_stocks, force_full, args, logger, **kwargs)` — keyword-only
- `log_factor_summary(result, factor_display_name, logger)` — 3 位置参数
- `register_factor(spec: FactorSpec) -> FactorSpec` — 1 位置参数

### 批次B：3个 IC 脚本（range_compression / volume_decay_rate / turnover_decay_rate）

| 文件 | 规范 | 行数预估 |
|------|------|---------|
| `factor_ic/ic_range_compression_1d.py` | M2 + M3.4 | 170 |
| `factor_ic/ic_volume_decay_rate_1d.py` | M2 + M3.4 | 170 |
| `factor_ic/ic_turnover_decay_rate_1d.py` | M2 + M3.4 | 170 |

### 批次C：3个回测脚本（return_acceleration_5d / downside_deceleration / amplitude_compression）

| 文件 | 规范 | 行数预估 |
|------|------|---------|
| `backtest/layered_backtest_return_acceleration_5d_1d.py` | M5 ClassVar 薄声明 + M6 Sequence + M8 factor_cli_main | 50 |
| `backtest/layered_backtest_downside_deceleration_1d.py` | M5 + M6 + M8 | 50 |
| `backtest/layered_backtest_amplitude_compression_1d.py` | M5 + M6 + M8 | 50 |

关键签名（codegraph 确认）：
- `factor_cli_main(config_cls, factor_calculator=None, *, add_cli_args, setup_calculator)`
- `LayerConfigBase` 子类只需 `factor_name: ClassVar[str]` + `layer_names: ClassVar[Sequence[str]]`
- 预计算因子传 `factor_calculator=None`

### 批次D：3个回测脚本（range_compression / volume_decay_rate / turnover_decay_rate）+ run_pipeline 注册

| 文件 | 规范 | 行数预估 |
|------|------|---------|
| `backtest/layered_backtest_range_compression_1d.py` | M5 + M6 + M8 | 50 |
| `backtest/layered_backtest_volume_decay_rate_1d.py` | M5 + M6 + M8 | 50 |
| `backtest/layered_backtest_turnover_decay_rate_1d.py` | M5 + M6 + M8 | 50 |

### run_pipeline 注册（单独批次）

12个新 ScriptTask：6个 IC（Stage 2）+ 6个回测（Stage 3）

## 3. 参考脚本

- IC: `factor_ic/ic_rsi_slope_3d_1d.py`（v2.35 合规示例）
- 回测: `backtest/layered_backtest_rsi_slope_3d_1d.py`（v2.35 合规示例）

## 4. 每批验证清单

```
□ ruff check --fix .
□ ruff format .
□ ruff check .
□ python3 <脚本路径> --help  (确认CLI可运行)
□ git add <显式文件路径> -m "feat: <批次描述>"
□ git show --stat HEAD | tail  (验证commit行数)
```

## 5. 启动方式

和 run_pipeline 一致：`python3 <脚本路径> <args>` + `PYTHONPATH=项目根`
