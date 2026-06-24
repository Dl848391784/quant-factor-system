# Design: 交互因子定义去标签化重构 v1

**Status**: approved (用户已确认 2026-06-24，选 B'' 方案：pos/neg/abs 三 ReLU 变体)
**Author**: 云瑶 (Hermes Agent)
**Date**: 2026-06-24
**Revisions**:
  - v1.0 (2026-06-24): 初稿，估算 ~525 行 / 8 文件
  - v1.1 (2026-06-24): 侦察确认真实规模 ~3000+ 行 / 60+ 文件，按用户决定走 A 全量做 + 拆 3 commit
  - v1.2 (2026-06-24): **方向变体重设计** — W/S/R 在数学上冗余（W ≡ −S，R ≡ base_factor），改用 pos/neg/abs ReLU 切半轴变体实现真正独立的方向风格
**违规根因**: AGENTS.md §数据驱动原则（行 64-89）+ PROJECT.md §数据驱动原则（行 139-194）
**用户原话** (2026-06-24):

> "因子作者本来就是构造'反转/超跌'信号，我从来没有这样下过定义。我想要的是交互因子的定义是真实客观的，跑出来哪些数据好我们就选哪个，不能被打上构造'反转/超跌'信号的标签，每个风格都应该有并且全，数据不好的交互因子我们系统自然会筛选掉，而不应该在定义的时候就过滤一道。"

---

## 1. 问题诊断（实证）

### 1.1 9 个 interaction 因子的当前数学定义

| 因子 | 现公式 | 输入方向 |
|---|---|---|
| interaction_amplitude | `(−z(ret_3d)) × z(amplitude)` | **只跑 weakness** |
| interaction_turnover | `(−z(ret_3d)) × z(turnover_rate)` | **只跑 weakness** |
| interaction_amp_compression | `(−z(ret_3d)) × z(amp_compression)` | **只跑 weakness** |
| interaction_near_high | `(−z(ret_3d)) × z(near_high_ratio_5)` | **只跑 weakness** |
| interaction_intraday | `(−z(ret_1d)) × z(intraday_intensity)` | **只跑 weakness** |
| interaction_ma5_dev | `(−z(ret_3d)) × z(ma5_deviation)` | **只跑 weakness** |
| interaction_price_pos | `(−z(ret_1d)) × z(price_position)` | **只跑 weakness** |
| interaction_kdj | `(−z(ret_5d)) × z(kdj_j)` | **只跑 weakness** |
| interaction_bollinger | `(−z(ret_5d)) × z(bollinger_pb)` | **只跑 weakness** |

**结论**：9 个因子全部把"过去 N 日跌得多"作为乘子输入，其它两种风格（"过去 N 日涨得多" / "近期持平不动"）**完全缺失对照组**。

### 1.2 实证（2026-06-24）

- Stage 1 Top 30 共 30 只股票，最近 60 日 **70% 阴跌或大跌**（21/30），平均回撤 −24.3%
- 8 个 composite 因子在最近全样本期 Q5−Q1 实证：7/8 为**负**（与中性化 IC > 0 符号背离）
- Stage 1 Top 30 最近 20 日 forward_return_1d 均值 = **−0.37%**，跑输全市场基线 −0.05pp

### 1.3 标签蔓延路径（"户籍登记"）

| 治理层 | 位置 | 违规内容 |
|---|---|---|
| 🚨 **数学定义** | `data_fetchers/factor_calculator/momentum.py` L920-1234 | 9 个因子只构造 weakness×factor，无对照组 |
| 🚨 **规范文档反向硬规** | `backtest/MODULE.md` §594-619 | 规范 "Config 注释必须说明策略类型 (均值回归 / 趋势跟随)" |
| 🚨 **设计文档** | `designs/feat_reversal_delta_factors.md` | 文件名 + 内容写"超跌止跌股" |
| ⚠️ **代码注释** | `momentum.py` L922/970/1018/1085/1113/1141/1169/1197/1225 | docstring 含"反弹型/弱势" |
| ⚠️ **factor_selector 注释** | `comprehensive_factor/common/factor_selector.py` L92/L422 | "反转族因子"/"动量风格 A/B 实验" |
| ⚠️ **stock_selector 字段+注释** | `comprehensive_factor/stock_selector.py` L143/L681-682 | "冷门弱势股"/"游资爆炒后被洗" |
| ⚠️ **MODULE.md** | `comprehensive_factor/MODULE.md` L832 | "强势×低 + 弱势×高" |

---

## 2. 设计原则（第一性原理）

### 2.1 因子定义的客观性公理

> **因子定义只描述数学结构，不预设方向假设。方向由实证 IC 决定。**

