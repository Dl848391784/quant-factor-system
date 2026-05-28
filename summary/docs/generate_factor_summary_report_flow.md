# generate_factor_summary_report.py 流程文档

> 版本: v1.3
> 生成时间: 2026-05-28 18:45
> 实测数据时间: 2026-05-28 18:45 北京时间
> 脚本版本: generate_factor_summary_report.py v1.3

---

## 概述

**脚本职责：** 读取各模块输出数据，生成因子分析汇总报告。

**数据来源：**
- factor_ic/result/ - IC 分析结果
- backtest/result/ - 分层回测结果
- comprehensive_factor/result/ - 综合因子结果
- data_fetchers/result/factor_ic_data.json.gz - 因子数据（用于计算相关性）

**输出位置：** summary/result/factor_summary_report_YYYY-MM-DD.txt

---

## 整体架构

```
┌──────────────────────────────────────────────────────────────────┐
│                    generate_factor_summary_report.py              │
├──────────────────────────────────────────────────────────────────┤
│  输入层                                                           │
│  ├── load_ic_results(date, logger)                               │
│  │   → 读取 factor_ic/result/ic_*_analysis_result.json           │
│  ├── load_backtest_results(date, logger)                         │
│  │   → 读取 backtest/result/*_layered_backtest.json              │
│  ├── load_composite_results(date, logger)                        │
│  │   → 读取 comprehensive_factor/result/composite_*_1d.json      │
│  └── calculate_factor_correlation(ic_results, logger, force_full)│
│      → 从综合因子结果读取相关性，或从因子数据计算                   │
├──────────────────────────────────────────────────────────────────┤
│  处理层                                                           │
│  ├── merge_factor_data(ic_results, backtest_results)             │
│  │   → 合并 IC 和回测数据                                         │
│  ├── generate_correlation_section(corr_matrix, ic_results)       │
│  │   → 生成相关性矩阵部分                                         │
│  └── get_factor_selection_info(composite_results, ic_results,   │
│      backtest_results, logger)                                   │
│      → 推断因子筛选结果                                           │
├──────────────────────────────────────────────────────────────────┤
│  输出层                                                           │
│  └── generate_report(date, logger, force_full_correlation)       │
│      → 生成完整汇总报告文本                                       │
│      → 写入 summary/result/factor_summary_report_YYYY-MM-DD.txt  │
└──────────────────────────────────────────────────────────────────┘
```

---

## 详细流程步骤

### Step 1: 初始化日志

```python
logger = setup_logger('generate_factor_summary_report')
logger.info(f"开始生成汇总报告 (版本 {__version__})")
```

日志文件路径：`summary/logs/generate_factor_summary_report_YYYY-MM-DD.log`

### Step 2: 加载 IC 结果

```python
ic_results = load_ic_results(date, logger)
```

**输入：** `factor_ic/result/ic_*_analysis_result.json`

**提取字段：**
- factor_name（去掉 `_1d` 后缀）
- ic_mean（IC 均值）
- icir（ICIR）
- ic_std（IC 标准差）
- valid_days（有效天数）

**输出结构：**
```python
[
    {'factor_name': 'turnover_surge', 'ic_mean': 0.032, 'icir': 0.51, 'ic_std': 0.089, 'valid_days': 498},
    {'factor_name': 'volume_ratio', 'ic_mean': -0.019, 'icir': 0.31, 'ic_std': 0.062, 'valid_days': 498},
    ...
]
```

**排序：** 按 ICIR 降序

### Step 3: 加载回测结果

```python
backtest_results = load_backtest_results(date, logger)
```

**输入：** `backtest/result/*_layered_backtest.json`

**提取字段：**
- factor_name
- long_short_return_annual（多空年化收益，转换为百分比）
- long_short_sharpe（夏普比率）
- monotonicity_correlation（单调性系数）
- monotonicity_quality（单调性质量）
- monotonicity_symbol（单调性符号）

**输出结构：**
```python
[
    {'factor_name': 'turnover_surge', 'long_short_return_annual': 17.35, 'long_short_sharpe': 2.10, ...},
    ...
]
```

### Step 4: 加载综合因子结果

```python
composite_results = load_composite_results(date, logger)
```

**输入：** `comprehensive_factor/result/composite_*_1d.json`

**权重方法：** ic_weight, icir_weight, rolling_icir_weight, equal_weight

**提取字段：**
- weight_method, weight_method_display
- long_short_return_annual, long_short_sharpe
- monotonicity_correlation, monotonicity_quality, monotonicity_symbol
- weight_str（格式化的权重字符串）

### Step 5: 计算因子相关性

```python
corr_matrix = calculate_factor_correlation(ic_results, logger, force_full=force_full_correlation)
```

**优先策略：** 从综合因子结果的 meta.correlation_matrix 读取

**备用策略（force_full=True）：** 从 factor_ic_data.json.gz 采样计算

**采样策略：** 最多 100 只股票，避免内存过大

### Step 6: 合并数据

```python
factor_data = merge_factor_data(ic_results, backtest_results)
```

合并 IC 和回测数据，用于后续对比分析。

### Step 7: 生成报告

```python
report = generate_report(date, logger, force_full_correlation=args.full_correlation)
output_path.write_text(report, encoding='utf-8')
```

**报告结构：**
1. 单因子 IC 数据汇总表
2. 单因子分层回测数据汇总表
3. 因子相关性矩阵
4. 因子筛选结果
5. 综合因子四种权重回测对比表
6. 综合因子 vs 单因子对比表

---

## CLI 参数

| 参数 | 说明 | 默认值 |
|------|------|--------|
| --date | 指定日期 | 当天 |
| --output | 输出文件路径 | summary/result/factor_summary_report_YYYY-MM-DD.txt |
| --full-correlation | 强制全量计算相关性 | False |

---

## 关键指标说明

| 指标 | 来源 | 说明 |
|------|------|------|
| ICIR | ic_metrics.icir | IC 均值 / IC 标准差，衡量因子稳定性 |
| 多空年化收益 | long_short.long_short_return_annual | Layer1 - Layer5 年化收益 |
| 单调性系数 | monotonicity.correlation | Layer 收益与 Layer 编号的相关性 |
| 单调性质量 | monotonicity.quality | good/moderate/poor/unknown |

---

## 异常处理

| 异常场景 | 处理方式 |
|---------|---------|
| IC 结果文件不存在 | logger.debug 记录，跳过 |
| 回测结果文件不存在 | logger.debug 记录，跳过 |
| 综合因子结果不存在 | 返回空列表 |
| 因子数据文件不存在 | 相关性矩阵设为 None |
| JSON 解析错误 | logger.warning 记录，返回 None |

---

## 更新记录

1. v1.2（2026-05-28）：
   - 创建流程文档
   - 记录数据流向和处理逻辑
   - 定义报告结构（6个部分）
   - 补充 CLI 参数说明