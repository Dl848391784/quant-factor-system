# Design: 综合因子加权改用中性化 IC（Plan D）

> 日期：2026-06-18
> 决策来源：用户选择 Plan D（用中性化 IC 加权替代 raw IC 加权）
> 涉及文件：`comprehensive_factor/common/factor_loader.py`、`comprehensive_factor/common/weight_engine.py`（2 文件）

---

## §1 背景与问题

### 现状

IC JSON 中 `ic_neutralized` 字段已包含经行业+log(流通市值)中性化后的完整 IC 统计：

```json
{
  "ic_metrics": { "ic_mean": -0.057, "icir": 0.35 },     // raw
  "ic_neutralized": {
    "enabled": true,
    "icir": 0.62,                                          // neutralized
    "ic_mean": -0.054,
    "decay_rate": 0.061,
    "decay_level": "low",
    "ic_values": [...],                                    // neutralized 日序列
    "dates": [...]
  }
}
```

但综合因子加权链路完全使用 raw IC：

| 环节 | 代码位置 | 数据源 | 问题 |
|------|---------|--------|------|
| `load_ic_results()` | factor_loader.py L330 | `ic_metrics` only | `ic_neutralized` 被丢弃 |
| `ICIRWeightMethod` | weight_engine.py L310 | `ic_results[name]["icir"]` | raw ICIR 含行业/市值 beta |
| `ICWeightMethod` | weight_engine.py L399 | `ic_results[name]["ic_mean"]` | raw IC mean 同上 |
| `RollingICIRWeightMethod` | weight_engine.py L460 | `load_ic_daily()` raw series | raw IC 日序列 |

### 后果

`decay_level="high"` 的因子（decay_rate ≥ 30%），其 raw ICIR 虚高——至少 30% 的预测力来自行业/市值暴露而非个股 alpha。综合因子因此系统性超配行业/市值 beta 驱动的因子。

---

## §2 方案设计

### 核心原则

**权重计算改用中性化 IC，因子筛选标准不变。**

- 筛选（factor_selector）：仍用 raw IC——筛选问的是"有没有预测力"，raw IC 回答这个问题
- 加权（weight_engine）：改用 neutralized IC——加权问的是"纯 alpha 贡献多大"，neutralized IC 回答这个问题

### 改动范围

| 文件 | 函数 | 改动 |
|------|------|------|
| `factor_loader.py` | `load_ic_results()` | 提取 `ic_neutralized.icir`/`ic_mean`/`enabled`/`decay_level` 并注入 `ic_results` |
| `factor_loader.py` | `load_ic_daily()` | 当 `ic_neutralized.enabled=True` 时优先用 `ic_neutralized.ic_values`/`dates` |
| `weight_engine.py` | `ICIRWeightMethod.get_weights()` | 优先 `neutralized_icir`，fallback raw `icir` |
| `weight_engine.py` | `ICWeightMethod.get_weights()` | 优先 `neutralized_ic_mean`，fallback raw `ic_mean` |
| `weight_engine.py` | `RollingICIRWeightMethod.calculate()` | 无改动（数据源由 `load_ic_daily()` 控制） |

### 数据流（改后）

```
IC JSON
  ├─ ic_metrics.icir = 0.35 (raw)
  └─ ic_neutralized.icir = 0.62 (neutralized, enabled=True)
        │
  factor_loader.load_ic_results()
        │  ic_results['amplitude'] = {
        │    'icir': 0.35,                    # raw (保留，供筛选/日志)
        │    'neutralized_icir': 0.62,        # NEW
        │    'neutralized_enabled': True,     # NEW
        │    'decay_level': 'low',            # NEW
        │  }
        │
  weight_engine.ICIRWeightMethod.get_weights()
        │  icir = neutralized_icir if enabled else raw icir
        │  icir = 0.62  (而非 0.35)
        │
  → weight = 0.62 / sum(all neutralized ICIRs)
```

### Fallback 规则

| 条件 | 使用值 | 理由 |
|------|--------|------|
| `ic_neutralized.enabled=True` 且 `icir` 非 None | `neutralized_icir` | 正常路径 |
| `ic_neutralized.enabled=False` | raw `icir` | 因子在排除清单中，未做中性化 |
| `ic_neutralized` 字段缺失 | raw `icir` | 旧版 IC 结果文件兼容 |
| `neutralized_icir` 为 None | raw `icir` | 中性化计算失败（如 raw_ic_mean≈0） |

