# 策略系统性改造 Design Document

> **日期**: 2026-06-21
> **触发**: H8 Design-First（涉及 8+ 文件，>200 行）
> **规范引用**: H5(因子方向), H8(Design-First), H9(任务粒度), H13(死代码禁止)

---

## 1. 背景与问题概述

### 1.1 改造动因

当前选股结果选出短期内持续阴跌的股票（Top3 中 603229 连续阴跌 20 天），选股结果在做因子维度分组前后无变化。经按 PROJECT.md + MODULE.md + codegraph 完整排查，发现 19 个结构性问题，归纳为 6 个改造层。

### 1.2 问题清单 → 改造层映射

| # | 问题 | 数据证据 | 改造层 |
|---|------|---------|--------|
| 1 | 4个尾盘因子买入层年化 -57%~-117% | tail_volume_acceleration L1=-117% | P1 |
| 2 | 34因子全部未通过M12门槛，靠豁免选9个 | 0/34直接通过 | P1 |
| 3 | 豁免让有毒因子(L1<0)和有效因子同等加权 | 4有毒+5有效混合 | P1 |
| 4 | min_sample_days=30，24天短样本通过豁免 | tail_*仅24天有效 | P1 |
| 5 | M12 long_short_return_annual基于多空收益 | 对只做多无意义 | P1 |
| 6 | industry维度6因子L1全正(+9%~+12%)全被淘汰 | IC<0.03门槛 | P1 |
| 7 | 维度权重只在rolling_icir(1/4方法)实现 | weight_engine.py:905 else分支不传参 | P2 |
| 8 | run_pipeline只给rolling_icir配--dimension_weight | 其他3个ScriptTask无此参数 | P2 |
| 9 | M58规范要求WeightEngine通用，非特定方法 | MODULE.md L1966 | P2 |
| 10 | weight_selector 9指标中4个多空/空头指标 | weight_selector.py:93-134 | P3 |
| 11 | Min-Max归一化放大效应(0.986 vs 0.34) | raw值差距仅2pp | P3 |
| 12 | "只做多"约束在PROJECT.md/MODULE.md零记录 | grep零命中 | P4 |
| 13 | 因子池全量"跌了多少"，缺"是否企稳"信号 | 0个趋势变化因子 | P5 |
| 14 | 无量价背离/缩量止跌信号 | 0个量价背离因子 | P5 |
| 15 | 不同功能因子按\|ICIR\|平等加权 | 反转vs确认无区分 | P6 |
| 16 | 确认信号因子IC低→ICIR加权给0权重 | 等于没补 | P6 |
| 17 | 基本面因子作为独立因子IC低被淘汰 | 但作为过滤器有价值 | P6 |
| 18 | 4种方法对比不公平(rolling_icir独享维度权重) | 得分0.986 vs 0.34 | P2+P3 |
| 19 | tail_behavior维度5因子L1全负，1个通过豁免入选 | tail_volume_acceleration | P1 |

### 1.3 公理推导（第一性原理）

**公理1**：只做多策略收益 = Layer1 买入层收益。不能做空 Layer5。
→ 推论1：因子价值由 L1 绝对收益决定，不由多空收益(L1-L5)决定。

**公理2**：IC(Spearman秩相关)测量全截面单调性，不测量 L1 端绝对收益。
→ 推论2：|IC|≥0.03 系统性偏好"两端极端"因子，而非"L1稳定正收益"因子。

**公理3**：维度权重(因子间分配)与加权方式(是否滚动)是正交设计。
→ 推论3：M58要求WeightEngine通用，耦合在rolling_icir中是架构缺陷。

**公理4**：反转策略需要"状态"+"状态变化"两个信号。
→ 推论4：只有"跌了多少"无"是否企稳"，无法区分错杀vs基本面恶化。

---

## 2. 决策矩阵

### 2.1 P1: M12 筛选门槛对齐只做多

**来源**: 问题 #1-#6, #19; 公理1-2; M12(MODULE.md L580-597)

**决策点1: L1 绝对收益约束**

| 方案 | 内容 | 优点 | 缺点 |
|------|------|------|------|
| A: L1年化>0 硬约束(不可豁免) | 直接淘汰有毒因子 | 简单、安全、第一性 | 无 |
| B: L1年化>0 可豁免(回测强劲时) | 保留灵活性 | 有毒因子可能通过豁免 | **违反公理1** |

