# feat(r2c): RollingICIRWeightMethod 接通角色固定权重 (R2 补全)

> **背景**：v2.41 (R2) 在静态加权方法 (Equal/ICIR/IC) 实施了 `_apply_role_weights_static`，但 RollingICIR 当时被显式标记为 "暂不支持 (r2c 待实现)"。
>
> **实证证据 (2026-06-23 报告)**：
> - 4 个加权方法综合得分排序：**Rolling ICIR 0.6292 (最优) → 被 weight_selector 选为最终方法**
> - 选股阶段日志：`12:15:32 RollingICIRWeightMethod: role_weights 暂不支持 (r2c 待实现), 已忽略`
> - 实际权重：confirmation 桶（amplitude_compression 17.6% + volume_decay_rate 14.2% + ...）合计 **49.8%**（远超 R2 期望 25%）
> - 结果：Top 10 选股 5/10 阴跌（5d<-3%），0/10 反弹，主力权重全在"低振幅+缩量"上 = 阴跌画像
>
> **目标**：让 RollingICIR 每日动态权重也走 R2 角色后处理，使 4 个 method 在 R2 语义上等价。

---

## §1 What

在 `RollingICIRWeightMethod.calculate()` 内，**在 `_cap_weight_matrix` 之后、`_dim_weight` 列写回之前**，对权重矩阵 `W_capped` (shape: `n_days × n_factors`) 的**每一行**应用与静态版同构的角色固定权重：

- **primary 桶**：行内总权重锚定 `PRIMARY_WEIGHT_TOTAL = 0.75`，按原行内权重比例分配
- **confirmation 桶**：行内总权重锚定 `1 - 0.75 = 0.25`，**均分**给 confirmation 因子
- **filter 桶**：权重置 0（由 stock_selector 硬过滤）
- 不变量：行处理后 `sum == 1.0`（filter 桶权重并入 primary/confirmation 总和），与现有"行级归一化"完全兼容

---

## §2 How

### 2.1 新增矩阵版函数 `_apply_role_weights_matrix` (基类)

放在 `WeightMethodBase._apply_role_weights_static` (L637) **正下方**，作为静态版的向量化兄弟函数：

```python
def _apply_role_weights_matrix(
    self,
    W: np.ndarray,
    factor_cols: list[str],
) -> np.ndarray:
    """角色后处理（矩阵版，用于 RollingICIR 每日动态权重）.

    与 _apply_role_weights_static 同构：primary 75% + confirmation 25% 均分 + filter 排除.
    向量化逐行处理 W，每行独立完成角色分桶 → 归一化.

    Args:
        W: shape (n_days, n_factors), 每行 sum 假定 == 1.0
        factor_cols: 因子列名列表，对应 W 的列

    Returns:
        重新分配权重后的 W (拷贝)，每行 sum == 1.0

    豁免: 若 enable_role_weights=False, 直接返回原矩阵.
    """
```

### 2.2 算法（向量化等价于静态版逐行 dict 实现）

输入：`W (D, F)`，sum_per_row=1.0

```
# Step 1: 角色分桶（factor_cols 静态决定，所有行共享）
primary_mask    = [FACTOR_ROLES[name] == "primary"      for col in factor_cols]   # (F,)
conf_mask       = [FACTOR_ROLES[name] == "confirmation" for col in factor_cols]
filter_mask     = [FACTOR_ROLES[name] == "filter"       for col in factor_cols]

n_primary, n_conf, n_filter = sum(primary_mask), sum(conf_mask), sum(filter_mask)
PRIMARY_TOTAL       = PRIMARY_WEIGHT_TOTAL                # 0.75
CONFIRMATION_TOTAL  = 1.0 - PRIMARY_WEIGHT_TOTAL          # 0.25

# Step 2: filter 桶置 0
W_new = W.copy()
W_new[:, filter_mask] = 0.0

# Step 3: confirmation 桶均分 25%
if n_conf > 0:
    W_new[:, conf_mask] = CONFIRMATION_TOTAL / n_conf
    primary_target = PRIMARY_TOTAL
else:
    primary_target = 1.0  # 无 confirmation → primary 独占

# Step 4: primary 桶按原行内权重比例分配 primary_target
if n_primary > 0:
    primary_sum_per_row = W[:, primary_mask].sum(axis=1, keepdims=True)  # (D, 1)
    # 防御性：primary 原权重全 0 行 → 等权降级
    zero_rows = (primary_sum_per_row < 1e-12).flatten()
    safe_sum = np.where(primary_sum_per_row < 1e-12, 1.0, primary_sum_per_row)
    W_new[:, primary_mask] = W[:, primary_mask] / safe_sum * primary_target
    if zero_rows.any():
        W_new[zero_rows][:, primary_mask] = primary_target / n_primary
elif n_conf > 0:
    # 无 primary，confirmation 单独承担 100%
    W_new[:, conf_mask] = 1.0 / n_conf

# Step 5: 行归一化校验（防浮点累积误差）
row_sum = W_new.sum(axis=1, keepdims=True)
W_new = W_new / np.where(row_sum > 1e-12, row_sum, 1.0)

return W_new
```

