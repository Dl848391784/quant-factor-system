# Design: 交互因子族独立门槛体系（v2.39）

> 作者: 云瑶
> 日期: 2026-06-22
> 关联: feat_interaction_factors.md (v2.36 三因子设计) + feat_interaction_exemption_and_weight_cap.md (v2.38 L1 豁免/权重 cap)
> Phase: Plan (Design-First, 遵循 PROJECT.md H8)
> 触发上下文: §10 Post-Mortem 暴露的 IC 口径错配 + 重跑发现三因子被多重门槛卡死

---

## 1. 问题与根因

### 1.1 现象

v2.38 已完成 Batch 1 (L1 豁免) + Batch 2 (权重 cap)，pipeline 重跑后：

- **Top10 全是 composite_value 负值（−1.39 ~ −1.12）**，方向 `negative`，阴跌股问题未解决
- v2.36 设计的 3 个交互因子（interaction_amplitude / turnover / amp_compression）**全部被 factor_selector 淘汰**，未进入综合因子池
- 选中的 15 个因子中虽有 7 个 interaction_*（第二批 v2.37 入池），但方向分布 `8N : 7P` → 综合方向仍 negative

### 1.2 三因子被卡的所有门槛

| 因子 | ic_mean (>0.01) | p_value (<0.05) | icir (>0.15) | mono_corr 主阈 (>0.4) | mono_corr L1 豁免 (>0.5) |
|---|---|---|---|---|---|
| interaction_amplitude | 0.005 ❌ | 0.113 ❌ | 0.077 ❌ | 0.42 ✓ | 0.42 ❌ |
| interaction_turnover | 0.002 ❌ | 0.611 ❌ | 0.024 ❌ | 0.37 ❌ | 0.37 ❌ |
| interaction_amp_compression | 0.008 ❌ | 缺失 | 0.120 ❌ | 0.36 ❌ | 0.36 ❌ |

**关键观察**: 不是单一门槛卡死，而是**整套门槛标定都对交互因子不友好**。

### 1.3 根因（第一性原理推导）

`factor_selector.DEFAULT_THRESHOLDS` 是**按线性单调因子标定**的（RSI、bollinger_pb 这类）：

| 门槛 | 线性因子典型值 | 交互因子典型值 | 数学原因 |
|---|---|---|---|
| ic_mean | 0.02~0.07 | 0.002~0.008 | 池化 IC 等权稀释（design v2.36 §10） |
| icir | 0.15~0.30 | 0.02~0.12 | 早期 30 日 IC 噪声 ±0.15 → IC_std 被拉高 |
| mono_corr | 0.5~0.8 | 0.3~0.5 | 乘法结构 `-z(weakness)×z(X)` 非单调 → 分层 U 形 |
| p_value | <0.05 | 0.1~0.6 | ic_mean 小 → t = ICIR×√T 不显著 |

**结论**: 交互因子的统计特性与线性因子**结构性不同**，硬套同一套门槛 = 把所有交互因子静默淘汰。
v2.38 Batch 1 只豁免了一个 `layer_1`，没意识到上游 4 个门槛已经先把因子砍掉。

**第一性原理**: 门槛标定必须匹配因子的统计结构。交互因子需要独立的门槛 dict，而不是给主 dict 打几个补丁。

---

## 2. 方案选型（架构两档）

### 2.1 方案 A（小步打补丁）— ❌ 不推荐

在主 dict 上加 5 个 `is_interaction_factor` 条件分支：
- L1 豁免 mono 阈值 0.5→0.3
- reverse_factor 豁免 mono 阈值 0.5→0.3
- ic_mean 阈值 0.01→0.005
- mono 主阈值 0.4→0.3 仅对 interaction
- icir 阈值 0.15→0.05 仅对 interaction

**问题**:
- 主 dict 被 5 处 if-else 污染，可读性 ↓
- 每加一个新因子族（如未来的 fundamental_x_momentum）就再叠加 5 个补丁
- 调参味浓，违反"门槛标定按因子结构"的第一性原理

### 2.2 方案 B（独立门槛体系，第一性原理）— ✅ 推荐

新增 `INTERACTION_THRESHOLDS` 独立 dict，是 `_validate_factor` 函数开头按 `is_interaction_factor` 二分派发：