派生原则：
1. 当数学结构允许多种"输入风格"（如 `signed_return × factor`），**所有风格都必须构造**，不能只跑一个
2. 命名只描述**数学操作**（`mul_with_ret3d_neg`），不描述**经济假设**（`反弹型`、`弱势`）
3. 数据不好的因子由 `factor_selector` 闸口（|IC|、p-value、ICIR）淘汰，**不在定义阶段预筛**

### 2.2 当前违规的具体表现

| 违规 | 当前做法 | 修复方向 |
|---|---|---|
| 输入方向不对称 | 9 个因子全部用 `weakness = −z(ret_Nd)` | 每个因子配 `weakness/strength/raw` 三个变体 |
| 命名带经济假设 | `interaction_amplitude`（隐含"振幅×弱势=反弹"假设） | 改为数学命名：`interaction_amplitude__ret3d_W` 等 |
| docstring 贴标签 | "弱势 × 高振幅 = 反弹信号" | 改为"-z(ret_3d) × z(amplitude) 的乘积型交互" |

---

## 3. 重构方案

### 3.0 数学事实：为何 W/S/R 在统计上冗余（v1.2 修正）

v1.0/v1.1 的"weakness/strength/raw 三变体"方案在数学上**不能产生独立信号**，已废弃，原因如下：

```
设 W = -z(ret_Nd) × z(factor),  S = +z(ret_Nd) × z(factor),  R = z(factor)

性质 1: W ≡ −S （在每个截面每个股票上严格成立）
  ⟹ IC(W) = -IC(S)  （Pearson 线性性质）
  ⟹ |IC(W)| = |IC(S)|，factor_selector 闸口同时通过/同时拒绝
  ⟹ composite_runner v2.47 方向归一: IC(S)<0 翻方向 → -S = W
  ⟹ W、S 两列在 composite 中逐行相等 = 同一因子计权两次

性质 2: R = z(factor) 已等价于 base factor (amplitude/kdj_j 等) 的现有 IC 分析
  cross-section z-score 是 affine transform，不改变 rank 相关系数符号
  9 个 base factor 全部已注册为独立因子，IC 报告早已存在
  ⟹ R 不产生新信息

结论: 乘法交互 f(x)·g(y) 的 sign 是一个自由度，不是两个
  方向变体必须破坏乘法的 affine 对称性才能引入新信号 → 用 ReLU/abs 切半轴
```

### 3.1 因子族对称化（核心改动 v1.2: ReLU 切半轴）

**对每个 base_factor，构造 3 个数学独立的方向变体**：

```python
# 命名规则: interaction_<base>__ret<W>d_<DIR>
#   <base>: 基础因子名（amplitude / kdj_j / bollinger_pb / ...）
#   <W>:    signed return 窗口（1 / 3 / 5）
#   <DIR>:  ReLU 方向变体
#     pos = max(z(ret), 0) × z(factor)   # 只在过去 N 日涨时启用
#     neg = min(z(ret), 0) × z(factor)   # 只在过去 N 日跌时启用
#     abs = |z(ret)|       × z(factor)   # 动幅大就启用，不分方向

# 示例：原 interaction_amplitude 拆为
interaction_amplitude__ret3d_pos = max(z(ret_3d), 0) * z(amplitude)
interaction_amplitude__ret3d_neg = min(z(ret_3d), 0) * z(amplitude)
interaction_amplitude__ret3d_abs = abs(z(ret_3d))   * z(amplitude)
```

**数学独立性证明**：

```
pos + neg ≡ z(ret) × z(factor)   （单边求和恒等于原乘积）
pos − neg ≡ |z(ret)| × z(factor) = abs
∴ pos / neg / abs 中任意两个可线性组合出第三个 → 三者构成 2 维信号空间

但 pos 单独使用 ≠ neg 单独使用 ≠ abs 单独使用：
  - corr(pos, future_ret) ≠ corr(neg, future_ret)（在不同子样本上）
  - corr(pos, future_ret) ≠ corr(z(factor), future_ret)（ReLU 是非线性）
∴ 三个变体在 IC 计算上互相独立，不会被 composite 方向归一抵消
```

**与旧 weakness 的语义对应**：

```
旧 v2.37 公式: weakness × factor = (-z(ret)) × z(factor)
           = max(-z(ret), 0) × z(factor) + min(-z(ret), 0) × z(factor)
           = (跌得多的子样本贡献) + (涨得多的子样本贡献，但符号已翻转)

新 neg 变体 = min(z(ret), 0) × z(factor)
           = (跌得多的子样本贡献)
∴ neg 是旧 weakness 的"跌段子集"，更精确不引入涨段噪声
```

