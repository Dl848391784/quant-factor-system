# Design: 修复 freshness 期望日期「早一天」错位 (对齐核心数据契约)

> **遵循**: designs/feat_t1_contract_semantic_alignment_2026-07-19.md (契约 SSOT) + PROJECT.md §核心数据契约
> **对抗验证**: 根因已经用户质疑 + agent parquet 实测双重确认（master=0717 等），本文以 `[ADVERSARIAL] verdict=UNSHAKEN` 记录
> **影响范围**: `summary`（freshness_check.py）+ `web_ui`（app.py 调用点）——跨模块数据契约，按陷阱1流程

---

## 根因（Why）

`check_data_freshness(date)` 内部算 `expected = prev_td(date)`。两个调用方传入的 `date` 语义不同：

| 调用方 | 传入 | prev_td 结果 | 契约应有期望 | 结果 |
|---|---|---|---|---|
| summary `generate_...:157` | 报告日 **R** | prev_td(R) = T-1 | T-1 | ✅ 正确 |
| web_ui `app.py:250` | `selection_date` = **T-1** | prev_td(T-1) = T-2 | T-1 | ❌ **早一天 → 误报 △延迟** |

**本质**：web_ui 把"T-1 数据日"当成"T"传给一个"内部再减一天"的函数 → 双重减一天。

衍生（ic_results）同理：summary 传 R → 期望 T-2 ✓；web_ui 传 T-1 → 期望 T-3 ✗（应 T-2）。

## 修法（What + How）—— 第一性原理

**原则**：期望日期应由"报告日 R"推导（契约语义），不是由"数据日"再减。让函数能显式接收 R。

**改动**：

1. **`summary/report/freshness_check.py`** — 两函数加可选参数 `report_date: str | None = None`：
   ```python
   def check_data_freshness(date, logger, report_date=None):
       expected = prev_td(report_date) if report_date else prev_td(date)  # T-1
   def check_derived_data_freshness(date, logger, report_date=None):
       t1 = prev_td(report_date) if report_date else prev_td(date)  # T-1
       expected = prev_td(t1)  # T-2
   ```
   - `report_date=None` 默认 → 行为不变（**向后兼容**，summary 现有调用不受影影响）
   - 函数仍返回 `expected_date`/`actual_date`/`status_symbol`，schema 不变

2. **`web_ui/app.py:250/254`** — 传 `report_date=selection_date or date`：
   ```python
   check_data_freshness(date, logger=logger, report_date=selection_date or date)
   ```
   web_ui 的 `date` 是 URL 报告日，`selection_date` 是数据日；用 `report_date` 显式声明"以 selection_date 为基准推期望"。

**为什么不直接改 web_ui 传参（最省事）**：web_ui 改传 `date`（R）虽能让期望=T-1，但 `date` 是 URL 报告日，语义不如 `selection_date` 准（报告可能补跑）。显式 `report_date` 参数让"以哪天为基准"变成**显式契约**而非隐式依赖调用方传对 date——第一性原理，数据分布变化时仍成立。

## Don't

- ❌ 不改 `get_expected_t_minus_1/_minus_2` 本身（它们是纯日期工具，语义正确）
- ❌ 不改 summary `generate_...:157` 调用（它已传对，改它=破坏正确路径）
- ❌ 不改 freshness_check 的 `!=` 判延迟逻辑（超前/落后区分是独立增强，不在本范围）

## 测试（pytest，新文件）

`summary/test_cases/test_freshness_check.py`：
1. `report_date=None` 时行为与现状一致（向后兼容回归）
2. `report_date=selection_date` 时期望=T-1（基础）/T-2（衍生）——对齐契约
3. 用 monkeypatch 造 parquet/json 数据使 actual=契约值 → 断言 `status_symbol` 为 ✓正常 非 △延迟

`web_ui/test_cases/test_app.py`：freshness section 渲染断言（已有 mock，补一条 report_date 透传断言）

## Verify

- `pytest summary/test_cases/test_freshness_check.py` 新测试过
- `pytest summary/test_cases/ web_ui/test_cases/` 无回归
- 重启 web_ui，浏览器 `/report/latest` 数据完整性 section：基础源 ✓正常（原 △延迟误报消失）、ic_results ✓正常
- `ruff check` 通过
