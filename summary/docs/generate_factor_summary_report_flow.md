# generate_factor_summary_report.py 流程文档

> 版本: v2.0
> 创建时间: 2026-05-28
> 最后更新: 2026-06-19
> 脚本版本: generate_factor_summary_report.py v2.23

---

## 概述

**脚本职责：** 读取各模块输出数据，生成因子分析汇总报告。

**数据来源：**
- factor_ic/result/ - IC 分析结果
- backtest/result/ - 分层回测结果
- comprehensive_factor/result/ - 综合因子结果
- data_fetchers/result/factor_ic_data.json.gz - 因子数据（用于计算相关性）
- data_fetchers/result/tail_trading_data.json.gz - 尾盘5分钟K线数据（用于基础数据完整性检查）

**输出位置：** summary/result/factor_summary_report_YYYY-MM-DD.txt

---

## 整体架构

```
┌──────────────────────────────────────────────────────────────────┐
│                    generate_factor_summary_report.py              │
├──────────────────────────────────────────────────────────────────┤
│  输入层                                                           │
│  ├── check_data_freshness(date, logger)                          │
│  │   → 检查基础数据源新鲜度（v1.9 新增）                           │
│  ├── check_derived_data_freshness(date, logger)                  │
│  │   → 检查衍生数据存在性（v1.9 新增）                             │
│  ├── load_ic_results(logger)                                     │
│  │   → 读取 factor_ic/result/ic_*_analysis_result.json           │
│  ├── load_backtest_results(logger)                               │
│  │   → 读取 backtest/result/*_layered_backtest.json              │
│  ├── load_composite_results(logger)                              │
│  │   → 读取 comprehensive_factor/result/composite_*_1d.json      │
│  └── calculate_factor_correlation(logger, force_full)            │
│      → 从综合因子结果读取相关性，或从因子数据计算                   │
├──────────────────────────────────────────────────────────────────┤
│  处理层                                                           │
│  ├── merge_factor_data(ic_results, backtest_results)             │
│  │   → 合并 IC 和回测数据                                         │
│  ├── _generate_data_check_section(data_results, derived_results) │
│  │   → 生成数据完整性检查部分（v1.9 新增）                         │
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

### Step 0: 数据完整性检查（v1.9 新增）

**触发时机：** generate_report() 函数开始时，在加载 IC/回测数据之前

```python
logger.info("执行数据完整性检查...")
data_results = check_data_freshness(date, logger)
derived_results = check_derived_data_freshness(date, logger)
```

**检查内容：**

| 检查类型 | 数据源 | 日期字段路径 | 文件格式 |
|---------|--------|-------------|----------|
| 基础数据 | factor_ic_data.json.gz | dates[-1] | full_json（gzip，头部包含顶层 dates 数组） |
| 基础数据 | factor_data.json.gz | meta.date_range.end | full_json（gzip） |
| 基础数据 | turnover_rate_data.json.gz | meta.date_range.end | full_json（gzip） |
| 基础数据 | tail_trading_data.json.gz | meta.date_range.end | full_json（gzip） |
| 衍生数据 | IC 结果文件 | ic_series[-1].date | JSON |
| 衍生数据 | 回测结果文件 | 文件存在性检查 | — |
| 衍生数据 | 综合因子结果文件 | 文件存在性检查 | — |

**期望标准：** 最新日期 = T-1（前一天）

**状态判定：**

| 状态 | 条件 | 符号 |
|------|------|------|
| ok | actual_date == expected_date | ✓正常 |
| warning | actual_date != expected_date（可能非交易日） | △延迟 |
| error | 文件不存在 | ✗缺失 |
| error | 文件损坏或格式错误 | ✗读取失败 |
| error | 无法解析日期字段 | ✗无日期 |

**报告展示：** 第零部分展示检查结果表格

**输出示例：**
```
零、数据完整性检查
----------------------------------------------------------------------
期望数据日期: 2026-06-01 (T-1)

【基础数据源】
数据源               描述                     最新日期     状态
----------------------------------------------------------------------
factor_ic_data       主数据源(行情+因子+收益)    2026-06-01    ✓正常
factor_data          基础因子数据               2026-06-01    ✓正常
turnover_data        换手率数据                 2026-06-01    ✓正常
----------------------------------------------------------------------

【衍生数据】
数据源               描述                     文件数量     状态
----------------------------------------------------------------------
ic_results           IC分析结果                    10     ✓正常(10因子)
backtest_results     分层回测结果                  10     ✓正常(10因子)
composite_results    综合因子结果                   4     ✓正常(4权重)
----------------------------------------------------------------------

