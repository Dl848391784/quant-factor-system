# 因子IC脚本抽象重构计划

> 创建时间: 2026-05-22 08:30
> 版本: v1.0
> 目标: 降低新增因子脚本的开发成本，从 ~700-1100行 降至 ~50-200行

---

## 一、背景与目标

### 问题分析

当前5个因子IC脚本存在大量重复代码：

| 脚本 | 行数 | 重复代码占比 | 核心逻辑 |
|------|------|-------------|----------|
| ic_rsi_1d.py | ~774 | ~65% | 直接用缓存列 |
| ic_kdj_j_1d.py | ~882 | ~45% | KDJ计算 |
| ic_bollinger_pb_1d.py | ~1129 | ~55% | 布林带计算 |
| ic_volume_ratio_1d.py | ~686 | ~70% | 直接用缓存列 |
| ic_turnover_surge_1d.py | ~798 | ~55% | 换手率突增计算 |

### 目标

新增因子脚本只需实现**因子计算逻辑**，其他部分复用公共模块：
- 新脚本代码量：**~50-200行**
- 开发时间：从数小时降至**15-30分钟**

---

## 二、抽象方案

### 新增公共模块（4个）

| 模块 | 功能 | 每脚本减少行数 | 实现复杂度 | 优先级 |
|------|------|----------------|------------|--------|
| `data_loader.py` | 数据加载（gzip解压、日期转换、列验证） | ~80-120行 | 低 | **P0** |
| `ic_result_builder.py` | IC结果构建（统一输出结构） | ~60-100行 | 低 | **P1** |
| `incremental_engine.py` | 增量更新引擎 | ~150-200行 | 中 | P2 |
| `factor_ic_runner.py` | 主入口模板 | ~100-150行 | 中 | P2 |

### 现有公共模块（保留）

- `ic_calculator.py` — IC计算核心（五维度判断、Newey-West）
- `convert_types.py` — 类型转换
- `data_completeness.py` — 数据完整性检查 + 输出路径
- `reverse_rank_ic.py` — 反向排名IC

---

## 三、实施步骤（Bite-sized Tasks）

### Phase 1: data_loader.py（P0，最高优先级）

**Task 1.1:** 创建 `common/data_loader.py` 模块文件
- 文件路径: `factor_ic/common/data_loader.py`
- 预估时间: 2分钟

**Task 1.2:** 实现 `load_factor_return_data()` 函数
- 输入: `factor_cols`, `return_col`, `dropna_cols`
- 输出: `(factor_df, return_df, raw_metadata)`
- 预估时间: 5分钟

**Task 1.3:** 实现日期转换和校验逻辑
- `pd.to_datetime()` + `strftime('%Y-%m-%d')`
- NaT检查 + 无效样本显示
- 预估时间: 3分钟

**Task 1.4:** 实现列存在检查
- KeyError + 显示可用列列表
- 预估时间: 2分钟

**Task 1.5:** 实现日期对齐验证（可选）
- 因子日期 vs 收益日期对齐检查
- 预估时间: 2分钟

**Task 1.6:** 验证 data_loader.py
- 运行 ic_rsi_1d.py 测试（修改导入）
- 检查输出数据结构
- 预估时间: 5分钟

**Task 1.7:** 更新 MODULE.md
- 添加"数据加载公共模块"章节
- 说明函数签名和用法
- 预估时间: 3分钟

---

### Phase 2: ic_result_builder.py（P1）

**Task 2.1:** 创建 `common/ic_result_builder.py` 模块文件
- 预估时间: 2分钟

**Task 2.2:** 实现 `build_ic_result()` 函数
- 输入: `ic_result`（来自 ic_calculator）
- 输出: 符合 PROJECT.md 规范的完整JSON结构
- 预估时间: 5分钟

**Task 2.3:** 实现 rolling_ic_mean 计算
- 20日窗口 + min_periods=10
- NaN → None 转换
- 预估时间: 3分钟

**Task 2.4:** 实现 sample_stats 构建
- total_days, valid_days, avg_stocks_per_day
- avg_stocks_period（口径范围）
- 预估时间: 2分钟

**Task 2.5:** 验证 ic_result_builder.py
- 运行 ic_rsi_1d.py 测试（组合使用 data_loader + ic_result_builder）
- 预估时间: 5分钟

**Task 2.6:** 更新 MODULE.md
- 添加"IC结果构建公共模块"章节
- 预估时间: 3分钟

---

### Phase 3: incremental_engine.py + factor_ic_runner.py（P2）

**Task 3.1:** 创建 `common/incremental_engine.py`
- 实现 `incremental_update_ic()` 函数
- 预估时间: 10分钟

**Task 3.2:** 创建 `common/factor_ic_runner.py`
- 实现 `run_factor_ic_analysis()` 主入口
- 预估时间: 10分钟

**Task 3.3:** 验证完整流程
- 用 ic_rsi_1d.py 作为测试脚本
- 测试全量模式和增量模式
- 预估时间: 10分钟

**Task 3.4:** 更新 MODULE.md
- 添加完整抽象架构章节
- 预估时间: 5分钟

---

### Phase 4: 迁移现有脚本（P3）

按优先级迁移，每次迁移一个脚本：

| 脚本 | 迁移难度 | 预估时间 |
|------|---------|----------|
| ic_rsi_1d.py | 低（直接用缓存列） | 15分钟 |
| ic_volume_ratio_1d.py | 低（直接用缓存列） | 15分钟 |
| ic_turnover_surge_1d.py | 中（需换手率计算） | 20分钟 |
| ic_bollinger_pb_1d.py | 中（需布林带计算） | 20分钟 |
| ic_kdj_j_1d.py | 高（KDJ复杂） | 30分钟 |

---

## 四、MODULE.md 更新要点

### 新增章节位置

在"一、概述与基础"章节下新增：

```
## 公共模块架构（2026-05-22新增）

### 数据加载公共模块
### IC结果构建公共模块  
### 增量更新引擎
### 主入口模板
```

### 规范内容

1. 函数签名和参数说明
2. 使用示例代码
3. 与现有脚本的对比
4. 新增因子的开发流程

---

## 五、验证标准

### Spec Compliance 检查

```
□ 新模块函数签名正确
□ 输出结构与 MODULE.md 定义一致
□ 测试脚本运行成功（ic_rsi_1d.py）
□ MODULE.md 同步更新
□ git commit（不 push）
```

---

## 六、风险控制

### 分步执行策略

每次只做一个小修改，避免大任务返回空：
- 先创建模块文件（空框架）
- 再逐个添加函数
- 每步验证后再继续

### Git 安全流程

- 每个模块完成后立即 commit
- MODULE.md 更新后 commit
- 不 push（用户偏好）

---

## 七、后续改进

完成抽象后：
1. 新增因子只需 ~50行代码
2. 开发流程文档化
3. 测试用例模板化

---

*计划结束，开始执行 Phase 1: data_loader.py*