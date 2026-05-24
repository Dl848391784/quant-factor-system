# data_fetchers 模块规范

> 本文档定义 data_fetchers/ 目录下数据拉取和因子生成脚本的开发规范。
> 创建时间: 2026-05-19
> 更新时间: 2026-05-24
> 版本: v1.0

---

## 概述

data_fetchers 模块负责：
1. 从外部数据源拉取因子数据、收益数据等
2. 统一因子生成（新增）
3. 存储到 cache 目录

**模块定位：**
- 输入：外部数据源（API、数据库等）+ 基础因子数据
- 输出：cache/factor_data/ 缓存文件

---

## 数据流程

```
外部数据源 → data_fetchers/ → cache/factor_data/ → factor_ic/
                   ↑
                   │
           factor_generator.py（统一因子生成）
```

**关键原则：**
- factor_ic 不自行拉取数据，只使用 cache
- data_fetchers 负责数据质量和格式转换
- **factor_generator.py 作为单一因子数据源（2026-05-24 新增）**

---

## 统一因子生成模块

### factor_generator.py

**职责：** 生成所有因子数据到缓存，提供单一数据源。

**位置：** `data_fetchers/factor_generator.py`

**输出：** `cache/factor_data/factor_data_extended.json.gz`

### 支持的因子

| 因子 | 列名 | 参数 | 数据依赖 |
|------|------|------|---------|
| RSI | rsi_6 | period=6 | close |
| Volume_Ratio | volume_ratio_5 | window=5 | volume |
| Bollinger_PB | bollinger_pb | n=20, k=2.0 | close |
| KDJ_J | kdj_j | n=9, m1=3, m2=3 | close, high, low |
| Turnover_Surge | turnover_surge | window=5 | turnover_rate, close |

### 输出结构

```json
{
  "dates": ["2024-04-19", "2024-04-20", ...],
  "data": [
    {
      "date": "2024-04-19",
      "asset": "000001",
      "open": 10.71,
      "close": 10.69,
      "high": 10.82,
      "low": 10.66,
      "rsi_6": 64.42,
      "volume_ratio_5": 0.74,
      "bollinger_pb": null,
      "kdj_j": null,
      "turnover_surge": null
    },
    ...
  ]
}
```

### 使用方式

**CLI：**
```bash
python data_fetchers/factor_generator.py
```

**Python：**
```python
from data_fetchers.factor_generator import generate_all_factors

metadata = generate_all_factors(
    verbose=True  # 打印进度
)
```

### 数据一致性验证

factor_generator.py 的因子计算逻辑从 IC 脚本迁移：
- `calculate_bollinger_pb()` ← `ic_bollinger_pb_1d.py`
- `calculate_kdj_j()` ← `ic_kdj_j_1d.py`
- `calculate_turnover_surge()` ← `ic_turnover_surge_1d.py`

**验证结果（2026-05-24）：**
- 均值差异 < 0.000001
- 有效数据数一致
- 因子计算逻辑完全一致

---

## 缓存格式

### factor_data.json.gz（基础因子）

**结构：**
```json
{
  "dates": ["2024-04-19", ...],
  "data": [
    {
      "date": "2024-04-19",
      "asset": "000001",
      "open": 10.71,
      "close": 10.69,
      "high": 10.82,
      "low": 10.66,
      "rsi_6": 64.42,
      "volume_ratio_5": 0.74
    },
    ...
  ]
}
```

### factor_data_extended.json.gz（扩展因子）

包含所有 5 个因子（见上方输出结构）。

### turnover_rate_data.json.gz

**结构：**
```json
{
  "data": [
    {
      "date": "2024-03-19",
      "asset": "000001",
      "turnover_rate": 0.6664
    },
    ...
  ]
}
```

---

## 因子计算参数规范

### 参数默认值

| 因子 | 参数 | 默认值 | 说明 |
|------|------|--------|------|
| RSI | period | 6 | RSI 计算周期 |
| Volume_Ratio | window | 5 | 成交量均值窗口 |
| Bollinger_PB | n | 20 | 移动平均周期 |
| Bollinger_PB | k | 2.0 | 标差倍数 |
| KDJ_J | n | 9 | RSV 计算周期 |
| KDJ_J | m1 | 3 | K 值平滑周期 |
| KDJ_J | m2 | 3 | D 值平滑周期 |
| Turnover_Surge | window | 5 | 换手率均值窗口 |

### 计算规范

**遵循 PROJECT.md 规范：**
- 函数入口必须 `.copy()` 避免副作用
- 使用 `transform` 方法避免 pandas 3.0 索引问题
- 异常检测而非静默修正
- 使用 EPSILON 避免除零

---

## pandas 3.0 兼容性规范（2026-05-24 新增）

**问题：**
```python
# ❌ 错误：pandas 3.0 返回 MultiIndex Series
middle = factor_df.groupby('asset', group_keys=False)['close'].rolling(window=n).mean()
factor_df['middle'] = middle  # TypeError: incompatible index
```

**解决方案：**
```python
# ✓ 正确：使用 transform 返回 RangeIndex Series
middle = factor_df.groupby('asset', group_keys=False)['close'].transform(
    lambda x: x.rolling(window=n).mean()
)
factor_df['middle'] = middle  # 成功赋值
```

**原因：**
- pandas 3.0 中，`groupby(group_keys=False).rolling()` 返回 MultiIndex Series
- 即使 `group_keys=False`，索引仍是 MultiIndex
- `transform` 返回与原 DataFrame 一致的 RangeIndex

---

## 模块边界规范

**遵循 PROJECT.md 模块边界规范：**

```
✓ factor_generator.py 独立运行（不依赖 factor_ic、backtest）
✓ 输出到 cache/factor_data/
✓ 被 factor_ic 模块读取
```

**禁止：**
```
❌ factor_generator.py 导入 factor_ic.common.*
❌ factor_generator.py 导入 backtest.common.*
```

---

## 待补充内容

```
□ 数据拉取脚本规范（real_data_loader.py 迁移到 data_fetchers/）
□ 增量更新策略
□ 数据质量检查自动化
□ 因子计算性能优化（大数据量测试）
```

---

*最后更新: 2026-05-24 15:22*