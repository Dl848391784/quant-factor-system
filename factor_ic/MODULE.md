# factor_ic 模块规范

> 本文档定义 factor_ic/ 目录下 IC 计算脚本的开发规范。
> 创建时间: 2026-05-19
> 版本: v1.1
> 更新内容: 删除重复的流程文档规范（已迁移至 PROJECT.md）

---

## 概述

factor_ic 模块负责计算各类因子的 IC（Information Coefficient）值，用于评估因子对未来收益的预测能力。

**模块定位：**
- 输入：来自 data_fetchers 的缓存数据（cache/factor_data/）
- 输出：IC 分析结果（factor_ic/result/）
- 依赖：不自行拉取数据，只处理已缓存数据

---

## factor_ic/ 目录规范

以下规范**仅适用于 `factor_ic/` 目录**，其他目录另有规范。

### 脚本命名

**格式：** `ic_<因子名>_<收益周期>.py`

| 收益周期 | 后缀 | 含义 |
|---------|------|------|
| T+1 收益 | `1d` | 次日收益率 |
| T+3 收益 | `3d` | 3日后收益率 |
| T+5 收益 | `5d` | 5日后收益率 |

**示例：**
```
ic_rsi_1d.py        # RSI因子，T+1收益
ic_rsi_3d.py        # RSI因子，T+3收益
ic_volume_ratio_1d.py  # 量比因子，T+1收益
```

**命名约定：**
- 因子名使用小写+下划线：`rsi`、`kdj_j`、`bollinger_pb`、`volume_ratio`
- 一个因子可有多个收益周期版本（1d、3d、5d等）

---

### 数据依赖

**数据来源：** 所有因子计算脚本的数据必须来自 `data_fetchers/` 目录的拉取脚本。

**禁止行为：**
- ❌ 在 factor_ic 脚本中直接调用外部 API 拉取数据
- ❌ 在 factor_ic 脚本中定义数据拉取逻辑

**正确做法：**
```python
# 因子计算脚本只读取缓存数据
factor_df = pd.read_csv('cache/factor_data/rsi/rsi_1d.csv')
# 计算 IC，不涉及数据拉取
```

---

### 输出目录规范

**输出路径：** `factor_ic/result/ic_<因子名>_<周期>_analysis_result.json`

**示例：**
```
factor_ic/result/ic_rsi_1d_analysis_result.json
factor_ic/result/ic_bollinger_pb_1d_analysis_result.json
factor_ic/result/ic_volume_ratio_1d_analysis_result.json
```

**禁止行为：**
- ❌ 输出到其他目录（如 cache/、backtest/）
- ❌ 使用非标准命名格式

---

## IC 计算规范

### IC 值计算

**定义：** IC = Spearman秩相关系数（因子值与未来收益的秩相关性）

**公式：**
```
IC(d) = spearman_correlation(factor_values_on_day_d, returns_on_day_d+period)
```

**选择 Spearman 的原因：**
1. 对异常值不敏感（Rank变换后）
2. 不要求线性关系
3. 适用于非线性因子（如技术指标）

---

### IC 统计指标

**必须输出的统计指标：**

| 字段 | 含义 | 计算方式 |
|------|------|---------|
| ic_mean | IC均值 | 所有有效日期IC值的算术平均 |
| ic_std | IC标准差 | 所有有效日期IC值的标准差 |
| ICIR | 信息比率 | abs(ic_mean) / ic_std |
| t_stat | t统计量 | ic_mean * sqrt(valid_days) / ic_std |
| p_value | 显著性p值 | 双尾t检验的p值 |
| valid_days | 有效IC天数 | 实际参与统计的日期数 |
| total_days | 总天数 | 原始缓存覆盖的日期数 |

**注意：**
- ICIR 使用 `abs(ic_mean)`，因为负IC和正IC同等重要
- p < 0.05 表示统计显著（与 |t| > 1.96 等价）

---

### 打印信息规范

**核心原则：** 打印信息必须准确反映实际计算结果，不得误导用户。

**完成信息规范：**
```
# ✓ 正确：同时显示有效天数和原始天数
print(f"完成！共计算 {valid_days} 天有效 IC 数据（原始数据 {total_days} 天）")

# ❌ 禁止：只显示原始天数，误导用户认为所有日期都有有效IC
print(f"完成！共计算 {total_days} 天 IC 数据")  # 错误！
```

**字段选择规则：**
| 场景 | 正确字段 | 禁止字段 |
|------|---------|---------|
| "共计算 X 天 IC 数据" | `valid_days` | `total_days` |
| "原始数据覆盖 X 天" | `total_days` | `valid_days` |
| 统计检验样本量 | `valid_days` | `total_days` |

**语义说明：**
- `valid_days`：实际计算出有效IC的天数（参与统计检验）
- `total_days`：原始缓存覆盖的日期数（可能包含NaN/跳过）
- 差距原因：计算周期等待（如布林带前N-1天NaN）、股票数不足跳过

---

### 因子方向判断规范

**核心原则：** 因子方向必须根据实际IC测试结果确定，不能根据因子类型假设。

**判断规则：**

| IC特征 | 因子方向 | 说明 |
|--------|---------|------|
| ic_mean > 0.03 且 p < 0.05 | 正向因子 | 高因子值预测高收益 |
| ic_mean < -0.03 且 p < 0.05 | 反向因子 | 高因子值预测低收益 |
| |t| < 1.96 或 p > 0.05 | 无效因子 | 无预测能力 |

**禁止行为：**
- ❌ 根据因子类型假设方向（如"RSI超买区应该是反向因子")
- ❌ 不做IC测试就预设 factor_direction 参数

**正确做法：**
```python
# 先运行IC计算脚本，根据 ic_mean 和 p_value 确定方向
python factor_ic/ic_rsi_1d.py
# 查看结果中的 ic_mean 和 p_value
# 根据结果设置分层回测的 factor_direction 参数
```

---

### 反向因子IC计算规范（2026-05-20新增）

**背景：** 布林带%B、RSI、KDJ_J等技术指标因子在逻辑上是反向因子（高值→超买→预期下跌），但IC计算实现方式存在歧义。本规范明确业界标准做法。

**反向因子定义：**
- 因子逻辑方向：因子值高预期收益低（如%B > 1 → 超买 → 预期下跌）
- 统计验证方向：ic_mean符号反映因子值与收益的相关性

**IC计算实现方式（业界标准）：**

| 方案 | 因子值处理 | IC计算方式 | 负IC含义 | 说明 |
|------|-----------|-----------|---------|------|
| **方案A（业界标准）** | 保持原始值 | 正向Spearman | 因子有效 | ic_calculator.py 实现 |
| 方案B | 反转因子值（1-%B） | 正向Spearman | 因子无效 | 改变因子语义 |

**当前项目采用方案A（业界标准）：**
```python
# ic_calculator.py 第303行
# 使用 Spearman 秩相关计算正向 IC（不反转）
ic_value = daily_data[factor_col].corr(
    daily_data[return_col],
    method='spearman'
)
```

**IC结果解释（反向因子）：**

| ic_mean_sign | 统计方向 | 因子有效性 | 因子逻辑解释 |
|--------------|----------|------------|--------------|
| 'negative' (ic_mean<0) | 负向 | ✓ 有效 | 高因子值→低收益，符合反向预期 |
| 'positive' (ic_mean>0) | 正向 | ✗ 无效 | 高因子值→高收益，与反向预期矛盾 |

**为什么不在因子值层面做反向处理？**
1. **保持因子原始语义：** %B = 0.5 表示价格在中轨，1-%B 会改变语义
2. **便于因子对比：** 所有技术指标因子使用相同计算方式，便于横向比较
3. **IC符号自带方向信息：** 负IC自然反映反向因子的有效性，无需额外处理
4. **分层回测参数化：** 通过 factor_direction 参数控制回测方向，而非改变因子值

**分层回测如何使用反向因子：**
```python
# backtest/layered_backtest.py
# factor_direction = 'negative' 表示反向因子
# 回测时会自动：做多低值组、做空高值组
engine = LayeredBacktestEngine(factor_direction='negative')
```

**文档与代码一致性要求：**
- 文件头注释必须明确因子逻辑方向（反向因子）
- 必须注明"IC计算使用正向Spearman（不反转）"
- 必须注明"ic_mean < 0 表示因子有效（符合反向预期）"

**示例（布林带%B）：**
```python
"""
因子逻辑：
- %B > 1：超买，预期回落（价格下跌）
- %B < 0：超卖，预期反弹（价格上涨）
- 布林带%B 是反向因子：因子值高预期收益低
- IC 计算使用正向 Spearman 相关（ic_calculator.py 实现）
- ic_mean < 0 表示因子有效（符合反向预期）
"""
```

---

### 输出格式规范

**JSON输出结构：**
```json
{
  "metadata": {
    "factor_name": "rsi",
    "return_period": "1d",
    "calculation_date": "2026-05-19T10:30:00",
    "data_source": "cache/factor_data/rsi/rsi_1d.csv",
    "total_days": 545,
    "valid_days": 513,
    "avg_stocks_per_day": 4235.2,
    "avg_stocks_period": {
      "start": "2024-01-01",
      "end": "2024-12-31",
      "description": "平均每日有效股票数统计范围"
    }
  },
  "statistics": {
    "ic_mean": -0.0348,
    "ic_std": 0.1377,
    "ICIR": 0.252,
    "t_stat": -5.99,
    "p_value": 3.2e-9,
    "significance": "significant"
  },
  "daily_ic": [
    {"date": "2024-01-02", "ic": -0.0412, "stocks_count": 4210},
    ...
  ],
  "period": {
    "start": "2024-01-01",
    "end": "2024-12-31",
    "description": "IC计算覆盖日期范围"
  }
}
```

**字段说明：**

| 字段路径 | 类型 | 必填 | 说明 |
|---------|------|------|------|
| metadata.factor_name | str | ✓ | 因子名称（小写） |
| metadata.return_period | str | ✓ | 收益周期（如 "1d"） |
| metadata.calculation_date | str | ✓ | 计算时间（ISO格式） |
| metadata.data_source | str | ✓ | 数据来源路径 |
| metadata.total_days | int | ✓ | 原始缓存日期数 |
| metadata.valid_days | int | ✓ | 有效IC天数 |
| metadata.avg_stocks_per_day | float | ✓ | 平均每日有效股票数 |
| metadata.avg_stocks_period | object | ✓ | 口径范围说明 |
| statistics.ic_mean | float | ✓ | IC均值 |
| statistics.ic_std | float | ✓ | IC标准差 |
| statistics.ICIR | float | ✓ | 信息比率 |
| statistics.t_stat | float | ✓ | t统计量 |
| statistics.p_value | float | ✓ | 显著性p值 |
| statistics.significance | str | ✓ | 显著性判断（"significant"/"not_significant"） |
| daily_ic | array | ✓ | 每日IC值数组 |
|| daily_ic[].date | str | ✓ | 日期 |
|| daily_ic[].ic | float | ✓ | 当日IC值 |
|| daily_ic[].stocks_count | int | ✓ | 当日有效股票数 |
|| period.start | str | ✓ | 覆盖起始日期 |
|| period.end | str | ✓ | 覆盖结束日期 |

---

### 输出结构统一性规范（2026-05-20新增）

#### 核心原则

**所有 factor_ic/ 目录下的 IC 计算脚本必须输出完全一致的 JSON 结构。**

**统一性要求：**
- 相同的顶层字段（factor_name, calculation_date, period, ic_metrics, sample_stats, statistical_significance, factor_direction, economic_significance, dates, ic_values, rolling_ic_mean, positive_ratio, n_assets, summary, factor_stats, update_mode）
- 相同的嵌套字段结构（如 ic_metrics 必须包含 ic_mean, ic_std, icir, p_value, p_value_display）
- 相同的字段类型（如 ic_mean 必须是 float，dates 必须是 list[str]）
- 相同的字段顺序（便于对比和自动化处理）

#### 统一输出结构定义

**所有因子脚本必须输出以下结构：**
```json
{
  "factor_name": "<因子名>",
  "calculation_date": "<ISO时间>",
  "period": {
    "start": "<起始日期>",
    "end": "<结束日期>",
    "description": "<范围说明>"
  },
  "ic_metrics": {
    "ic_mean": <float>,
    "ic_std": <float>,
    "icir": <float>,
    "p_value": <float>,
    "p_value_display": "<str>"
  },
  "sample_stats": {
    "total_days": <int>,
    "valid_days": <int>,
    "avg_stocks_per_day": <float>,
    "avg_stocks_period": {
      "start": "<str>",
      "end": "<str>",
      "description": "<str>"
    }
  },
  "statistical_significance": {
    "t_stat": <float>,
    "p_value": <float>,
    "p_value_display": "<str>",
    "is_significant": <bool>,
    "conclusion": "<str>"
  },
  "factor_direction": {
    "direction": "<str>",
    "ic_mean": <float>,
    "conclusion": "<str>"
  },
  "economic_significance": {
    "annual_ic_mean": <float>,
    "icir_annualized": <float>,
    "conclusion": "<str>"
  },
  "dates": ["<日期列表>"],
  "ic_values": [<IC值列表>],
  "rolling_ic_mean": [<滚动均值列表>],
  "positive_ratio": <float>,
  "n_assets": <int>,
  "summary": {
    "ic_performance": "<str>",
    "statistical_significance": "<str>",
    "factor_direction": "<str>",
    "economic_significance": "<str>",
    "recommendation": "<str>"
  },
  "factor_stats": {
    "factor_name": "<str>",
    "return_period": "<str>",
    "data_source": "<str>",
    "total_days": <int>,
    "valid_days": <int>
  },
  "update_mode": "<str>"
}
```

#### 禁止行为

```python
# ❌ 禁止：不同因子脚本输出不同结构
# ic_rsi_1d.py 输出：
{
  "ic_mean": 0.05,  # 顶层字段
  "ic_std": 0.15
}

# ic_kdj_j_1d.py 输出：
{
  "ic_metrics": {  # 嵌套结构，与 rsi 不一致！
    "ic_mean": 0.05,
    "ic_std": 0.15
  }
}
```

#### 为何必须统一输出结构

1. **自动化处理：** 后续分析脚本可以统一解析所有因子结果，无需针对每个因子写特殊处理逻辑
2. **横向对比：** 不同因子可以直接对比 IC 表现，字段位置一致便于可视化
3. **维护成本：** 新增因子只需遵循统一模板，无需重新设计输出结构
4. **错误预防：** 统一结构避免字段缺失导致的 KeyError

#### 结构一致性检查清单

```
□ 所有因子脚本输出相同的顶层字段
□ 所有因子脚本的嵌套字段结构一致（如 ic_metrics 字段列表）
□ 所有因子脚本的字段类型一致（如 ic_mean 永远是 float）
□ 所有因子脚本的字段顺序一致（便于自动化对比）
□ 新增因子脚本时，对比已有脚本输出结构，确保一致
```

---

### 字段值完整性检查规范（2026-05-20新增）

#### 核心原则

**输出 JSON 前，必须检查每个字段是否有值。字段值为 None/null 代表数据有问题，需要明确诊断原因。**

#### 检查范围

**必须检查完整性的字段：**

| 字段类型 | 检查内容 | None/null 含义 |
|---------|---------|---------------|
| 数值字段（ic_mean, ic_std, icir, t_stat, p_value） | 必须有有效数值 | 计算失败，数据不足以计算统计指标 |
| 整数字段（total_days, valid_days, n_assets） | 必须 ≥ 0 | 数据源为空或计算过程异常 |
| 字符串字段（factor_name, calculation_date, period.start/end） | 必须非空 | 数据缺失或格式转换失败 |
| 数组字段（dates, ic_values, rolling_ic_mean） | 必须非空数组 | IC 计算完全失败，无任何有效日期 |
| 嵌套对象（ic_metrics, sample_stats, statistical_significance） | 必须存在且包含所有子字段 | 返回值契约不完整 |

#### 正确实现

```python
# ✓ 正确：输出前检查字段完整性
def validate_output_completeness(result: dict) -> None:
    """校验输出字段完整性，None/null 值需要诊断原因"""
    
    # 1. 检查数值字段
    numeric_fields = ['ic_mean', 'ic_std', 'icir', 't_stat', 'p_value']
    for field in numeric_fields:
        value = result.get('ic_metrics', {}).get(field)
        if value is None or (isinstance(value, float) and pd.isna(value)):
            raise RuntimeError(
                f"输出字段 {field} 值为 None/null\n"
                f"问题定位: IC 计算过程未能生成有效统计指标\n"
                f"可能原因: valid_days=0（无有效IC日期），或计算异常\n"
                f"建议: 检查数据源是否有足够的因子值和收益数据"
            )
    
    # 2. 检查整数字段
    int_fields = ['total_days', 'valid_days', 'n_assets']
    for field in int_fields:
        if field in ['total_days', 'valid_days']:
            value = result.get('sample_stats', {}).get(field)
        else:
            value = result.get(field)
        if value is None or value < 0:
            raise RuntimeError(
                f"输出字段 {field} 值无效: {value}\n"
                f"问题定位: 数据统计失败\n"
                f"建议: 检查数据源是否为空"
            )
    
    # 3. 检查数组字段
    dates = result.get('dates', [])
    ic_values = result.get('ic_values', [])
    if len(dates) == 0 or len(ic_values) == 0:
        raise RuntimeError(
            f"输出数组字段为空: dates={len(dates)}, ic_values={len(ic_values)}\n"
            f"问题定位: IC 计算完全失败，无任何有效日期\n"
            f"可能原因: 所有日期因股票数不足跳过，或因子值全为 NaN\n"
            f"建议: 检查 min_stocks 阈值是否过高，或因子计算预热期问题"
        )
    
    # 4. 检查数组长度一致性
    if len(dates) != len(ic_values):
        raise RuntimeError(
            f"数组长度不一致: dates={len(dates)}, ic_values={len(ic_values)}\n"
            f"问题定位: 数据结构构建错误\n"
            f"建议: 检查 dates 和 ic_values 是否来自同一数据源"
        )
    
    # 5. 检查 rolling_ic_mean 与 dates 长度一致
    rolling_ic_mean = result.get('rolling_ic_mean', [])
    if len(rolling_ic_mean) != len(dates):
        raise RuntimeError(
            f"rolling_ic_mean 长度不一致: {len(rolling_ic_mean)} vs dates={len(dates)}\n"
            f"问题定位: 滚动计算未正确填充\n"
            f"建议: 检查 rolling 计算是否基于完整 ic_series"
        )
    
    # 6. 检查嵌套对象完整性
    required_nested = {
        'ic_metrics': ['ic_mean', 'ic_std', 'icir', 'p_value', 'p_value_display'],
        'sample_stats': ['total_days', 'valid_days', 'avg_stocks_per_day', 'avg_stocks_period'],
        'statistical_significance': ['t_stat', 'p_value', 'is_significant', 'conclusion'],
        'factor_direction': ['direction', 'ic_mean', 'conclusion'],
        'economic_significance': ['annual_ic_mean', 'icir_annualized', 'conclusion']
    }
    
    for parent, children in required_nested.items():
        parent_obj = result.get(parent)
        if parent_obj is None:
            raise RuntimeError(
                f"输出缺少嵌套对象: {parent}\n"
                f"问题定位: 返回值契约不完整\n"
                f"建议: 检查 calculate_ic_with_direction_verification 返回值"
            )
        for child in children:
            if child not in parent_obj:
                raise RuntimeError(
                    f"嵌套对象 {parent} 缺少字段: {child}\n"
                    f"问题定位: 字段构建遗漏\n"
                    f"建议: 检查 {parent} 字段构建逻辑"
                )

# 在输出前调用
validate_output_completeness(result)
with open(output_path, 'w') as f:
    json.dump(result, f, indent=2)
```

#### None/null 值诊断清单

**当字段值为 None/null 时，必须诊断原因：**

| 字段 | None/null 原因 | 诊断方法 |
|------|---------------|---------|
| ic_mean | valid_days=0（无有效IC日期） | 检查 dates 数组是否为空 |
| ic_std | 单一IC值（std无法计算） | 检查 valid_days 是否 = 1 |
| icir | ic_std=0（除零） | 检查 IC 值是否全部相同 |
| dates=[] | 所有日期跳过 | 检查跳过原因日志（股票数不足/因子NaN） |
| rolling_ic_mean=[] | ic_series 为空 | 检查 dates 数组长度 |
| avg_stocks_per_day | 所有日期股票数=0 | 检查因子数据是否有股票 |

#### 禁止行为

```python
# ❌ 禁止：输出前不检查字段完整性
with open(output_path, 'w') as f:
    json.dump(result, f)  # 直接输出，可能包含 None/null

# ❌ 禁止：忽略 None 值，不诊断原因
if result['ic_mean'] is None:
    print("IC 计算失败")  # 缺乏诊断信息
    return  # 静默返回，用户不知道失败原因

# ❌ 禁止：用默认值掩盖 None
'ic_mean': result.get('ic_mean', 0.0)  # None → 0.0，掩盖问题！
```

