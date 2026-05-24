# 实现计划：统一因子生成模块

## 任务目标

将 bollinger_pb、kdj_j、turnover_surge 三个因子的计算逻辑从 IC 脚本迁移到统一因子生成模块，使得所有因子数据都能通过单一数据源生成到缓存中。

---

## 背景

**现状问题**：
- `real_data_loader.py` 只计算 RSI + Volume_Ratio
- `ic_bollinger_pb_1d.py`, `ic_kdj_j_1d.py`, `ic_turnover_surge_1d.py` 各自计算因子但不保存到缓存
- 综合因子模块无法使用这三个因子（缓存中缺失）

**目标架构**：
```
data_fetchers/factor_generator.py  → cache/factor_data/  → factor_ic/ic_xxx.py
    (统一因子计算)                    (单一数据源)           (读取缓存)
```

---

## 任务拆分（Bite-sized Tasks）

### Task 1: 创建因子生成模块骨架（2分钟）

**文件**: `data_fetchers/factor_generator.py`

**操作**:
- 新建文件，定义 FactorGenerator 类
- 从 real_data_loader.py 复制 RSI/Volume_Ratio 计算逻辑

**验证**: `python -c "from data_fetchers.factor_generator import FactorGenerator"`

---

### Task 2: 迁移 bollinger_pb 计算逻辑（5分钟）

**来源**: `factor_ic/ic_bollinger_pb_1d.py` 的 `calculate_bollinger_pb()`

**操作**:
- 复制 calculate_bollinger_pb() 到 factor_generator.py
- 调整参数：接收 factor_df（面板数据长格式）
- 保持函数签名一致

**验证**: 对比新旧函数输出

---

### Task 3: 迁移 kdj_j 计算逻辑（5分钟）

**来源**: `factor_ic/ic_kdj_j_1d.py` 的 `calculate_kdj_j()` 和 `_calculate_ewm_with_initial()`

**操作**:
- 复制 calculate_kdj_j() 和辅助函数到 factor_generator.py
- 保持 Wilder 平滑逻辑（ewm 向量化）

**验证**: 对比新旧函数输出

---

### Task 4: 迁移 turnover_surge 计算逻辑（5分钟）

**来源**: `factor_ic/ic_turnover_surge_1d.py` 的 `calculate_turnover_surge()`

**操作**:
- 复制 calculate_turnover_surge() 到 factor_generator.py
- 注意数据依赖：需要 turnover_rate 列

**验证**: 对比新旧函数输出

---

### Task 5: 整合因子生成入口函数（3分钟）

**操作**:
- 创建 `generate_all_factors()` 函数
- 按顺序调用各因子计算函数
- 输出到统一缓存结构

**输出字段**:
```
date, asset, open, close, high, low
rsi_6, volume_ratio_5, bollinger_pb_20, kdj_j_9, turnover_surge_5
```

---

### Task 6: 数据一致性验证（5分钟）

**验证方式**:
1. 用新模块生成因子数据
2. 用 IC 脚本计算因子数据（现有逻辑）
3. 对比两者输出是否一致

**对比项**:
- 因子值均值、标准差、极值
- NaN 比例
- 相关系数（理论上应为 1.0）

---

### Task 7: 更新缓存生成脚本（2分钟）

**操作**:
- 修改 `regenerate_cache_real.py` 调用新模块
- 或新建 `data_fetchers/regenerate_factor_cache.py`

---

### Task 8: 更新 MODULE.md 规范（3分钟）

**操作**:
- 更新 `data_fetchers/MODULE.md` 定义因子生成规范
- 定义输出缓存结构
- 定义因子计算参数默认值

---

## 关键决策

### 决策1: factor_generator.py 放在哪里？

**用户指定**: `data_fetchers/` 目录

**理由**: 符合 PROJECT.md 模块依赖关系
```
data_fetchers → cache → factor_ic
```

### 决策2: 是否保留 IC 脚本中的因子计算函数？

**保留但标记为 deprecated**

**理由**:
- IC 脚本仍需要因子计算函数用于增量模式
- 标记为 deprecated 提示未来迁移
- 新脚本应从缓存读取而非自己计算

### 决策3: 因子列名规范

**格式**: `<因子名>_<参数>`

| 因子 | 列名 | 参数 |
|------|------|------|
| RSI | rsi_6 | period=6 |
| Volume_Ratio | volume_ratio_5 | window=5 |
| Bollinger_PB | bollinger_pb_20 | n=20 |
| KDJ_J | kdj_j_9 | n=9 |
| Turnover_Surge | turnover_surge_5 | window=5 |

---

## 数据依赖分析

| 因子 | 需要的输入列 | 是否已在缓存 |
|------|-------------|-------------|
| RSI | close | ✓ |
| Volume_Ratio | volume | ✓ |
| Bollinger_PB | close | ✓ |
| KDJ_J | close, high, low | ✓ |
| Turnover_Surge | turnover_rate | ❌ |

**问题**: turnover_rate 列不在缓存中

**解决方案**: 需要在数据拉取阶段添加 turnover_rate 列

---

## 验证检查清单

```
□ 新模块因子计算结果与 IC 脚本一致
□ 缓存包含所有 5 个因子列
□ IC 脚本能正确读取新缓存
□ 综合因子能使用所有 5 个因子
□ MODULE.md 规范已更新
□ 流程文档已创建
```

---

## 风险点

1. **turnover_rate 缺失**: 需要在数据拉取阶段补充
2. **内存开销**: 5 个因子列增加缓存大小，需考虑压缩
3. **性能**: 向量化计算需要验证大数据量下的执行时间

---

*创建时间: 2026-05-24*
*作者: 云瑶*