### 与 short_sample 惩罚的关系

两个调整独立叠加，无交互：

```
final_icir = (neutralized_icir or raw_icir) × short_sample_penalty
```

- neutralized ICIR 回答"纯 alpha 有多大"
- short_sample penalty 回答"这个统计值可不可靠"
- 两者正交，先取中性化值再乘惩罚

### 对 `decay_level="inverse"` 的处理

`decay_rate < 0` 意味着中性化后 |IC| 反而上升（结构性增益）。使用 neutralized ICIR 会**增加**这类因子权重——这是正确行为：去除行业/市值噪声后因子 alpha 更强，理应获得更高权重。

---

## §3 决策矩阵

| 子节 | 决策 | 来源 |
|------|------|------|
| §2.1 筛选用 raw IC | 不改 factor_selector | 用户选 Plan D（仅改加权）|
| §2.2 加权用 neutralized IC | 改 weight_engine + factor_loader | 用户选 Plan D |
| §2.3 Fallback 规则 | enabled=False / 缺失 → raw | 规范默认（向后兼容）|
| §2.4 short_sample 叠加 | 先取 neutralized 再乘惩罚 | 逻辑正交，无冲突 |
| §2.5 RollingICIR | 改 load_ic_daily 数据源 | 完整性（4 种加权方式一致）|

---

## §4 实施步骤

| 步骤 | 文件 | 改动 | 验证 |
|------|------|------|------|
| 1 | factor_loader.py | `load_ic_results()` 注入 neutralized 字段 | 单元测试：mock IC JSON 验证字段存在 |
| 2 | factor_loader.py | `load_ic_daily()` 优先 neutralized 日序列 | 单元测试：验证 fallback 到 raw |
| 3 | weight_engine.py | `ICIRWeightMethod.get_weights()` 优先 neutralized_icir | 单元测试：验证权重变化 |
| 4 | weight_engine.py | `ICWeightMethod.get_weights()` 优先 neutralized_ic_mean | 单元测试 |
| 5 | ruff + pytest | 全量检查 | ruff check + pytest comprehensive_factor/ |

---

## §5 不改动项

- `factor_selector.py`：筛选标准不变（raw IC 判断有效性）
- `composite_runner.py`：仅传透 `ic_results`，无需改动
- `weight_selector.py`：权重选择标准不变
- `summary/generate_factor_summary_report.py`：已读 `ic_neutralized`，无需改动
- `EqualWeightMethod`：等权不依赖 IC，无需改动

---

## §6 风险与缓解

| 风险 | 概率 | 缓解 |
|------|------|------|
| 旧版 IC 结果无 `ic_neutralized` 字段 | 低（已全量重跑）| Fallback to raw ICIR |
| `neutralized_icir` 为 None（raw_ic_mean≈0）| 低 | Fallback to raw ICIR |
| 权重变化导致综合因子排名大幅变动 | 中 | `weight_selector.py` 会重新选最优加权方式 |
| RollingICIR 日序列长度不一致 | 低 | `ic_neutralized.n_days` 可能 < raw 天数；`load_ic_daily` 已有长度校验 |

---

## §7 实施记录

| 轮次 | 日期 | 文件 | 改动 | commit |
|------|------|------|------|--------|
| 1 | 2026-06-18 | factor_loader.py | `load_ic_results()` 注入 neutralized 字段 | `49dc1b4` |
| 2 | 2026-06-18 | factor_loader.py | `load_ic_daily()` 优先中性化日序列 | `e6c00ab` |
| 3 | 2026-06-18 | weight_engine.py | `ICIRWeightMethod` 优先 neutralized_icir | `2cd8b19` |
| 4 | 2026-06-18 | weight_engine.py | `ICWeightMethod` 优先 neutralized_ic_mean | `896ed06` |
| 5 | 2026-06-18 | — | 全量 ruff + pytest + 端到端 smoke test | — |

端到端验证（amplitude/rsi/volume_ratio 三因子）：
- 全部正确使用 neutralized ICIR 计算权重
- `neutralized_enabled=False` 时正确 fallback 到 raw
- RollingICIR 日序列正确切换到中性化值（509 天 vs raw 516 天）
