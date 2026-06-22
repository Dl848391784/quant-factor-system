# R2: 角色固定权重接入（主 75% + 确认 25%）

**版本**: R2-v1
**作者**: 云瑶
**日期**: 2026-06-22
**状态**: Plan（Design-First）
**前置**: master_l1_l6_roadmap.md
**关联**: strategy_systemic_overhaul.md §2.6 决策点 2 方案 B；factor_definitions.py:585-586 半成品常量

---

## §1 What — 规范定义

将"主信号 75% + 确认信号 25% 平摊"由静态常量（factor_definitions.py:585-586）
接入到 `weight_engine` 的权重计算流程，作为 `_apply_dimension_weights_static`
之后、`_cap_*` 之前的角色后处理步骤。

---

## §2 现状盘点

| 项 | 状态 |
|---|---|
| 角色常量定义 | ✅ `CONFIRMATION_WEIGHT_PER_FACTOR=0.05`, `PRIMARY_WEIGHT_TOTAL=0.75` |
| FACTOR_ROLES 字典 | ✅ 已分配（factor_definitions.py:520-579），confirmation 共 11 个 |
| 测试存在 | ✅ test_factor_roles.py 校验常量 |
| **生产代码读取** | ❌ **零调用**（grep 全项目无 `CONFIRMATION_WEIGHT_PER_FACTOR` 在 weight_engine/composite_runner 中） |

→ R2 = 接线工作，非新开发。

---

## §3 How — 实施方案

### 3.1 weight_engine 新方法 `_apply_role_weights_static`

**位置**: `WeightMethodBase`，紧邻 `_apply_dimension_weights_static`（L547）之后。

**职责**: 输入 `weights dict`，把 confirmation 因子强制压到固定权重 5%/因子，
剩余权重比例缩放给 primary 因子，filter 因子权重置 0（不进入 composite）。

```python
def _apply_role_weights_static(
    self,
    weights: dict[str, float],
    factor_cols: list[str],
) -> dict[str, float]:
    """角色后处理：主 75% + 确认 25% 平摊 + filter 排除

    第一性原理（master_l1_l6_roadmap §2.2）:
        - 主信号（reversal trigger）: 高 IC, 单独可形成多头收益
        - 确认信号（stabilization）: 低 IC 但低相关, 作过滤器不作主导
        - filter 角色: 基本面/累计跌幅, 在 stock_selector 硬过滤, 不进 composite
        - 业界依据: Asness 2013, AQR 核心+卫星 70-80/20-30

    Args:
        weights: 上游（dimension_weights 后）权重字典.
        factor_cols: 因子列名列表（含 _std 前的列名）.

    Returns:
        角色处理后的权重字典, sum ≈ 1.0 (filter 因子已剔除).

    豁免: 若 confirmation 因子 = 0 → 退化为旧逻辑（所有 weight 归一化）.
        若 primary = 0 但 confirmation 存在 → 异常配置, 警告 + 退化为等权.
    """
    if not self.factor_categories:
        # factor_categories 是 dim 用的, 但 role 是独立维度; 用 FACTOR_ROLES
        pass

    from factor_definitions import (
        FACTOR_ROLES,
        CONFIRMATION_WEIGHT_PER_FACTOR,
        PRIMARY_WEIGHT_TOTAL,
    )

    # 1) 按角色分桶
    primary_cols: list[str] = []
    confirmation_cols: list[str] = []
    filter_cols: list[str] = []
    for col in factor_cols:
        factor_name = self._get_factor_name_from_col(col)
        role = FACTOR_ROLES.get(factor_name, "primary")
        if role == "primary":
            primary_cols.append(col)
        elif role == "confirmation":
            confirmation_cols.append(col)
        elif role == "filter":
            filter_cols.append(col)

    logger = getattr(self, "logger", None) or get_logger(__name__)

    # 2) filter 角色: 不进 composite, 权重置 0（实际由 stock_selector 硬过滤）
    new_weights: dict[str, float] = {col: 0.0 for col in filter_cols}

    # 3) confirmation 角色: 每个固定 5%
    if confirmation_cols:
        for col in confirmation_cols:
            new_weights[col] = CONFIRMATION_WEIGHT_PER_FACTOR
        confirmation_total = CONFIRMATION_WEIGHT_PER_FACTOR * len(confirmation_cols)
    else:
        confirmation_total = 0.0

    # 4) primary 角色: 剩余权重 (1 - confirmation_total - filter_total=0)
    primary_total_target = 1.0 - confirmation_total
    if primary_cols:
        # 按原权重在 primary 池内的比例分配
        primary_orig_sum = sum(weights.get(c, 0.0) for c in primary_cols)
        if primary_orig_sum > 0:
            for col in primary_cols:
                new_weights[col] = (
                    weights[col] / primary_orig_sum * primary_total_target
                )
        else:
            # primary 原权重全 0 → 等权降级
            logger.warning(
                "_apply_role_weights: primary 原权重全 0, 降级为 primary 池等权"
            )
            for col in primary_cols:
                new_weights[col] = primary_total_target / len(primary_cols)
    else:
        # 无 primary, 把 confirmation_total 扩到 1.0
        logger.warning(
            "_apply_role_weights: 因子池无 primary 角色, confirmation 单独承担 100%%"
        )
        if confirmation_cols:
            scale = 1.0 / confirmation_total
            for col in confirmation_cols:
                new_weights[col] *= scale

    # 5) 行级归一化校验（容忍 1e-9）
    total = sum(new_weights.values())
    if total > 0 and abs(total - 1.0) > 1e-6:
        new_weights = {k: v / total for k, v in new_weights.items()}

    logger.info(
        "角色权重: primary=%d (%.0f%%) + confirmation=%d (%.0f%%) + filter=%d (排除)",
        len(primary_cols),
        primary_total_target * 100,
        len(confirmation_cols),
        confirmation_total * 100,
        len(filter_cols),
    )
    return new_weights
```

