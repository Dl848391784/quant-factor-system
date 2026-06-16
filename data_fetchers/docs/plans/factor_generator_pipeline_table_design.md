# factor_generator.py generate_all_factors 表驱动重构 design

**版本**：v1.0
**日期**：2026-06-16
**作者**：云瑶
**状态**：已确认，执行中（D1 起）
**前置**：B 步搬迁 design（factor_generator_split_tail_intraday_design.md）已闭环

---

## 1. 背景与目标

`generate_all_factors`（行 270-887，~620 行）当前 step 3.5~11.9 段（行 443-663，~220 行）
存在严重模板重复：22 个 simple 因子 + 1 个 tail（5 列输出）+ 3 个 industry 因子族 + industry drop。

**目标**：以"元数据表 + helper 循环"替换重复调用，单文件减约 -190 行（946 → ~756）。
约束 #3（因子计算复用）已在 B 步恢复，本步聚焦"管线编排去重"。

---

## 2. 设计方案

### 2.1 元数据表

模块级 tuple of dict（与 `_OUTPUT_COLS` 风格对齐，遵循 MODULE.md R4）：

```python
_FACTOR_PIPELINE_STEPS: tuple[dict[str, Any], ...] = (
    # (step_label, factor_func, output_cols, valid_keys, log_label, kind)
    {"step_label": "Step 3.5: 计算当日涨跌幅因子...",
     "factor_func": calculate_past_return_1d,
     "output_cols": ("past_return_1d",),
     "kind": "simple"},
    # ... 22 项 simple
    {"step_label": "Step 11: 计算尾盘因子...",
     "factor_func": calculate_tail_factors,
     "output_cols": ("tail_price_position", "tail_price_slope",
                     "tail_price_volume_intensity", "tail_volume_acceleration",
                     "tail_volume_shrink"),
     "kind": "tail"},
    # ... 3 项 industry simple
)
```

### 2.2 Helper 函数（共 2 + 1 utility）

```python
def _run_simple_factor_step(
    factor_df: pd.DataFrame, step: dict, logger: logging.Logger,
) -> tuple[pd.DataFrame, dict[str, int]]:
    """处理单/多输出列的因子调用 + 日志 + 有效数统计。

    返回 (新 factor_df, {output_col: valid_count, ...})
    """

def _drop_industry_column(factor_df: pd.DataFrame) -> pd.DataFrame:
    """删除 industry 临时列（不属于 _OUTPUT_COLS）"""
```

> 注：tail 与 simple 用同一个 `_run_simple_factor_step`——只是 output_cols 长度不同，循环
> 统计每列即可，kind 字段保留供未来扩展（如某类因子需要特殊预处理时）。当前实现里
> tail 与 simple 走同一分支。

### 2.3 step 半代号分组

| step | 因子数 | 备注 |
|------|--------|------|
| 3.5 | 1 | past_return_1d |
| 4-9 | 8 | bollinger_pb, kdj_j, turnover_surge, amplitude, price_position, return_5d, momentum_strength, overnight_ret |
| 10 | 1 | intraday_intensity |
| 11 | 1 → 5 列 | tail（特殊 output_cols 长度=5）|
| 11.5 | 4 | amplitude_delta, turnover_surge_delta, tail_price_position_delta, tail_volume_shrink_delta |
| 11.6 | 4 | volume_price_strength, positive_day_ratio_5, ma5_deviation, near_high_ratio_5 |
| 11.7 | 3 | industry_momentum_5d, industry_turnover_trend, industry_amplitude_trend |
| 11.8 | 3 | industry_roe_trend, industry_earnings_growth, industry_pe_trend |
| 11.9 | 2 | capital_flow_ratio_trend, capital_flow_intensity（之后 industry drop）|
| **合计** | **26 simple + 1 tail = 27 项 → 31 输出列** | |

### 2.4 valid_counts 累积