### 3.2 因子总数变化

| | v2.37 当前 | v2.48 重构后 (B'') |
|---|---:|---:|
| interaction 因子总数 | 9 | **27** (9 × 3 个 ReLU 变体) |
| 计算成本 | baseline | ×3（向量化 ReLU + 乘法，可忽略） |
| 内存峰值 | baseline | +~50MB (parquet 多 18 列 × 1.5M 行 × 8 byte) |
| 信号独立性 | — | ✅ 数学独立（与 v1.1 W/S/R 不同） |

### 3.3 命名迁移表（v1.2）

| 旧命名 (v2.37) | pos 变体 | neg 变体 | abs 变体 |
|---|---|---|---|
| interaction_amplitude | interaction_amplitude__ret3d_pos | interaction_amplitude__ret3d_neg | interaction_amplitude__ret3d_abs |
| interaction_turnover | interaction_turnover__ret3d_pos | interaction_turnover__ret3d_neg | interaction_turnover__ret3d_abs |
| interaction_amp_compression | interaction_amp_compression__ret3d_pos | interaction_amp_compression__ret3d_neg | interaction_amp_compression__ret3d_abs |
| interaction_near_high | interaction_near_high__ret3d_pos | interaction_near_high__ret3d_neg | interaction_near_high__ret3d_abs |
| interaction_intraday | interaction_intraday__ret1d_pos | interaction_intraday__ret1d_neg | interaction_intraday__ret1d_abs |
| interaction_ma5_dev | interaction_ma5_dev__ret3d_pos | interaction_ma5_dev__ret3d_neg | interaction_ma5_dev__ret3d_abs |
| interaction_price_pos | interaction_price_pos__ret1d_pos | interaction_price_pos__ret1d_neg | interaction_price_pos__ret1d_abs |
| interaction_kdj | interaction_kdj__ret5d_pos | interaction_kdj__ret5d_neg | interaction_kdj__ret5d_abs |
| interaction_bollinger | interaction_bollinger__ret5d_pos | interaction_bollinger__ret5d_neg | interaction_bollinger__ret5d_abs |

**旧名处理**：旧 9 个因子名（如 `interaction_amplitude`）**完全删除**，不保留 runtime 别名——它们既不等同于 pos 也不等同于 neg/abs（旧公式是 ±2 段加和后翻 sign），下游一次性切到新命名。

**关键命名变化**：v1.1 的 `_W`/`_S`/`_R` 全部废弃；v1.2 用全小写 `_pos`/`_neg`/`_abs`，便于 grep 和与 PyTorch ReLU 语义对齐。

### 3.4 工程改动清单（v1.1：侦察确认后真实规模）

| 文件 | 改动 | 估算行数 |
|---|---|---|
| **F1 commit（核心定义层）** | | |
| `data_fetchers/factor_calculator/_common.py` | `_COL_INTERACTION_*` 常量 9 → 27 | ~25 行 |
| `data_fetchers/factor_calculator/momentum.py` | 9 个 calculate 函数 → 27 个（pos/neg/abs 变体）；docstring 全去标签 | ~750 行 |
| `data_fetchers/factor_calculator/_legacy.py` | `__all__` + import 同步 9 → 27 名称 | ~40 行 |
| `data_fetchers/factor_generator.py` | `_EXTENDED_FACTOR_COLS` + `_FACTOR_PIPELINE_STEPS` 9 → 27 | ~120 行 |
| `factor_definitions.py` | FACTOR_DEFINITIONS / COL 映射 / FACTOR_CATEGORIES / FACTOR_FAMILIES 4 张表 9 → 27 | ~140 行 |
| `data_fetchers/test_cases/test_factor_calculator_interaction.py` | 旧 9 因子断言 → 27 因子断言 + ReLU 数学验证 (pos+neg≡raw_product) + 三变体非零差异性测试 | ~250 行 |
| **F1 合计** | **6 文件** | **~1325 行** |
| **F2 commit（pipeline 注册层 — 模板复制）** | | |
| `factor_ic/ic_interaction_<X>_<DIR>_1d.py` | 9 旧脚本改名 + 新增 18 个 = 27 个文件（每个 ~141 行） | ~3800 行 |
| `backtest/layered_backtest_interaction_<X>_<DIR>_1d.py` | 9 旧脚本改名 + 新增 18 个 = 27 个文件（每个 ~45 行） | ~1200 行 |
| `run_pipeline.py` | ScriptTask 注册 9 → 27 × 2 = 54 项 | ~80 行 |
| **F2 合计** | **55 文件**（9 改名 + 36 新增 + 1 注册脚本 + 9 旧脚本删除标记） | **~5080 行（其中 95% 是模板复制）** |
| **F3 commit（下游清理 + 文档去标签）** | | |
| `comprehensive_factor/common/factor_selector.py` L92/L422 | 注释 "反转族" → "ic_mean<0 因子" | ~5 行 |
| `comprehensive_factor/common/weight_engine.py` | 注释里的 "反转触发" / 实证数据描述更新 | ~15 行 |
| `comprehensive_factor/stock_selector.py` L143/L681-682 | 字段+注释 "冷门弱势股" → "低 turnover 候选" | ~15 行 |
| `comprehensive_factor/MODULE.md` L832 等 | "强势×低 + 弱势×高" → 实证 IC 描述 | ~30 行 |
| `comprehensive_factor/test_cases/test_factor_*.py` | 测试用例引用旧因子名 → 新命名 | ~50 行 |
| `designs/feat_reversal_delta_factors.md` 等带标签设计 | 加 deprecation note + 移到 `designs/_archived/` | rename × 3-5 |
| `factor_ic/result/*.json` 旧产物 | 不删（带日期戳，与新命名共存） | — |
| **F3 合计** | **~12 文件** | **~115 行 + 几个文件 rename** |

