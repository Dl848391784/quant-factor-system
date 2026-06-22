# v2.40: 家族权重上限 + 流动性硬过滤（B 方案）

> 根因：v2.39 验证交互因子门槛后，振幅信号族(amplitude_compression 25% + interaction_amp_compression 13.75% = 38.75%)主导权重，叠加 volume 族(18.09%) + price_position(14.33%) → "阴跌组合" 71.17% 权重。Top10 alpha 实测 -4.45%/6d。
>
> 关联：factor-diversity-and-classification.md §15.9

---

## §1 决策矩阵

| 选项 | 原理 | ROII | 影响范围 | 复杂度 |
|------|------|------|---------|--------|
| **A: 家族级权重上限** | 在单因子 cap(25%) 之后，再聚合到"经济含义族"施加族级 cap(30%) | 高——直接切断振幅族垄断 | weight_engine.py + factor_definitions.py + 测试 | 中 |
| **B: 流动性硬过滤** | stock_selector 阶段剔除流动性枯竭票（成交额 < N） | 高——直接用否定权保护排序不扩散到尾部 | stock_selector.py + 测试 | 低 |
| **C: 扩充 IC 正向因子** | 开发新因子族 | 中——需 ≥3 个才有效，中远期 | 新因子（本次不做） | 高 |

**B 方案 = A + B**。C 作为后续方向。

**为什么 A+B 不违反第一性原理**：
- A（家族级 cap）= 从因子库层约束**权重结构**，不是针对"阴跌"调参数，而是普适性防垄断规则
- B（流动性过滤）= 从选股层消除 IC 线性假设在**尾部分位的固有失效**，不是调阈值而是用硬约束切断排序扩散到流动性枯竭区

两个改动**层级正确**（分别在因子库层和选股层），不是"一个层级打补丁弥补另一层级缺陷"。

---

## §2 改动总览

| 文件 | 改动量 | 性质 |
|------|--------|------|
| `factor_definitions.py` | +~35 行 | 新增 `FACTOR_FAMILIES` dict |
| `weight_engine.py` | +~70 行 | 新增 `_cap_family_weight` + 调用点 2 处 |
| `stock_selector.py` | +~25 行 | sort_and_select 新增 enable_liquidity_filter + min_amount |
| `test_cases/test_dimension_weight.py` | +~50 行 | 新增族级 cap 测试 |
| `test_cases/test_stock_selector.py` | +~30 行 | 新增流动性过滤测试 |

---

## §3 A：家族级权重上限

### 3.1 FACTOR_FAMILIES 定义（factor_definitions.py）

比 FACTOR_CATEGORIES（8 维度）更粗粒度的**经济含义族**映射：

```
FACTOR_FAMILIES: dict[str, str] = {
    # === 振幅族（流动性的振幅维度） ===
    "amplitude": "amplitude_family",
    "amplitude_delta": "amplitude_family",
    "amplitude_compression": "amplitude_family",
    "range_compression": "amplitude_family",
    # interaction_amp_compression 原始信号 = weakness × amplitude_compression_z
    # 同源 amplitude_compression 信号
    "interaction_amplitude": "amplitude_family",
    "interaction_amp_compression": "amplitude_family",

    # === 量能族 ===
    "volume_ratio": "volume_family",
    "volume_decay_rate": "volume_family",
    "volume_shrink_rate": "volume_family",
    "volume_price_strength": "volume_family",
    "price_volume_divergence": "volume_family",
    "turnover_surge": "volume_family",
    "turnover_surge_delta": "volume_family",
    "turnover_decay_rate": "volume_family",
    "interaction_turnover": "volume_family",
    "interaction_intraday": "volume_family",

    # === 价格位置族 ===
    "price_position": "price_family",
    "bollinger_pb": "price_family",
    "tail_price_position": "price_family",
    "tail_price_position_delta": "price_family",
    "interaction_price_pos": "price_family",
    "interaction_near_high": "price_family",
    "interaction_bollinger": "price_family",

    # === 动量/趋势族 ===
    "momentum_strength": "momentum_family",
    "return_3d": "momentum_family",
    "return_5d": "momentum_family",
    "rsi": "momentum_family",
    "kdj_j": "momentum_family",
    "ma5_deviation": "momentum_family",
    "ma5_slope": "momentum_family",
    "rsi_slope_3d": "momentum_family",
    "near_high_ratio_5": "momentum_family",
    "past_return_1d": "momentum_family",
    "positive_day_ratio_5": "momentum_family",
    "return_acceleration_5d": "momentum_family",
    "downside_deceleration": "momentum_family",
    "interaction_ma5_dev": "momentum_family",
    "interaction_kdj": "momentum_family",

    # === 尾盘行为族 ===
    "tail_price_slope": "tail_family",
    "tail_price_volume_intensity": "tail_family",
    "tail_volume_acceleration": "tail_family",
    "tail_volume_shrink": "tail_family",
    "tail_volume_shrink_delta": "tail_family",

    # === 隔夜族 ===
    "overnight_ret": "overnight_family",

    # === 资金流族 ===
    "capital_flow_ratio_trend": "capital_flow_family",
    "capital_flow_intensity": "capital_flow_family",

    # === 行业族 ===
    "industry_momentum_5d": "industry_family",
    "industry_turnover_trend": "industry_family",
    "industry_amplitude_trend": "industry_family",
    "industry_roe_trend": "industry_family",
    "industry_earnings_growth": "industry_family",
    "industry_pe_trend": "industry_family",

    # === 无归类 ===
    "lower_shadow_ratio": "uncategorized_family",
    "intraday_intensity": "uncategorized_family",
}
```