### 2.3 接通点 (RollingICIRWeightMethod.calculate)

在 `weight_engine.py` 现有结构里，**最小入侵**地在 L1350 (`# 写回 _dim_weight 列`) **之前**插入：

```python
W_capped = self._cap_weight_matrix(...)   # 原 L1342-1347 不变

# v2.41 (r2c): 角色固定权重后处理（与静态版同构）
if getattr(self, "enable_role_weights", False):
    W_capped = self._apply_role_weights_matrix(W_capped, factor_cols)
    self.logger.info(
        "RollingICIR 角色权重: primary 75%% + confirmation 25%% 均分 + filter 排除（每日）"
    )

# 写回 _dim_weight 列
for i, col in enumerate(factor_cols):
    factor_df[f"{col}_dim_weight"] = W_capped[:, i]
```

### 2.4 删除 `__init__` 的 warning 旁路

`weight_engine.py:1088-1089` 当前代码：
```python
self.enable_role_weights = enable_role_weights
if enable_role_weights:
    self.logger.warning("RollingICIRWeightMethod: role_weights 暂不支持 (r2c 待实现), 已忽略")
```

改为：
```python
self.enable_role_weights = enable_role_weights  # v2.41 (r2c): 已接通
```

### 2.5 同步更新 `__init__` 注释 (L1079)

```python
enable_role_weights: bool = False,  # v2.41 (R2): 滚动版暂不支持，r2c 扩展
```
↓
```python
enable_role_weights: bool = False,  # v2.41 (r2c): 已接通到 _apply_role_weights_matrix
```

---

## §3 Don't

### 3.1 不要在 calculate() 里复用静态 dict 版

```python
# ❌ 错：静态版接收 dict，对 dict 处理后输出 dict，不能在矩阵循环里逐行 dict 化（性能/语义都不对）
for day in range(n_days):
    daily_dict = {col: W[day, i] for i, col in enumerate(factor_cols)}
    new_dict = self._apply_role_weights_static(daily_dict, factor_cols)
    ...
```

理由：每日单独 dict 化 + dict 操作 → **O(D × F²)** 复杂度（dict get/set），相比矩阵版 O(D × F) 慢 100×。RollingICIR 每日动态权重 D ≥ 100，无法接受。

### 3.2 不要在 `_apply_dimension_weights` 之前/之后非 cap 之后接通

`_cap_weight_matrix` 处理后矩阵保持每行 sum=1.0，是角色后处理的**唯一干净入口**。若放在 cap 之前：角色重分配 → cap 再压 → 角色总额漂移 → R2 失效。

### 3.3 不要把"无 confirmation 因子"当作错误退出

设计豁免：无 confirmation 因子时 primary 独占 100%（等于"无 R2 影响"），保留矩阵原状归一化。这与静态版 L709-712 同构。

### 3.4 不要在 RollingICIR 里重新 import FACTOR_ROLES

`_apply_role_weights_matrix` 必须复用基类 (`WeightMethodBase`) 已 import 的 `_MODULE_FACTOR_ROLES` (L41)，禁止再次 import 出现重复符号。

---

## §4 Why

### 4.1 第一性原理：4 method 在 R2 语义上必须等价

