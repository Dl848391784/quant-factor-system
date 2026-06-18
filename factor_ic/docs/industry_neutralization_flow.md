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

### 4.1 schema 定义（`factor_ic/schemas/ic_analysis_result.schema.json`）

`ic_neutral_industry` 字段使用 `oneOf` 双路径：

```jsonc
"ic_neutral_industry": {
  "oneOf": [
    {  // 路径 A: disabled (2 字段)
      "type": "object",
      "properties": {
        "enabled": {"const": false},
        "skipped_reason": {"type": "string"}
      },
      "required": ["enabled", "skipped_reason"],
      "additionalProperties": false
    },
    {  // 路径 B: enabled (13 字段)
      "type": "object",
      "properties": {
        "enabled": {"const": true},
        "ic_mean": {"type": "number"},
        "ic_std": {"type": "number"},
        "icir": {"type": "number"},
        "p_value": {"type": "number"},
        "p_value_display": {"type": "string"},
        "positive_ratio": {"type": "number"},
        "n_days": {"type": "integer"},
        "dates": {"type": "array", "items": {"type": "string"}},
        "ic_values": {"type": "array", "items": {"type": "number"}},
        "decay_rate": {"type": "number"},
        "decay_level": {"enum": ["high", "low", "inverse", "undefined"]},
        "min_industry_stocks": {"type": "integer"}
      },
      "required": [/* 全部 13 字段 */],
      "additionalProperties": false
    }
  ]
}
```

> 双层防御：`oneOf` 互斥 + `additionalProperties: false` 防字段污染。

### 4.2 R20 实测三因子对照表（2024-05-13 ~ 2026-06-13，509 交易日）

| 因子 | raw IC mean | neutral IC mean | decay_rate | decay_level | 备注 |
|---|---|---|---|---|---|
| `rsi_1d` | -0.0396 | -0.0304 | **23.3%** | `low` | 真 alpha，行业 beta 占比小 |
| `amplitude_1d` | -0.0574 | -0.0494 | **13.9%** | `low` | 真 alpha，几乎不受行业影响 |
| `overnight_ret_1d` | 0.0212 | — | — | — | 残差回归含 NaN，降级 disabled（见 §5） |

### 4.3 enabled payload 实例（`ic_rsi_1d_analysis_result.json` 摘录）

```jsonc
{
  "ic_neutral_industry": {
    "enabled": true,
    "ic_mean": -0.030356,
    "ic_std": 0.106727,
    "icir": 0.2844,
    "p_value": 1.22e-14,
    "p_value_display": "1.22e-14",
    "positive_ratio": 0.3733,
    "n_days": 509,
    "dates": ["2024-05-13", "2024-05-14", /* ... */],
    "ic_values": [/* 509 个每日 IC */],
    "decay_rate": 0.2330,
    "decay_level": "low",
    "min_industry_stocks": 5
  }
}
```

### 4.4 disabled payload 实例（`ic_overnight_ret_1d_analysis_result.json`）

```jsonc
{
  "ic_neutral_industry": {
    "enabled": false,
    "skipped_reason": "computation failed: Input y contains NaN."
  }
}
```

### 4.5 行业映射统计（参考）

```
全样本                  1,491,862 行
├─ '其他' 行业剔除        -392,021 行 (26.3%)
└─ 参与残差回归          1,099,841 行
    └─ 有效残差          1,099,487 行 (剔除回归 NaN 等)
```

> 数据来源: `data_fetchers/fetch_industry.get_industry_map()`；统计基于 R20 全量回测日志。


---

## 五、异常降级路径

行业中性化是诊断信息，**绝不允许污染主流程 raw IC**。所有失败路径都降级为 `enabled=false` payload。

### 5.1 降级触发条件