```python
INTERACTION_THRESHOLDS = {
    "ic_mean_abs_min": 0.005,    # 池化 IC 稀释后, 交互族典型值 0.002~0.020
    "p_value_max": None,          # 跳过 (ic_mean 小 → t 统计天然不显著)
    "icir_abs_min": 0.05,         # 早期噪声 + IC 衰减, 典型 0.02~0.15
    "monotonicity_corr_abs_min": 0.30,  # 乘法非单调, 典型 0.30~0.50
    "long_return_min": 0.05,      # 多头年化, 保持 5% 经济意义门槛
    "high_corr_threshold": 0.70,  # 维度相关性, 与主 dict 一致
    "min_sample_days": 60,        # 样本量, 与主 dict 一致
    "layer_1_return_min": -0.25,  # L1 必亏的数学必然 (design v2.38), 容忍到 −25%
    "layer_1_sharpe_min": -1.50,  # L1 夏普容忍下限, 与 v2.38 设计一致
}
```

**关键设计**:
1. **`layer_1_return_min = −0.25`**: 不是"豁免"，是**门槛本身就允许 L1 负**。交互因子族数学必然 L1 亏，是预期行为，不应做特殊豁免逻辑
2. **`p_value_max = None`**: 显式跳过，承认 t 统计不适用
3. **`long_return_min = 0.05`**: 多头年化保持 5%（高于 3% 基线），因为这是"只做多策略能否赚钱"的关键判据，**不可放宽**
4. **`high_corr_threshold` 保持 0.7**: 同维度相关性是物理结构约束，不因因子类型变化

**优势**:
- 单点修改: 后续新因子族（基本面交互、波动率交互）按同模式新加 dict 即可
- 主 dict 干净: 不被补丁污染
- 第一性原理: 门槛标定显式承认因子结构差异
- 可审计: `selection_result.invalid` 里能区分用哪套门槛判定

**风险**:
- 多维护一个 dict（约 9 个字段）
- 需新加 5~8 个测试 case（不同因子类型走对应门槛）

### 2.3 方案 C（白名单 force_include）— ❌ 不推荐

跳过 factor_selector，直接把交互因子塞进入选列表 → 但绕过门槛 = 失去淘汰失效因子的能力（如果某个交互因子真的失效，会进池污染综合因子）。**违反"门槛存在的意义"原则**。

### 2.4 决策矩阵

| 维度 | A 小补丁 | **B 独立门槛 ✅** | C 白名单 |
|---|---|---|---|
| 第一性原理符合度 | 低（调参式） | **高（结构差异显式建模）** | 低（绕过门槛） |
| 主 dict 污染 | 高（5 处分支） | **无** | 无 |
| 扩展性（未来新因子族） | 差（线性叠加） | **好（同模式新 dict）** | 差（无淘汰能力） |
| 失效因子保护 | 有 | **有** | 无 ⚠️ |
| 实现复杂度 | 中（5 处改动） | 中（重构 + 测试） | 低（绕过） |
| 测试覆盖增量 | +5 case | **+8 case** | +2 case |
| 实施风险 | 中（漏改某处） | 低（集中改 1 处） | 高（失效因子进池）|
| **选择** | ❌ | **✅** | ❌ |

**来源**:
- A 阈值数字来自 §1.2 实测 + skill ref `factor-development/conditional-ic-analysis.md`
- B 的 layer_1_return_min = −0.25: amplitude L1=−0.206, turnover=−0.163, amp_comp=−0.118，取 −0.25 留 20% 缓冲
- B 的 mono 阈值 0.30: 三因子 mono ∈ [0.36, 0.42]，取 0.30 留下界

---

## 3. 实现详细

### 3.1 代码改动范围

| 文件 | 改动 | 行数预估 |
|---|---|---|
| `comprehensive_factor/common/factor_selector.py` | 新增 `INTERACTION_THRESHOLDS` dict + `_get_thresholds_for_factor()` 派发函数 + `_validate_factor` 使用派发后的 dict | +30 / −12 |
| `comprehensive_factor/MODULE.md` | 新增 M16b 章节: 交互因子独立门槛体系（What/How/Why/Examples/Verify）| +40 |
| `comprehensive_factor/test_cases/test_factor_selector_interaction_thresholds.py` 🆕 | 测试派发逻辑 + 三因子能否通过新门槛 | +120 |