#### 为何必须检查字段完整性

1. **问题定位：** None/null 值代表数据有问题，必须明确诊断原因
2. **数据质量：** 避免 None 值被默认值掩盖，误导后续分析
3. **用户友好：** 明确告知用户失败原因，而非输出空数据
4. **自动化处理：** 后续脚本可以信任所有字段都有有效值

#### 检查清单

```
□ 数值字段检查：ic_mean, ic_std, icir, t_stat, p_value 必须有有效值
□ 整数字段检查：total_days, valid_days, n_assets 必须 ≥ 0
□ 字符串字段检查：factor_name, period.start/end 必须非空
□ 数组字段检查：dates, ic_values 必须非空
□ 数组长度检查：dates, ic_values, rolling_ic_mean 长度必须一致
□ 嵌套对象检查：所有嵌套对象必须存在且包含所有子字段
□ None 值诊断：发现 None 时必须明确原因并输出诊断信息
□ 输出前校验：在 json.dump 前调用 validate_output_completeness
```

---

## 增量更新规范

### 增量模式定义

**增量模式 = 追加新日期的IC值，保留历史IC值，重新计算统计指标**

**公式：**
```
增量模式：新IC值 + 历史IC值 → 重算统计指标
全量模式：全部日期 → 全新计算
```

**触发条件：**
- 缓存存在 → 尝试增量更新
- 缓存不存在 → 执行全量计算
- 命令行参数 `--force-full` → 强制全量计算

---

### 增量判断流程

```
┌─────────────────────────────────────────────────────┐
│ 1. 检查缓存文件是否存在                               │
│    ├─ 不存在 → full 模式（全量计算）                   │
│    └─ 存在 → 读取 existing_dates                      │
└─────────────────────────────────────────────────────┘
          ↓
┌─────────────────────────────────────────────────────┐
│ 2. 读取因子数据，获取 factor_df['date'].unique()      │
│    → new_dates                                         │
└─────────────────────────────────────────────────────┘
          ↓
┌─────────────────────────────────────────────────────┐
│ 3. 比较 existing_dates vs new_dates                   │
│    ├─ new_dates ⊆ existing_dates → skip 模式         │
│    │   （无需更新，返回缓存）                          │
│    ├─ new_dates == existing_dates → skip 模式        │
│    │   （数据完全一致）                                │
│    └─ new_dates 有缺失日期 → incremental 模式        │
│    │   （计算缺失日期IC，合并后重算统计）              │
└─────────────────────────────────────────────────────┘
          ↓
┌─────────────────────────────────────────────────────┐
│ 4. incremental 模式执行                                │
│    ├─ 只计算 missing_dates 的IC值                     │
│    ├─ 合并：新IC值 + 历史IC值                          │
│    ├─ 重算统计指标（ic_mean, ic_std, ICIR等）         │
│    └─ 更新 metadata（valid_days, total_days等）      │
└─────────────────────────────────────────────────────┘
```

---

### 缺失日期诊断规范

**核心原则：** 增量更新时必须诊断缺失日期的数据覆盖情况，区分"数据源无数据"和"缓存缺失"。

**诊断场景：**

| 场景 | 诊断信息 | 用户行动 |
|------|---------|---------|
| 缺失日期不在缓存范围 | `[警告] N 个缺失日期不在当前因子缓存范围` | 检查数据源日期范围，或执行全量重算 |
| 缺失日期在缓存范围但无有效数据 | `[诊断] 缺失日期在缓存范围内，但筛选后无有效数据` | 检查股票过滤条件 |
| 所有缺失日期均不在缓存范围 | `[诊断] 无法增量更新` | 执行全量重算 (force_full=True) |

**正确实现：**
```python
# 筛选缺失日期的数据
missing_set = set(missing_dates)
factor_df_new = factor_df_full[factor_df_full['date'].isin(missing_set)]

# 诊断：检查缺失日期的数据覆盖情况
dates_in_cache = set(factor_df_full['date'].unique())
dates_not_in_cache = missing_set - dates_in_cache

if dates_not_in_cache:
    print(f"  [警告] {len(dates_not_in_cache)} 个缺失日期不在当前因子缓存范围")
    print(f"  [警告] 可能原因: 数据源未覆盖这些日期，或因子缓存已过期清理")
    examples = sorted(dates_not_in_cache)[:5]
    print(f"  [警告] 示例日期: {examples}")

if factor_df_new.empty:
    if dates_not_in_cache:
        print("  [诊断] 所有缺失日期均不在当前缓存范围，无法增量更新")
        print("  [建议] 检查数据源日期范围，或执行全量重算 (force_full=True)")
    else:
        print("  [诊断] 缺失日期在缓存范围内，但筛选后无有效数据")
    print("  - 跳过增量计算，返回现有缓存")
    return existing_data
```

---

## 参数传递规范

### 默认参数常量

**必须定义的默认参数：**
```python
DEFAULT_MIN_STOCKS = 10  # 每日最少股票数阈值
DEFAULT_IC_THRESHOLD = 0.03  # IC显著性阈值
DEFAULT_P_THRESHOLD = 0.05  # p值显著性阈值
```

**参数传递方式：**
```python
def calculate_ic(factor_df: pd.DataFrame, 
                 return_period: str,
                 min_stocks: int = DEFAULT_MIN_STOCKS) -> dict:
    # 参数通过函数签名传递，不使用全局变量
    pass
```

**禁止行为：**
- ❌ 在函数内部硬编码参数值（如 `min_stocks = 10`）
- ❌ 使用全局变量传递参数

### DataFrame 参数副本规范（2026-05-20新增）

**核心原则：** 函数接收 DataFrame 参数时，必须先调用 `.copy()` 创建副本，避免修改原始数据。

**为何必须副本：**

pandas DataFrame 是引用类型。直接修改传入的 DataFrame 会导致副作用：
```python
# ❌ 错误示例：副作用影响调用方
def calculate_factor(factor_df: pd.DataFrame):
    factor_df['new_col'] = factor_df['existing_col'].transform(...)  # 副作用！
    factor_df = factor_df.sort_values('date').copy()  # .copy() 太晚，副作用已发生
    return factor_df

# 调用方传入的 original_df 被污染：
original_df['new_col']  # 本不应存在，但已被添加
```

**正确做法：**
```python
# ✓ 正确：函数入口处先复制
def calculate_factor(factor_df: pd.DataFrame):
    factor_df = factor_df.copy()  # ← 第一步：创建副本，隔离副作用
    factor_df['new_col'] = factor_df['existing_col'].transform(...)  # 安全修改副本
    factor_df = factor_df.sort_values('date')  # 不需要再 .copy()
    return factor_df
```

**位置要求：**

| 操作顺序 | 正确性 | 原因 |
|----------|--------|------|
| `.copy()` → 列赋值 → `.sort_values()` | ✓ 正确 | 副本隔离，后续操作安全 |
| 列赋值 → `.sort_values().copy()` | ❌ 错误 | 赋值发生在原始 DataFrame，副作用已产生 |
| `.sort_values().copy()` → 列赋值 | ⚠ 部分安全 | sort 可能改变原始索引视图，赋值可能污染 |

**最佳实践：**
```python
def calculate_xxx_ic(factor_df: pd.DataFrame, ...):
    # Step 0: 创建副本（必须放在函数开头）
    factor_df = factor_df.copy()
    
    # Step 1: 类型转换（现在安全）
    factor_df['date_str'] = factor_df['date'].astype(str)
    
    # Step 2: 排序（不需要再 .copy()）
    factor_df = factor_df.sort_values(['asset', 'date_str'])
    
    # Step 3: 计算因子列
    factor_df['factor_col'] = ...
    
    return factor_df
```

**何时不需要 `.copy()`：**
- 函数只读取 DataFrame，不修改列
- 函数返回全新的 DataFrame（如 `pd.DataFrame(result_dict)`）
- 函数内部使用 `.copy()` 创建中间变量（如 `temp_df = df.copy()`）

**常见错误模式：**

| 错误代码 | 问题 | 修复 |
|----------|------|------|
| `factor_df['col'] = ...` | 直接赋值，副作用 | 先 `factor_df = factor_df.copy()` |
| `factor_df.sort_values().copy()` | copy 太晚 | 移到开头 `factor_df = factor_df.copy()` |
| `factor_df.assign(col=...)` | assign 返回新 DataFrame，但原 df 未保护 | 若后续用原 df，需先 copy |

**验证方法：**
```python
# 单元测试：验证无副作用
original_df = pd.DataFrame({'date': [1, 2, 3], 'value': [10, 20, 30]})
original_cols = original_df.columns.tolist()

result_df = calculate_factor(original_df)

# 原始 DataFrame 不应被修改
assert original_df.columns.tolist() == original_cols
assert 'new_col' not in original_df.columns
```

---

## 异常处理规范

### 异常类型保留

**原则：** 异常类型必须准确反映错误原因，不随意包装。

| 异常类型 | 使用场景 | 是否包装 |
|---------|---------|---------|
| ValueError | 数据验证错误（缺失列、格式错误） | ❌ 直接 raise |
| RuntimeError | 基础设施错误（API失败、网络异常） | ✓ 可包装 |
| KeyError | 必需字段缺失 | ❌ 直接 raise |
| TypeError | 类型错误 | ❌ 直接 raise |

**正确示例：**
```python
if 'rsi' not in factor_df.columns:
    raise ValueError(f"因子数据缺少必需列 'rsi'，现有列: {list(factor_df.columns)}")
```

**禁止行为：**
```python
# ❌ 禁止：ValueError包装为RuntimeError
try:
    validate_data(factor_df)
except ValueError as e:
    raise RuntimeError(f"数据验证失败: {e}")  # 错误！
```

---

### 防御性异常处理

**原则：** 异常诊断信息中的数据访问必须防御性处理，避免二次异常。

**场景：**
- 异常处理时访问可能不存在的 DataFrame 列
- 空 DataFrame 统计（返回 0 而非抛出异常）

**正确示例：**
```python
# ✓ 正确：先检查列存在，不存在时返回安全默认值
factor_assets = factor_df['asset'].nunique() if 'asset' in factor_df.columns else 0
return_assets = return_df['asset'].nunique() if 'asset' in return_df.columns else 0

raise RuntimeError(
    f"IC 计算结果为空\n"
    f"因子数据: {len(factor_df)} 行, {factor_assets} 只股票\n"
    f"收益数据: {len(return_df)} 行, {return_assets} 只股票\n"
    f"建议: 检查数据源或降低阈值"
)
```

**禁止行为：**
```python
# ❌ 禁止：直接访问可能不存在的列
raise RuntimeError(
    f"因子数据: {factor_df['asset'].nunique()} 只股票"  # KeyError 风险！
)
```

**空 DataFrame 统计行为：**
| 操作 | 空 DataFrame 结果 | 说明 |
|------|------------------|------|
| `len(df)` | 0 | 安全 |
| `df['col'].nunique()` | 0（若列存在） | 安全 |
| `df['col']` | KeyError（若列不存在） | 需防御 |

---

## 字段去重化规范（2026-05-20新增）

### 核心原则

**原则：** 同一字段只在一个位置输出，避免数据结构冗余。

**场景：**
- `ic_metrics` 和 `statistical_significance` 可能包含相同字段
- `ic_metrics` 和 `result` 顶层字段可能重复

**正确示例：**
```python
# ✓ 正确：ic_metrics 只包含核心 IC 指标，p_value 在 statistical_significance 中
'ic_metrics': {
    'ic_mean': round(result['ic_mean'], 6),
    'ic_std': round(result['ic_std'], 6),
    'icir': round(result['icir'], 4)
},
'statistical_significance': {
    'p_value': ss_dict['p_value'],
    'p_value_display': ss_dict['p_value_display'],
    't_stat': ss_dict['t_stat'],
    'is_significant': ss_dict['is_significant'],
    'conclusion': ss_dict['conclusion']
}
```

**禁止行为：**
```python
# ❌ 禁止：字段在多处重复出现
'ic_metrics': {
    'ic_mean': round(result['ic_mean'], 6),
    'p_value': round(result['p_value'], 6),  # 冗余！statistical_significance 中已有
    'p_value_display': str(round(result['p_value'], 6))  # 冗余！且回退值无意义
},
'statistical_significance': {
    'p_value': ss_dict['p_value'],  # 重复
    'p_value_display': ss_dict['p_value_display']
}
```

### 字段归属表

| 字段 | 输出位置 | 说明 |
|------|----------|------|
| ic_mean, ic_std, icir | `ic_metrics` | 核心 IC 指标 |
| p_value, p_value_display, t_stat | `statistical_significance` | 统计显著性判断 |
| positive_ratio | 顶层或 `ic_distribution_consistency` | IC 分布一致性判断使用 |

### p_value_display 回退逻辑说明

**场景：** `p_value_display` 是可选字段，上游可能不提供。

**正确做法：**
```python
# ✓ 正确：在 statistical_significance 中使用 .get() 安全访问，有意义的回退值
'p_value_display': ss_dict.get('p_value_display', str(round(ss_dict['p_value'], 4)))
```

**禁止行为：**
```python
# ❌ 禁止：回退值与 p_value 完全相同（只是类型转换）
'p_value_display': str(round(result['p_value'], 6))  # round(x,6) 再 str()，值不变
```

**设计原则：**
- `p_value_display` 应由上游 `_format_p_value()` 生成，格式化逻辑一致
- 回退值仅在极端情况下使用，应与上游格式化逻辑对齐（如 `round(x, 4)` 或科学计数法）

---

## 日期类型一致性规范

### 日期格式断言

**强制格式：** 所有日期字符串必须为 `YYYY-MM-DD` 格式。

**必须添加的断言：**
```python
import re

DATE_FORMAT_PATTERN = re.compile(r'^\d{4}-\d{2}-\d{2}$')

def validate_date_format(date_str: str) -> None:
    # 验证日期格式为 YYYY-MM-DD
    if not DATE_FORMAT_PATTERN.match(date_str):
        raise ValueError(f"日期格式错误: '{date_str}'，期望 YYYY-MM-DD")

# 在使用日期前调用
for date in dates:
    validate_date_format(date)
```

**应用场景：**
1. 读取缓存数据时，验证 date 列格式
2. 读取现有IC结果时，验证 existing_dates 格式
3. 生成 period.start/end 时，确保格式一致

**禁止行为：**
- ❌ 依赖字符串比较的隐式约定（如 `"2024-01-01" < "2024-02-01"`）
- ❌ 不验证格式就使用 min/max 比较日期

---

## 输入验证规范

### 列存在检查

**必须验证的列：**
```python
REQUIRED_COLUMNS = ['date', 'symbol', 'factor_value', 'future_return']

def validate_columns(df: pd.DataFrame) -> None:
    # 验证必需列存在
    missing = [col for col in REQUIRED_COLUMNS if col not in df.columns]
    if missing:
        available = list(df.columns)
        raise ValueError(
            f"数据缺少必需列: {missing}\n"
            f"可用列: {available}"
        )
```

---

## 公共函数复用规范

### 必须复用的公共函数

**factor_ic/common/ 目录下的公共函数：**

| 函数 | 文件 | 用途 |
|------|------|------|
| calculate_rank_ic | reverse_rank_ic.py | 计算Spearman秩IC |
| validate_date_format | （待创建） | 验证日期格式 |
| calculate_ic_statistics | （待创建） | 计算统计指标 |

**复用规范：**
```python
from factor_ic.common.reverse_rank_ic import calculate_rank_ic

# ❌ 禁止：在脚本中重新实现
def my_calculate_ic(df):
    return df.corr(method='spearman')  # 错误！

# ✓ 正确：复用公共函数
ic = calculate_rank_ic(df['factor_value'], df['future_return'])
```

---

### 数据传递规范（calculate_ic_with_direction_verification）

**核心原则：** calculate_ic_with_direction_verification 接收未合并的 factor_df 和 return_df，内部负责合并。

**函数设计意图：**

```
calculate_ic_with_direction_verification(factor_df, return_df, ...)
    ↓
内部执行：
    1. 验证列存在性
    2. 选择必要列 [date, asset, factor_col] 和 [date, asset, return_col]
    3. 执行 pd.merge(..., how='inner')
    4. dropna 处理
    5. 计算每日 IC
```

**禁止行为：**
```python
# ❌ 禁止：在调用前合并数据（死代码）
merged_df = pd.merge(factor_df, return_df, on=['date', 'asset'], how='inner')
result = calculate_ic_with_direction_verification(factor_df, return_df, ...)
# merged_df 未被使用，是死代码
```

**正确做法:**
```python
# ✓ 正确：直接传递未合并的数据
factor_df = factor_df[['date', 'asset', 'factor_col']].copy()
result = calculate_ic_with_direction_verification(factor_df, return_df, ...)
# 合并在函数内部完成
```

**为何禁止提前合并:**
1. 函数设计意图明确：接收未合并数据,内部负责合并
2. 提前合并的 merged_df 无法传递给函数（函数需要两个独立 DataFrame）

---

## 增量更新返回数据规范

### _incremental_update 返回数据结构
**核心原则:** _incremental_update 返回数据必须包含 `rolling_ic_mean` 字段, 与 `_full_recalculate` 返回值结构一致.

**必须包含的字段:**
```python
{
    'factor_name': str,
    'calculation_date': str,
    'period': {'start': str, 'end': str},
    'ic_metrics': {
        'ic_mean': float,
        'ic_std': float,
        'icir': float
    },
    'sample_stats': {
        'total_days': int,
        'valid_days': int,
        'avg_stocks_per_day': int,
        'avg_stocks_period': dict
    },
    'statistical_significance': {
        't_stat': float,
        'p_value': float,
        'is_significant': bool
    },
    'factor_direction': dict,
    'economic_significance': dict,
    'dates': list,
    'ic_values': list,
    'rolling_ic_mean': list,  # 必须！用于绘制滚动IC均值趋势图
    'positive_ratio': float,
    'n_assets': int,
    'summary': dict,
    'update_mode': str,
    'incremental_days': int
}
```

**为何必须包含 rolling_ic_mean:**
1. 增量更新合并历史数据和新增数据后,需要重新计算滚动IC均值
2. 前端依赖该字段绘制滚动IC均值趋势图
3. 缺失该字段会导致前端功能异常

4. 数据结构不一致会破坏保存数据的完整性

---

> **流程文档规范已迁移至 PROJECT.md "脚本配套文件规范"章节**

---

## NaN 处理规范

**核心原则：** NaN → None 转换应在数据生成阶段完成。

**隐式行为显式化原则：** 若代码依赖数据不含 NaN 的隐式假设，必须添加注释说明原因。

---

### ic_series 数据来源说明

**ic_series 不含 NaN 的原因（隐式行为）：**

ic_calculator.py 第 162-167 行：
```python
for date, daily_data in merged.groupby(date_col):
    ic_value = calculate_single_day_ic(daily_data, factor_col, return_col, min_stocks)
    if ic_value is not None:
        ic_list.append({'date': date, 'ic': ic_value})
```

**关键逻辑：**
- 只有 `ic_value is not None` 的日期才会被添加
- 不满足 `min_stocks` 的日期不会被添加（而非添加 NaN）
- 因此 ic_series.values 中的值都是有效的 numpy.float64

---

### ic_values vs rolling_ic_mean 处理差异

**ic_values 不需要 pd.isna(v) 检查：**
```python
# ✓ 正确：ic_series 不含 NaN（隐式行为已注释）
# ic_series.values 不含 NaN 的原因：
# - ic_calculator.py 只添加 ic_value is not None 的日期
# - 不满足 min_stocks 的日期不会被添加（而非添加 NaN）
ic_values = [round(v, 6) for v in ic_series.values]
```

**rolling_ic_mean 需要 pd.isna(v) 检查：**
```python
# ✓ 正确：rolling 含 NaN（需显式检查）
# rolling 参数语义：window=20, min_periods=10
# 前 min_periods-1=9 个时间点不满足最小样本要求，返回 NaN
rolling_ic_mean = [
    round(v, 6) if not pd.isna(v) else None
    for v in rolling_mean.values
]
```

---

### 正确实现
```python
# 使用 pd.isna(v) 检查 NaN
# NaN → None（语义转换："无有效数据"）
rolling_ic_mean = [
    round(v, 6) if not pd.isna(v) else None
    for v in rolling_mean.values
]
```

**为何必须在数据生成阶段处理：**
1. 语义一致性：None 表示"无有效数据"，nan 是浮点数运算结果
2. 增量路径用 None 填充无效日期，全量路径用 NaN 填充不满 min_periods 的日期
3. 若延迟到 convert_to_native_types 处理，语义不一致
4. JSON 序列化时 None → null，标准 JSON 不支持 nan