**核心论证**：R2 是因子库层的**普适性架构规则**（每个因子的"角色"不依赖于加权方法）。当 weight_selector 自动从 4 个方法中选"最优"时，4 个方法必须遵守同一个 R2 契约，否则：

- 静态方法被 R2 约束 → confirmation 桶 25%
- RollingICIR 不被 R2 约束 → confirmation 桶可漂移到任何值（实测 49.8%）
- → "最优方法"的客观指标比较失去公平基础，因为两组方法在不同的权重空间里竞争

实证：2026-06-23 Rolling ICIR 综合得分 0.6292 之所以"最优"，部分来自 confirmation 桶超额配置（amplitude_compression 17.6% + volume_decay_rate 14.2%）在历史多头收益上的虚高。若 4 method 都套 R2，Rolling ICIR 未必仍是最优。

### 4.2 矩阵实现 vs 逐行 dict 实现

- **矩阵版**：O(D × F) 单次向量化；与现有 `_cap_weight_matrix` 共栈结构（同为 n_days × n_factors 操作）
- **逐行 dict 版**：O(D × F²) dict 操作 + n_days 次 logger 输出污染日志
- 选矩阵：性能 + 语义清晰（静态版处理 dict 是因为 "全 dataset 一份权重"，矩阵版处理 W 是因为 "每日动态权重"）

### 4.3 历史教训：R2 部分实施 → 静默旁路

2026-06-22 R2 实施时的妥协（"先做静态版，RollingICIR r2c 待实现"）本意是分阶段交付，但低估了 weight_selector 的"自动选最优"会**优先选未实施 R2 的方法**。

→ **教训入 skill**：任何带"自动选最优"的多方法分支，**部分实施一个新约束等同于完全没实施**（因为最优分支恰好绕过约束）。

---

## §5 When

- ✅ R2 在静态方法已实施 (`f1d5d00`/`c42a7c8`)，r2c 是 R2 的最后一块拼图
- ✅ weight_selector 已稳定选 Rolling ICIR 为最优方法（多次 pipeline 运行均如此）
- ✅ 实测 R3 的 -10% 阈值已无法继续兜底（今天 Top 10 全员擦边）
- ✅ R4 (v2.13 取反契约) 推迟仍是合理决策——必须先把 R2 在所有 method 上接通，才能客观评估 R4 是否真的必做

---

## §6 改动清单

| # | 文件 | 改动 | 行数估算 |
|---|------|------|---------|
| 1 | `comprehensive_factor/common/weight_engine.py` | `WeightMethodBase` 新增 `_apply_role_weights_matrix` 方法 | ~60 行 |
| 2 | `comprehensive_factor/common/weight_engine.py` | `RollingICIRWeightMethod.calculate()` 在 cap 后插入 R2 调用（4 行） | ~4 行 |
| 3 | `comprehensive_factor/common/weight_engine.py` | `__init__` 删除 warning + 更新注释 (L1088-1089, L1079) | -2 +2 行 |
| 4 | `comprehensive_factor/test_cases/test_role_weights_matrix.py` | 新增测试：矩阵版与静态版逐行等价 + RollingICIR 端到端集成测试 | ~150 行 |
| **合计** | | | **~216 行**，单文件 ≤200 行（生产代码 ≤66 行，测试 ≤150 行；H9 合规） |

---

## §7 测试用例 (test_role_weights_matrix.py)

### T1 `test_matrix_equals_static_per_row`
构造 1 日 × N 因子矩阵，对比 `_apply_role_weights_matrix(W, cols)[0]` 与 `_apply_role_weights_static({col: W[0,i] for ...}, cols)` 应数值相等 (atol=1e-9)。

### T2 `test_matrix_multi_day_independent`
构造 5 日 × N 因子矩阵，每日 W 不同，验证每日独立处理：每行单独跑静态版得到的 dict 应与矩阵版第 i 行等价。

### T3 `test_matrix_no_confirmation`
所有因子 role="primary"，矩阵版应保留各行原归一化（不变）。

### T4 `test_matrix_no_primary`
所有因子 role="confirmation"，每行 confirmation 应等权 1/n_conf（独占 100%）。

### T5 `test_matrix_filter_zeroed`
含 filter 因子时，对应列被置 0，其他列重新归一化 sum=1.0。