汇总: ✓ 所有数据源已更新至 T-1
```

### Step 1: 初始化日志

```python
logger = setup_logger('generate_factor_summary_report')
logger.info(f"开始生成汇总报告 (版本 {__version__})")
```

日志文件路径：`summary/logs/generate_factor_summary_report_YYYY-MM-DD.log`

### Step 2: 加载 IC 结果

```python
ic_results = load_ic_results(logger)
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
backtest_results = load_backtest_results(logger)
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
composite_results = load_composite_results(logger)
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
corr_matrix = calculate_factor_correlation(logger, force_full=force_full_correlation)
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
0. 数据完整性检查（v1.9 新增）
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
| 数据文件不存在 | 返回 error 状态，记录 logger.warning |
| IC 结果文件不存在 | logger.debug 记录，跳过 |
| 回测结果文件不存在 | logger.debug 记录，跳过 |
| 综合因子结果不存在 | 返回空列表 |
| 因子数据文件不存在 | 相关性矩阵设为 None |
| JSON 解析错误 | logger.warning 记录，返回 None |
| gzip 文件损坏 | 返回 error 状态，记录 logger.error |

---

## 数据完整性检查配置（v1.9 新增）

**DATA_CHECK_SOURCES 配置：**

```python
DATA_CHECK_SOURCES = {
    'factor_ic_data': {
        'path': 'data_fetchers/result/factor_ic_data.json.gz',
        'description': '主数据源(行情+因子+收益)',
        'date_field': 'dates',  # 从顶层 dates 数组获取最新日期
        'format': 'line_json',  # 每行一个 JSON 对象
        'is_gzip': True,
    },
    'factor_data': {
        'path': 'data_fetchers/result/factor_data.json.gz',
        'description': '基础因子数据',
        'date_field': 'meta.date_range.end',
        'format': 'full_json',
        'is_gzip': True,
    },
    'turnover_data': {
        'path': 'data_fetchers/result/turnover_rate_data.json.gz',
        'description': '换手率数据',
        'date_field': 'meta.date_range.end',
        'format': 'full_json',
        'is_gzip': True,
    },
}
```

---

## 更新记录

1. v1.2（2026-05-28）：
   - 创建流程文档
   - 记录数据流向和处理逻辑
   - 定义报告结构（6个部分）
   - 补充 CLI 参数说明

2. v1.5（2026-06-02）：
   - 新增 Step 0 数据完整性检查流程
   - 更新整体架构图（新增 check_data_freshness/check_derived_data_freshness）
   - 新增数据完整性检查配置说明

3. v1.8（2026-06-19）：
   - 同步脚本版本至 v2.21
   - v2.21 修复 6 项报告问题：
     - Fix1: Rolling ICIR last_day_weights 权重查找增加因子名回退（volume_ratio 0%→6.5%）
     - Fix2: overnight_ret 异常说明"其他因子均为负"→"其他主要因子均为负"
     - Fix3: Section 6 综合因子收益说明动态编号，避免条件不满足时跳号
     - Fix4: load_backtest_results 剥离 _1d 后缀（intraday_intensity_1d→intraday_intensity）
     - Fix5: overnight_ret 回测夏普/单调性精度格式化（15位小数→2位）
     - Fix6: z-score 列移除"≈0(真实)"标签，统一显示"0.00"

4. v1.9（2026-06-19）：
   - 同步脚本版本至 v2.22
   - v2.22 修复 5 项报告格式问题：
     - Fix1: format_weights 缩写表提取为模块级 FACTOR_ABBR，键归一化（列名→因子名）解决 vol/vr 不一致
     - Fix2: 权重 <0.5% 显示1位小数（momentum_strength 0%→0.4%）
     - Fix3: 相关性矩阵列头用因子缩写替代 name[:8]（tp_pos/tp_vol/tp_pos_d 可区分）
     - Fix4: 剔除因子列表拆多行显示，避免单行超长截断
     - Fix5: Section 8 新增覆盖率过滤信息（stock_selector v1.15 配合，meta 新增 excluded_by_coverage/min_weight_coverage）

5. v2.0（2026-06-19）：
   - 同步脚本版本至 v2.23
   - v2.23: format_weights 权重统一 :.1f 精度，与 Section 4/6 保持一致
     （修复 vr:6% vs 6.5% 跨节显示差异）