### 3.2 调用链接入（4 个 get_weights）

**get_weights 方法位置**:
- `EqualWeightMethod.get_weights`     ~ L693
- `ICIRWeightMethod.get_weights`      ~ L751
- `ICWeightMethod.get_weights`        ~ L886
- `RollingICIRWeightMethod.get_weights` ~ L849（滚动权重特殊处理）

**统一改动模式**（Equal/ICIR/IC 三方法）:

```python
def get_weights(...) -> dict[str, float]:
    # 1. 原有逻辑 (ICIR 加权等)
    weights = {...}
    # 2. dimension_weights 后处理 (已存在)
    weights = self._apply_dimension_weights_static(weights, factor_cols)
    # 3. NEW: role_weights 后处理（角色固定权重）
    weights = self._apply_role_weights_static(weights, factor_cols)
    return weights
```

**RollingICIRWeightMethod**: 由于权重每日动态（DataFrame 列），需在
`_apply_dimension_weights`（L997，per-row）之后调用同样逻辑的 DataFrame 版
`_apply_role_weights_rolling`。该实现复用上面静态版的逻辑，作用于 weight_df 列。

简化方案（决策点）：第一版**只支持 Equal/ICIR/IC 三方法**，
RollingICIRWeightMethod 加 `assert role_weights_disabled or single_method`，
若用户传 rolling_icir + role_weights 抛 NotImplementedError，
待 R2b 完成后做 R2c 扩展（不阻塞 R1-R3 主线）。

### 3.3 cap 顺序保证

```
权重计算 → dimension_weights → role_weights → single_cap (25%) → family_cap (30%)
```

- confirmation 固定 5% 永远不会触 25%/30% cap → 不受影响
- primary 75% 分到 N 个 primary 因子时，若单因子 > 25% 触发 cap：
  例：3 个 primary，75% / 3 = 25%，恰好不触；
  4+ primary：每个 ≤ 18.75%，不触；
  2 个 primary：每个 37.5% → 触 25% cap，摊分到另一个 → 50% / 50% 又触 → 这种极端情况 cap 会回到等权。

**第一性审视**: 2 个 primary 是极端配置，实际不会发生（系统通常 8-12 个 primary
入选）。无需特殊处理。

### 3.4 composite_runner 改动

`composite_runner.py` 调用 `WeightEngine.calculate` 处需检查是否传入
`enable_role_weights` 参数。提议：

```python
# 默认 True（R2 完成后启用）
class CompositeRunner:
    def __init__(self, ..., enable_role_weights: bool = True):
        self.enable_role_weights = enable_role_weights
```

WeightEngine 加同名构造参数，传递到 WeightMethodBase。
`_apply_role_weights_static` 内首行加：
```python
if not getattr(self, "enable_role_weights", True):
    return weights
```

### 3.5 run_pipeline 配置

`run_pipeline.py` 现有 4 个 composite ScriptTask，无需新参数（用默认 True）。
仅在 composite_*_1d.py 加 argparse `--disable-role-weights`（可选回滚开关）。

### 3.6 测试