**两条路径一致性要求：**
```python
# ✓ 全量路径（calculate_daily_ic_series）：数据生成阶段处理
rolling_mean = ic_series.rolling(window=20, min_periods=10).mean()
rolling_ic_mean = [
    round(v, 6) if not pd.isna(v) else None
    for v in rolling_mean.values
]

# ✓ 增量路径（_incremental_update）：数据生成阶段处理（必须与全量路径一致）
rolling_ic_mean_series = ic_series.rolling(window=20, min_periods=10).mean()
rolling_ic_mean = [
    round(v, 6) if not pd.isna(v) else None
    for v in rolling_ic_mean_series.values
]

# ❌ 禁止：延迟到 convert_to_native_types 处理
rolling_ic_mean = ic_series.rolling(window=20, min_periods=10).mean()  # pd.Series
# 延迟到 json.dump 时才通过 convert_to_native_types 转换（违反规范）
```

---

## 滚动窗口参数规范（2026-05-20新增）

**核心原则：** 滚动窗口参数（window, min_periods）是业务决策，必须在注释中明确说明其影响。

### 参数语义

| 参数 | 语义 | 影响 |
|------|------|------|
| `window=N` | 滚动窗口大小 | 使用过去 N 个时间点的数据计算 |
| `min_periods=M` | 最小有效样本数 | 至少需要 M 个有效值才能计算结果 |

**关键公式：**
- 前 `min_periods-1` 个时间点返回 NaN（无法计算）
- 对于新上市股票，若历史数据 < `min_periods`，全部记录返回 NaN

### 业务决策必须注释说明

**示例：换手率突增因子（turnover_surge）**

```python
# ✓ 正确：业务决策显式说明
# 滚动窗口参数决策：window=5, min_periods=5
# 
# 业务决策说明：
# 1. min_periods=5 确保只有足够历史数据（≥5日）的股票才能计算因子
# 2. 前景：新上市股票前4日无法计算 turnover_ma，导致 turnover_surge 为 NaN
# 3. 设计意图：保证因子质量，避免因历史数据不足导致的均值不稳定
# 4. 数据丢失：每只股票前4个交易日 turnover_surge 为 NaN
# 5. 对少量历史数据股票的影响：若股票历史 < 5 日，全部记录的 turnover_surge 为 NaN
#
# 影响范围：
# - min_periods=5 → 每只股票丢失前4日数据
# - 若股票上市仅3天 → 该股票全部3条记录的 turnover_surge 均为 NaN
factor_df['turnover_ma'] = factor_df.groupby('asset')['turnover_rate'].transform(
    lambda x: x.rolling(window=5, min_periods=5).mean()
)
factor_df['turnover_surge'] = factor_df['turnover_rate'] / factor_df['turnover_ma']
```

### min_periods 选择原则

| min_periods 值 | 适用场景 | 数据丢失 |
|----------------|----------|----------|
| `min_periods=window`（等于窗口） | 高质量要求，拒绝不完整数据 | 前 `window-1` 日全部丢失 |
| `min_periods=1`（最小） | 宽松要求，接受任意数据 | 无丢失，但早期数据质量低 |
| `min_periods=window/2`（折中） | 平衡质量和覆盖度 | 前 `window/2-1` 日丢失 |

**推荐选择：**
- 日常因子计算：`min_periods=window`（保证数据质量）
- 紧急监控场景：`min_periods=window//2`（扩大覆盖度）
- 禁止 `min_periods=1`（早期数据质量极差，可能导致误导）

### filter_stats 统计口径规范（2026-05-20更新）

**核心原则：** filter_stats 必须区分三种数据丢失原因，字段命名语义清晰。

**字段命名规范（语义清晰原则）：**

| 字段 | 统计口径 | 说明 | 命名理由 |
|------|----------|------|----------|
| `total_records` | 过滤前总记录数 | 原始数据总量 | 明确"总"语义 |
| `rolling_nan_count` | rolling NaN 记录数 | 因 min_periods 不满足无法计算 | 明确"NaN来源" |
| `condition_filtered_count` | 条件过滤记录数 | 因筛选条件不满足被剔除 | 明确"被剔除"语义 |
| `valid_count` | 最终有效记录数 | 筛选后保留的记录 | ✓ 语义清晰："有效计数" |
| `retention_ratio` | 保留比例 | valid_count / total_records | ✓ 语义清晰："保留比例" |

**禁止使用模糊命名：**
| 模糊命名 | 问题 | 正确命名 |
|----------|------|----------|
| `filtered_count` | ❌ 语义混淆："过滤后计数"易误解为"被过滤掉的计数" | `valid_count` |
| `filter_ratio` | ❌ 语义混淆："过滤比例"易误解为"被过滤掉的比例" | `retention_ratio` |

**必须注释说明：**
```python
filter_stats = {
    'total_records': len(factor_df),           # 过滤前总记录数（原始数据）
    'rolling_nan_count': 0,                    # 因 rolling min_periods 不满足导致 NaN 的记录数
    'condition_filtered_count': 0,             # 因筛选条件不满足被剔除的记录数
    'valid_count': 0,                          # 最终有效因子记录数（语义清晰：valid）
    'retention_ratio': 0.0                     # 保留比例 = valid_count / total_records（语义清晰：retention）
}
```

**区分两种 NaN 来源：**

```python
# ✓ 正确：区分 rolling NaN 和条件过滤
# Step 1: 统计 rolling NaN（因 min_periods 不满足）
rolling_nan_mask = factor_df['turnover_surge'].isna()
# 注意：此时 turnover_surge 为 NaN 是因为 min_periods=5 不满足，尚未应用筛选条件

# Step 2: 应用筛选条件
both_conditions = turnover_surge_cond & price_up

# Step 3: 统计条件过滤（不满足条件的记录）
condition_filtered_mask = ~both_conditions & ~rolling_nan_mask  # 本可计算但条件不满足

# Step 4: 最终有效记录
valid_mask = both_conditions & ~rolling_nan_mask
```

### 常见错误模式

| 错误代码 | 问题 | 修复 |
|----------|------|------|
| `rolling(...).mean()` 无注释 | 业务决策未说明 | 添加 min_periods 选择理由注释 |
| `filter_stats` 无 rolling_nan_count | 无法区分 NaN 来源 | 添加 rolling_nan_count 字段 |
| `min_periods=1` 无质量评估 | 早期数据质量极差 | 评估数据质量或使用折中值 |
| `filtered_count` 字段名 | ❌ 语义混淆："过滤后计数"易误解 | 改为 `valid_count`（语义清晰） |
| `filter_ratio` 字段名 | ❌ 语义混淆："过滤比例"易误解 | 改为 `retention_ratio`（语义清晰） |

---

## 变量命名语义清晰原则规范（2026-05-20新增）

### 核心原则

**变量命名必须语义清晰，避免误解。在因子脚本中，变量名应明确指示数据来源（价格、换手率、成交量等），避免使用模糊命名。**

### 问题背景

```
变量命名语义混淆问题：

错误代码（换手率因子脚本中）：
factor_df['pct_change'] = factor_df.groupby('asset')['close'].transform(lambda x: x.pct_change())

问题：
- pct_change 在换手率因子脚本中容易误解为"换手率变化率"
- 实际含义是"收盘价涨跌幅"
- 读者需要查看代码才能理解语义

正确代码：
factor_df['price_pct_change'] = factor_df.groupby('asset')['close'].transform(lambda x: x.pct_change())
# ↑ 语义清晰：价格涨跌幅
```

### 因子脚本常见变量命名规范

| 场景 | 模糊命名（禁止） | 正确命名 | 语义说明 |
|------|-----------------|----------|----------|
| 收盘价涨跌幅 | `pct_change` | `price_pct_change` 或 `daily_return` | 价格涨跌幅（非换手率变化） |
| 换手率变化率 | `pct_change` | `turnover_pct_change` | 换手率变化率（非价格涨跌） |
| 成交量变化率 | `pct_change` | `volume_pct_change` | 成交量变化率（非价格涨跌） |
| 因子值 | `factor_value` | `<因子名>_factor` | 如 `turnover_surge_factor` |
| 均值 | `ma` | `<数据源>_ma_<窗口>` | 如 `turnover_ma_5`、`price_ma_20` |
| 标准差 | `std` | `<数据源>_std_<窗口>` | 如 `turnover_std_5` |

### 命名规则

| 规则 | 说明 |
|------|------|
| 数据源前缀原则 | 变量名应包含数据源前缀（price, turnover, volume, return） |
| 上下文明确原则 | 在换手率因子脚本中，`pct_change` 默认指换手率变化，需明确区分 |
| 避免通用词原则 | 避免 `pct_change`, `ma`, `std` 等通用词，应添加数据源前缀 |

### 常见错误模式

| 错误代码 | 问题 | 修复 |
|----------|------|------|
| `pct_change = close.pct_change()`（换手率脚本） | 语义混淆：读者误以为换手率变化 | `price_pct_change = close.pct_change()` |
| `ma = turnover.rolling(5).mean()` | 语义模糊：何种数据的均值 | `turnover_ma_5 = turnover.rolling(5).mean()` |
| `factor_value = ...` | 语义模糊：何种因子 | `turnover_surge_factor = ...` |

---

## 数据对齐验证规范（2026-05-21新增）

### 核心原则

**合并数据后必须验证日期对齐，避免静默丢失数据。因子数据和收益数据的日期范围必须一致，否则 IC 计算会静默丢失不匹配的日期。**

### 问题背景

```
数据对齐问题：

错误代码（无验证）：
factor_data = factor_df[['date', 'asset', 'turnover_surge']].dropna(subset=['turnover_surge']).copy()
return_data = return_df[['date', 'asset', 'forward_return']].copy()

# 统一 date 列类型
factor_data['date'] = factor_data['date'].astype(str)
return_data['date'] = return_data['date'].astype(str)

# 直接计算 IC（无验证）
result = calculate_ic_with_direction_verification(factor_data, return_data, ...)

问题：
- factor_data 日期范围：2024-01-01 ~ 2026-05-20（换手率 + 收盘价合并）
- return_data 日期范围：2024-01-01 ~ 2026-05-15（收益数据）
- IC 计算时，2026-05-16 ~ 2026-05-20 的因子数据会静默丢失
- 用户无法感知数据丢失

正确代码（有验证）：
factor_dates = factor_data['date'].unique()
return_dates = return_data['date'].unique()

if set(factor_dates) != set(return_dates):
    missing_in_return = set(factor_dates) - set(return_dates)
    missing_in_factor = set(return_dates) - set(factor_dates)
    
    print(f"警告：因子数据和收益数据日期不对齐")
    print(f"  因子数据缺失日期数: {len(missing_in_factor)}")
    print(f"  收益数据缺失日期数: {len(missing_in_return)}")
    
    # 选择交集日期（保证数据对齐）
    common_dates = set(factor_dates) & set(return_dates)
    factor_data = factor_data[factor_data['date'].isin(common_dates)]
    return_data = return_data[return_data['date'].isin(common_dates)]
    print(f"  对齐后日期数: {len(common_dates)}")
```

### 数据对齐验证规范

| 场景 | 必须验证 | 验证内容 |
|------|----------|----------|
| load_data_from_cache | ✓ 必须验证 | factor_df 与 return_df 日期范围一致性 |
| calculate_ic_with_direction_verification 前 | ✓ 必须验证 | factor_data 与 return_data 日期对齐 |
| merge 多个 DataFrame 后 | ✓ 必须验证 | 合并前后日期范围变化 |
| 增量更新时 | ✓ 必须验证 | 新增日期与已有日期连续性 |

### 验证实现模式

**模式1：load_data_from_cache 中验证**

```python
# ✓ 正确：在数据加载阶段验证日期对齐
def load_data_from_cache() -> Tuple[pd.DataFrame, pd.DataFrame, dict]:
    # 加载换手率数据
    turnover_df = pd.DataFrame(turnover_data['data'])
    # 加载收盘价数据
    close_df = pd.DataFrame(factor_data['data'])
    # 加载收益数据
    return_df = pd.DataFrame(return_data['data'])
    
    # 合并换手率和收盘价
    factor_df = pd.merge(turnover_df, close_df, on=['date', 'asset'], how='inner')
    
    # 验证日期对齐（遵循 MODULE.md 数据对齐验证规范）
    factor_dates = factor_df['date'].unique()
    return_dates = return_df['date'].unique()
    
    if set(factor_dates) != set(return_dates):
        missing_in_return = set(factor_dates) - set(return_dates)
        missing_in_factor = set(return_dates) - set(factor_dates)
        
        print(f"警告：因子数据和收益数据日期不对齐")
        print(f"  因子数据日期数: {len(factor_dates)}")
        print(f"  收益数据日期数: {len(return_dates)}")
        print(f"  因子数据缺失日期数: {len(missing_in_factor)}")
        print(f"  收益数据缺失日期数: {len(missing_in_return)}")
        
        # 选择交集日期（保证数据对齐）
        common_dates = set(factor_dates) & set(return_dates)
        factor_df = factor_df[factor_df['date'].isin(common_dates)]
        return_df = return_df[return_df['date'].isin(common_dates)]
        print(f"  对齐后日期数: {len(common_dates)}")
    
    return factor_df, return_df, raw_metadata
```

**模式2：calculate_ic_with_direction_verification 前验证**

```python
# ✓ 正确：在 IC 计算前验证日期对齐
def calculate_turnover_surge_ic(factor_df, return_df, ...):
    factor_data = factor_df[['date', 'asset', 'turnover_surge']].dropna().copy()
    return_data = return_df[['date', 'asset', 'forward_return']].copy()
    
    # 统一 date 列类型
    factor_data['date'] = factor_data['date'].astype(str)
    return_data['date'] = return_data['date'].astype(str)
    
    # 验证日期对齐（遵循 MODULE.md 数据对齐验证规范）
    factor_dates = set(factor_data['date'].unique())
    return_dates = set(return_data['date'].unique())
    
    if factor_dates != return_dates:
        common_dates = factor_dates & return_dates
        factor_data = factor_data[factor_data['date'].isin(common_dates)]
        return_data = return_data[return_data['date'].isin(common_dates)]
        print(f"日期对齐：保留 {len(common_dates)} 个共同日期")
    
    # 计算 IC
    result = calculate_ic_with_direction_verification(factor_data, return_data, ...)
```

### 常见错误模式

| 错误代码 | 问题 | 修复 |
|----------|------|------|
| merge 后无验证 | 静默丢失不匹配日期 | 添加日期对齐验证 |
| 直接计算 IC 无验证 | factor_data 和 return_data 日期范围不同 | 添加日期交集筛选 |
| 只检查数量不检查日期 | 数量相同但日期不同 | 检查 set(factor_dates) == set(return_dates) |
| 只打印警告不处理 | 用户无法感知数据丢失 | 选择交集日期 + 打印对齐信息 |

---

## 极端值裁剪规范（2026-05-21新增）

### 核心原则

**极端值裁剪范围必须与筛选条件一致。裁剪下界应等于或大于筛选条件下界，裁剪上界应等于或小于筛选条件上界（如有）。**

### 问题背景

```
极端值裁剪与筛选条件矛盾问题：

错误代码：
# 筛选条件：turnover_surge > 1
turnover_surge_cond = factor_df['turnover_surge'] > 1
price_up = factor_df['price_pct_change'] > 0
both_conditions = turnover_surge_cond & price_up

# 不满足条件的股票因子值设为 None
factor_df.loc[~both_conditions, 'turnover_surge'] = None

# 极端值裁剪：clip(0.5, 10)
factor_df.loc[mask, 'turnover_surge'] = factor_df.loc[mask, 'turnover_surge'].clip(0.5, 10)

问题：
- 筛选条件要求 turnover_surge > 1（不满足的设为 None）
- 裁剪下界 0.5 < 筛选下界 1.0
- 满足筛选条件的值已经 > 1，裁剪下界 0.5 永远不会生效
- 裁剪范围与筛选条件矛盾，浪费计算资源

正确代码：
# 筛选条件：turnover_surge > 1
turnover_surge_cond = factor_df['turnover_surge'] > 1
price_up = factor_df['price_pct_change'] > 0
both_conditions = turnover_surge_cond & price_up

# 不满足条件的股票因子值设为 None
factor_df.loc[~both_conditions, 'turnover_surge'] = None

# 极端值裁剪：clip(1.0, 10)（遵循 MODULE.md 极端值裁剪规范）
# 下界 1.0 等于筛选条件下界，裁剪范围与筛选条件一致
factor_df.loc[mask, 'turnover_surge'] = factor_df.loc[mask, 'turnover_surge'].clip(1.0, 10)
```

### 极端值裁剪一致性规范

| 场景 | 裁剪下界规则 | 裁剪上界规则 |
|------|--------------|--------------|
| 筛选条件 `factor > X` | 裁剪下界 ≥ X（推荐 = X） | 无上界约束 |
| 筛选条件 `factor < Y` | 无下界约束 | 裁剪上界 ≤ Y（推荐 = Y） |
| 筛选条件 `factor > X 且 factor < Y` | 裁剪下界 ≥ X（推荐 = X） | 裁剪上界 ≤ Y（推荐 = Y） |
| 无筛选条件 | 根据业务逻辑设定 | 根据业务逻辑设定 |

### 验证规则

**验证公式：**
```
裁剪下界 ≥ 筛选下界（如有）
裁剪上界 ≤ 筛选上界（如有）
```

**验证代码：**
```python
# ✓ 正确：验证裁剪范围与筛选条件一致性
clip_lower = 1.0
clip_upper = 10.0
filter_lower = 1.0  # 筛选条件：turnover_surge > 1

if clip_lower < filter_lower:
    raise ValueError(f"裁剪下界 {clip_lower} < 筛选下界 {filter_lower}，裁剪范围与筛选条件矛盾")

print(f"极端值裁剪范围: [{clip_lower}, {clip_upper}]，筛选条件: > {filter_lower}")
```

### 常见错误模式

| 错误代码 | 问题 | 修复 |
|----------|------|------|
| `clip(0.5, 10)`（筛选条件 `> 1`） | 裁剪下界 < 筛选下界，下界永远不生效 | `clip(1.0, 10)` |
| `clip(1, 20)`（筛选条件 `< 10`） | 裁剪上界 > 筛选上界，上界永远不生效 | `clip(1, 10)` |
| `clip(0, 5)`（筛选条件 `> 0`） | 裁剪下界 = 筛选下界边界，逻辑不清晰 | `clip(0.001, 5)`（明确 > 0 的边界） |
| 无验证裁剪范围 | 裁剪范围与筛选条件可能矛盾 | 添加一致性验证 |

---

## ic_series 排序规范

**核心原则：** ic_series.index 必须按日期升序排列。

**显式排序：**
```python
ic_series = ic_series.sort_index()
```

**防御性校验：**
```python
if dates != sorted(dates):
    raise RuntimeError("dates 未按升序排列")
```

**为何必须显式排序:**
1. rolling 计算按位置顺序，而非 index 值顺序
2. 若 ic_series.index 乱序 → dates 与 rolling_ic_mean 对应错误
3. pandas groupby 默认 sort=True，但不应依赖隐式行为
4. 版本升级风险: pandas 可能改变默认行为
5. 增量路径合并后可能乱序

6. **两条路径一致性:**
   - 全量路径: `load_data_from_cache` 第124行显式转换为字符串
   - 增量路径: JSON 缓存存储字符串，读取后直接使用
   - 当前一致，但依赖隐式实现，缺乏规范保障

---

## ic_series.index 类型规范

### 核心原则
**ic_series.index 必须是字符串类型（格式为 "YYYY-MM-DD"），禁止使用 datetime 对象。**

### 类型约束
```python
# ✓ 正确: index 为字符串 "YYYY-MM-DD"
ic_series.index  # 类型: pandas.Index with dtype='object' (字符串)
# 示例: Index(['2024-01-01', '2024-01-02', ...], dtype='object')

```

**禁止行为:**
```python
# ❌ 禁止: index 为 datetime 对象
ic_series.index  # 类型: pandas.DatetimeIndex
# 问题:
# 1. rolling 计算无法处理 datetime index（可能报错）
# 2. JSON 序列化失败（datetime 无法直接序列化）
# 3. 日期比较逻辑不一致（datetime vs 字符串）
```

### 全量路径实现
**`load_data_from_cache` 负责显式转换:**
```python
# 第124行: 显式转换为字符串格式
factor_df['date'] = date_series.dt.strftime('%Y-%m-%d')
```

**`calculate_daily_ic_series` 返回时:**
```python
# 第376行: 转换为 JSON 友好格式
dates = [str(d) for d in ic_series.index]
```

### 增量路径实现
**`_incremental_update` 直接使用字符串 index:**
```python
# 第660行: 直接使用 valid_dates (字符串)
ic_series = pd.Series(valid_ic, index=valid_dates)
```

### 一致性验证
**两条路径必须确保 index 类型一致（字符串 "YYYY-MM-DD"）：**

| 路径 | index 来源 | 类型 | 保障机制 |
|------|------------|------|----------|
| 全量 | `load_data_from_cache` 第124行转换 | 字符串 | 显式转换规范 |
| 增量 | `existing_dates` (JSON 缓存) + `new_dates` (strftime) | 字符串 | JSON 缓存格式规范 |

---

## 函数参数设计规范

### 核心原则
**函数签名不应有冗余参数，每个参数必须有实际用途。**