```python
valid_counts: dict[str, int] = {}
for step in _FACTOR_PIPELINE_STEPS:
    factor_df, step_valid = _run_simple_factor_step(factor_df, step, logger)
    valid_counts.update(step_valid)
factor_df = _drop_industry_column(factor_df)  # step 11.9 末尾
```

metadata 段（D3 内）：
```python
"valid_records": {key: valid_counts[key] for key in _VALID_KEY_ORDER},
"valid_records_percent": {key: _calc_pct(valid_counts[key], total_records)
                          for key in _VALID_KEY_ORDER},
```
`_VALID_KEY_ORDER` 是 31 个 key 的 tuple，定义顺序 = 表里 output_cols 拼接顺序。
（**注**：E 步会把这两段也拍平为单一派生；D 步保持显式 dict comprehension 引用，方便 review。）

---

## 3. 4 轮细拆

| 轮 | 范围 | 编辑预算 | 净 | commit 时机 |
|----|------|---------|-----|-------------|
| D1 | 建 `_FACTOR_PIPELINE_STEPS` 表 + `_VALID_KEY_ORDER`，零调用切换 | +120 / 0 | +120 | ruff + collect-only OK 即提交 |
| D2 | 实现 `_run_simple_factor_step` + `_drop_industry_column`，零调用切换 | +60 / 0 | +60 | 同上 + 表驱动单元 smoke |
| D3 | 切换 step 3.5~11.9 + metadata `valid_records` / `valid_records_percent` 替换 | +30 / -250 | -220 | ruff + 包导入 + 脚本入口 + pytest collect + 端到端 smoke 一次 |
| D4 | design.md 状态闭环 + 视情况 MODULE.md 微调 | +15 / -2 | +13 | 最后一次 |

**累计预算**：+225 / -252 = **净 -27 行**？看似少。复盘原代码：

- step 3.5~11.9 段 ~220 行 = 22 simple × ~5 行 + tail × 27 行 + 注释 + 行业 drop
- D3 替换后约 30 行调用 + 20 行 metadata dict comp = 50 行
- **段内净 -170 行**，但 D1+D2 又增 180 行（表 + helper）→ 整体 **+10 行净**

**修正预期**：D 步的真实价值不是减行数，是**减重复模式**——
- 新增因子从"3 处编辑（func + step 段 + metadata 两个 dict）"减为"1 处编辑（表里加一行）"
- 行数小幅波动；瘦身主要靠 E 步（metadata 派生 -50）+ F 步（I/O helper -80）

**修订**：把 D1 表设计紧凑些（每项 1 行 dict literal），把 D2 helper 写紧凑，预期 -50 行净。

---

## 4. 关键设计决定

1. **表形态**：tuple of dict（模块级私有常量，R4 规范）
2. **行业族**：每项独立列出，drop 用独立 utility
3. **valid_counts 接口**：helper 返回 `(df, dict)`，主函数累积
4. **tail 5 列**：与 simple 同一 helper，靠 output_cols 长度区分
5. **日志兼容**：step_label 一致 / `有效 xxx:` 行格式一致

---

## 5. 兼容性

| 维度 | D 步前 | D 步后 |
|------|-------|-------|
| `generate_all_factors` 签名 | 不变 | 不变 |
| 输出 schema (`_OUTPUT_COLS`) | 不变 | 不变 |
| metadata 字段 keys | 不变 | 不变 |
| 日志 `Step xx.x:` / `有效 xxx:` 行 | 现状 | 字符级一致 |
| factor_calculator 公共 API | 不变 | 不变 |

下游 factor_ic / backtest / comprehensive_factor / summary 零修改。

---

## 6. 状态闭环

| 轮 | commit | 时间 | 状态 |
|---|--------|------|------|
| D1 | `<待填>` | 2026-06-16 | ✅ 已完成（27 项表 + 31 项 _VALID_KEY_ORDER；ruff/包导入/校验全过） |
| D2 | — | — | 待执行 |
| D3 | — | — | — |
| D4 | — | — | — |