**决策**: 方案A。L1年化>0 是公理1的数学定义，不是可调阈值，不可豁免。

**决策点2: M12 的 long_short_return_annual 指标**

| 方案 | 内容 | 优点 | 缺点 |
|------|------|------|------|
| A: 替换为 long_return_annual(多头年化) | 对齐只做多 | 语义正确 | 需同步改weight_selector |
| B: 保留多空+新增多头双指标 | 兼容 | 多空指标对只做多无意义 | **违反公理1** |

**决策**: 方案A。多空收益对只做多无意义，替换而非叠加。

**决策点3: min_sample_days 阈值**

| 方案 | 阈值 | 统计依据 |
|------|------|---------|
| A: 60天 | ICIR的t检验: t=ICIR×√N, N=60时 t=0.15×√60=1.16 | 边际显著 |
| B: 90天 | t=0.15×√90=1.42 | 更严格但损失数据 |

**决策**: 方案A。60天≈3个月交易日，统计学大样本近似最低门槛。24天样本 t=0.73 不显著。

**决策点4: IC 门槛调整**

| 方案 | IC门槛 | 理由 |
|------|--------|------|
| A: 保持\|IC\|≥0.03 + L1>0约束兜底 | L1约束已排除有毒因子 | 门槛不变，约束补位 |
| B: 放宽至\|IC\|≥0.02 + L1>0约束 | 让industry因子入选 | 放宽可能引入噪声 |

**决策**: 方案A。L1>0 约束已解决"高IC但L1负"的有毒因子问题，IC门槛保持0.03。industry维度L1全正但IC<0.03，它们在P6过滤器角色中有价值，不需要强行作为主信号入选。

---

### 2.2 P2: 维度权重全方法支持

**来源**: 问题 #7-#9, #18; 公理3; M58(MODULE.md L1966-2017)

**决策点1: _apply_dimension_weights 提取位置**

| 方案 | 内容 | 优点 | 缺点 |
|------|------|------|------|
| A: 提到 WeightMethodBase | 所有方法继承复用 | 符合M58"WeightEngine通用" | 需改基类 |
| B: 各方法各自实现 | 独立 | 代码重复 | **违反DRY** |

**决策**: 方案A。M58规范说的是WeightEngine(通用)，逻辑不依赖滚动ICIR，提到Base类。

**决策点2: 静态权重方法如何应用维度权重**

| 方案 | 内容 |
|------|------|
| A: 静态权重计算后，按维度两阶段再分配 | 维度内归一化→维度间归一化 |
| B: 静态权重计算时就按维度分组 | 改变计算逻辑 |

**决策**: 方案A。静态权重先按原逻辑计算(equal/icir/ic)，然后对结果做维度两阶段再分配。不改变核心计算逻辑，维度权重是"后处理"层。

**决策点3: run_pipeline 配置方式**

| 方案 | 内容 |
|------|------|
| A: 4个ScriptTask都加 `--dimension_weight icir` | 统一配置 |
| B: 通过环境变量或配置文件 | 灵活但复杂 |

**决策**: 方案A。4个ScriptTask统一加参数，与现有rolling_icir配置方式一致。

---

### 2.3 P3: weight_selector 评分对齐只做多

**来源**: 问题 #10-#11, #18; 公理1; MODULE.md L126-131

**决策点1: 多空/空头指标处理**

| 方案 | 内容 | 优点 | 缺点 |
|------|------|------|------|
| A: 删除4个多空/空头指标 | long_short_return_annual, long_short_sharpe, long_short_net_daily, turnover_short_avg | 语义干净 | 指标数减少 |
| B: 保留但权重设0 | 兼容 | 死代码(H13违规) | **违反H13** |

**决策**: 方案A。保留权重=0的指标是死代码，直接删除。改后9指标→7指标（含新增2个L1指标）。

**决策点2: 新增 L1 指标**

| 指标 | 含义 | 方向 | 依据 |
|------|------|------|------|
| layer_1_annual | L1单独年化收益 | 越大越好 | 公理1: 只做多收益=L1 |
| layer_1_sharpe | L1夏普比率 | 越大越好 | L1正收益但不稳定不可用 |