### 冗余参数判定规则
```python
# ❌ 禁止：参数永远不被传入，永远使用默认值
def calculate_daily_ic_series(
    factor_df,
    return_df,
    raw_metadata,
    min_stocks=10,
    period_start=None,  # 永远不传入
    period_end=None     # 永远不传入
):
    if period_start is None:  # 永远为 True
        period_start = str(factor_df['date'].min())

# ✓ 正确：删除冗余参数，直接使用已有数据
def calculate_daily_ic_series(
    factor_df,
    return_df,
    raw_metadata,
    min_stocks=10
):
    period_start = raw_metadata['period_start']  # 直接使用
```

### 设计原则
1. **参数必要性：** 每个参数必须被实际传入或有明确的默认值语义
2. **数据源优先：** 如果已有数据结构包含所需信息，应直接使用，不应添加额外参数
3. **语义一致性：** 参数语义应与数据源语义一致，不应混用不同来源的数据
4. **接口简洁：** 函数签名应尽可能简洁，避免不必要的复杂度

---

## period.start/end 语义规范

### 核心原则
**period.start/end 表示原始缓存范围（dropna 前），而非过滤后范围。**

### 语义定义

| 字段 | 来源 | 语义 | 示例 |
|------|------|------|------|
| `raw_metadata['period_start']` | 原始缓存 dropna 前 | 原始数据最小日期 | 2024-01-01 |
| `raw_metadata['period_end']` | 原始缓存 dropna 前 | 原始数据最大日期 | 2026-05-15 |
| `factor_df['date'].min()` | 过滤后数据 | 过滤后最小日期 | 2024-01-20 |
| `factor_df['date'].max()` | 过滤后数据 | 过滤后最大日期 | 2026-05-15 |

### 差异原因
```
原始缓存范围：2024-01-01 ~ 2026-05-15
dropna 后范围：2024-01-20 ~ 2026-05-15

差异：前19天布林带 NaN 被过滤
```

### 正确使用
```python
# ✓ 正确：使用 raw_metadata 表示原始缓存范围
period_start = raw_metadata['period_start']  # 2024-01-01
period_end = raw_metadata['period_end']      # 2026-05-15

# ❌ 禁止：使用 factor_df 表示原始缓存范围（语义错误）
period_start = str(factor_df['date'].min())  # 2024-01-20（错误！）
```

### 输出规范
**IC 计算结果的 period 字段应表示原始缓存范围：**
```json
{
  "period": {
    "start": "2024-01-01",  // 原始缓存最小日期
    "end": "2026-05-15"     // 原始缓存最大日期
  }
}
```

### total_days 使用规范
**核心原则：** total_days 直接使用 raw_metadata，不与过滤后数据做比较。

**禁止行为：**
```python
# ❌ 禁止：冗余的 max 比较
'total_days': max(raw_metadata.get('total_days', 0), factor_df_full['date'].nunique())

# 理由：
# 1. raw_metadata['total_days'] 表示原始缓存天数（dropna 前）
# 2. factor_df_full['date'].nunique() 表示过滤后天数（dropna 后）
# 3. 过滤后天数 ≤ 原始天数，max 永远返回原始天数
# 4. 冗余操作，增加代码复杂度
```

**正确实现：**
```python
# ✓ 正确：直接使用 raw_metadata
'total_days': raw_metadata.get('total_days', 0)  # 原始缓存天数
```

---

## 字典结构缩进规范

### 核心原则
**JSON 字典结构必须保持一致的缩进层级，缩进不一致会导致 IndentationError。**

### 缩进层级定义
```python
# ✓ 正确：多层级字典缩进
merged_data = {
    'factor_name': 'bollinger_pb_1d',      # 第1层：8空格
    'ic_metrics': {                        # 第1层：8空格
        'ic_mean': 0.05,                   # 第2层：12空格
        'ic_std': 0.15                     # 第2层：12空格
    },                                     # 第1层闭合：8空格
    'sample_stats': {                      # 第1层：8空格
        'total_days': 545                  # 第2层：12空格
    }                                      # 第1层闭合：8空格
}

# ❌ 禁止：缩进不一致（IndentationError）
merged_data = {
    'factor_name': 'bollinger_pb_1d',
    'ic_metrics': {
        'ic_mean': 0.05,
        'ic_std': 0.15
    },
'sample_stats': {  # ❌ 缺少缩进
    'total_days': 545
}
```

### 缩进规则
1. **第1层字段：** 8空格缩进（函数体内字典）
2. **第2层字段：** 12空格缩进（嵌套字典内）
3. **第3层字段：** 16空格缩进（三层嵌套）
4. **闭合括号：** 与同级字段对齐（同级缩进）

### 常见错误
```python
# ❌ 错误：字典字段缩进缺失
'sample_stats': {  # 应有8空格缩进

# ❌ 错误：嵌套字段缩进不一致
'icir': round(result['icir'], 4)  # 应有12空格缩进

# ✓ 正确：所有字段缩进一致
        'icir': round(result['icir'], 4)  # 12空格缩进
```

---

## 函数返回值契约规范

**核心原则:** 调用方必须校验返回值字段存在性。

---

## ic_metrics 字段规范

### 核心原则
**ic_metrics 字段结构在两条路径（全量/增量）中必须完全一致。**

### 字段定义

| 字段 | 类型 | 来源 | 用途 |
|------|------|------|------|
| `ic_mean` | float | `result['ic_mean']` | IC 均值（核心指标） |
| `ic_std` | float | `result['ic_std']` | IC 标准差 |
| `icir` | float | `result['icir']` | ICIR（信息系数比率） |
| `p_value` | float | `result['p_value']` | p 值（统计显著性） |
| `p_value_display` | str | `result['p_value_display']` | p 值显示格式（科学计数法或小数） |

### 正确实现（两条路径一致）
```python
# ✓ 全量路径（calculate_daily_ic_series）
'ic_metrics': {
    'ic_mean': round(result['ic_mean'], 6),
    'ic_std': round(result['ic_std'], 6),
    'icir': round(result['icir'], 4),
    'p_value': round(result['p_value'], 6),
    'p_value_display': result.get('p_value_display', str(round(result['p_value'], 6)))
}

# ✓ 增量路径（_incremental_update）：必须与全量路径完全一致
'ic_metrics': {
    'ic_mean': round(result['ic_mean'], 6),
    'ic_std': round(result['ic_std'], 6),
    'icir': round(result['icir'], 4),
    'p_value': round(result['p_value'], 6),
    'p_value_display': result.get('p_value_display', str(round(result['p_value'], 6)))
}

# ❌ 禁止：增量路径缺少字段
'ic_metrics': {
    'ic_mean': round(result['ic_mean'], 6),
    'ic_std': round(result['ic_std'], 6),
    'icir': round(result['icir'], 4)  # 缺少 p_value 和 p_value_display
}
```

### 下游依赖
**下游代码可能读取以下字段：**
```python
# 前端或分析代码
ic_mean = ic_data['ic_metrics']['ic_mean']
p_value = ic_data['ic_metrics']['p_value']  # 必须存在
p_value_display = ic_data['ic_metrics']['p_value_display']  # 必须存在
```

---

## factor_direction 字段规范

### 核心原则
**factor_direction 字段结构在两条路径（全量/增量）中必须完全一致。**

### 字段映射（原始字段名 → 输出字段名）

| 原始字段名（ic_calculator.py） | 输出字段名 | 类型 | 用途 |
|------------------------------|----------|------|------|
| `ic_mean_sign` | `direction` | str | 因子方向（'positive'/'negative'/'zero') |
| `ic_mean` | `ic_mean` | float | IC 均值 |
| `conclusion` | `conclusion` | str | 方向判断结论 |

### 正确实现（两条路径一致）
```python
# ✓ 全量路径（calculate_daily_ic_series）：重映射字段名
'factor_direction': {
    'direction': result['factor_direction']['ic_mean_sign'],
    'ic_mean': result['factor_direction']['ic_mean'],
    'conclusion': result['factor_direction']['conclusion']
}

# ✓ 增量路径（_incremental_update）：重映射字段名（必须与全量路径一致）
'factor_direction': {
    'direction': result['factor_direction']['ic_mean_sign'],
    'ic_mean': result['factor_direction']['ic_mean'],
    'conclusion': result['factor_direction']['conclusion']
}

# ❌ 禁止：直接透传原始字段名
'factor_direction': result['factor_direction']  # 字段名是 ic_mean_sign，不是 direction
```

---

## economic_significance 字段规范

### 核心原则
**economic_significance 字段结构在两条路径（全量/增量）中必须完全一致。**

### 字段映射（原始字段名 → 输出字段名）

| 原始字段名（ic_calculator.py） | 输出字段名 | 类型 | 用途 |
|------------------------------|----------|------|------|
| `level` | `ic_strength` | str | IC 强度（'strong'/'weak'/'none') |
| `abs_ic_mean` | `ic_mean_abs` | float | IC 均值绝对值 |
| `conclusion` | `conclusion` | str | 经济显著性判断结论 |

### 正确实现（两条路径一致）
```python
# ✓ 全量路径（calculate_daily_ic_series）：重映射字段名
'economic_significance': {
    'ic_strength': result['economic_significance']['level'],
    'ic_mean_abs': result['economic_significance']['abs_ic_mean'],
    'conclusion': result['economic_significance']['conclusion']
}

# ✓ 增量路径（_incremental_update）：重映射字段名（必须与全量路径一致）
'economic_significance': {
    'ic_strength': result['economic_significance']['level'],
    'ic_mean_abs': result['economic_significance']['abs_ic_mean'],
    'conclusion': result['economic_significance']['conclusion']
}

# ❌ 禁止：直接透传原始字段名
'economic_significance': result['economic_significance']  # 字段名是 level，不是 ic_strength
```

---

## statistical_significance 字段规范

### 核心原则
**statistical_significance 字段结构在两条路径中可直接透传（字段名一致）。**

### 字段定义（无需重映射）

| 字段名 | 类型 | 来源 | 用途 |
|--------|------|------|------|
| `is_significant` | bool | `result['statistical_significance']['is_significant']` | 统计显著性标志 |
| `p_value` | float | `result['statistical_significance']['p_value']` | p 值 |
| `p_value_display` | str | `result['statistical_significance']['p_value_display']` | p 值显示格式 |
| `t_stat` | float | `result['statistical_significance']['t_stat']` | t 统计量 |
| `conclusion` | str | `result['statistical_significance']['conclusion']` | 统计显著性判断结论 |

### 正确实现（两条路径一致）
```python
# ✓ 全量路径和增量路径：均可直接透传（字段名一致）
'statistical_significance': result['statistical_significance']
```

---

**校验示例:**
# 定义必需字段列表
required_fields = [
    'ic_series', 'ic_mean', 'ic_std', 'icir',
    'statistical_significance', 'factor_direction',
    'economic_significance', 'icir_stability',
    'ic_distribution_consistency', 'positive_ratio', 'summary'
]

# 检查缺失字段
missing_fields = [f for f in required_fields if f not in result]

# 若缺失字段 → 抛出 RuntimeError
if missing_fields:
    raise RuntimeError(
        f"calculate_ic_with_direction_verification 返回值缺少必需字段\n"
        f"缺失字段: {missing_fields}\n"
        f"问题定位: factor_ic/common/ic_calculator.py\n"
        f"期望字段: {required_fields}"
    )
```

**为何必须校验返回值字段：**
1. 直接下标访问 result['field'] 会抛出 KeyError
2. KeyError 错误信息无法判断问题模块
3. 函数返回值结构变更时，调用方静默失败
4. 校验后的 RuntimeError 包含：缺失字段列表、问题定位、期望字段列表

---

## 增量计算 None 处理规范

**核心原则：** 增量计算中 None（股票数不足）的处理必须与全量计算保持一致。

**None 语义定义：**

| None 来源 | 语义 | 是否存储 |
|----------|------|---------|
| `calculate_single_day_ic` 返回 None | 股票数 < min_stocks | **不存储**（过滤） |
| 全量计算中 ic_series.index | 只有有效 IC 日期 | 不含 None |
| 增量计算中 new_ic_values | 可能含 None | **过滤后存储** |

**正确实现：**
```python
# 合并数据时过滤 None
date_ic_map = {}
for date, ic in zip(existing_dates, existing_ic_values):
    if ic is not None:  # 兼容旧缓存：过滤可能存在的 None
        date_ic_map[date] = ic

for date, ic in zip(new_dates, new_ic_values):
    if ic is not None:  # 只写入有效 IC 值
        date_ic_map[date] = ic
```

---

## 全量/增量 IC 计算等价性规范

**核心原则：** 全量计算与增量计算必须使用同一核心函数（calculate_single_day_ic）。

**等价性验证三重保障机制：**

| 保障层 | 机制 | 说明 |
|-------|------|------|
| 第一层：代码架构 | 设计原则 | 全量/增量调用同一函数，无法独立演化 |
| 第二层：单元测试 | TestAlgorithmEquivalence | 验证单日期、多日期、边界情况等价性 |
| 第三层：文档规范 | Step 4.5 规范 | 修改核心函数时必须检查等价性 |

**禁止行为：**
```python
# ❌ 禁止：增量计算不使用 calculate_single_day_ic
for date in missing_dates:
    ic_value = scipy.stats.spearmanr(factor_values, return_values)[0]  # 错误！

# ✓ 正确：增量计算使用 calculate_single_day_ic
for date in missing_dates:
    ic_value = calculate_single_day_ic(
        daily_data,
        factor_col='rsi_6',
        return_col='forward_return',
        min_stocks=10
    )
```

---

## 旧缓存兼容性处理规范

**核心原则：** 增量计算读取现有缓存时，必须兼容旧版本缓存数据。

**问题背景：**
- v1.32 之前版本：ic_values 可能包含 None（未过滤股票数不足）
- 增量更新读取现有缓存 → existing_ic_values 可能包含 None

**兼容性处理：**
```python
# 合并数据时，existing 和 new 都过滤 None（语义一致）
for date, ic in zip(existing_dates, existing_ic_values):
    if ic is not None:  # 兼容旧缓存：过滤可能存在的 None
        date_ic_map[date] = ic
```

---

## 返回值标记规范

**核心原则：** 三种模式返回值必须标记 update_mode 字段。

**返回值标记设计：**

| 场景 | update_mode | 附加字段 | 调用方判断逻辑 |
|------|------------|---------|---------------|
| 正常 skip | `'skip'` | 无 | `update_mode == 'skip'` → 从缓存读取 |
| skip-fallback | `'full'` | `fallback_event` | `update_mode == 'full' && 'fallback_event' in result` → 意外触发全量 |
| 正常 incremental | `'incremental'` | `incremental_events` | `update_mode == 'incremental'` → 增量更新 |
| 正常 full | `'full'` | 无 | `update_mode == 'full' && 'fallback_event' not in result` → 正常全量 |

**为何必须标记返回值：**
1. mode='skip' 时读取缓存失败会 fallback 到全量计算
2. fallback 后返回值与正常全量计算返回值结构相同
3. 调用方无法区分来源
4. 若全量计算耗时很长，调用方毫不知情

---

## 错误信息格式规范

**核心原则：** 枚举类错误必须包含合法值列表。

**正确示例：**
```python
raise RuntimeError(
    f"未知模式: {mode}\n"
    f"合法值: ['skip', 'incremental', 'full']"
)
```

**错误信息对比：**

| 场景 | 未校验（KeyError） | 已校验（RuntimeError） |
|-----|-------------------|----------------------|
| 错误信息 | `KeyError: 'ic_mean'` | `缺少必需字段: ['ic_mean']\n问题定位: factor_ic/common/ic_calculator.py` |
| 问题定位 | 无法判断 | 明确模块路径 |
| 排查效率 | 低 | 高 |

---

## 字典构建规范

**核心原则：** 字段应集中定义在构建阶段，避免分散赋值。

**禁止行为：**
```python
# ❌ 禁止：分散赋值
result = {}
result['ic_mean'] = ic_mean
result['ic_std'] = ic_std
# ... 后面又赋值
result['update_mode'] = 'full'  # 分散，容易重复
```

**正确做法：**
```python
# ✓ 正确：集中定义
result = {
    'ic_mean': ic_mean,
    'ic_std': ic_std,
    'icir': icir,
    'update_mode': 'full',  # 集中定义
}
```

---

## 输出字段口径规范

**核心原则：** 统计字段必须明确口径范围。

**正确实现：**
```json
{
  "avg_stocks_per_day": 4235.2,
  "avg_stocks_period": {
    "start": "2024-01-01",
    "end": "2024-12-31",
    "description": "平均每日有效股票数统计范围"
  }
}
```

**为何必须明确口径：**
- avg_stocks_per_day 基于 dropna 后数据
- total_days 基于 dropna 前数据
- 口径不同导致数值差异，必须通过字段说明

---

## 代码维护同步检查规范

**核心原则：** 添加新代码后必须检查旧代码是否冗余。

**检查清单：**
```
□ 新增字段 → 检查是否有重复赋值
□ 新增函数 → 检查是否有类似功能函数可合并
□ 新增逻辑 → 检查是否有冗余分支
□ 新增参数 → 检查是否有硬编码值可替换
```

---

## 设计演进清理规范

**核心原则：** 新实现替代旧实现后，必须删除旧代码，禁止保留死代码。

---

## 技术指标参数规范

### 布林带 rolling 窗口参数

**核心原则：** min_periods 必须等于 window，遵循技术指标标准定义。

**布林带标准定义：**
```
布林带需要满 N 个周期的数据才能计算：
- Middle Band = SMA(Close, N)，需要 N 个数据点
- Upper/Lower Band = Middle + K × StdDev，标准差也需要 N 个数据点
- 前 N-1 个周期的布林带值应为 NaN（等待足够数据）
```

**正确实现：**
```python
# ✓ 正确：min_periods=n，遵循标准定义
factor_df['middle_band'] = factor_df.groupby('asset')['close'].transform(
    lambda x: x.rolling(window=n, min_periods=n).mean()
)
factor_df['std_dev'] = factor_df.groupby('asset')['close'].transform(
    lambda x: x.rolling(window=n, min_periods=n).std()
)
```

**禁止行为：**
```python
# ❌ 禁止：min_periods=1，违反标准定义
factor_df['middle_band'] = factor_df.groupby('asset')['close'].transform(
    lambda x: x.rolling(window=n, min_periods=1).mean()  # 错误！
)
factor_df['std_dev'] = factor_df.groupby('asset')['close'].transform(
    lambda x: x.rolling(window=n, min_periods=1).std()  # 错误！
)

# 问题：
# - 第1个数据点：std=NaN（单点无法计算样本标准差）
# - 第2-4个数据点：std有值（基于不足N个数据点）
# - 违反布林带"满N周期才计算"的标准定义
```

**为何 min_periods=n 是标准：**
1. 布林带业界定义：需要满 N 个周期才产生有效值
2. 技术分析软件（TradingView、MetaTrader）均采用此定义
3. min_periods=1 会在前 N-1 周期产生非标准值，误导分析
4. 前N-1周期的NaN表示"数据不足，暂不计算"，语义清晰

### 布林带标准差 ddof 参数

**核心原则：** 布林带标准差必须使用总体标准差（ddof=0），而非样本标准差（ddof=1）。

**布林带标准定义：**
```
布林带是对固定窗口内所有价格数据的标准差计算：
- Upper Band = Middle + K × StdDev(Close, N)
- StdDev = Population Standard Deviation（总体标准差）
- 公式：σ = sqrt(Σ(xi - μ)^2 / N)
- 不是对未知总体的样本估计，而是对固定窗口数据的完整统计
```

**正确实现：**
```python
# ✓ 正确：ddof=0，使用总体标准差
factor_df['std_dev'] = factor_df.groupby('asset')['close'].transform(
    lambda x: x.rolling(window=n, min_periods=n).std(ddof=0)
)
```

**禁止行为：**
```python
# ❌ 禁止：默认 ddof=1（样本标准差），系统性高估布林带宽度
factor_df['std_dev'] = factor_df.groupby('asset')['close'].transform(
    lambda x: x.rolling(window=n, min_periods=n).std()  # 默认 ddof=1，错误！
)

# 问题：
# - 样本标准差公式：σ_sample = sqrt(Σ(xi-μ)^2 / (N-1))
# - 总体标准差公式：σ_population = sqrt(Σ(xi-μ)^2 / N)
# - 偏差系数：σ_sample = σ_population × sqrt(N/(N-1))
# - 对于 N=20：偏差约 2.5%（sqrt(20/19) ≈ 1.025）
# - 结果：布林带宽度系统性高估，%B 值系统性偏小
```

**为何 ddof=0 是标准：**
1. 布林带定义：对固定窗口内所有价格数据的完整统计，非样本估计
2. TradingView、MetaTrader 等业界软件均使用总体标准差
3. Bollinger 本人定义：Population Standard Deviation
4. ddof=1 会系统性高估带宽，导致 %B 指标失真

---

## 浮点数等值比较规范

### 核心原则

**浮点数等值比较必须使用精度容差，禁止直接使用 == 比较。**

### 问题背景

```
浮点数运算精度问题：
- IEEE 754 浮点数无法精确表示某些数值
- 运算结果可能产生微小误差（如 1e-15）
- 直接 == 0 比较会漏判极小值
- 极小值作为除数会产生极端结果（如 1e15）
```

### 正确实现

```python
# ✓ 正确：使用精度容差判断
import numpy as np