**设计原则**：
- 经济同源归一族：interaction_amp_compression 原始信号 = weakness × amplitude_compression_z，同源 amplitude_compression → 归振幅族
- interaction_kdj 和 interaction_ma5_dev 原始信号 = 弱票×动量信号 → 动量族（不是新维度）
- interaction_intraday 原始信号 = weakness × intraday_intensity_z，intraday_intensity 属量能 → 量能族

### 3.2 _cap_family_weight 算法（weight_engine.py）

在 `_cap_single_factor_weight` 和 `_apply_dimension_weights_static` **之间**插入 `_cap_family_weight`：

```
算法:
1. 输入: 已单因子 capped 的 weights dict + factor_cols + FACTOR_FAMILIES + 族 cap
2. 按 FACTOR_FAMILIES 聚合: family_total = sum(abs(w) for w in family_cols)
3. 迭代摊分（与 _cap_single_factor_weight 同构）:
   while any(family_total > FAMILY_CAP):
       excess = sum(family_total - FAMILY_CAP for over-cap families)
       over-cap families 内部按原权重比例降权至 FAMILY_CAP
       under-cap families 按原权重比例分摊 excess
       迭代直到所有族 ≤ FAMILY_CAP
4. 输出: 调整后的 weights dict（族级受限，因子级比例不变）
```

**FAMILY_CAP 选择**：
- 8 个 family → 理论 12.5%等权 → 但 IC 加权应有更多
- Asness(2013) AQR 多因子产品: 任意策略 ≤ 33%
- 当前问题：振幅族 38.75% → 用 **30%** 作为 balance（8.75% 被砍到 5 个其他族分配）
- 物理可行性：最小时 4 族各 30%=120%>100% → 可解（当前实际有 5-8 族非零）

**调用点**：

| 加权方法 | 插入位置 |
|---------|---------|
| EqualWeightMethod.calculate | cap → family_cap → dim_weight |
| ICIRWeightMethod.calculate | cap → family_cap → dim_weight |
| ICWeightMethod.calculate | cap → family_cap → dim_weight |
| RollingICIRWeightMethod._apply_dimension_weights | 矩阵化版本，最后加入行级 family cap |

**默认值**：
```python
FAMILY_CAP_DEFAULT = 0.30  # 30%，防振幅族主导
FACTOR_FAMILIES = {}  # 由调用方传入; 空 dict 时跳过 family cap
```

### 3.3 预期效果（定量推演）

v2.39 权重 | 族 cap 后估计：
- amplitude_family: 38.75% → **30.00%** ✅
- volume_family: 18.09% + 从振幅族收到 5.53% → **23.62%** ⬆
- price_family: 14.33% + 从振幅族收到 1.61% → **15.94%** ⬆
- momentum_family: 10.00% → **10.00%**
- 其他 4 族: 8.73% + 从振幅族收到 1.61% → **10.34%**

**选股预期**：Top10 不再被"低振幅+缩量"主导。owie 的流动性枯竭股排名下降，动量/尾盘/资金流等"不阴跌"的维度权重上升。

---

## §4 B：流动性硬过滤（stock_selector.py）

### sort_and_select 新增参数（v2.40 实际实现）

```python
def sort_and_select(
    ...,
    enable_liquidity_filter: bool = True,        # 默认开（cli/SelectionConfig 可关）
    min_amount_percentile: float = 0.05,         # 截面分位阈值（默认底部 5%）
    ...
)
```

**关键设计变更（vs 第一版草稿）**：
- ~~`min_amount: float = 5_000_000`（固定 500 万元）~~ → **`min_amount_percentile: float = 0.05`（截面分位）**
- ~~`enable_liquidity_filter: bool = False`~~ → **`True`**（默认开启）

### 实现逻辑（截面百分位，第一性原理）

在 `valid_mask` 阶段（覆盖率过滤之后、振幅过滤之前）增加：

```python
if enable_liquidity_filter and "volume" in result_df.columns and "close" in result_df.columns:
    amount = result_df["volume"] * result_df["close"]
    # 截面阈值：每日 P5 分位
    amount_threshold = amount.quantile(min_amount_percentile)
    liquidity_mask = amount >= amount_threshold
    excluded_by_liquidity = int((~liquidity_mask & valid_mask).sum())
    valid_mask = valid_mask & liquidity_mask
    logger.info(
        "流动性过滤: 排除 %d 只 (amount < P%.0f = %.0f 元)",
        excluded_by_liquidity, min_amount_percentile * 100, amount_threshold,
    )
else:
    excluded_by_liquidity = 0  # 列缺失或开关关闭，安全跳过
```