**决策**: 新增上述2个指标。改后7指标全部对只做多有意义。

**决策点3: 评分归一化方式**

| 方案 | 内容 | 优点 | 缺点 |
|------|------|------|------|
| A: 保持Min-Max | 与现有逻辑一致 | 改动最小 | 放大效应仍在 |
| B: 改Z-score标准化 | 减少极值放大 | 需改归一化逻辑 | 引入新风险 |

**决策**: 方案A。移除多空指标后Min-Max的输入变化，放大效应自然缓解。不改归一化方式，减少改动范围。

---

### 2.4 P4: 规范文档补充"只做多"约束

**来源**: 问题 #12; grep零命中

**决策点1: 约束记录位置**

| 方案 | 位置 | 理由 |
|------|------|------|
| A: PROJECT.md 新增"策略约束"章节 | 项目级约束 | 只做多是策略级约束 |
| B: MODULE.md M12章节内补充 | 模块级 | 影响范围跨模块 |

**决策**: 方案A。只做多约束影响 M12(筛选)、weight_selector(评分)、stock_selector(选股)三个环节，是项目级约束，放PROJECT.md。MODULE.md相关章节引用PROJECT.md。

**决策点2: M12 门槛修改的规范记录**

| 方案 | 内容 |
|------|------|
| A: M12直接修改 long_short_return_annual→long_return_annual | 替换 |
| B: M12保留原文+新增注释说明只做多影响 | 双源漂移风险 |

**决策**: 方案A。直接修改M12，同步更新阈值依据说明。遵循"流程文档前后定义不能不一致"原则。

---

### 2.5 P5: 补齐信息维度

**来源**: 问题 #13-#14; 公理4; FACTOR_CATEGORIES(factor_definitions.py)

**决策点1: 新增因子范围**

| 方案 | 因子列表 | 测量维度 |
|------|---------|---------|
| A: 趋势导数3个 + 量价背离2个 | rsi_slope_3d, ma5_slope, volume_shrink_rate, price_volume_divergence, lower_shadow_ratio | "是否在企稳" |
| B: 只补趋势导数3个 | rsi_slope_3d, ma5_slope, volume_shrink_rate | 部分覆盖 |

**决策**: 方案A。公理4要求"状态"+"状态变化"两个信号，5个因子覆盖趋势变化(3个)和量价背离(2个)。

**决策点2: 因子公式定义**

| 因子 | 公式 | 经济含义 | 预期方向 |
|------|------|---------|---------|
| rsi_slope_3d | RSI(6)当前值 - RSI(6)3日前值 | RSI拐头=卖压减弱 | 正向(值大→收益高) |
| ma5_slope | (MA5今日 - MA5三日前) / MA5三日前 | 均线走平/拐头 | 正向 |
| volume_shrink_rate | 1 - vol_5d_mean / vol_10d_mean | 缩量=卖盘衰竭 | 正向 |
| price_volume_divergence | sign(价格5日变化) × sign(成交量5日变化) 的负值 | 价跌量缩=背离 | 正向 |
| lower_shadow_ratio | max(0, 开盘价-最低价) / (最高价-最低价) | 下影线长=低位承接 | 正向 |

**决策**: 采用上述公式。5个因子全部为正向因子（值大→收益高），与现有反向因子互补。

**决策点3: 新因子开发流程**

遵循 PROJECT.md "因子开发规范"（L489-531）6步：factor_generator → factor_selector → weight_engine → factor_definitions → PROJECT.md。

---

### 2.6 P6: 角色化权重体系

**来源**: 问题 #15-#17; 公理2; M57(MODULE.md L1897)

**决策点1: 因子角色定义**

| 角色 | 功能 | 入选条件 | 权重分配 |
|------|------|---------|---------|
| 主信号 | 反转触发 | L1>0 + \|IC\|≥0.03 + L1>L5 + ≥60天 | 维度ICIR加权(M58) |
| 确认信号 | 趋势变化确认 | L1>0 + \|IC\|≥0.01(更低) | 固定权重(各10%) |
| 过滤器 | 排除基本面恶化 | 不参与加权 | 硬过滤(入选/排除) |

**决策**: 三角色体系。主信号用现有ICIR+维度权重机制；确认信号因IC低用固定权重(避免ICIR加权给0权重)；过滤器为二值硬过滤。