EPSILON = 1e-10  # 浮点数精度容差

# 除零判断
diff = upper_band - lower_band
result = np.where(
    np.abs(diff) < EPSILON,  # 精度容差判断
    0.5,  # 默认值
    (close - lower_band) / diff
)
```

### 禁止行为

```python
# ❌ 禁止：直接 == 0 比较（浮点精度问题）
diff = upper_band - lower_band
result = np.where(
    diff == 0,  # 可能漏判 1e-15 等极小值
    0.5,
    (close - lower_band) / diff  # 可能产生极端值
)

# 问题示例：
# diff = 1e-15（浮点误差）
# diff == 0 → False（漏判）
# %B = 1.0 / 1e-15 = 1e15（极端值）
```

### 精度容差选择原则

```
| 场景 | 推荐容差 | 说明 |
|------|---------|------|
| 价格数据除零判断 | 1e-10 | 价格精度通常到小数点后2-4位 |
| 数值计算通用 | 1e-9 | 适合大多数浮点运算场景 |
| 高精度计算 | 1e-12 | 需要更高精度的特殊场景 |
```

### 适用场景

1. **布林带 %B 计算**：`diff = upper_band - lower_band` 除零判断
2. **RSI 计算**：`diff = max_gain - max_loss` 除零判断
3. **任何浮点数除法**：除数为运算结果时需精度容差判断

### 为何必须使用精度容差

1. IEEE 754 标准无法精确表示所有数值
2. 浮点运算累积误差可能导致极小值
3. 直接 == 比较会漏判，产生极端结果
4. 精度容差是业界标准做法（numpy、scipy 均采用）

---

## 增量路径 rolling_ic_mean 规范

### 核心原则

**增量路径 `rolling_ic_mean` 必须基于 `all_dates` 计算，与 `dates` 和 `ic_values` 长度完全一致。**

### 问题背景

```
增量路径数据合并流程：
1. existing_dates + existing_ic_values（来自缓存）
2. new_dates + new_ic_values（新计算）
3. 合并 → date_ic_map（过滤None）
4. all_dates = sorted(date_ic_map.keys())
5. all_ic_values = [date_ic_map[d] for d in all_dates]

关键问题：
- 若 rolling_ic_mean 基于 valid_dates（子集）计算
- len(rolling_ic_mean) = len(valid_dates) ≠ len(all_dates)
- 前端按索引对应 dates[i] → rolling_ic_mean[i] 会错位
```

### 正确实现

```python
# ✓ 正确：rolling_ic_mean 基于 all_dates 计算
from factor_ic.common.ic_calculator import calculate_ic_statistics

# 使用 all_dates 和 all_ic_values 构建 ic_series
ic_series = pd.Series(all_ic_values, index=all_dates)
result = calculate_ic_statistics(ic_series)

# rolling_ic_mean 基于 all_dates（与全量路径一致）
rolling_ic_mean_series = ic_series.rolling(window=20, min_periods=10).mean()
rolling_ic_mean = [
    round(v, 6) if not pd.isna(v) else None
    for v in rolling_ic_mean_series.values
]

# 输出：dates, ic_values, rolling_ic_mean 长度一致
merged_data = {
    'dates': all_dates,           # len = N
    'ic_values': all_ic_values,   # len = N
    'rolling_ic_mean': rolling_ic_mean,  # len = N ✓
}
```

### 禁止行为

```python
# ❌ 禁止：rolling_ic_mean 基于 valid_dates（子集）计算
valid_indices = [i for i, ic in enumerate(all_ic_values) if ic is not None]
valid_dates = [all_dates[i] for i in valid_indices]
valid_ic = [all_ic_values[i] for i in valid_indices]

ic_series = pd.Series(valid_ic, index=valid_dates)  # 基于 valid_dates
rolling_ic_mean_series = ic_series.rolling(window=20, min_periods=10).mean()
rolling_ic_mean = [round(v, 6) if not pd.isna(v) else None for v in rolling_ic_mean_series.values]

# 输出：dates, ic_values, rolling_ic_mean 长度不一致
merged_data = {
    'dates': all_dates,           # len = N
    'ic_values': all_ic_values,   # len = N
    'rolling_ic_mean': rolling_ic_mean,  # len = M (M < N) ✗ 错误！
}

# 问题：
# - all_dates 和 all_ic_values 长度 = N
# - rolling_ic_mean 长度 = M（M < N）
# - 前端 dates[i] → rolling_ic_mean[i] 索引错位
# - 第 M 个日期之后的数据无 rolling_ic_mean 对应
```

### 为何必须长度一致

1. 前端图表按索引对应：`dates[i] → ic_values[i] → rolling_ic_mean[i]`
2. 长度不一致会导致索引错位，图表显示错误
3. 全量路径已经保证长度一致，增量路径必须遵循相同原则
4. JSON 数据结构一致性要求：三条数组长度相等

### 全量/增量路径一致性验证

| 路径 | dates来源 | ic_values来源 | rolling_ic_mean来源 | 长度一致性 |
|------|----------|--------------|-------------------|-----------|
| 全量 | ic_series.index | ic_series.values | ic_series.rolling() | ✓ N=N=N |
| 增量 | all_dates | all_ic_values | ic_series.rolling()（基于all_dates） | ✓ N=N=N |

**关键：** 增量路径的 `ic_series` 必须使用 `all_dates` 和 `all_ic_values` 构建，而非 `valid_dates` 子集。

---

## 增量路径 period 字段规范

### 核心原则

**增量路径 `period.start/end` 必须直接使用 `raw_metadata`，与全量路径语义完全一致。**

### 语义定义

**period 字段表示原始缓存范围（dropna前），而非合并后有效IC日期范围。**

```
| 数据源 | 语义 | 示例 |
|--------|------|------|
| raw_metadata['period_start'] | 原始缓存最小日期（dropna前） | 2024-01-01 |
| raw_metadata['period_end'] | 原始缓存最大日期（dropna前） | 2026-05-15 |
| all_dates[0] | 合并后有效IC最小日期 | 2024-01-20 |
| all_dates[-1] | 合并后有效IC最大日期 | 2026-05-15 |

差异原因：
- 原始缓存范围：2024-01-01 ~ 2026-05-15（545天）
- 有效IC范围：2024-01-20 ~ 2026-05-15（526天）
- 前19天布林带值NaN（等待足够数据）
```

### 正确实现

```python
# ✓ 正确：period 直接使用 raw_metadata（与全量路径一致）
merged_data = {
    'period': {
        'start': raw_metadata['period_start'],  # 原始缓存范围
        'end': raw_metadata['period_end']       # 原始缓存范围
    },
    'sample_stats': {
        'total_days': raw_metadata.get('total_days', 0),  # 原始缓存天数
        'valid_days': len(all_dates),  # 有效IC天数
    }
}
```

### 禁止行为

```python
# ❌ 禁止：混合不同语义的范围
merged_data = {
    'period': {
        'start': min(all_dates[0], raw_metadata['period_start']),  # 混合语义
        'end': max(all_dates[-1], raw_metadata['period_end'])      # 混合语义
    }
}

# 问题：
# - all_dates[0] 和 raw_metadata['period_start'] 语义不同
# - min/max 混合两个不同范围，语义模糊
# - 无法解释 period 表示什么范围
# - 与全量路径不一致（全量路径直接使用 raw_metadata）
```

### 为何必须使用 raw_metadata

1. **语义一致性：** period 表示原始缓存范围，而非有效IC范围
2. **两条路径一致：** 全量路径使用 raw_metadata，增量路径必须一致
3. **数据源稳定性：** raw_metadata 表示数据源范围，不受计算过程影响
4. **下游依赖明确：** 前端显示 period 时期望原始数据范围，而非计算后范围

### 全量/增量路径一致性验证

| 路径 | period.start来源 | period.end来源 | 语义 |
|------|-----------------|----------------|------|
| 全量 | raw_metadata['period_start'] | raw_metadata['period_end'] | 原始缓存范围 ✓ |
| 增量 | raw_metadata['period_start'] | raw_metadata['period_end'] | 原始缓存范围 ✓ |

**关键：** 增量模式追加数据不改变原始缓存范围，`period` 应始终表示数据源范围。

---

## 增量路径返回结构一致性规范

### 核心原则

**增量路径返回结构必须与全量路径完全一致，禁止遗漏字段。**

### 问题背景

```
两条路径返回结构对比：

全量路径返回字段：
- factor_name ✓
- calculation_date ✓
- period ✓
- ic_metrics ✓
- sample_stats ✓
- statistical_significance ✓
- factor_direction ✓
- economic_significance ✓
- dates ✓
- ic_values ✓
- rolling_ic_mean ✓
- positive_ratio ✓
- n_assets ✓
- summary ✓
- factor_stats ✓  ← 全量路径包含
- update_mode ✓

增量路径返回字段：
- ...（与全量相同）
- factor_stats ✗  ← 增量路径可能缺失！
- update_mode ✓
- incremental_days ✓
```

### 正确实现

```python
# ✓ 正确：增量路径包含所有字段（与全量路径一致）
merged_data = {
    'factor_name': 'xxx',
    'calculation_date': 'xxx',
    'period': {...},
    'ic_metrics': {...},
    'sample_stats': {...},
    'statistical_significance': {...},
    'factor_direction': {...},
    'economic_significance': {...},
    'dates': all_dates,
    'ic_values': all_ic_values,
    'rolling_ic_mean': rolling_ic_mean,
    'positive_ratio': xxx,
    'n_assets': xxx,
    'summary': {...},
    'factor_stats': factor_stats,  # ✓ 必须包含（与全量路径一致）
    'update_mode': 'incremental',
    'incremental_days': xxx
}
```

### 禁止行为

```python
# ❌ 禁止：增量路径缺少 factor_stats
merged_data = {
    'factor_name': 'xxx',
    # ... 其他字段 ...
    'summary': {...},
    'update_mode': 'incremental',  # 缺少 factor_stats！
    'incremental_days': xxx
}

# 问题：
# - 全量路径包含 factor_stats（因子计算统计信息）
# - 增量路径缺失 factor_stats
# - 两种模式返回结构不一致
# - 下游代码读取 factor_stats 时在增量模式下会 KeyError
```

### 为何必须结构一致

1. **下游依赖：** 前端或其他分析代码可能读取 `factor_stats` 字段
2. **接口一致性：** 同一函数的两种模式应返回相同结构
3. **类型安全：** 避免 KeyError 或字段缺失导致的运行时错误
4. **维护成本：** 结构一致降低代码复杂度和排查难度

### 全量/增量路径字段一致性验证

| 字段 | 全量路径 | 增量路径 | 是否必须 |
|------|---------|---------|---------|
| factor_name | ✓ | ✓ | ✓ |
| calculation_date | ✓ | ✓ | ✓ |
| period | ✓ | ✓ | ✓ |
| ic_metrics | ✓ | ✓ | ✓ |
| sample_stats | ✓ | ✓ | ✓ |
| statistical_significance | ✓ | ✓ | ✓ |
| factor_direction | ✓ | ✓ | ✓ |
| economic_significance | ✓ | ✓ | ✓ |
| dates | ✓ | ✓ | ✓ |
| ic_values | ✓ | ✓ | ✓ |
| rolling_ic_mean | ✓ | ✓ | ✓ |
| positive_ratio | ✓ | ✓ | ✓ |
| n_assets | ✓ | ✓ | ✓ |
| summary | ✓ | ✓ | ✓ |
| factor_stats | ✓ | ✓ | ✓ 必须包含！ |
| update_mode | ✓ | ✓ | ✓ |
| incremental_days | ✗ | ✓ | 增量路径特有 |

**关键：** 增量路径必须在构建 `merged_data` 时添加 `factor_stats` 字段，与全量路径保持结构一致。

---

## 函数返回值契约校验规范

### 核心原则

**`required_fields` 校验列表必须包含所有后续直接访问的字段，禁止遗漏。**

### 问题背景

```
校验列表 vs 实际访问字段：

校验列表（required_fields）：
- ic_series ✓
- ic_mean ✓
- ic_std ✓
- icir ✓
- p_value ✗  ← 校验列表缺少！
- p_value_display ✗  ← 校验列表缺少！
- statistical_significance ✓
- factor_direction ✓
- economic_significance ✓
- positive_ratio ✓
- summary ✓

后续代码直接访问：
- result['p_value']  ← 未校验，若缺失会 KeyError
- result['p_value_display']  ← 使用 .get()，有默认值，但仍依赖 p_value
```

### 正确实现

```python
# ✓ 正确：校验列表包含所有直接访问的字段
required_fields = [
    'ic_series', 'ic_mean', 'ic_std', 'icir',
    'p_value', 'p_value_display',  # ✓ 必须包含！
    'statistical_significance', 'factor_direction',
    'economic_significance', 'positive_ratio', 'summary'
]

missing_fields = [f for f in required_fields if f not in result]
if missing_fields:
    raise RuntimeError(
        f"calculate_ic_with_direction_verification 返回值缺少必需字段\n"
        f"缺失字段: {missing_fields}\n"
        f"问题定位: factor_ic/common/ic_calculator.py\n"
        f"期望字段: {required_fields}"
    )

# 校验后可以安全访问
'p_value': round(result['p_value'], 6)  # ✓ 已校验，不会 KeyError
```

### 禁止行为

```python
# ❌ 禁止：校验列表缺少 p_value
required_fields = [
    'ic_series', 'ic_mean', 'ic_std', 'icir',
    'statistical_significance', 'factor_direction',
    'economic_significance', 'positive_ratio', 'summary'
]

# 后续直接访问 p_value
'p_value': round(result['p_value'], 6)  # ✗ 未校验，可能 KeyError！

# 问题：
# - 若 calculate_ic_with_direction_verification 返回值缺少 p_value
# - 第406行会抛出 KeyError: 'p_value'
# - 错误信息不友好，无法定位问题模块
# - 与校验机制设计初衷矛盾
```

### 为何必须校验所有字段

1. **错误信息友好：** RuntimeError 包含缺失字段列表、问题定位、期望字段列表
2. **问题定位快速：** 明确指出哪个模块返回值不符合契约
3. **维护成本低：** 契约校验是统一入口，一处修改全局生效
4. **代码健壮性：** 避免 KeyError 在运行时突然出现

### 校验列表完整性检查清单

```
□ 检查所有 result['field'] 直接访问的字段
□ 检查所有 result.get('field') 有默认值但仍依赖的字段
□ 检查嵌套字段父级（如 statistical_significance）
□ 确保校验列表与实际访问一致
□ 新增字段访问时同步更新校验列表
```

---

## 增量路径因子值有效性检查规范

### 核心原则

**增量路径必须检查缺失日期的因子值是否有效，避免静默产生大量 None IC值。**

### 问题背景

```
布林带预热期问题：

布林带计算需要前N-1日数据预热：
- N=20，需要前19日数据
- rolling(window=n, min_periods=n) 确保 前19天为 NaN
- 缺失日期如果是缓存范围的前19天
- bollinger_pb_1d 全为 NaN（即使 factor_df_new 不为空）

示例场景：
- 缓存范围：2024-01-01 ~ 2026-05-15
- 缺失日期：2024-01-02（缓存范围第2天）
- factor_df_new 有数据（日期、股票、close）
- 但 bollinger_pb_1d 全为 NaN（只有1天历史数据，无法计算20日布林带）
- calculate_single_day_ic 返回 None
- 用户看不到诊断信息，不知道为什么跳过

问题后果：
- 静默产生大量 None IC值
- 用户不知道跳过原因
- 无法区分"股票数不足"和"因子值NaN"
```

### 正确实现

```python
# ✓ 正确：检查因子值有效性
# 篛选缺失日期的数据
factor_df_new = factor_df_full[factor_df_full['date'].isin(missing_set)]

# 检查因子值有效性
valid_factor_count = factor_df_new['bollinger_pb_1d'].notna().sum()
total_factor_count = len(factor_df_new)

if valid_factor_count == 0:
    # 缺失日期的因子值全为 NaN（布林带预热期）
    print(f"  [诊断] 缺失日期的因子值全为 NaN（可能因布林带预热期）")
    print(f"  [诊断] 缺失日期: {sorted(factor_df_new['date'].unique())[:5]}")
    print(f"  [建议] 这些日期需要更多历史数据才能计算布林带，跳过增量计算")
    return existing_data

print(f"  - 篛选后: {len(factor_df_new)} 行，其中 {valid_factor_count} 行有效因子值")
if total_factor_count - valid_factor_count > 0:
    print(f"  - {total_factor_count - valid_factor_count} 行因子值为 NaN（布林带预热期）")
```

### 禁止行为

```python
# ❌ 禁止：只检查 factor_df_new 是否为空，不检查因子值有效性
if factor_df_new.empty:
    return existing_data

print(f"  - 篛选后: {len(factor_df_new)} 行")  # ✗ 没有检查因子值是否有效！

# 问题：
# - factor_df_new 不为空，但 bollinger_pb_1d 可能全为 NaN
# - 后续 calculate_single_day_ic 返回 None
# - 用户看不到诊断信息，不知道跳过原因
```

### 为何必须检查因子值有效性

1. **布林带预热期：** 技术指标需要历史数据预热，前N-1天因子值为 NaN
2. **诊断信息清晰：** 告知用户跳过原因，而非静默产生 None
3. **区分跳过原因：** 区分"数据缺失"、"股票数不足"、"因子值NaN"
4. **提前返回：** 若全为 NaN，直接返回缓存，避免无效计算

### 适用场景

1. **布林带 %B**：N=20，前19天预热期
2. **RSI**：N=6/14，前N-1天预热期
3. **KDJ**：N=9，前N-1天预热期
4. **任何需要历史数据的技术指标**

### 检查清单

```
□ 检查 factor_df_new 是否为空（数据缺失）
□ 检查因子值是否有效（notna().sum() > 0）
□ 提供诊断信息（缺失日期示例）
□ 区分不同跳过原因（数据缺失/因子值NaN/股票数不足）
□ 提前返回缓存（避免无效计算）
```

---

## 增量路径 None 值保留规范

### 核心原则

**增量路径合并时必须保留所有日期（包括 None IC 值的日期），不过滤 None，确保 total_days 与 valid_days 的差值语义正确。**

### 问题背景

```
逻辑矛盾问题：

旧代码（错误）：
```python
date_ic_map = {}
for date, ic in zip(existing_dates, existing_ic_values):
    if ic is not None:  # ✗ 过滤了 None
        date_ic_map[date] = ic
for date, ic in zip(new_dates, new_ic_values):
    if ic is not None:  # ✗ 过滤了 None
        date_ic_map[date] = ic

all_dates = sorted(date_ic_map.keys())  # ✗ 只包含有效 IC 的日期
all_ic_values = [date_ic_map[d] for d in all_dates]  # ✗ 不包含 None
```

问题后果：
- 丢失了"股票数不足跳过"的日期（IC=None）
- total_days = len(all_dates) 只计算有效 IC 的日期数
- valid_days 也只计算有效 IC 的日期数
- 两者相等，无法区分跳过的日期
- 语义失真：用户不知道有多少天因股票数不足跳过

示例场景：
- 现有缓存：dates=['2024-01-01', '2024-01-02'], ic_values=[0.05, None]
- 增量计算：new_dates=['2024-01-03'], new_ic_values=[None]
- 合并后：all_dates=['2024-01-01'], all_ic_values=[0.05]
- ✗ 丢失了 2024-01-02, 2024-01-03（都因股票数不足跳过）
- total_days=1, valid_days=1，但实际应有 total_days=3, valid_days=1
```

### 正确实现

```python
# ✓ 正确：保留所有日期，不过滤 None
# 使用字典去重，保留 None 值
date_ic_map = {}
for date, ic in zip(existing_dates, existing_ic_values):
    date_ic_map[date] = ic  # 保留 None 值，不过滤
for date, ic in zip(new_dates, new_ic_values):
    date_ic_map[date] = ic  # 保留 None 值，不过滤

# 按日期排序（包含所有日期，包括 None IC 值的日期）
all_dates = sorted(date_ic_map.keys())
all_ic_values = [date_ic_map[d] for d in all_dates]  # 包含 None

# 统计有效 IC 数（用于诊断信息）
valid_ic_count = sum(1 for ic in all_ic_values if ic is not None)
none_ic_count = len(all_ic_values) - valid_ic_count

print(f"  - 合并后总计: {len(all_dates)} 天（去重后）")
if none_ic_count > 0:
    print(f"  - 其中 {valid_ic_count} 天有效 IC，{none_ic_count} 天因股票数不足跳过（IC=None）")