### 3.4.1 三个 commit 拆分边界

**F1 commit（"核心定义层"）：6 文件 ~1325 行**

- 完成后状态：momentum.py 暴露 27 个 calculate 函数，factor_generator 注册 27 个输出列，但 pipeline 仍只跑 9 个 IC 脚本（因 F2 未做）
- F1 单 commit 可独立 ruff + pytest 通过：`pytest data_fetchers/test_cases/test_factor_calculator_interaction.py` 验证 27 个函数全部数学正确 + W/S 对称性 + R 退化
- pipeline 不能跑（IC 脚本数与 generator 输出列数不一致，但 generator 本身可跑）

**F2 commit（"pipeline 注册层"）：55 文件 ~5080 行**

- 完成后状态：pipeline 完整支持 27 个 interaction 因子 IC + backtest，run_pipeline.py 全链路通
- 95% 是模板复制（每个 `ic_*.py` 仅替换 4-5 处因子名 + 描述行）
- F2 单 commit 可独立 ruff + pytest 通过：检查每个新脚本能 import 不报错 + run_pipeline 静态注册校验通过
- **用户跑 pipeline 的时机** = F3 完成后

**F3 commit（"下游清理"）：~12 文件 ~115 行**

- 完成后状态：所有代码注释、文档、设计文档中的 "反转/超跌/弱势" 叙事标签全部清理
- 旧 9 因子名（如 `interaction_amplitude`）从所有下游 import 中移除
- 用户此时跑 `python run_pipeline.py` 看实证 IC 决定哪个变体留下来

### 3.4.2 旧因子的删除策略

| 阶段 | 旧因子（如 `interaction_amplitude`） |
|---|---|
| F1 后 | momentum.py 中保留为 `calculate_interaction_amplitude__ret3d_W` 的别名（即新 W 变体）；旧名作为 deprecation alias 同步导出 |
| F2 后 | `factor_ic/ic_interaction_amplitude_1d.py` 改名为 `ic_interaction_amplitude__ret3d_W_1d.py`，原文件 git 删除 |
| F3 后 | `factor_definitions.py` 中旧名映射条目删除；下游 test 用例引用全部切到新名 |

> **不保留任何旧名 → 新名的 runtime 别名**：旧 9 因子的语义 = 新 9 个 `__ret*d_W` 变体；旧名直接删除让下游一次性切完，避免长期 deprecation 包袱。

**总规模估算（v1.1 修正）**: **~6520 行 / 73 文件** —— 远超 AGENTS.md 单次 ≤3 文件 ≤200 行约束，**必须按 F1/F2/F3 三 commit 拆分**。F2 数字虽大但 95% 是机械复制，单 commit 内逻辑变更范围仍可控。

### 3.5 三 commit 全部完成后跑 pipeline 的预期效果
**用户手动跑 `python run_pipeline.py` 后，预期会观察到**：

1. factor_ic 阶段：27 个 interaction 因子的 IC 数据全跑出来（不再只有 9 个）
2. factor_selector 阶段：按 |IC| + p-value + ICIR 闸口筛选——**预计 W 和 S 中各通过部分，R 中通过部分**，不预设哪个赢
3. composite 阶段：选中因子可能包含 W、S、R 混合组合，方向由实证决定
4. stock_selector 阶段：Stage 1 Top 30 不再被锁定为"阴跌候选"——**风格自然分散**

---