**决策点2: 确认信号固定权重值**

| 方案 | 权重 | 理由 |
|------|------|------|
| A: 各10% | 5个确认因子共占50%，主信号占50% | 确认信号与主信号平等 |
| B: 各5% | 5个确认因子共占25%，主信号占75% | 主信号主导 |
| C: 按L1夏普等比例 | 动态分配 | 复杂且可能不稳定 |

**决策**: 方案B。主信号是反转策略核心(已有验证)，确认信号是辅助，主信号占75%、确认信号占25%更合理。5个确认因子各5%。

**决策点3: 过滤器实现方式**

| 方案 | 内容 | 位置 |
|------|------|------|
| A: stock_selector 中硬过滤 | 选股排序后排除 | stock_selector.py |
| B: factor_selector 中标记+stock_selector执行 | 筛选时标记filter角色 | factor_selector + stock_selector |

**决策**: 方案B。角色在factor_definitions.py定义，factor_selector筛选时标记，stock_selector执行过滤。职责分离：定义→筛选→执行。

**决策点4: 角色定义位置**

| 方案 | 位置 |
|------|------|
| A: factor_definitions.py 新增 FACTOR_ROLES 字典 | 与FACTOR_CATEGORIES同级 |
| B: factor_selector.py 中硬编码 | 混入筛选逻辑 |

**决策**: 方案A。角色是因子的固有属性（类似维度分类），放factor_definitions.py，与FACTOR_CATEGORIES同级。

---

## 3. 实施路线图

### 3.1 依赖关系与执行顺序

```
P1(M12筛选) ──────────────┐
                           ├──→ P3(评分对齐) ──→ P4(规范文档)
P2(维度权重全方法) ────────┘                        ↑
                                                   │
P5(补维度) ──→ P6(角色化权重) ────────────────────┘
```

- P1 和 P2 无相互依赖，可并行
- P3 依赖 P2（公平对比需要维度权重全方法支持）
- P5 和 P6 依赖 P1（新因子和角色化权重需要新的筛选标准）
- P4 最后做（记录所有改动结果）

### 3.2 分批计划（每批 ≤3文件 ≤200行，遵循 H9）

| 批次 | Phase | 文件 | 估计行数 | 前置 |
|------|-------|------|---------|------|
| 1 | P1 | factor_selector.py | ~30行 | 无 |
| 2 | P2-Step1 | weight_engine.py | ~60行 | 无 |
| 3 | P2-Step2 | composite_runner.py + run_pipeline.py | ~20行 | 批次2 |
| 4 | P3 | weight_selector.py | ~40行 | 批次2-3 |
| 5 | P5-Step1 | factor_generator.py + factor_definitions.py | ~80行 | 批次1 |
| 6 | P5-Step2 | factor_selector.py + weight_engine.py(映射) | ~30行 | 批次5 |
| 7 | P6-Step1 | factor_definitions.py + factor_selector.py | ~40行 | 批次5-6 |
| 8 | P6-Step2 | stock_selector.py | ~30行 | 批次7 |
| 9 | P4 | PROJECT.md + MODULE.md | ~50行 | 批次1-8 |

**每批独立 commit**，遵循 ruff → pytest → commit 流程。

---

## 4. 文件改动清单

| 文件 | 批次 | 改动内容 |
|------|------|---------|
| `comprehensive_factor/common/factor_selector.py` | 1, 6, 7 | P1: L1>0硬约束 + min_sample→60 + LS→多头; P5: 新因子FACTOR_NAME_TO_COL_MAP; P6: 角色标记 |
| `comprehensive_factor/common/weight_engine.py` | 2, 6 | P2: _apply_dimension_weights提到Base + else分支传参; P5: 新因子映射 |
| `comprehensive_factor/common/composite_runner.py` | 3 | P2: 4个composite脚本统一接收--dimension_weight |
| `run_pipeline.py` | 3 | P2: 4个ScriptTask都加--dimension_weight icir |
| `comprehensive_factor/weight_selector.py` | 4 | P3: 删4个多空指标 + 新增layer_1_annual/layer_1_sharpe |
| `data_fetchers/factor_generator.py` | 5 | P5: 新增5个因子计算函数 + _EXTENDED_FACTOR_COLS |
| `factor_definitions.py` | 5, 7 | P5: FACTOR_DEFINITIONS新增5因子 + FACTOR_CATEGORIES更新; P6: 新增FACTOR_ROLES |
| `comprehensive_factor/stock_selector.py` | 8 | P6: 过滤器执行(排除基本面恶化股票) |
| `PROJECT.md` | 9 | P4: 新增"策略约束"章节 + 因子列表更新 |
| `comprehensive_factor/MODULE.md` | 9 | P4: M12更新 + M58适用范围明确 + 版本历史 |