| # | 触发场景 | skipped_reason 值 | 实际案例 |
|---|---|---|---|
| 1 | factor 在排除清单（`industry_*`, `capital_flow_*`） | `"EXCLUDED: factor in exclusion list"` | `industry_momentum_5d` |
| 2 | 用户 CLI `--no-neutralize` 显式禁用 | `"USER_DISABLED: neutralize=False"` | `--neutralize false` |
| 3 | 行业映射全部为 `'其他'`（剔除后无行业可残差） | `"computation failed: <详情>"` | 罕见 |
| 4 | 残差回归输入含 NaN（sklearn LinearRegression 拒收） | `"computation failed: Input y contains NaN."` | `overnight_ret_1d` (R20) |
| 5 | 残差全为 0（常数列，IC 未定义） | enabled=True + decay_level=`high`/`undefined` | R15d 集成测试 |
| 6 | 单行业股票数 < `min_industry_stocks=5` | 该行业整体剔除（不触发降级） | 小盘行业 |

### 5.2 降级实现位置

```python
# factor_ic/common/factor_ic_runner.py: _compute_industry_neutral_ic
try:
    residual = industry_neutral_residual(...)
    neutral_ic = compute_ic(residual, return_series)
    return {"enabled": True, ..., 13 字段}
except Exception as exc:
    logger.exception("Industry neutral computation failed for %s", factor_name)
    raise RuntimeError(f"computation failed: {exc}") from exc

# 上层 run_factor_ic_analysis 捕获:
try:
    neutral_payload = _compute_industry_neutral_ic(...)
except RuntimeError as exc:
    neutral_payload = {"enabled": False, "skipped_reason": str(exc)}
```

> **设计原则**：低层抛 `RuntimeError`（带 `from exc` 异常链）→ 上层捕获降级。raw IC 主流程独立完成，不受中性化失败影响。

### 5.3 已知 follow-up

`overnight_ret_1d` 在 R20 实测中触发场景 #4，根因待排查（独立 follow-up，不在 R22 范围）：
- 假设 1：`industry_neutral_residual` 函数 dropna 不彻底
- 假设 2：上游因子计算输出含 NaN，merge 后行业列正常但因子列含 NaN
- 验证方向：`assert not np.isnan(y).any()` + 逐步排查

---

## 六、验证方法

### 6.1 schema 校验

```bash
cd factor_ic && python3.11 -c "
import json, jsonschema
schema = json.load(open('schemas/ic_analysis_result.schema.json'))
result = json.load(open('result/ic_rsi_1d_analysis_result.json'))
jsonschema.validate(result, schema)
print('OK')
"
```

### 6.2 单元测试

```bash
# runner 决策优先级 (R15a-e, 6 case)
pytest factor_ic/test_cases/test_factor_ic_runner_neutralize.py -v

# builder 双路径 schema 校验 (R17a-c, 21 case)
pytest factor_ic/test_cases/test_ic_result_builder_neutral.py -v

# summary 中性化敏感列展示 (R19a-b, 13 case)
pytest summary/test_cases/test_neutral_cell.py -v
```

### 6.3 全量回测验证

```bash
# 单因子真实数据
python3.11 -m factor_ic.ic_rsi_1d --force-full

# 检查输出 schema
python3.11 -c "
import json
d = json.load(open('factor_ic/result/ic_rsi_1d_analysis_result.json'))
n = d['ic_neutral_industry']
assert n['enabled'] in (True, False)
if n['enabled']:
    assert set(n.keys()) == {'enabled', 'ic_mean', 'ic_std', 'icir', 'p_value',
        'p_value_display', 'positive_ratio', 'n_days', 'dates', 'ic_values',
        'decay_rate', 'decay_level', 'min_industry_stocks'}
    print(f'decay={n[\"decay_rate\"]:.1%} level={n[\"decay_level\"]}')
"
```

### 6.4 衰减率三档分布巡检

```bash
# summary 报告自动展示"中性化敏感"列, 巡检 high 因子
python3.11 -m summary.generate_factor_summary_report
grep -E "\\d+% ⚠" summary/result/factor_summary_report_*.txt
```

> high 因子（衰减率 ≥ 30%）需重点审视：alpha 是否主要来自行业 beta，是否需要在策略层面行业中性化或剔除。

---

## 七、版本历史

| 版本 | 日期 | 变更 |
|---|---|---|
| v1.0 | 2026-06-18 | 初版（R22 行业中性化 [experimental] 项目闭环） |

---

*最后更新: 2026-06-18*