**总计**: 3 文件，~150 行净增，满足 PROJECT.md H9 (≤3 文件 ≤200 行)

### 3.2 派发逻辑

```python
def _get_thresholds_for_factor(factor_name: str, base_thresholds: dict) -> dict:
    """根据因子名前缀派发门槛 dict。

    交互因子族（factor_name.startswith("interaction_")）使用独立门槛，
    其余因子使用 base_thresholds。
    """
    if factor_name.startswith("interaction_"):
        # 交互因子独立门槛：承认乘法结构的统计特性差异
        merged = dict(base_thresholds)
        merged.update(INTERACTION_THRESHOLDS)
        return merged
    return base_thresholds
```

**关键**: 用 `merge` 而非完全替换，避免 INTERACTION_THRESHOLDS 漏定义某字段导致 KeyError。

### 3.3 _validate_factor 改动点

```python
# 原:
def _validate_factor(factor_name, factor_data, thresholds, logger):
    # thresholds = DEFAULT_THRESHOLDS

# 新:
def _validate_factor(factor_name, factor_data, thresholds, logger):
    thresholds = _get_thresholds_for_factor(factor_name, thresholds)  # 🆕 派发
    # 其余逻辑不变
```

**只改 1 个函数入口**。L1 豁免 logic (v2.38 Batch 1) 仍保留——主因子族未来若也想 L1 豁免可复用（但 layer_1_return_min=−0.25 后交互因子根本不会触发 L1 检查，豁免代码对交互族变成 dead code，需评估是否同时删除）。

### 3.4 L1 豁免代码的处理

**两个选项**:

**选项 1 (保守)**: 保留 v2.38 Batch 1 的 L1 豁免代码作为 fallback。layer_1_return_min=−0.25 后，三因子的 L1 −0.206/−0.163/−0.118 全部 > −0.25 → 不触发 L1 检查 → 豁免代码不执行（但仍存在）。

**选项 2 (彻底)**: 删除 v2.38 Batch 1 加的 L1 豁免代码（约 60 行），因为交互因子走独立门槛后不需要豁免。

**初步建议**: **选项 1**。理由:
- v2.38 Batch 1 是 2 天前 commit `4c845c0`，刚加就删，破坏 git 历史可读性
- 未来非交互因子若也想 L1 豁免（如某些因子方向反转），保留代码有用
- 不影响功能（dead 但不害）

**待你裁定**。

### 3.5 invalid 报告增强

`exempt_details` 字段加 `"threshold_source": "interaction" | "default"` 标识，便于审计：

```json
{
  "trigger": "ic_mean",
  "threshold": 0.005,
  "threshold_source": "interaction",  // 🆕
  "actual": 0.0048,
  "exempted": true,
  ...
}
```

---

## 4. 验收标准（6 项）

1. ✅ ruff check / format / pytest 全通过；新增测试 ≥8 case 全过
2. ✅ pipeline --start-stage 4 重跑后，v2.36 三因子全部进入 `selected` 列表
3. ✅ stock_selection_result.json `factor_direction` 字段从 `negative` 翻转为 `positive`（关键!）
4. ✅ Top10 选股 composite_value 全部为**正值**（与现状 −1.39~−1.12 反向）
5. ✅ Top10 选股至少 5 只**非阴跌股**（最近 5 日累计收益 > −3%）—— v2.36 design §8 同标准
6. ✅ `selection_result.invalid` 不再包含 v2.36 三因子；若包含，必须有明确不过新门槛的理由

**若 ③④ 不达标**: 说明问题不在因子进池，在 weight_engine 的 factor_direction 决策机制 → 触发问题③深挖（独立 design）。

---

## 5. Phase 划分

| Phase | 内容 | 产出 |
|---|---|---|
| **Plan** | 本设计文档 | 本 design.md（待审）|
| **Execute** | 改 factor_selector.py + 新测试 + MODULE.md | 1 commit |
| **Review** | ruff + pytest + Spec Compliance（PROJECT.md H1/H8/H9）| 报告 |
| **重跑** | pipeline --start-stage 4 后台 + notify_on_complete | 验收 6 项 |