<!-- 逐节 patch 补充 -->

---

## 5. 测试计划

### 5.1 单元测试

| 批次 | 测试文件 | 测试内容 |
|------|---------|---------|
| 1 | `test_cases/test_factor_selector_p1.py` | L1<0因子被淘汰(不可豁免); min_sample=60验证; long_return_annual替代LS验证 |
| 2 | `test_cases/test_dimension_weight_all_methods.py` | 4种方法都支持dimension_weight; 静态权重维度再分配正确性 |
| 4 | `test_cases/test_weight_selector_p3.py` | 7指标评分; 多空指标已删除; L1指标生效 |
| 5 | `test_cases/test_new_factors.py` | 5个新因子计算正确性; 正向方向验证 |
| 7 | `test_cases/test_factor_roles.py` | 三角色分类正确; 角色从factor_definitions读取 |
| 8 | `test_cases/test_stock_selector_filter.py` | 过滤器排除基本面恶化股票 |

### 5.2 回归测试

每批完成后运行全量回归：
```bash
python3 -m pytest comprehensive_factor/test_cases/ -x -q
ruff check comprehensive_factor/
```

### 5.3 集成验证

批次1-4完成后重跑 pipeline Stage 4-7，验证：
- 4种方法都带维度权重
- weight_selector 评分不含多空指标
- 有毒因子(4个尾盘)不再入选

批次5-8完成后重跑 pipeline Stage 1-7，验证：
- 5个新因子进入IC计算
- 角色化权重生效
- 选股结果含企稳确认信号

---

## 6. 验证标准

| 验证项 | 标准 | 验证方法 |
|--------|------|---------|
| 有毒因子淘汰 | 4个尾盘因子(L1<0)不在入选列表 | 检查composite JSON factor_list |
| 维度权重全方法 | 4个composite JSON都含`dimension_weight_method: icir` | python3 -c 读JSON验证 |
| 评分无多空指标 | weight_selection_result.json metric_configs无long_short_* | 检查JSON |
| 新因子IC | 5个新因子有IC结果和回测结果 | 检查factor_ic/result/ |
| 角色化权重 | composite JSON含factor_roles信息 | 检查JSON |
| 只做多约束记录 | PROJECT.md含"策略约束"章节 | grep "只做多" PROJECT.md |
| 选股结果变化 | Top10不再全是阴跌股 | 对比改造前后选股结果 |

---

## 7. 回滚方案

### 7.1 每批回滚

每批独立 commit，可单独 revert：
```bash
git revert <commit_hash>
```

### 7.2 全量回滚

若整体方案需回退，按批次逆序 revert（9→8→7→...→1）。

### 7.3 数据回滚

pipeline 重跑会覆盖 result/ 目录产物。如需保留改造前结果作为对比基线：
```bash
cp -r comprehensive_factor/result/ comprehensive_factor/result_baseline_20260621/
```

---

## 8. 决策来源汇总

| 决策 | 来源 | 规范行号 |
|------|------|---------|
| L1>0不可豁免 | 公理1 | — |
| LS→多头 | 公理1 | M12 L590 |
| min_sample=60 | t检验 | M12 L595 |
| IC门槛保持0.03 | M12 | L586 |
| 维度权重提到Base | M58 | L1966 |
| 删除多空指标 | 公理1+H13 | MODULE.md L126-131 |
| 新增L1指标 | 公理1 | — |
| 5个新因子 | 公理4 | — |
| 三角色体系 | 公理2+M57 | L1897 |
| 确认信号固定5% | 经验 | — |
| FACTOR_ROLES放factor_definitions | 与FACTOR_CATEGORIES同级 | PROJECT.md L499 |