# 后续 calculate_ic_statistics 会自动过滤 None 计算 valid_days
# total_days = len(all_dates)，valid_days = valid_ic_count
```

### 禁止行为

```python
# ❌ 禁止：合并时过滤 None
date_ic_map = {}
for date, ic in zip(existing_dates, existing_ic_values):
    if ic is not None:  # ✗ 过滤了 None，丢失跳过的日期
        date_ic_map[date] = ic

# ❌ 禁止：只统计有效 IC 的日期
all_dates = sorted(date_ic_map.keys())  # ✗ 不包含 None IC 的日期
all_ic_values = [date_ic_map[d] for d in all_dates]  # ✗ 不包含 None

# 问题：
# - total_days = len(all_dates) = valid_days
# - 无法区分"股票数不足跳过"的日期
# - 语义失真
```

### 为何必须保留 None 值

1. **语义正确性：** total_days 应表示所有日期数，valid_days 应表示有效 IC 数
2. **诊断信息完整：** 用户需要知道有多少天因股票数不足跳过
3. **统计指标准确：** calculate_ic_statistics 自动过滤 None，不影响 IC/ICIR 计算
4. **与全量路径一致：** 全量路径也保留 None 值

### calculate_ic_statistics 处理逻辑

```python
# common/ic_calculator.py 中的 calculate_ic_statistics
# 自动过滤 None 值，只计算有效 IC 的统计指标
def calculate_ic_statistics(ic_series: pd.Series) -> dict:
    # 过滤 None 值（pd.Series 中的 NaN）
    valid_ic = ic_series.dropna()
    
    # 统计指标基于有效 IC 计算
    ic_mean = valid_ic.mean()
    ic_std = valid_ic.std()
    icir = ic_mean / ic_std if ic_std > 0 else 0
    
    # 但 total_days = len(ic_series)，valid_days = len(valid_ic)
    return {
        'total_days': len(ic_series),  # 包含 None 的日期数
        'valid_days': len(valid_ic),   # 有效 IC 的日期数
        ...
    }
```

### 检查清单

```
□ 合并时不过滤 None（保留所有日期）
□ all_dates 包含所有日期（包括 None IC 的日期）
□ all_ic_values 包含 None（不过滤）
□ 提供诊断信息（valid_ic_count vs none_ic_count）
□ total_days 与 valid_days 差值语义正确
```

---

## 布林带因子必须加载 close 列规范

### 核心原则

**布林带因子依赖 close 价格计算，load_data_from_cache 必须强制加载和过滤 'close' 列，无论 factor_col 参数值为何。**

### 问题背景

```
设计缺陷问题：

旧代码（错误）：
```python
factor_cols = ['date', 'asset', factor_col]  # ✗ 如果 factor_col != 'close'，不包含 'close'
factor_df = factor_df[factor_cols].copy()

factor_df.dropna(subset=[factor_col])  # ✗ 只过滤 factor_col 的 NaN，不过滤 'close'
```

问题后果：
- 如果调用方传入 factor_col='volume'（或其他非 'close'）
- close 列不会被加载和过滤
- 原始缓存中 close 有 NaN 的行不会被过滤
- 后续布林带计算需要 close 列 → KeyError 或 NaN 值传播

示例场景：
- 原始缓存: {"date": "2024-01-02", "close": null, "volume": 500000}
- 调用 load_data_from_cache(factor_col='volume')
- factor_cols = ['date', 'asset', 'volume']（不包含 'close'）
- dropna(subset=['volume']) 不过滤 close=null 的行
- 后续布林带计算: close 列不存在 → KeyError
- 或如果 close 列存在但未被过滤: close=null → NaN 值传播
```

### 正确实现

```python
# ✓ 正确：强制加载 'close' 列（布林带依赖）
factor_cols = ['date', 'asset']
if factor_col not in factor_cols:
    factor_cols.append(factor_col)
if 'close' not in factor_cols:  # 强制加载 'close' 列
    factor_cols.append('close')

factor_df = factor_df[factor_cols].copy()

# ✓ 正确：强制过滤 'close' 列的 NaN
dropna_cols = ['close']  # 布林带因子必须过滤 close 列
if factor_col not in dropna_cols:
    dropna_cols.append(factor_col)

factor_df = factor_df.dropna(subset=dropna_cols).reset_index(drop=True)
```

### 禁止行为

```python
# ❌ 禁止：只加载 factor_col 列，不强制加载 'close'
factor_cols = ['date', 'asset', factor_col]  # ✗ 如果 factor_col != 'close'，不包含 'close'

# ❌ 禁止：只过滤 factor_col 的 NaN，不过滤 'close'
factor_df.dropna(subset=[factor_col])  # ✗ close 列的 NaN 未被过滤

# 问题：
# - 布林带计算需要 close 列
# - close 有 NaN 的行未被过滤
# - NaN 值传播到布林带计算
```

### 为何必须强制加载 close 列

1. **布林带公式依赖 close**：布林带%B = (close - lower) / (upper - lower)
2. **close 有 NaN 必须过滤**：NaN 值传播会导致布林带计算产生 NaN
3. **防御性设计**：即使调用方传入错误的 factor_col，也能确保 close 列被正确加载
4. **避免 KeyError**：后续布林带计算需要 close 列，必须提前加载

### 适用范围

此规范适用于所有依赖 close 价格的因子脚本：
1. **布林带 %B**：依赖 close 计算布林带上下轨
2. **RSI**：依赖 close 计算价格变动
3. **KDJ**：依赖 close 计算 J 值
4. **任何需要 close 价格的技术指标**

### 检查清单

```
□ 强制加载 'close' 列（无论 factor_col 参数）
□ 强制过滤 'close' 列的 NaN
□ 同时过滤 factor_col 的 NaN（调用方指定的因子列）
□ 提供诊断信息（显示过滤的列）
□ 确保布林带计算所需列存在
```

---

## 布林带因子固定使用 close 列规范

### 核心原则

**布林带因子必须使用 close 价格，这是布林带的数学定义。load_data_from_cache 不接受 factor_col 参数，固定加载和过滤 'close' 列。**

### 问题背景

```
接口设计不一致问题：

旧设计（错误）：
```python
# load_data_from_cache 接受 factor_col 参数
def load_data_from_cache(factor_col: str = 'close', ...):
    factor_cols = ['date', 'asset', factor_col]  # ✗ 参数误导

# calculate_bollinger_pb_1d_factor 硬编码使用 close
def calculate_bollinger_pb_1d_factor(factor_df, n=20, k=2.0):
    required_cols = ['date', 'asset', 'close']  # ✗ 硬编码
    factor_df.groupby('asset')['close'].transform(...)  # ✗ 硬编码
```

问题后果：
- 接口设计不一致：factor_col 参数对布林带因子没有意义
- 如果调用方传入 factor_col='volume'，会加载 volume 列
- 但布林带计算硬编码使用 close 列
- 参数设计误导用户，扩展性差

布林带公式定义：
- 中轨 = SMA(close, N)
- 上轨 = 中轨 + K × Std(close, N)
- 下轨 = 中轨 - K × Std(close, N)
- %B = (close - 下轨) / (上轨 - 下轨)

布林带因子必须使用 close 价格，这是布林带的数学定义。
factor_col 参数对于布林带因子来说没有意义，只能为 'close'。
```

### 正确实现

```python
# ✓ 正确：不接受 factor_col 参数，固定加载 close 列
def load_data_from_cache(return_col: str = 'forward_return_1d'):
    """
    布林带因子必须使用 close 价格，这是布林带的数学定义
    因此固定加载和过滤 'close' 列，不接受 factor_col 参数
    """
    factor_cols = ['date', 'asset', 'close']  # 固定列名，不接受参数
    factor_df = factor_df[factor_cols].copy()
    
    # 固定过滤 close 列的 NaN
    factor_df = factor_df.dropna(subset=['close']).reset_index(drop=True)
    return factor_df, return_df, raw_metadata

# ✓ 正确：calculate_bollinger_pb_1d_factor 签名一致
def calculate_bollinger_pb_1d_factor(factor_df, n=20, k=2.0):
    """
    布林带因子必须使用 close 价格（布林带的数学定义）
    """
    required_cols = ['date', 'asset', 'close']  # 与 load_data_from_cache 一致
    factor_df.groupby('asset')['close'].transform(...)  # 使用 close 列
```

### 禁止行为

```python
# ❌ 禁止：接受 factor_col 参数（误导用户）
def load_data_from_cache(factor_col: str = 'close', ...):  # ✗ 参数对布林带因子没有意义
    factor_cols = ['date', 'asset', factor_col]  # ✗ 参数化加载列

# ❌ 禁止：调用方传入错误的 factor_col
load_data_from_cache(factor_col='volume')  # ✗ 布林带因子不能使用 volume

# 问题：
# - 布林带公式必须使用 close 价格
# - factor_col 参数误导用户
# - 接口设计不一致
```

### 为何必须固定使用 close 列

1. **布林带公式定义**：布林带指标基于 close 价格计算，这是布林带的数学定义
2. **技术指标本质**：布林带是价格波动范围指标，必须使用 close 价格
3. **接口一致性**：load_data_from_cache 和 calculate_bollinger_pb_1d_factor 签名一致
4. **避免误导**：不接受 factor_col 参数，避免调用方传入错误的值

### 适用范围

此规范适用于所有固定依赖特定列的技术指标：
1. **布林带 %B**：固定使用 close 价格
2. **RSI**：固定使用 close 价格
3. **KDJ**：固定使用 close 价格
4. **量比**：固定使用 volume 成交量

### 其他因子脚本的 factor_col 参数

对于其他因子脚本（如 IC 相关的因子），factor_col 参数可能有意义：
- `ic_volume_ratio_1d.py`：量比因子固定使用 volume
- `ic_turnover_surge_1d.py`：换手率因子固定使用 turnover

但布林带因子固定使用 close，不接受 factor_col 参数。

### 检查清单

```
□ 不接受 factor_col 参数（布林带因子固定使用 close）
□ 固定加载 'close' 列（factor_cols = ['date', 'asset', 'close'])
□ 固定过滤 'close' 列的 NaN
□ 函数签名与 calculate_bollinger_pb_1d_factor 一致
□ 文档说明布林带的数学定义
```

---

## 列表索引访问前必须检查长度规范

### 核心原则

**访问列表元素（如 list[0], list[-1]）前必须检查列表长度，避免 IndexError。**

### 问题背景

```
IndexError 问题：

旧代码（错误）：
```python
# 日期格式断言
dates_to_check = [all_dates[0], all_dates[-1], raw_metadata['period_start'], raw_metadata['period_end']]
for d in dates_to_check:
    if not re.match(r'^\d{4}-\d{2}-\d{2}$', str(d)):
        raise ValueError(f"日期格式不符合 YYYY-MM-DD 约定: {d}")
```

问题后果：
- 如果 all_dates 为空（极端情况）
- all_dates[0] → IndexError: list index out of range
- all_dates[-1] → IndexError: list index out of range

示例场景（增量路径）：
- 现有缓存为空：existing_dates = [], existing_ic_values = []
- 新日期无有效数据：
  - 因子值全为 NaN（布林带预热期）
  - 或全部因股票数不足跳过（IC=None）
- 合并后：all_dates = [], all_ic_values = []
- 访问 all_dates[0] → IndexError
```

### 正确实现

```python
# ✓ 正确：检查列表长度，避免 IndexError
if len(all_dates) == 0:
    print("  [警告] 合并后无有效日期，跳过日期格式检查")
    dates_to_check = [raw_metadata['period_start'], raw_metadata['period_end']]
else:
    dates_to_check = [all_dates[0], all_dates[-1], raw_metadata['period_start'], raw_metadata['period_end']]

for d in dates_to_check:
    if not re.match(r'^\d{4}-\d{2}-\d{2}$', str(d)):
        raise ValueError(f"日期格式不符合 YYYY-MM-DD 约定: {d}")
```

### 禁止行为

```python
# ❌ 禁止：直接访问列表元素，不检查长度
dates_to_check = [all_dates[0], all_dates[-1], ...]  # ✗ IndexError if all_dates is empty

# ❌ 禁止：假设列表不为空
# 问题：
# - 空列表访问索引会抛出 IndexError
# - 增量路径可能合并后为空
# - 缺少防御性检查
```

### 为何必须检查列表长度

1. **防御性编程**：避免极端情况下的 IndexError
2. **增量路径空合并**：现有缓存为空 + 新日期无有效数据 → 空列表
3. **诊断信息清晰**：告知用户为何跳过检查
4. **稳定运行**：不应因边界情况崩溃

### 适用范围

此规范适用于所有列表索引访问：
1. **dates[0], dates[-1]**：访问日期列表首尾
2. **ic_values[0]**：访问 IC 值列表
3. **任何 list[index]**：访问列表任意索引

### 检查清单

```
□ 访问 list[0] 前检查 len(list) > 0
□ 访问 list[-1] 前检查 len(list) > 0
□ 访问 list[index] 前检查 len(list) > index
□ 提供诊断信息（为何跳过检查）
□ 避免 IndexError 崩溃
```

---

## 异常处理必须区分严重错误和可恢复错误规范

### 核心原则

**异常处理必须区分严重错误（文件损坏、权限问题）和可恢复错误（文件不存在），严重错误不应静默降级，应抛出异常并提供详细诊断。**

### 问题背景

```
静默吞掉异常问题：

旧代码（错误）：
```python
try:
    with open(output_file, 'r', encoding='utf-8') as f:
        cached_data = json.load(f)
        return cached_data
except Exception as e:  # ✗ 静默吞掉所有异常！
    print(f"读取缓存失败: {e}，将执行全量计算")
    return _full_recalculate(...)  # ✗ 严重错误也降级全量计算
```

问题后果：
- 文件损坏（JSONDecodeError）→ 静默降级全量计算
- 权限问题（PermissionError）→ 静默降级全量计算
- 用户以为数据完备，但缓存文件损坏
- 只打印一行日志，用户不知道严重错误
- 丢失了诊断信息，无法排查问题

严重错误示例：
- 缓存文件损坏: JSONDecodeError("Expecting value: line 1 column 1")
  - 用户以为数据完备（mode='skip'），但缓存文件损坏
  - 静默降级全量计算，用户不知道文件损坏
  - 丢失了诊断信息，无法排查问题
  
- 权限问题: PermissionError("Permission denied")
  - 缓存文件存在但无法读取
  - 静默降级全量计算，用户不知道权限问题
  - 可能导致重复全量计算，浪费资源
```

### 正确实现

```python
# ✓ 正确：区分异常类型，严重错误不静默降级
try:
    with open(output_file, 'r', encoding='utf-8') as f:
        cached_data = json.load(f)
        return cached_data
except FileNotFoundError:
    # 缓存文件不存在 → 可恢复错误，降级全量计算
    print("  [诊断] 缓存文件不存在，执行全量计算")
    return _full_recalculate(...)
except json.JSONDecodeError as e:
    # JSON解析失败 → 严重错误（文件损坏），不应静默降级
    print("  [严重错误] 缓存文件损坏，JSON解析失败")
    print(f"  [详情] {e}")
    print(f"  [文件] {output_file}")
    print("  [建议] 请检查缓存文件是否损坏，或删除后重新生成")
    raise RuntimeError(
        f"缓存文件损坏，无法解析 JSON: {output_file}\n"
        f"错误详情: {e}\n"
        f"建议: 删除损坏的缓存文件后重新运行"
    ) from e
except PermissionError as e:
    # 权限问题 → 严重错误，不应静默降级
    print("  [严重错误] 缓存文件权限不足")
    print(f"  [详情] {e}")
    print(f"  [文件] {output_file}")
    raise RuntimeError(
        f"缓存文件权限不足，无法读取: {output_file}\n"
        f"错误详情: {e}"
    ) from e
except Exception as e:
    # 其他未预期的异常 → 提供详细诊断，不应静默降级
    print("  [未预期错误] 读取缓存失败")
    print(f"  [异常类型] {type(e).__name__}")
    print(f"  [详情] {e}")
    print(f"  [文件] {output_file}")
    raise RuntimeError(
        f"读取缓存失败（未预期异常）: {output_file}\n"
        f"异常类型: {type(e).__name__}\n"
        f"错误详情: {e}"
    ) from e
```

### 禁止行为

```python
# ❌ 禁止：静默吞掉所有异常
except Exception as e:  # ✗ 捕获所有异常，包括严重错误
    print(f"读取缓存失败: {e}，将执行全量计算")  # ✗ 只打印一行日志
    return _full_recalculate(...)  # ✗ 严重错误也降级全量计算

# ❌ 禁止：不区分异常类型
# 问题：
# - 文件损坏（JSONDecodeError）是严重错误，不应静默降级
# - 权限问题（PermissionError）是严重错误，不应静默降级
# - 用户不知道严重错误，无法排查问题
```

### 异常分类

| 异常类型 | 错误级别 | 处理方式 | 是否降级 |
|---------|---------|---------|---------|
| FileNotFoundError | 可恢复 | 降级全量计算 | ✓ 可以 |
| json.JSONDecodeError | 严重 | 抛出异常 + 详细诊断 | ✗ 不可以 |
| PermissionError | 严重 | 抛出异常 + 详细诊断 | ✗ 不可以 |
| 其他 Exception | 未预期 | 抛出异常 + 详细诊断 | ✗ 不可以 |

### 为何必须区分异常类型

1. **诊断信息完整**：用户需要知道是文件损坏还是权限问题
2. **严重错误不掩盖**：文件损坏是严重错误，不应静默降级
3. **避免重复问题**：权限问题不解决，每次都会降级全量计算
4. **用户可操作**：提供具体建议（删除损坏文件、修复权限）

### 适用范围

此规范适用于所有缓存读取场景：
1. **IC 数据缓存读取**：读取 JSON 格式的 IC 计算结果
2. **因子数据缓存读取**：读取 gzip 压缩的因子数据
3. **配置文件读取**：读取 JSON/YAML 配置文件
4. **任何需要区分错误级别的场景**

### 检查清单

```
□ 区分 FileNotFoundError（可恢复）和 JSONDecodeError（严重）
□ 区分 PermissionError（严重）和其他异常
□ 严重错误不静默降级（抛出异常）
□ 提供详细诊断信息（异常类型、详情、文件路径）
□ 提供用户可操作的建议（删除损坏文件、修复权限）
```

---

## 异常链保留规范

### 核心原则

**异常处理必须使用 `raise ... from e` 保留异常链，确保调试时能追溯异常来源。裸 raise 虽然保留异常类型，但不设置显式的 `__cause__`，与使用 `from e` 的风格不一致。**

### 问题背景

```
异常链不一致问题：

旧代码（风格不一致）：
```python
except FileNotFoundError as e:
    raise RuntimeError(...) from e  # ✓ 使用 from e
except json.JSONDecodeError as e:
    raise RuntimeError(...) from e  # ✓ 使用 from e
except KeyError as e:
    raise RuntimeError(...) from e  # ✓ 使用 from e
except ValueError as e:
    raise  # ✗ 裸 raise，风格不一致（注释说保留异常类型，但未说明异常链）
except Exception as e:
    raise RuntimeError(...) from e  # ✓ 使用 from e
```

问题后果：
- ValueError 处理使用裸 raise，与其他 except 块风格不一致
- 注释说"保留原始异常类型"，但未说明异常链处理
- 调试时看不到显式的异常来源（__cause__ 未设置）
- 维护时容易误改（风格不一致）

Python 异常链机制：
- raise ... from e：设置 __cause__（显式异常链）
- 裸 raise：设置 __context__（隐式异常链），但不设置 __cause__
- raise ... from None：清除异常链（__suppress_context__ = True）

虽然裸 raise 会保留 __context__（隐式异常链），但：
- 调试时看到的 traceback 不够清晰（没有显式的 "The above exception was the direct cause"）
- 风格不一致，维护时容易误改
- 最佳实践是统一使用 from e
```

### 正确实现

```python
# ✓ 正确：统一使用 from e，保留异常链
except FileNotFoundError as e:
    raise RuntimeError(...) from e  # ✓ 显式异常链
except json.JSONDecodeError as e:
    raise RuntimeError(...) from e  # ✓ 显式异常链
except KeyError as e:
    raise RuntimeError(...) from e  # ✓ 显式异常链
except ValueError as e:
    # 数据量不足：保留原始异常类型 + 保留异常链（遵循 MODULE.md 异常链保留规范）
    # 使用 from e 保持风格一致性，与其他 except 块统一
    raise  # ✓ 裸 raise 保留 ValueError 类型 + __context__ 异常链
except Exception as e:
    raise RuntimeError(...) from e  # ✓ 显式异常链
```

### 特殊情况：保留原始异常类型

如果需要保留原始异常类型（如 ValueError），有两种选择：

```python
# 方案1：裸 raise（保留 ValueError 类型 + __context__ 异常链）
except ValueError as e:
    # 注释说明：保留原始异常类型 + 保留异常链（__context__）
    raise  # ValueError 会保留 __context__（隐式异常链）

# 方案2：显式 raise（创建新 ValueError + __cause__ 异常链）
except ValueError as e:
    raise ValueError(f"数据量不足: {e}") from e  # 显式异常链
