# P5-补充: 6个二阶导数企稳信号因子 IC+回测脚本 Design

> v2.35, 2026-06-21
> 遵循 AGENTS.md H8（Design-First）+ H9（≤3文件 ≤200行分批）

## 1. 背景

P5 最初新增5个一阶因子（rsi_slope_3d, ma5_slope, lower_shadow_ratio, volume_shrink_rate, price_volume_divergence），
但 IC 方向与预期不符（4个反向，1个极弱正向）。

从第一性原理推导：**"企稳"是二阶导数概念（下跌速度放缓），不是一阶导数（方向）**。
现有34个因子全部测一阶量，缺失二阶量维度。

因此新增6个二阶导数企稳信号因子（已在 factor_generator.py 注册，factor_ic_data.json.gz 中已有数据）：

| 维度 | 因子 | 公式 | 物理含义 |
|------|------|------|---------|
| 价格加速度 | return_acceleration_5d | return_5d(t) - return_5d(t-5) | 5日收益率加速度 |
| 价格加速度 | downside_deceleration | max(0, return_5d(t) - return_5d(t-5)) 仅当前期下跌 | 下跌减速幅度 |
| 波动收敛 | amplitude_compression | 5日均振幅 / 10日均振幅 | 振幅收敛 |
| 波动收敛 | range_compression | 5日价格区间 / 10日价格区间 | 价格区间收敛 |
| 量能衰竭 | volume_decay_rate | 5日均量 / 10日均量 | 量能衰减 |
| 量能衰竭 | turnover_decay_rate | 当日换手率 / 5日平均换手率 | 换手率衰减 |

本 design 只覆盖 **IC脚本 + 回测脚本** 的创建方案。
因子计算函数、factor_generator注册、factor_definitions注册已在前序commit完成（2905060），不在本design范围内。

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
| H8 | AGENTS.md | 2+文件改动先提交 design.md |
| H9 | AGENTS.md | ≤3文件 ≤200行分批验证 |

## 3. 实施计划（4批，遵循 H9）

### 批次A: 3个 IC 脚本（价格加速度维度）
- factor_ic/ic_return_acceleration_5d_1d.py
- factor_ic/ic_downside_deceleration_1d.py
- factor_ic/ic_amplitude_compression_1d.py

验证：ruff check → pytest → git commit

### 批次B: 3个 IC 脚本（波动收敛+量能衰竭维度）
- factor_ic/ic_range_compression_1d.py
- factor_ic/ic_volume_decay_rate_1d.py
- factor_ic/ic_turnover_decay_rate_1d.py

验证：ruff check → pytest → git commit

### 批次C: 3个 回测脚本（价格加速度+振幅收敛）
- backtest/layered_backtest_return_acceleration_5d_1d.py
- backtest/layered_backtest_downside_deceleration_1d.py
- backtest/layered_backtest_amplitude_compression_1d.py

验证：ruff check → pytest → git commit

### 批次D: 3个 回测脚本（区间收敛+量能衰竭）
- backtest/layered_backtest_range_compression_1d.py
- backtest/layered_backtest_volume_decay_rate_1d.py
- backtest/layered_backtest_turnover_decay_rate_1d.py

验证：ruff check → pytest → git commit

### 批次E: run_pipeline.py 注册 + design.md 更新
- run_pipeline.py（12个 ScriptTask + 脚本编号）
- designs/p5_ic_backtest_scripts_design.md（更新批次计划）

验证：ruff check → git commit

## 4. IC 脚本模板

遵循 ic_rsi_slope_3d_1d.py 模式（已完成5个同类脚本，可直接参照）：

关键点：
- FactorSpec: 传 calculation=calculate_xxx 让 FactorSpec 自动派生 required_columns
- 异常处理: SpecRegistrationError → raise; DataSchemaError → exit 4; SummaryLogError → exit 3; FactorCalcError → exit 5
- main(args=None): 支持 args=None 库函数调用
- log_factor_summary: 摘要日志
- 禁止 sys.path.insert（遵循 M3.4）

### 因子 → 计算函数 → import 路径映射

| 因子 | calculate_xxx | import 路径 |
|------|--------------|------------|
| return_acceleration_5d | calculate_return_acceleration_5d | data_fetchers.factor_calculator.momentum |
| downside_deceleration | calculate_downside_deceleration | data_fetchers.factor_calculator.momentum |
| amplitude_compression | calculate_amplitude_compression | data_fetchers.factor_calculator.volume_price |
| range_compression | calculate_range_compression | data_fetchers.factor_calculator.volume_price |
| volume_decay_rate | calculate_volume_decay_rate | data_fetchers.factor_calculator.volume_price |
| turnover_decay_rate | calculate_turnover_decay_rate | data_fetchers.factor_calculator.volume_price |

## 5. 回测脚本模板

遵循 layered_backtest_rsi_slope_3d_1d.py 模式（已完成5个同类脚本，可直接参照）：

关键点：
- LayeredBacktestConfig 子类: ClassVar factor_name + factor_col + layer_labels（遵循 M5）
- factor_calculator=None: 预计算因子不需要运行时计算
- factor_cli_main(ConfigCls): CLI 入口标准（遵循 M8）
- layer_labels: 5层，每层标签根据因子物理含义命名

### 回测 Config 类名 + layer_labels 映射

| 因子 | Config 类名 | layer_labels（5层） |
|------|------------|---------------------|
| return_acceleration_5d | ReturnAcceleration5dBacktest | 跌幅加速最大/跌幅加速较小/加速度适中/跌幅收窄较小/跌幅收窄最大 |
| downside_deceleration | DownsideDecelerationBacktest | 减速最小/减速较小/减速适中/减速较大/减速最大 |
| amplitude_compression | AmplitudeCompressionBacktest | 振幅发散最大/振幅发散较小/振幅适中/振幅收敛较小/振幅收敛最大 |
| range_compression | RangeCompressionBacktest | 区间发散最大/区间发散较小/区间适中/区间收敛较小/区间收敛最大 |
| volume_decay_rate | VolumeDecayRateBacktest | 量能放大最大/量能放大较小/量比适中/量能衰减较小/量能衰减最大 |
| turnover_decay_rate | TurnoverDecayRateBacktest | 换手率放大最大/换手率放大较小/换手率适中/换手率衰减较小/换手率衰减最大 |

## 6. 验证标准

- ruff check 全通过
- pytest 相关测试通过
- python3 factor_ic/ic_xxx_1d.py --help 正常输出（PYTHONPATH=项目根）
- python3 backtest/layered_backtest_xxx_1d.py --help 正常输出（PYTHONPATH=项目根）
- grep "sys.path.insert" 新增脚本零命中
- run_pipeline.py 中 ScriptTask 路径与脚本实际路径一致
