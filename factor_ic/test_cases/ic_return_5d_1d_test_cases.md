# ic_return_5d_1d 测试用例文档

> 版本: v1.0
> 最后更新: 2026-05-31 19:10 (北京时间)
> 测试脚本: factor_ic/test_cases/test_ic_return_5d_1d.py
> 因子脚本: factor_ic/ic_return_5d_1d.py

---

## 测试覆盖矩阵

| 测试类 | 测试场景 | pytest 标记 |
|-------|---------|------------|
| TestOutputPath | 输出路径规范 | 基础 |
| TestCalculateReturn5d | 因子计算逻辑 | 核心 |
| TestOutputStructure | 输出结构规范 | 验证 |

---

## 测试场景详解

### 1. TestOutputPath（基础测试）

**测试目标**: 验证输出路径和命名规范

| 测试方法 | 验证内容 | 期望结果 |
|---------|---------|---------|
| test_output_path_format | 输出文件命名 | `ic_return_5d_1d_analysis_result.json` |
| test_output_directory | 输出目录 | `factor_ic/result/` |
| test_output_directory_exists_or_created | 目录自动创建 | 目录存在或父目录存在 |

---

### 2. TestCalculateReturn5d（核心测试）

**测试目标**: 验证因子计算函数逻辑正确性

| 测试方法 | 测试场景 | 输入数据 | 期望输出 |
|---------|---------|---------|---------|
| test_basic_calculation | 基本计算 | close=[100, 102, 101, 103, 105, 108] | return_5d[5]=0.08 (108/100-1) |
| test_first_5_days_nan | 前5日边界 | 6天数据 | 前5天 return_5d=NaN |
| test_negative_return | 下跌场景 | close=[110, 108, 107, 106, 105, 100] | return_5d[5]=-0.09 |
| test_zero_close_handling | 除零保护 | close[0]=0 | return_5d[5]=NaN |
| test_multiple_assets | 多资产分组 | A/B两只股票 | 各组独立计算 |
| test_nan_handling | NaN传播 | close[0]=NaN | return_5d[5]=NaN |
| test_a_stock_range | A股典型范围 | 每日涨10% | return_5d[5]=0.61 |

**边界处理验证**:
- 前5日数据不足 → NaN（符合规范）
- close[t-5]=0 → NaN（除零保护）
- close[t-5]=NaN → NaN（数据质量）

---

### 3. TestOutputStructure（验证测试）

**测试目标**: 验证输出 JSON 结构符合规范

**必需字段检查**（MODULE.md 第43-67行）:

| 顶层字段 | 子字段要求 | 来源 |
|---------|-----------|------|
| factor_name | - | 固定值 `return_5d_1d` |
| calculation_date | - | ISO 时间戳 |
| period | start, end, description | 实测日期范围 |
| ic_metrics | ic_mean, ic_std, icir, p_value, p_value_display | IC计算结果 |
| sample_stats | total_days, valid_days, avg_stocks_per_day, avg_stocks_period | 样本统计 |
| statistical_significance | 7字段 | Newey-West t检验 |
| factor_direction | 4字段 | 方向判断 |
| economic_significance | 5字段 | 经济显著性 |
| icir_stability | 5字段 | ICIR稳定性 |
| ic_distribution_consistency | 6字段 | 分布一致性 |

**测试方法**:
- test_output_file_exists_after_run: 跳过条件（需先运行脚本）
- test_output_structure_if_exists: 检查顶层必需字段
- test_ic_metrics_fields_if_exists: 检查 ic_metrics 子字段
- test_sample_stats_fields_if_exists: 检查 sample_stats 子字段

---

## 实测验证数据（2026-05-31 19:07）

**运行结果**（对照流程文档 ic_return_5d_1d_flow.md）:

```
IC 均值: -0.0337
IC 标准差: 0.1566
ICIR: 0.21
p_value: 3.61e-08
有效天数: 509
总天数: 545
```

**五维度判断验证**:
- 统计显著性: p=3.61e-08 < 0.05 ✓
- 因子方向: negative（反向因子） ✓
- 经济显著性: |ic_mean|=0.0337 >= 0.03（弱） ✓
- ICIR稳定性: 0.21 < 0.5（不足） ✓
- IC分布一致性: 42.04% < 50%（一致） ✓

---

## pytest 运行命令

```bash
# 运行所有测试
pytest factor_ic/test_cases/test_ic_return_5d_1d.py -v

# 运行核心测试（因子计算）
pytest factor_ic/test_cases/test_ic_return_5d_1d.py::TestCalculateReturn5d -v

# 运行输出结构验证（需先运行脚本）
pytest factor_ic/test_cases/test_ic_return_5d_1d.py::TestOutputStructure -v
```

---

## 规范引用

- PROJECT.md：输出数据规范（第400-450行）
- MODULE.md：因子脚本规范（第1-150行）
- MODULE.md：输出结构模板（第43-67行）

---

## 版本历史

| 版本 | 日期 | 变更 |
|------|------|------|
| v1.0 | 2026-05-31 | 初始版本，测试覆盖完整 |