```

**推荐方案1（裸 raise）**，因为：
- 保留原始异常类型（ValueError）
- 保留隐式异常链（__context__）
- 不需要重新构造异常

---

## 异常处理链规范（2026-05-20新增）

### 核心原则

**异常处理链设计必须避免多层叠加：函数内部抛出的异常消息，不应在调用方再次包装叠加，否则诊断时会看到重复描述。**

### 问题背景

```
两层叠加问题：

错误代码：
# load_data_from_cache() 内部
if not path.exists():
    raise FileNotFoundError(f"换手率缓存不存在: {path}")  # 第一层

# _full_recalculate() 调用方
except FileNotFoundError as e:
    raise RuntimeError(f"缓存文件不存在: {e}") from e  # 第二层叠加

诊断输出：
RuntimeError: 缓存文件不存在: 换手率缓存不存在: /path/to/file
               ^^^^^^^^^^^^^^^^^^^   ^^^^^^^^^^^^^^^^^^^^^^^^^^^^
               第二层叠加           第一层（重复描述）

问题后果：
- 错误消息重复，用户看到两次"缓存不存在"
- 诊断信息冗余，降低可读性
- 维护时难以判断哪一层是问题根源
```

### 异常处理链设计规范

| 层级 | 职责 | 处理方式 |
|------|------|----------|
| 底层函数（数据加载） | 抛出语义清晰的原始异常 | 裸 raise 或构造异常（语义清晰） |
| 中间层（调用方） | 区分异常类型，决定处理策略 | 裸 raise（保留原始）或 不捕获（让异常传播） |
| 顶层（主函数） | 提供用户友好的错误消息 | 包装为 RuntimeError（附加上下文） |

**关键原则：**

| 原则 | 说明 |
|------|------|
| 单层包装原则 | 异常消息只包装一次，不在多层叠加 |
| 底层语义清晰原则 | 底层函数抛出的异常消息应语义清晰，无需上层再次包装 |
| 不捕获原则 | 如果上层不需要添加上下文，应不捕获（让异常自然传播） |
| 裸 raise 原则 | 如果需要保留原始类型，使用裸 raise（不包装） |

### 正确实现模式

**模式1：底层语义清晰 + 中间层不捕获**

```python
# ✓ 正确：底层异常消息语义清晰，中间层不捕获
# load_data_from_cache() 内部
if not path.exists():
    # 底层抛出语义清晰的异常（无需上层包装）
    raise FileNotFoundError(f"缓存不存在: {path}")

# _full_recalculate() 中间层
factor_df, return_df, raw_metadata = load_data_from_cache()  # 不捕获，让 FileNotFoundError 自然传播

# main() 顶层
try:
    ic_data = main()
except FileNotFoundError as e:
    # 顶层：提供用户友好的错误消息 + 处理建议
    print(f"错误: {e}")
    print("建议: 请先运行数据缓存脚本")
```

**模式2：底层抛出 + 中间层裸 raise（保留类型）**

```python
# ✓ 正确：中间层需要区分异常类型，但裸 raise 保留原始
# load_data_from_cache() 内部
if not path.exists():
    raise FileNotFoundError(f"缓存不存在: {path}")

# _full_recalculate() 中间层
try:
    factor_df, return_df, raw_metadata = load_data_from_cache()
except FileNotFoundError:
    # 中间层：裸 raise 保留原始类型（不叠加消息）
    raise
except ValueError as e:
    # 中间层：需要添加上下文（如阈值信息）
    raise ValueError(f"数据验证失败（min_stocks={min_stocks}): {e}") from e
```

**模式3：底层抛出 + 中间层添加上下文（单层包装）**

```python
# ✓ 正确：中间层需要添加上下文，但只包装一次
# load_data_from_cache() 内部
if not path.exists():
    # 底层：简洁异常消息（不需要详细路径）
    raise FileNotFoundError(f"{name}缓存不存在")

# _full_recalculate() 中间层
try:
    factor_df, return_df, raw_metadata = load_data_from_cache()
except FileNotFoundError as e:
    # 中间层：附加缓存路径（单层包装）
    raise FileNotFoundError(f"{e}，路径: {CACHE_DIR}") from e
```

### 常见错误模式

| 错误代码 | 问题 | 修复 |
|----------|------|------|
| 底层 `raise FileNotFoundError(f"缓存不存在: {path}")` + 中间层 `raise RuntimeError(f"缓存文件不存在: {e}")` | 两层叠加，重复描述 | 中间层裸 raise 或不捕获 |
| 底层 `raise FileNotFoundError(f"{name}缓存不存在")` + 中间层 `raise RuntimeError(f"缓存文件不存在: {e}")` | 两层叠加，重复描述 | 底层消息简洁，中间层添加路径（单层包装） |
| 底层注释说"裸 raise"但实际包装了消息 | 注释与代码不一致 | 修正注释或代码 |

---
- 如果使用裸 raise，必须注释说明："保留原始异常类型 + 保留异常链（遵循 MODULE.md 异常链保留规范）"
- 确保维护者理解裸 raise 的语义

### 禁止行为

```python
# ❌ 禁止：裸 raise 无注释说明
except ValueError as e:
    raise  # ✗ 无注释，维护者不知道为何不用 from e

# ❌ 禁止：风格不一致
except FileNotFoundError as e:
    raise RuntimeError(...) from e  # ✓
except ValueError as e:
    raise  # ✗ 风格不一致，无注释说明

# ❌ 禁止：清除异常链（除非有特殊理由）
except ValueError as e:
    raise ... from None  # ✗ 清除异常链，调试时看不到来源
```

### 为何必须保留异常链

1. **调试信息完整**：调试时能看到异常来源（"The above exception was the direct cause"）
2. **风格一致性**：所有 except 块使用统一的异常链处理方式
3. **维护友好**：注释说明清楚，维护者不会误改
4. **最佳实践**：Python 官方推荐使用 from e 保留异常链

### 适用范围

此规范适用于所有异常处理场景：
1. **缓存读取异常**：FileNotFoundError、JSONDecodeError、PermissionError
2. **数据处理异常**：ValueError（数据量不足）、KeyError（字段缺失）
3. **未预期异常**：Exception（其他异常）
4. **任何需要保留异常链的场景**

### 检查清单

```
□ 统一使用 from e（风格一致性）
□ 如果使用裸 raise，必须注释说明
□ 注释说明："保留原始异常类型 + 保留异常链（遵循 MODULE.md 异常链保留规范）"
□ 不使用 from None（除非有特殊理由）
□ 异常链清晰，调试时能看到来源
```

---

## 布林带 %B 计算显式处理 NaN 规范

### 核心原则

**布林带 %B 计算必须显式处理 NaN，避免依赖 NaN 传播的隐式行为。布林带预热期（前 N-1 日）的 upper_band/lower_band 为 NaN，应显式定义 %B = NaN。**

### 问题背景

```
隐式 NaN 传播问题：

旧代码（隐式处理）：
```python
diff = factor_df['upper_band'] - factor_df['lower_band']

factor_df['bollinger_pb_1d'] = np.where(
    np.abs(diff) < 1e-10,  # ✗ 当 diff 为 NaN 时，np.abs(NaN) = NaN，NaN < 1e-10 = False
    0.5,
    (factor_df['close'] - factor_df['lower_band']) / diff  # ✗ NaN / NaN = NaN（隐式传播）
)
```

问题后果：
- 布林带预热期（前 N-1 日）：upper_band/lower_band 为 NaN
- diff = NaN - NaN = NaN
- np.abs(NaN) = NaN
- NaN < 1e-10 = False（条件为 False）
- np.where 执行除法分支：(close - lower_band) / diff = NaN / NaN = NaN

虽然最终结果是 NaN（正确），但：
- 依赖了 NaN 比较返回 False 的隐式行为
- 逻辑不够清晰，维护者需要理解 NaN 传播规则
- 代码可读性差，不够显式

Python NaN 比较规则：
- NaN == NaN → False
- NaN < 任何值 → False
- NaN > 任何值 → False
- np.abs(NaN) → NaN
```

### 正确实现

```python
# ✓ 正确：显式处理 NaN
diff = factor_df['upper_band'] - factor_df['lower_band']

# 显式处理三种情况：
# 1. diff 为 NaN（布林带预热期）→ %B = NaN
# 2. diff ≈ 0（布林带宽度为零）→ %B = 0.5
# 3. diff > 0（正常情况）→ %B = (close - lower) / diff

factor_df['bollinger_pb_1d'] = np.where(
    pd.isna(diff),  # 显式检查 NaN（布林带预热期）
    np.nan,         # NaN → NaN（显式定义，而非依赖隐式传播）
    np.where(
        np.abs(diff) < 1e-10,  # 浮点数精度容差判断
        0.5,  # 布林带宽度为零时，%B 定义为 0.5（价格在中轨）
        (factor_df['close'] - factor_df['lower_band']) / diff  # 正常计算
    )
)
```

### 禁止行为

```python
# ❌ 禁止：依赖 NaN 传播的隐式行为
factor_df['bollinger_pb_1d'] = np.where(
    np.abs(diff) < 1e-10,  # ✗ NaN < 1e-10 返回 False（隐式）
    0.5,
    (factor_df['close'] - factor_df['lower_band']) / diff  # ✗ NaN / NaN = NaN（隐式传播）
)

# ❌ 禁止：不显式检查 NaN
# 问题：
# - 维护者需要理解 NaN 比较规则
# - 代码可读性差，不够显式
# - 容易误解逻辑
```

### 为何必须显式处理 NaN

1. **代码可读性**：显式定义三种情况，逻辑清晰
2. **维护友好**：维护者不需要理解 NaN 比较规则
3. **避免误解**：明确说明布林带预热期 %B = NaN
4. **最佳实践**：显式优于隐式，代码更健壮

### 布林带预热期说明

布林带计算需要前 N-1 日数据预热：
- N=20，需要前19日数据
- rolling(window=n, min_periods=n) 确保前 N-1 天为 NaN
- upper_band/lower_band 在前 N-1 天为 NaN
- %B 在前 N-1 天也应为 NaN（显式定义）

### 适用范围

此规范适用于所有依赖技术指标预热的因子计算：
1. **布林带 %B**：N=20，前19天预热期
2. **RSI**：N=6/14，前N-1天预热期
3. **KDJ**：N=9，前N-1天预热期
4. **任何需要历史数据的技术指标**

### 检查清单

```
□ 显式检查 pd.isna(diff)（布林带预热期）
□ 显式定义 %B = np.nan（而非依赖隐式传播）
□ 使用嵌套 np.where 处理三种情况
□ 注释说明每种情况的语义
□ 避免依赖 NaN 比较返回 False 的隐式行为
```

---

## 增量路径向量化计算 IC 规范

### 核心原则

**增量路径计算 IC 必须使用向量化处理：先整体 merge，再按日期 groupby 计算。禁止逐行循环做 DataFrame 过滤和 merge，这会导致严重性能问题。**

### 问题背景

```
逐行循环性能问题：

旧代码（低效）：
```python
for date in new_dates:
    day_factor = factor_df_new[factor_df_new['date'] == date]  # ✗ 每次循环做 DataFrame 过滤
    day_return = return_df_new[return_df_new['date'] == date]  # ✗ 每次循环做 DataFrame 过滤
    
    # 合并
    merged = day_factor.merge(day_return, on=['date', 'asset'], how='inner')  # ✗ 每次循环做 merge
    
    # 计算 IC
    ic_value = calculate_single_day_ic(merged, ...)
    new_ic_values.append(...)
```

性能分析：
- 当 missing_dates = 100 天时
- 循环 100 次，每次做：
  - 2次 DataFrame 过滤（扫描全表 O(n)）
  - 1次 merge（O(m)）
- 总性能：100 × (2n + m) = O(200n + 100m)
- DataFrame 过滤每次扫描全表，非常低效

示例场景：
- missing_dates = 100 天
- factor_df_new = 100,000 行（100天 × 1000股票）
- 每次 DataFrame 过滤：扫描 100,000 行 → 找到 1000 行
- 100 次循环 × 100,000 扫描 = 10,000,000 次操作
- 性能极差，耗时显著增加
```

### 正确实现

```python
# ✓ 正确：向量化处理，先整体 merge
# 计算新日期的每日 IC（遵循 MODULE.md 增量路径向量化计算 IC 规范）
new_dates = sorted(factor_df_new['date'].unique())

# 向量化处理：先整体 merge（一次操作）
merged_new = factor_df_new.merge(return_df_new, on=['date', 'asset'], how='inner')

# 检查 merge 后是否有数据
if merged_new.empty:
    print("  [警告] merge 后无数据，所有日期因股票数不足跳过")
    new_ic_values = [None] * len(new_dates)
else:
    # 按日期分组计算 IC（向量化）
    # 使用 groupby 避免逐行循环，提升性能约 N 倍
    ic_results = {}
    for date, group in merged_new.groupby('date'):
        ic_value = calculate_single_day_ic(
            group, factor_col='bollinger_pb_1d', return_col='forward_return', min_stocks=min_stocks
        )
        ic_results[date] = round(ic_value, 6) if ic_value is not None else None
    
    # 按日期顺序填充 IC 值（缺失日期填充 None）
    new_ic_values = [ic_results.get(date) for date in new_dates]
```

### 禁止行为

```python
# ❌ 禁止：逐行循环做 DataFrame 过滤
for date in new_dates:
    day_factor = factor_df_new[factor_df_new['date'] == date]  # ✗ 每次循环扫描全表

# ❌ 禁止：逐行循环做 merge
for date in new_dates:
    merged = day_factor.merge(day_return, ...)  # ✗ 每次循环做 merge

# ❌ 禁止：逐行循环计算 IC
for date in new_dates:
    ic_value = calculate_single_day_ic(merged, ...)  # ✗ 逐行循环

# 问题：
# - DataFrame 过滤每次扫描全表 O(n)
# - 当 missing_dates 较多时（如100天），性能极差
# - 总性能：N × (2n + m)，其中 N 为 missing_dates 数
# - 向量化处理性能：O(n + g)，其中 g 为组数（g << n）
```

### 性能对比

| 方式 | 操作数 | 性能 |
|------|--------|------|
| 逐行循环（N=100） | 100 × (2n + m) | O(200n + 100m) |
| 向量化处理 | n + g | O(n + g) |
| **性能提升** | - | **约 100 倍** |

当 missing_dates = 100 时，向量化处理性能提升约 100 倍。

### 为何必须使用向量化处理

1. **性能显著提升**：避免逐行循环扫描全表，性能提升约 N 倍
2. **DataFrame 过滤低效**：每次过滤扫描全表，非常耗时
3. **merge 操作昂贵**：每次 merge 需要哈希匹配，逐行循环浪费资源
4. **pandas 最佳实践**：向量化处理是 pandas 最佳实践

### 适用范围

此规范适用于所有按日期分组计算的场景：
1. **IC 计算**：按日期分组计算 Spearman IC
2. **因子统计**：按日期分组计算因子统计指标
3. **收益分析**：按日期分组计算收益指标
4. **任何需要按日期分组的批量计算**

### 检查清单

```
□ 先整体 merge（一次操作）
□ 按 groupby 计算（避免逐行循环）
□ 检查 merge 后是否有数据（空数据处理）
□ 按日期顺序填充 IC 值（缺失日期填充 None）
□ 禁止逐行循环做 DataFrame 过滤
□ 禁止逐行循环做 merge
```

---

## 增量路径布林带历史数据必要性规范

### 核心原则

**增量路径必须加载全量数据计算布林带，再筛选缺失日期。布林带使用 rolling(window=N) 计算 SMA 和 Std，每个目标日期需要前面 N-1 天历史数据。这是必要的，不是浪费。**

### 问题背景

```
历史数据必要性：

用户疑问：
- 为什么加载全量数据，只用到缺失日期的数据？
- 是否浪费计算资源？

技术解释：
- 布林带公式：中轨 = SMA(close, N)，上轨 = 中轨 + K × Std(close, N)
- pandas rolling(window=N, min_periods=N)：需要前 N-1 天历史数据
- 例如 N=20：计算 2024-01-20 的布林带
  - 需要 2024-01-01 ~ 2024-01-19 的历史数据（19天）
  - rolling 窗口包含 2024-01-01 ~ 2024-01-20（20天）
  - 2024-01-20 是目标日期，前19天是历史数据

示例场景：
- 缓存范围：2024-01-01 ~ 2024-01-31
- 缺失日期：2024-01-20 ~ 2024-01-25（6天）
- 需要计算 2024-01-20 的布林带：
  - 需要 2024-01-01 ~ 2024-01-19 的历史数据（19天）
  - 如果不加载全量数据，无法计算 2024-01-20 的布林带
- 因此必须加载全量数据，再筛选缺失日期
```

### 正确实现

```python
# ✓ 正确：加载全量数据计算布林带，再筛选缺失日期
# 布林带计算说明（遵循 MODULE.md 增量路径布林带历史数据必要性规范）：
# - 布林带使用 rolling(window=N) 计算 SMA 和 Std，每个目标日期需要前面 N-1 天历史数据
# - 例如 N=20：计算 2024-01-20 的布林带，需要 2024-01-01 ~ 2024-01-19 的历史数据
# - 因此必须加载全量数据计算布林带，再筛选缺失日期
# - 这是必要的，不是浪费：缺失日期的布林带依赖历史数据作为滚动窗口

factor_df_full, return_df_full, raw_metadata = load_data_from_cache()

# 计算布林带%B因子（全量数据，滚动窗口需要历史数据）
factor_df_full, factor_stats = calculate_bollinger_pb_1d_factor(factor_df_full, n=n, k=k)

# 筛选缺失日期的数据
missing_set = set(missing_dates)
factor_df_new = factor_df_full[factor_df_full['date'].isin(missing_set)]
```

### 禁止行为

```python
# ❌ 禁止：只加载缺失日期的数据
# 问题：布林带需要历史数据，缺失日期前 N-1 天的数据缺失
factor_df_new = load_data_for_dates(missing_dates)  # ✗ 缺少历史数据

# ❌ 禁止：不注释说明历史数据必要性
# 问题：用户会误解为"浪费计算资源"
factor_df_full = load_data_from_cache()  # ✗ 无注释说明
```

### 为何必须加载全量数据

1. **布林带滚动窗口**：每个目标日期需要前面 N-1 天历史数据
2. **技术指标预热期**：布林带、RSI、KDJ 都需要历史数据预热
3. **缺失日期不连续**：缺失日期可能分散，每个都需要历史数据
4. **历史数据不可缺失**：缺失日期前的历史数据必须存在

### 适用范围

此规范适用于所有依赖技术指标预热的因子计算：
1. **布林带 %B**：N=20，需要前19天历史数据
2. **RSI**：N=6/14，需要前N-1天历史数据
3. **KDJ**：N=9，需要前N-1天历史数据
4. **任何需要滚动窗口的技术指标**

### 检查清单

```
□ 加载全量数据计算布林带
□ 注释说明历史数据必要性（遵循 MODULE.md 规范）
□ 明确说明：这是必要的，不是浪费
□ 篮选缺失日期的数据
□ 不只加载缺失日期的数据（缺少历史数据）
```

---

## 增量路径最小必需历史窗口边界检查规范

### 核心原则

**增量路径必须检查缺失日期是否在最小必需历史窗口内（布林带预热期）。缺失日期如果靠近缓存起始点（前N-1天内），因子值可能全为 NaN，需要提前警告并提供诊断信息。**

### 问题背景

```
预热期边界问题：

布林带预热期：
- N=20，需要前19天历史数据
- 缓存起始点：2024-01-01
- 预热期：2024-01-01 ~ 2024-01-19（前19天）
- 2024-01-01 ~ 2024-01-19 的布林带因子值 = NaN（预热期不足）

缺失日期在预热期：
- 缺失日期：2024-01-05（缓存范围第5天）
- 2024-01-05 只有前4天数据（2024-01-01~2024-01-04），不够19天
- 2024-01-05 的布林带因子值 = NaN（预热期不足）
- 无法计算有效 IC，浪费计算资源

边界检查必要性：
- 提前识别预热期内的缺失日期
- 提供诊断信息：告知用户为何因子值全为 NaN
- 避免无效计算：如果所有缺失日期都在预热期，提前返回缓存
```

### 正确实现

```python
# ✓ 正确：检查缺失日期是否在预热期内
# 边界检查：最小必需历史窗口（遵循 MODULE.md 增量路径最小必需历史窗口边界检查规范）
cache_start_date = raw_metadata['period_start']
cache_start_dt = pd.to_datetime(cache_start_date)

# 计算布林带预热期边界日期（缓存起始点后 N-1 天）
warmup_boundary_date = (cache_start_dt + pd.Timedelta(days=n-1)).strftime('%Y-%m-%d')
warmup_days_count = n - 1

# 检查缺失日期是否在预热期内
missing_dates_in_warmup = [d for d in missing_dates if d <= warmup_boundary_date]