新增 `comprehensive_factor/test_cases/test_role_weights.py`:

```python
def test_only_primary():
    """全 primary → role_weights 退化为原权重归一化"""

def test_primary_plus_confirmation():
    """3 primary + 2 confirmation → confirmation 各 5%, primary 共 90% 按原比例"""
    weights = {"f_p1": 0.4, "f_p2": 0.3, "f_p3": 0.2, "f_c1": 0.05, "f_c2": 0.05}
    # 期望: f_c1 = f_c2 = 0.05, primary 共 0.9, 按 4:3:2 = 0.4/0.3/0.2

def test_filter_factor_zeroed():
    """filter 角色因子权重置 0"""

def test_no_primary_warning():
    """无 primary, 仅 confirmation → warning + confirmation 占 100%"""

def test_sum_equals_one():
    """各种组合, 权重和 = 1.0 (1e-6 精度)"""

def test_integration_with_dimension_weights():
    """dimension + role 链式调用, 结果合理"""

def test_integration_with_cap():
    """role 后 cap, 极端情况不破坏"""
```

---

## §4 Don't — 禁止事项

| ❌ | 原因 |
|---|---|
| 在 `_apply_weights`（cap 之前）插入 role 处理 | 应在 dimension_weights 后，cap 前；位置错乱破坏抽象层级 |
| 删除 `FACTOR_ROLES` 静态分类 | 角色是因子固有属性，类似 dimension；不可动态计算 |
| 让 confirmation 因子参与 ICIR 加权 | 整个 R2 的意义就是把它隔离出来 |
| 让 filter 角色因子进入 composite | filter = stock_selector 硬过滤，不参与综合因子计算 |
| RollingICIR 强行支持 | 滚动版需重新设计（按日期窗口角色加权），不阻塞 R1-R3 |
| 改 `CONFIRMATION_WEIGHT_PER_FACTOR=0.05` 数值 | 这是 design.md 已审常量；要改需另开 design.md |

---

## §5 Why — 设计理由

### 5.1 为什么是后处理而非源头加权

ICIR/IC 是数据驱动权重，反映"过去 N 日因子有效性"。
角色（primary/confirmation）是**因子固有属性**（设计时确定），与数据无关。
后处理保持源头逻辑纯净，可读性高。

### 5.2 为什么 confirmation 不参与 ICIR

confirmation 因子 IC≈+0.02（低于 0.03 门槛），按 ICIR 自然加权会被赋 ~0 权重。
固定 5% 保证它"有发言权"，作为"企稳确认开关"用。

### 5.3 为什么 RollingICIR 推迟

滚动权重需要按日期窗口分别角色加权，涉及 weight_df 列操作。
属于独立工作量（~100 行 + 测试），与 R2 主线解耦。
当前 run_pipeline 默认用 `rolling_icir` 是 weight_selector 自动选的，可临时切回 `icir`。

---

## §6 When — 适用场景

**默认启用**: 所有 composite_*_1d.py。
**临时禁用**: `composite_runner --disable-role-weights`（仅作 ablation 实验用）。

---

## §7 Verify — 验证方法

```bash
# 1. 单元测试
pytest comprehensive_factor/test_cases/test_role_weights.py -v

# 2. 链路冒烟
python comprehensive_factor/composite_icir_weight_1d.py
# 查 log: "角色权重: primary=N (75%) + confirmation=M (25%) + filter=K (排除)"

# 3. weight 总和校验
python -c "
import json
data = json.load(open('comprehensive_factor/result/composite_icir_weight_1d.json'))
weights = data['meta']['weights']
total = sum(weights.values())
assert abs(total - 1.0) < 1e-6, f'weights 总和 = {total} ≠ 1.0'
print('PASS')
"

# 4. 选股回归（fin 阶段）
python comprehensive_factor/stock_selector.py
```

---

## §8 实施批次拆分（H9 ≤3 文件 ≤200 行）

| 批 | 文件 | 行数 |
|---|---|---|
| r2a | `comprehensive_factor/common/weight_engine.py` + `comprehensive_factor/test_cases/test_role_weights.py` | ~150 |
| r2b | `comprehensive_factor/common/composite_runner.py` + `comprehensive_factor/composite_icir_weight_1d.py` 等 4 个 + `run_pipeline.py`（仅 CLI 注释） | ~50 |

---

## §9 回滚预案

```bash
# 完全回滚
git revert <r2a_sha> <r2b_sha>

# 临时禁用（保留代码）
python composite_icir_weight_1d.py --disable-role-weights
```