---

## 7. Post-Mortem（v2.39 实施后）

### 7.1 设计错误：`p_value_max=None` 跳过

**§2.2 初稿**写了 `p_value_max: None  # 跳过 (ic_mean 小 → t 统计天然不显著)`。

**实施时被 amp_compression 反例证伪**：

| 因子 | ic_mean | ic_std | N | t = ic_mean / (ic_std/√N) | p_value |
|---|---|---|---|---|---|
| interaction_amp_compression | 0.0077 | 0.065 | ~500 | 2.65 | **0.012 显著** ✓ |
| interaction_amplitude | 0.0048 | 0.065 | ~500 | 1.65 | 0.113 边缘 |
| interaction_turnover | 0.0016 | 0.068 | ~500 | 0.53 | **0.611 几乎纯随机** |

**根因**: "ic_mean 小所以 t 必然不显著" 是错误归纳——ic_mean 小但 ic_std 也跟着小时，t 统计照样能显著。amp_compression 就是反例。

**正确推理**: p_value 在 ic_mean 小的时候**反而更重要**——它是统计学最直接的"信号真实性"判据，自动区分:
- 真小信号（p < 0.05, 如 amp_compression）→ 入池
- 边缘噪声（0.05 < p < 0.5）→ 淘汰
- 纯随机（p > 0.5, 如 turnover）→ 必须淘汰

**修正**: `INTERACTION_THRESHOLDS["p_value_max"] = 0.05`（与 DEFAULT_THRESHOLDS 一致）。

### 7.2 实施结果（v2.36 三因子）

| 因子 | 设计预期 | pipeline 实测 | 是否进池 (v2.39 INTERACTION_THRESHOLDS) |
|---|---|---|---|
| interaction_amp_compression | +0.008 | ic_mean=0.0077 / icir=0.120 / mono=0.357 / p=0.012 | ✅ **进池**（所有指标过线）|
| interaction_amplitude | +0.020 | ic_mean=0.0048 / icir=0.077 / mono=0.418 / p=0.113 | ❌ 淘汰（ic_mean+p_value 卡）|
| interaction_turnover | +0.016 | ic_mean=0.0016 / icir=0.024 / mono=0.374 / p=0.611 | ❌ 淘汰（ic_mean+icir+p_value 三卡）|

**门槛在正常工作**：amp_compression 是"真小信号"（小但统计显著），其他两个是"过拟合/数据噪声"。**接受 amplitude/turnover 被淘汰是正确的第一性原理决策**——继续放宽阈值救它们 = 调参式修复，会让综合因子被噪声污染。

### 7.3 第一性原理沉淀

1. **不要绕过 p_value**: 即使 ic_mean 小，p_value 仍是最强的信号真实性判据
2. **门槛是过滤器，不是收纳器**: 设计独立门槛是承认因子结构差异，**不是为了"让所有交互因子都进池"**
3. **设计 design 时用精确值，不用 invalid 报告 .3f 截断显示值**: design §1.2 的 0.005/0.002/0.008 来自 invalid 报告 .3f 显示，精确值 0.0048/0.0016/0.0077 才是真相

1. **方案 B 是否通过**？还是想看更细的实现 patch？
2. **L1 豁免代码处理**：选项 1 (保守保留) vs 选项 2 (彻底删除)？
3. **门槛数字微调**：
   - `monotonicity_corr_abs_min = 0.30` 是否偏松？（三因子 mono ∈ [0.36, 0.42]，0.30 留 6 个 pp 缓冲）
   - `icir_abs_min = 0.05` 是否偏松？（三因子 icir ∈ [0.024, 0.120]，0.05 仍卡 turnover/amplitude）
   - `long_return_min = 0.05` 是否过严？（三因子 long_return ∈ [10.1%, 11.6%] 都过 5%）
4. **invalid 报告 `threshold_source` 字段**：是否需要？（增强可审计性 vs 多一个字段）
5. **§3.4 L1 豁免 dead-code 处理**：要在本轮处理还是单开 cleanup PR？

回答后即进 Execute。
