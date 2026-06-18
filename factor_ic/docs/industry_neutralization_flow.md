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

> R22b 待补 ASCII 决策树

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