### T6 `test_matrix_primary_zero_row`
某日 primary 原权重全 0（退化），应等权降级 primary_target/n_primary。

### T7 `test_rolling_icir_e2e_role_weights`
**集成测试**：构造小型 factor_df + ic_daily_data，跑完整 `RollingICIRWeightMethod.calculate()`，断言：
- `_last_day_weights` 中 confirmation 桶合计 ≈ 0.25 (±1e-6)
- `_last_day_weights` 中 primary 桶合计 ≈ 0.75 (±1e-6)
- filter 桶权重 = 0

### T8 `test_rolling_icir_disabled_role_weights`
`enable_role_weights=False` 时，矩阵版不被调用，权重保留 cap 后状态（向后兼容）。

---

## §8 验证 (Verify)

```bash
# 单元测试
pytest comprehensive_factor/test_cases/test_role_weights_matrix.py -v

# 现有测试不退化
pytest comprehensive_factor/test_cases/test_role_weights.py -v
pytest comprehensive_factor/test_cases/test_weight_engine_nan.py -v
pytest comprehensive_factor/test_cases/ -q   # 全量回归

# ruff
ruff check comprehensive_factor/common/weight_engine.py \
            comprehensive_factor/test_cases/test_role_weights_matrix.py

# 端到端：重跑 composite_rolling_icir + stock_selector，日志应有
#   "RollingICIR 角色权重: primary 75% + confirmation 25% 均分 + filter 排除（每日）"
# 而 12:15:22 的 "role_weights 暂不支持" warning 应消失
```

---

## §9 验收

- ✅ 4 个加权方法（Equal/ICIR/IC/RollingICIR）日志均出现 "角色权重: primary=... confirmation=... filter=..."
- ✅ composite_rolling_icir_weight_1d.json 的因子权重表中 confirmation 桶合计 ≈ 25%
- ✅ 重跑 pipeline 后阴跌 Top 10 数 < 历史基线 5 只（数据驱动判定 R4 是否必做）

---

## §10 决策矩阵

| 备选方案 | 优点 | 缺点 | 决策 |
|---------|------|------|------|
| **A. 矩阵向量化（本设计）** | O(D×F); 与 cap 同栈结构; 数值与静态版逐行等价 | 新增 ~60 行函数 | ✅ 采纳 |
| B. 逐日 dict 化 + 复用静态版 | 零新增逻辑，复用 `_apply_role_weights_static` | O(D×F²) 慢 100×; 每日 logger 污染 | ❌ |
| C. 在 weight_selector 端禁止选 Rolling ICIR 为最优 | 改动只在 1 个文件 | 治标不治本；丢失 Rolling ICIR 信息；R2 仍未在 4 method 等价 | ❌ |

---

## §11 风险

| 风险 | 缓解 |
|------|------|
| 矩阵版与静态版行为不等价 | T1/T2 测试**逐行 dict 对比**做强约束 |
| `_apply_role_weights_matrix` 对 primary_sum=0 行处理错误 | T6 专项测试 + 静态版同语义 L702-705 已验证多次 |
| RollingICIR 端到端权重 drift | T7 集成测试 + 日志验收 |
| 历史 `disable_role_weights` CLI flag 兼容 | 矩阵版受 `enable_role_weights` 守卫，flag=True 时不进入 if 分支，向后兼容 |
| 与 `_cap_weight_matrix` 联动后 sum 漂移 | 矩阵 Step 5 强制行归一化兜底；T7 集成测试断言 sum=1.0 |

---

## §12 引用规范

- PROJECT.md 第一性原理（元规则）：4 method 在 R2 语义上必须等价
- PROJECT.md §2 #5: 因子方向 → 角色权重需由实际 IC 决定 (R2 由 FACTOR_ROLES 静态决定)
- AGENTS.md §0 Design-First：2+ 文件 (`weight_engine.py` + 新增测试文件) 改动先 design
- AGENTS.md §2 #14: 死代码禁止 (warning + return 的"半启用"是死代码模式)
- designs/feat_role_based_fixed_weight_75_25.md (R2 原设计)
- designs/master_l1_l6_roadmap.md L2.4 (R2 工作量评估)