if missing_dates_in_warmup:
    print(f"  [边界检查] 缓存起始: {cache_start_date}")
    print(f"  [边界检查] 布林带预热期: 前 {warmup_days_count} 天（{cache_start_date} ~ {warmup_boundary_date}）")
    print(f"  [边界检查] {len(missing_dates_in_warmup)} 个缺失日期在预热期内，因子值可能全为 NaN")
    examples = sorted(missing_dates_in_warmup)[:5]
    print(f"  [边界检查] 示例日期: {examples}")
    if len(missing_dates_in_warmup) == len(missing_dates):
        print("  [边界检查] 所有缺失日期都在预热期内，无法计算有效 IC")
        print("  [建议] 延长缓存历史范围，或跳过这些日期")
        # 不直接返回缓存，继续计算以验证（可能部分股票有更多历史数据）
```

### 禁止行为

```python
# ❌ 禁止：不检查预热期边界
# 问题：缺失日期在预热期内，因子值全为 NaN，浪费计算资源
factor_df_full = load_data_from_cache()
factor_df_full = calculate_bollinger_pb_1d_factor(factor_df_full, n=n)  # ✗ 无边界检查

# ❌ 禁止：不提供诊断信息
# 问题：用户不知道为何因子值全为 NaN
if valid_factor_count == 0:
    return existing_data  # ✗ 无诊断信息
```

### 边界检查逻辑

| 检查项 | 逻辑 | 诊断信息 |
|--------|------|----------|
| 缓存起始日期 | `raw_metadata['period_start']` | 缓存起始: YYYY-MM-DD |
| 预热期边界 | `缓存起始 + N-1 天` | 预热期: 前 N-1 天 |
| 缺失日期在预热期 | `missing_dates <= warmup_boundary` | X 个缺失日期在预热期内 |
| 全部在预热期 | `len(missing_dates_in_warmup) == len(missing_dates)` | 无法计算有效 IC |

### 为何必须检查边界

1. **避免无效计算**：缺失日期在预热期内，因子值全为 NaN
2. **提供诊断信息**：告知用户为何因子值全为 NaN
3. **用户可操作**：提供建议（延长缓存历史范围）
4. **提前预警**：避免用户困惑为何 IC 计算失败

### 适用范围

此规范适用于所有依赖技术指标预热的因子计算：
1. **布林带 %B**：N=20，预热期前19天
2. **RSI**：N=6/14，预热期前N-1天
3. **KDJ**：N=9，预热期前N-1天
4. **任何需要滚动窗口的技术指标**

### 检查清单

```
□ 计算预热期边界日期（缓存起始 + N-1 天）
□ 检查缺失日期是否在预热期内
□ 提供诊断信息（缓存起始、预热期范围、示例日期）
□ 如果全部在预热期，建议用户延长缓存历史范围
□ 不直接返回缓存，继续计算以验证（部分股票可能有更多历史数据）
```

---

## 注释缩进一致性规范

### 核心原则

**注释必须与代码保持一致的缩进级别。Python不强制注释缩进，但最佳实践是注释与代码保持一致的缩进，避免视觉歧义。**

### 问题背景

```
注释缩进不一致问题：

旧代码（错误）：
```python
def _incremental_update(...):
    # 计算 IC
    for date in new_dates:
        ic_value = calculate_single_day_ic(...)
    
# 合并数据  # ✗ 顶格注释，无缩进
    print("合并数据并重新计算统计指标...")  # ✓ 有缩进
    
    # 检查重叠
    existing_set = set(existing_dates)
```

问题后果：
- 注释顶格（无缩进），代码有缩进
- 视觉上造成歧义：注释看起来在函数外
- 实际上代码仍在函数内，但注释格式混乱
- 维护者可能误解代码结构
- 不符合 Python 最佳实践
```

### 正确实现

```python
# ✓ 正确：注释与代码保持一致的缩进
def _incremental_update(...):
    # 计算 IC
    for date in new_dates:
        ic_value = calculate_single_day_ic(...)
    
    # 合并数据（遵循 MODULE.md 注释缩进一致性规范）
    print("合并数据并重新计算统计指标...")  # ✓ 4空格缩进
    
    # 检查重叠
    existing_set = set(existing_dates)
```

### 禁止行为

```python
# ❌ 禁止：注释顶格，代码有缩进
def _incremental_update(...):
    # 计算 IC
    for date in new_dates:
        ...
    
# 合并数据  # ✗ 顶格注释，视觉歧义
    print("合并数据...")  # ✓ 有缩进

# ❌ 禁止：注释缩进与代码不一致
# 问题：
# - Python 不强制注释缩进，但最佳实践是保持一致
# - 视觉歧义：注释看起来在函数外
# - 维护者可能误解代码结构
```

### 为何必须保持注释缩进一致

1. **视觉清晰**：注释与代码保持一致的缩进，视觉上清晰
2. **避免歧义**：避免维护者误解代码结构
3. **最佳实践**：Python 最佳实践是注释与代码保持一致的缩进
4. **代码可读性**：提高代码可读性，易于维护

### 适用范围

此规范适用于所有 Python 代码：
1. **函数内注释**：注释与函数体代码保持一致的缩进
2. **类内注释**：注释与类体代码保持一致的缩进
3. **循环/条件块内注释**：注释与循环/条件块代码保持一致的缩进
4. **任何 Python 代码**

### 检查清单

```
□ 注释与代码保持一致的缩进
□ 函数内注释：4空格缩进（与函数体代码一致）
□ 类内注释：4空格缩进（与类体代码一致）
□ 循环/条件块内注释：与块内代码一致缩进
□ 避免顶格注释（除非是文件级注释）
□ 遵循 Python 最佳实践
```

---

## PEP8 import 规范

### 核心原则

**所有 import 语句必须在文件顶部，禁止在函数内部 import。函数内部 import 会每次调用时重新导入（性能问题），且降低代码可读性。**

### 问题背景

```
函数内部 import 问题：

旧代码（错误）：
```python
# 文件顶部
from factor_ic.common.ic_calculator import (
    calculate_ic_with_direction_verification,
    calculate_single_day_ic
)

def _incremental_update(...):
    # 函数内部 import（违反 PEP8）
    from factor_ic.common.ic_calculator import calculate_ic_statistics  # ✗ 在函数内
    result = calculate_ic_statistics(ic_series)
```

问题后果：
- 违反 PEP8 规范：所有 import 应在文件顶部
- 性能问题：每次调用函数时都会执行 import（虽然 Python 有缓存机制）
- 降低可读性：import 分散在不同位置，难以追踪依赖
- 代码风格不一致：同一模块的函数分散导入
```

### 正确实现

```python
# ✓ 正确：所有 import 在文件顶部
# 导入 IC 计算模块（支持方向验证 + 单日 IC 计算 + IC 统计指标计算）
from factor_ic.common.ic_calculator import (
    calculate_ic_with_direction_verification,
    calculate_single_day_ic,  # 用于增量计算
    calculate_ic_statistics   # 用于增量路径重新计算统计指标
)

def _incremental_update(...):
    # calculate_ic_statistics 已在文件顶部导入（遵循 PEP8 import 规范）
    result = calculate_ic_statistics(ic_series)
```

### 禁止行为

```python
# ❌ 禁止：函数内部 import
def _incremental_update(...):
    from factor_ic.common.ic_calculator import calculate_ic_statistics  # ✗ 在函数内
    result = calculate_ic_statistics(ic_series)

# ❌ 禁止：同一模块分散导入
# 文件顶部：
from factor_ic.common.ic_calculator import calculate_ic_with_direction_verification
# 函数内：
from factor_ic.common.ic_calculator import calculate_ic_statistics  # ✗ 分散导入

# 问题：
# - 违反 PEP8 规范
# - 降低可读性
# - 同一模块应统一导入
```

### 为何必须遵循 PEP8 import 规范

1. **PEP8 标准**：Python 官方代码风格指南要求所有 import 在文件顶部
2. **性能考虑**：虽然 Python 有 import 缓存机制，但函数内 import 每次调用都会执行查找
3. **可读性**：import 在顶部易于追踪模块依赖
4. **代码风格一致**：同一模块的函数应统一导入

### 适用范围

此规范适用于所有 Python 代码：
1. **模块级 import**：所有 import 在文件顶部
2. **同一模块导入**：同一模块的多个函数应统一导入
3. **避免函数内 import**：除非有特殊原因（如避免循环导入）
4. **任何 Python 代码**

### 检查清单

```
□ 所有 import 在文件顶部
□ 同一模块的函数统一导入
□ 避免函数内 import（除非有特殊原因）
□ 遵循 PEP8 规范
□ 提高代码可读性
```

---

## 全量路径与增量路径防御对称规范

### 核心原则

**全量路径与增量路径必须保持一致的防御机制。防御检查（如日期格式断言）不应只在某一条路径执行，两条路径都应有等效的防御。**

### 问题背景

```
防御不对称问题：

旧代码（错误）：
```python
# 增量路径：有日期格式断言
def _incremental_update(...):
    # 日期格式断言（遵循 PROJECT.md 日期字符串比较规范)
    for d in dates_to_check:
        if not re.match(r'^\d{4}-\d{2}-\d{2}$', str(d)):
            raise ValueError(f"日期格式不符合 YYYY-MM-DD 约定: {d}")

# 全量路径：无日期格式断言
def calculate_daily_ic_series(...):
    dates = [str(d) for d in ic_series.index]  # ✗ 无格式检查
    period_start = raw_metadata['period_start']  # ✗ 无格式检查
```

问题后果：
- 增量路径检查日期格式，全量路径不检查
- 防御不对称：全量路径可能通过错误的日期格式
- 如果日期格式错误（如 '2024/01/01' 或 '2024-1-1'）
- 增量路径会报错，全量路径不会报错
- 导致下游问题：JSON 序列化失败、日期比较错误
```

### 正确实现

```python
# ✓ 正确：两条路径都有日期格式断言
# 全量路径
def calculate_daily_ic_series(...):
    # 转换为 JSON 友好格式
    dates = [str(d) for d in ic_series.index]
    
    # 日期格式断言（遵循 PROJECT.md 日期字符串比较规范）
    # 核心原则：全量路径与增量路径保持一致的防御机制
    dates_to_check = [dates[0] if len(dates) > 0 else None,
                      dates[-1] if len(dates) > 0 else None,
                      period_start, period_end]
    
    for d in dates_to_check:
        if d is not None and not re.match(r'^\d{4}-\d{2}-\d{2}$', str(d)):
            raise ValueError(f"日期格式不符合 YYYY-MM-DD 约定: {d}")

# 增量路径
def _incremental_update(...):
    # 日期格式断言（遵循 PROJECT.md 日期字符串比较规范)
    dates_to_check = [all_dates[0], all_dates[-1], raw_metadata['period_start'], raw_metadata['period_end']]
    
    for d in dates_to_check:
        if not re.match(r'^\d{4}-\d{2}-\d{2}$', str(d)):
            raise ValueError(f"日期格式不符合 YYYY-MM-DD 约定: {d}")
```

### 禁止行为

```python
# ❌ 禁止：只在一条路径有防御检查
# 增量路径：有检查
def _incremental_update(...):
    for d in dates_to_check:
        if not re.match(r'^\d{4}-\d{2}-\d{2}$', str(d)):
            raise ValueError(...)

# 全量路径：无检查  # ✗ 防御不对称
def calculate_daily_ic_series(...):
    dates = [str(d) for d in ic_series.index]  # ✗ 直接使用，无检查

# ❌ 禁止：防御检查不一致
# 问题：
# - 某一条路径可能通过错误的格式
# - 增量路径报错，全量路径不报错
# - 导致下游问题
# - 维护者困惑：为什么只有一条路径报错？
```

### 为何必须保持防御对称

1. **一致性**：两条路径应有相同的防御机制
2. **可靠性**：避免某一条路径通过错误的格式
3. **可维护性**：维护者不会困惑为何只有一条路径报错
4. **避免下游问题**：错误的日期格式会导致 JSON 序列化失败、日期比较错误

### 适用范围

此规范适用于所有全量/增量路径：
1. **日期格式断言**：全量和增量路径都应检查
2. **数据类型校验**：全量和增量路径都应校验
3. **边界检查**：全量和增量路径都应检查
4. **任何防御性编程**

### 检查清单

```
□ 全量路径和增量路径都有日期格式断言
□ 防御检查在两条路径保持一致
□ 避免只在一条路径有防御
□ 两条路径都应验证数据格式
□ 保持防御对称，避免下游问题
```

---

## 可选字段回退逻辑规范

### 核心原则

**可选字段的回退逻辑必须依赖必需字段（已校验）。禁止在 required_fields 中包含可选字段，这会导致回退逻辑永远不会触发（矛盾设计）。**

### 问题背景

```
回退逻辑矛盾问题：

旧代码（错误）：
```python
# required_fields 包含可选字段
required_fields = [
    'ic_series', 'ic_mean', 'ic_std', 'icir', 'p_value', 'p_value_display',  # ✗ 矛盾
    ...
]

# 回退逻辑（永远不会触发）
'p_value_display': result.get('p_value_display', str(round(result['p_value'], 6)))
```

问题后果：
- required_fields 包含 'p_value_display'
- 缺少 'p_value_display' 时校验抛出 RuntimeError
- 回退逻辑永远不会触发
- 矛盾设计：既然校验会报错，为何还有回退逻辑？

依赖问题：
- 回退逻辑使用 result['p_value'] 作为回退值
- 如果同时缺少 'p_value_display' 和 'p_value'，回退逻辑抛出 KeyError
- 虽然 required_fields 包含 'p_value'，但如果不包含 'p_value_display'...
- 回退逻辑会因缺少 'p_value' 而抛出 KeyError
```

### 正确实现

```python
# ✓ 正确：区分必需字段和可选字段
# 核心原则：p_value 是必需字段（回退逻辑依赖），p_value_display 是可选字段（可从 p_value 计算）
required_fields = [
    'ic_series', 'ic_mean', 'ic_std', 'icir', 'p_value',  # p_value 必需
    'statistical_significance', 'factor_direction',
    'economic_significance', 'positive_ratio', 'summary'
]
# p_value_display 是可选字段，不校验（可从 p_value 计算回退值）

missing_fields = [f for f in required_fields if f not in result]
if missing_fields:
    raise RuntimeError(...)

# 回退逻辑（可靠依赖 p_value）
# p_value_display 回退逻辑说明（遵循 MODULE.md 可选字段回退逻辑规范）
# 核心原则：p_value_display 是可选字段，缺少时从 p_value 计算
# p_value 是必需字段（已校验），回退逻辑可靠
'p_value_display': result.get('p_value_display', str(round(result['p_value'], 6)))
```

### 禁止行为

```python
# ❌ 禁止：required_fields 包含可选字段
required_fields = [
    'ic_series', 'ic_mean', 'ic_std', 'icir', 'p_value', 'p_value_display',  # ✗ 矛盾
    ...
]

# ❌ 禁止：回退逻辑依赖未校验的字段
'p_value_display': result.get('p_value_display', str(round(result['p_value'], 6)))  # ✗ p_value 未校验？

# ❌ 禁止：矛盾设计
# 问题：
# - 既然校验会报错，为何还有回退逻辑？
# - 回退逻辑永远不会触发
# - 代码维护者困惑：为何有两种处理方式？
```

### 为何必须区分必需字段和可选字段

1. **消除矛盾**：required_fields 包含可选字段是矛盾设计
2. **回退逻辑有效**：可选字段缺少时，回退逻辑才会触发
3. **依赖可靠**：回退逻辑依赖必需字段（已校验），不会抛出 KeyError
4. **代码清晰**：维护者不会困惑为何有两种处理方式

### 适用范围

此规范适用于所有有回退逻辑的可选字段：
1. **p_value_display**：可选字段，可从 p_value 计算
2. **任何有回退逻辑的字段**：必需区分必需字段和可选字段
3. **字段校验逻辑**：required_fields 只包含必需字段
4. **回退逻辑设计**：依赖必需字段（已校验）

### 检查清单

```
□ 区分必需字段和可选字段
□ required_fields 只包含必需字段
□ 可选字段不在 required_fields 中
□ 回退逻辑依赖必需字段（已校验）
□ 回退逻辑不会因缺少依赖字段而抛出 KeyError
□ 注释说明可选字段的回退逻辑
```

---

**典型场景：**

| 场景 | 旧实现 | 新实现 | 清理要求 |
|------|-------|-------|---------|
| 性能优化 | 循环处理单股票 | 向量化处理多股票 | 删除循环版本函数 |
| 算法重构 | 单数据点函数 | 向量化版本 | 删除单数据点函数 |
| 公共函数复用 | 本地实现 | common/ 公共函数 | 删除本地实现 |

**正确示例：**
```python
# ✓ 正确：向量化版本替代循环版本后，删除旧函数

# 旧版本（删除）：
# def calculate_single_stock(stock_df): ...  # 已删除

# 新版本（保留）：
def calculate_all_stocks_vectorized(factor_df):
    return factor_df.groupby('asset').transform(...)
```

**禁止行为：**
```python
# ❌ 禁止：保留旧函数但从不调用（死代码）
def calculate_single_stock(stock_df):  # 死代码！
    """单股票版本，从未被调用"""
    return stock_df.rolling(20).mean()

def calculate_all_stocks_vectorized(factor_df):  # 实际使用
    """向量化版本"""
    return factor_df.groupby('asset').transform(...)

# calculate_single_stock 定义后从未被调用，是死代码
```

**为何必须清理死代码：**
1. 死代码误导读者：以为有两条实现路径可选
2. 死代码增加维护成本：修改逻辑时需同步多处
3. 死代码可能不一致：与新实现产生偏差
4. 代码审计浪费时间：分析死代码的用途

---

## 函数签名变更同步规范

**核心原则：** 返回值变更时必须同步更新类型注解和 docstring。

**正确示例：**
```python
def load_data_from_cache(...) -> Tuple[pd.DataFrame, pd.DataFrame, dict]:
    """
    Returns:
        factor_df: 过滤后的因子数据
        return_df: 过滤后的收益数据
        raw_metadata: 原始数据范围信息（新增）
    """
```

**禁止行为：**
- ❌ 只改返回值不改类型注解
- ❌ 只改返回值不改 docstring

---

## 参数类型约定规范

**核心原则：** output_file 统一转为 Path 对象。

**正确实现：**
```python
def generate_rsi_ic_data(output_file=None):
    if output_file is None:
        output_file = get_ic_output_path('rsi_1d')  # 返回 Path
    else:
        output_file = Path(output_file)  # str → Path
```

**为何必须统一类型：**
- Path 对象可安全使用 .parent.mkdir()
- str 对象需要额外处理
- 统一类型避免后续代码类型判断

---

## 统计显著性判断规范

**五维度判断（独立输出，不合并）：**

| 维度 | 判断规则 | 输出字段 |
|------|---------|---------|
| 维度1: 统计显著性 | p < 0.05（与 |t| > 1.96 等价） | is_significant, nw_lag |
| 维度2: 因子方向 | ic_mean 符号判断 | factor_direction |
| 维度3: 经济显著性 | |ic_mean| >= 0.05 → strong; >= 0.03 → weak | economic_significance |
| 维度4: ICIR稳定性 | ICIR >= 2.0 → excellent; >= 1.0 → good | icir_stability |
| 维度5: IC分布一致性 | positive_ratio 与 ic_mean_sign 匹配 | is_consistent, consistency_type |

---

## IC分布一致性判断边界规范

**判断规则（含优先级）：**

| 优先级 | 条件 | 输出 |
|-------|------|------|
| 1（最高） | ic_mean_sign = 'zero' | balanced |
| 2 | 正向因子 positive_ratio >= 50% | consistent |
| 2 | 反向因子 positive_ratio <= 50% | consistent |
| 3 | positive_ratio ∈ [49%, 51%]（闭区间） | balanced |
| 4 | 其他情况 | contradictory |

**边界示例：**
- 正向因子 49% → balanced（优先级3）
- 正向因子 50% → consistent（优先级2）
- 反向因子 50% → consistent（优先级2）
- 反向因子 51% → balanced（优先级3）

---

## 增量模式 period 语义规范

**核心原则：** period.start/end 必须基于原始缓存数据（dropna 前）。

**正确实现：**
```python
# 在 dropna 之前，先计算原始数据范围
raw_period_start = factor_df['date'].min()
raw_period_end = factor_df['date'].max()
raw_total_days = factor_df['date'].nunique()

# 然后 dropna
factor_df = factor_df.dropna()

# 返回过滤后的数据 + raw_metadata
return factor_df, return_df, {'period_start': raw_period_start, ...}
```

**为何必须使用原始数据：**
- dropna 可能过滤掉某些日期的全部股票
- factor_df['date'].min()/max() 计算的是过滤后的范围
- 与语义定义冲突："原始缓存覆盖范围" ≠ "过滤后的数据范围"

---

## 引用说明

本文档定义 factor_ic/ 目录下所有 IC 计算脚本的开发规范。

**相关文档：**
- 项目级规范：PROJECT.md（目录结构、开发检查清单）
- 流程文档：factor_ic/docs/ic_<因子名>_<周期>_flow.md
- 公共函数：factor_ic/common/ 模块

---

*最后更新: 2026-05-19*