### 为什么改成截面百分位（第一性原理）

| | 固定 500 万元（草稿） | 截面 P5（实现） |
|---|---|---|
| **依据** | 经验值，无理论 | 截面分布自适应 |
| **市场环境** | 牛市萎缩日全市场都被刷 / 熊市放量日没人被刷 | 始终是"今日最差的 5%" |
| **可移植性** | 转 1 分钟 / 港股 / 美股需重新校准 | 跨频跨市场自适应 |
| **第一性原理** | ✗ 调参数式（数据分布漂移即失效） | ✓ 分布尾部切除（任何分布下成立） |

符合 AGENTS.md "调参数式修复 vs 第一性原理推导" 元规则。

### factor_df 上游列追加（composite_runner）

为支持流动性过滤，`composite_runner.py` 两个分支（auto_select=True/False）都在 `factor_df` 提取列时追加 `volume, close`：

```python
factor_required_cols = ["date", "asset"] + factor_cols
for liq_col in ("volume", "close"):
    if liq_col in full_df.columns and liq_col not in factor_required_cols:
        factor_required_cols.append(liq_col)
factor_df = full_df[factor_required_cols].copy()
```

列缺失时（如某些上游数据源），stock_selector 通过 `if "volume" in result_df.columns` 安全跳过过滤，不报错。

### 与现有过滤的协调

```
现有过滤顺序:
  valid_mask (composite NaN) 
  → 覆盖率过滤 (coverage < 50%)
  → 振幅过滤 (amplitude < 1%)   [v1.12]
  → 单因子暴露限制 (max_exposure)  [v2.20]
  → 排序选股

本次加入:
  valid_mask → 覆盖率过滤 → 流动性过滤 → 振幅过滤 → 暴露限制 → 排序
```

**为什么流动性在振幅之前**：不流动的票比振幅不足更严重——振幅不足可能是一字板（仍有流动性），不流动则没有任何买入出口。

---

## §5 测试计划

### 5.1 族级 cap 测试（test_dimension_weight.py 追加）

| 测试 | 场景 | 断言 |
|------|------|------|
| `test_family_cap_basic` | 3 个因子同一族超出 30% | 族合计 ≤ 30% |
| `test_family_cap_two_families` | 两族分别在 25%、35% | 超的降到 30%，不超的不变 |
| `test_family_cap_all_under` | 所有族 ≤ 30% | 权重不变 |
| `test_family_cap_physical_check` | 1 族 2 因子各 30%=60%<100% | skip（n×cap < 1.0） |
| `test_family_cap_integration` | _apply_weights 完整链路 cap→family→dim | 最终权重 sum=1.0 |

### 5.2 流动性过滤测试（test_liquidity_filter.py，独立文件）

| 测试 | 场景 | 断言 |
|------|------|------|
| `test_disabled_by_default` | enable_liquidity_filter=False | 不过滤，结果不变 |
| `test_enabled_excludes_low_amount` | enable=True, P25 | 5 只低成交额股票被排除 |
| `test_missing_volume_column_skipped` | volume 列缺失 | 安全跳过 + warning 日志 |
| `test_zero_percentile_no_exclusion` | min_amount_percentile=0 | 阈值=min(amount), 不排除 |
| `test_top_n_respects_filter` | 极低成交额股票 composite 最优 | top_n 不包含被流动性排除股票 |

---

## §6 风险与回退

| 风险 | 概率 | 缓解 |
|------|------|------|
| 振幅族降到 30% 后选股大幅变化 | 低 | 扩散到其他族更健康，监测 7 天 |
| 流动性过滤误杀暴涨前的小盘股 | 中 | 默认 P5（截面 5%）保守；SelectionConfig.enable_liquidity_filter=False 可关 |
| FACTOR_FAMILIES 映射错误归类 | 低 | 映射公开，review 可校验 |
| 2 个改动叠加效果不可预测 | 中 | 按 A→B 顺序分两次提交、独立验证 |

---

## §7 提交计划

```
1. factor_definitions.py  ← 新增 FACTOR_FAMILIES + 测试
2. weight_engine.py       ← _cap_family_weight + 调用点
3. 跑 test_dimension_weight.py + ruff check
4. stock_selector.py      ← 流动性过滤参数 + 逻辑
5. 跑 test_stock_selector.py + ruff check
6. pipeline --start-stage 4 验证
7. 读实际 stock_selection_result 比对 Top10
8. git commit
```

---

## §8 附录：引用规范

- PROJECT.md 规则 #5（因子方向根据 IC 确定）——不违反，家族 cap 不改变方向
- PROJECT.md 规则 #14（死代码禁止）——新增代码不造成死分支
- MODULE.md M16a（交互因子独立门槛）——不冲突，B 方案与 M16a 正交
- MODULE.md M49（sys.path 处理）——继承现有
- factor-diversity-and-classification.md §15.9——B 方案直接响应"维度族权重硬上限"和"极端分位流动性硬过滤"