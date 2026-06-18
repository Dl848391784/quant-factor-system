# 行业中性化 IC 计算流程文档

> 生成时间: 2026-06-18 (北京时间)
> 审阅版本: v1.0
> 实施完成日期: 2026-06-18
> 流程归属: `factor_ic/common/` 公共流程（跨因子复用）
> 配套规范: `factor_ic/MODULE.md` M66 (类别 L. 行业中性化)
> 配套设计: `.hermes/plans/factor-ic-industry-neutralization-design.md`

---

## 一、流程目的

为每个非行业类因子在标准 IC 计算之上额外输出一套**行业中性化 IC**（neutral IC），通过对比 raw IC 与 neutral IC 诊断因子 alpha 的来源：

| 衰减率 (decay_rate) | 解读 | 因子结论 |
|---|---|---|
| `< 30%` (low) | neutral IC 与 raw IC 接近 → 行业 beta 占比小 | **真 alpha**，行业中性化后仍有效 |
| `≥ 30%` (high) | neutral IC 显著小于 raw IC → 行业 beta 占主导 | alpha 主要来自**行业 beta**，非个股层面真 alpha |
| `< 0%` (inverse) | neutral IC 反向于 raw IC | 因子方向被行业掩盖，需重新评估 |

> 核心公式：`decay_rate = 1 - |neutral_ic_mean| / |raw_ic_mean|`

---

## 二、输入输出契约

### 输入
| 字段 | 来源 | 类型 | 说明 |
|---|---|---|---|
| factor_df | 上游 IC runner | DataFrame | 含 `[date, asset, <factor_col>]` |
| return_df | 上游 IC runner | DataFrame | 含 `[date, asset, return_*]` |
| industry_map | `data_fetchers/fetch_industry.get_industry_map()` | dict | `{asset → industry_name}` |
| neutralize | CLI / 调用方 | bool | 默认 `True`；`False` 跳过中性化 |

### 输出（顶层 `ic_neutral_industry` 字段）

| 路径 | enabled | 字段数 | 字段清单 |
|---|---|---|---|
| **disabled** | `False` | 2 | `enabled`, `skipped_reason` |
| **enabled** | `True` | 13 | `enabled`, `ic_mean`, `ic_std`, `icir`, `p_value`, `p_value_display`, `positive_ratio`, `n_days`, `dates`, `ic_values`, `decay_rate`, `decay_level`, `min_industry_stocks` |

> **互斥约束**：由 `factor_ic/schemas/ic_analysis_result.schema.json` 的 `oneOf` + `additionalProperties: false` 强制（详见 R21a commit `06e58f4`）。

---

## 三、决策流程图

```
┌─────────────────────────────────────────────────────────────────┐
│  run_factor_ic_analysis(factor_name, neutralize=True, ...)      │
│  (factor_ic/common/factor_ic_runner.py)                         │
└──────────────────────────────┬──────────────────────────────────┘
                               │
                               ▼
        ┌──────────────────────────────────────────────────┐
        │  Step 1: raw IC 计算（现有主流程，不受影响）       │
        │  → ic_metrics + factor_direction + statistical... │
        └──────────────────────────────┬───────────────────┘
                                       │
                                       ▼
        ┌──────────────────────────────────────────────────┐
        │  Step 2: _resolve_neutralize_decision()           │
        │  优先级 #1 排除清单 > #2 用户禁用                   │
        └──────┬─────────────────┬─────────────────┬───────┘
               │                 │                 │
   factor 在排除清单           neutralize=False      其余情况
   (industry_*/capital_flow_*) (用户显式禁用)       (默认走中性化)
               │                 │                 │
               ▼                 ▼                 ▼
        enabled=False      enabled=False        enabled=True
        skipped_reason=    skipped_reason=
        EXCLUDED           USER_DISABLED
               │                 │                 │
               │                 │                 ▼
               │                 │      ┌──────────────────────────┐
               │                 │      │ Step 3: 残差回归           │
               │                 │      │ a) merge_industry_column  │
               │                 │      │ b) 剔除 '其他' 行业         │
               │                 │      │ c) industry_neutral_      │
               │                 │      │    residual()             │
               │                 │      │ d) IC on 残差 → neutral_ic │
               │                 │      └──────────┬───────────────┘
               │                 │                 │
               │                 │                 ▼
               │                 │         ┌─────────────────┐
               │                 │         │  成功 / 失败？    │
               │                 │         └────┬────────┬───┘
               │                 │              │ 成功    │ 失败 (NaN/...)
               │                 │              ▼        ▼
               │                 │      enabled=True  enabled=False
               │                 │      13 字段       skipped_reason=
               │                 │      payload      "computation failed:..."
               │                 │              │        │
               └─────────────────┴──────────────┼────────┘
                                                ▼
        ┌──────────────────────────────────────────────────┐
        │  Step 4: build_ic_result(ic_neutral_payload=...)  │
        │  → _normalize_neutral_payload() 校验+顺序固定     │
        │  → result["ic_neutral_industry"] = 标准化 schema   │
        └──────────────────────────────┬───────────────────┘
                                       │
                                       ▼
        ┌──────────────────────────────────────────────────┐
        │  Step 5: validate_and_save_output()               │
        │  → schema oneOf 校验 + additionalProperties=false │
        │  → 写入 factor_ic/result/ic_<因子>_*.json          │
        └──────────────────────────────────────────────────┘
```

**关键决策点**：
1. **优先级**：排除清单 > 用户禁用（`industry_*` 因子即使 `neutralize=True` 也强制 disabled）
2. **降级原则**：Step 3 失败 → disabled payload（不污染 raw IC 主流程）
3. **'其他' 行业剔除**：行业映射缺失的股票被聚到 '其他'，无法估计行业 beta，剔除避免污染残差
4. **min_industry_stocks**：默认 5（每个行业 < 5 只股票时无法稳定估计行业均值），少于阈值的行业整体剔除


---

## 四、schema 与真实数据示例

> R22c 待补

---

## 五、异常降级路径

> R22d 待补

---

## 六、验证方法

> R22d 待补

---

*最后更新: 2026-06-18*