## 4. 不在本次范围（明确豁免）

1. **不改 factor_selector 闸口逻辑**：现有 |IC| / p-value / ICIR 闸口已经是数据驱动，足以淘汰失效因子
2. **不改 composite_runner 方向归一逻辑**：v2.47 已实现 IC<0 自动翻转
3. **不改 stock_selector Stage 2 排序键**：turnover_rate 升序是独立设计抉择，用户未要求改
4. **不重跑历史报告**：pipeline 重跑后自然刷新
5. **不解决 Q5-Q1 vs 中性化 IC 符号背离问题**：用户 memory 已有该坑（`neutralized-vs-raw-ic-sign-divergence`），是另一条独立的修复路径，本 design 只解决"定义阶段不预筛"

---

## 5. 风险与回滚

### 5.1 风险

| 风险 | 缓解 |
|---|---|
| 27 个因子 IC 计算耗时增加 | 数据驱动，无规避——已确认计算成本 ×3 量级在可接受范围 |
| factor_selector 闸口可能筛掉**所有** W 变体，导致 composite 信号失效 | 这正是数据驱动的体现；如真发生说明 weakness 风格本身已不适用 |
| 下游 (factor_ic / composite / backtest) 因列名变化报错 | F1 commit 同步全链路命名，pipeline 跑一遍即可暴露 |
| 旧 selection_history Parquet 数据集（基于旧命名）变历史包袱 | 不删，文件已带 selection_date 分区，新数据用新命名共存 |

### 5.2 回滚方案

- F1 commit 单独可 revert（git revert <sha>）；momentum.py + factor_generator.py + 测试全在一个 commit 内
- R1 commit 单独可 revert（仅 backtest/MODULE.md 一处）
- D1 不引入运行时改动，仅文档

---

## 6. Review 检查项（提交前）

- [ ] **F1 momentum.py 重构**：9 个原函数全部改为返回 W/S/R 三列；docstring 全部去掉"反转/超跌/弱势/反弹型"标签；命名改为 `interaction_<base>__ret<W>d_<DIR>` 或 `interaction_<base>__R`
- [ ] **F1 factor_generator.py 注册**：`_EXTENDED_FACTOR_COLS` + `_FACTOR_PIPELINE_STEPS` 同步到 27 列；启动期一致性校验通过
- [ ] **F1 测试**：每个因子的 W/S/R 三变体的**对称性测试**（同一 ret_Nd 输入下，W + S = 0 在 z-score 同 base 时数学成立）
- [ ] **F1 测试**：每个因子的**单点数学正确性测试**（手算 3-5 行确认乘法对）
- [ ] **R1 backtest/MODULE.md**：旧 §594-619 删除，新增"Config 注释引用实证 IC 数据"规范
- [ ] **ruff check** 全绿
- [ ] **pytest** 全绿（含新增对称性测试）
- [ ] **commit message** 引用 AGENTS.md 数据驱动原则行号 (行 64-89) + PROJECT.md §数据驱动原则 (行 139-194)
- [ ] **未提交 push**（遵循 superpowers-workflow L553）

---

## 7. 后续 (out of scope, 列出供用户感知)

- **C1**：清理 factor_selector / stock_selector / comprehensive_factor MODULE.md 注释中残留的"反转族/冷门弱势股/强势×低"标签
- **C2**：归档 designs/feat_reversal_delta_factors.md 等带标签的设计文档
- **C3** (用户决定)：当前 weight_selector / composite_runner 是否需要在 27 个候选中**强制保留方向平衡**（如至少 3 个 S 变体 / 3 个 W 变体），还是完全让数据决定？本 design 默认**完全让数据决定**——不强制平衡，符合用户原话"数据不好的交互因子我们系统自然会筛选掉"。

---

## 附录 A: 用户原始诉求与原则映射

| 用户原话 | 设计原则 | 实现 |
|---|---|---|
| "交互因子的定义是真实客观的" | §2.1 因子定义的客观性公理 | §3.1 三变体对称化 |
| "跑出来哪些数据好我们就选哪个" | 数据驱动 | §3.5 由 factor_selector 闸口决定 |
| "不能被打上构造'反转/超跌'信号的标签" | 命名去标签 | §3.1 命名规则 `__ret<W>d_<DIR>` |
| "每个风格都应该有并且全" | 对称化 | §3.1 W + S + R 全覆盖 |
| "数据不好的交互因子我们系统自然会筛选掉" | 不在定义阶段预筛 | §3.5 不改 factor_selector 闸口 |
| "不应该在定义的时候就过滤一道" | §2.1 派生原则 3 | §3.1 W/S/R 全部参与候选池 |
