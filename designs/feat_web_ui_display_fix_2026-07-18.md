# Design: web_ui 报告页 UI 展示修复 (B1/B2/B3 + E1/E2 + S1/S2)

> **范围**: 仅 `web_ui/` 目录（H1.1 严守：不改 summary / data_loaders / freshness_check）
> **触发**: 用户实测反馈 + 浏览器实测排查（2026-07-18）
> **遵循**: superpowers-workflow Plan→Execute→Review；AGENTS.md 硬规则 #1(边界) #2(输出位置) #14(禁死代码)

---

## 影响范围（战略目标模板必填）

- [x] **web_ui 报告页展示层**（量化产出的可视化，不改变任何数值/逻辑）
- [ ] 短名单 (30~50) — 不涉及
- [ ] 最终持仓 (3~5) — 不涉及
- [ ] Layer 1 候选池 — 不涉及

**说明**: 本次全部为 HTML 模板 + CSS 展示修复，不触碰任何数据计算、选股、权重逻辑。所有 KPI 数值来源字段已在生产代码中存在（B2 复用 `_section_filter.html` 同口径字段），无新数据假设。

---

## 问题清单与修法（每条含 What/How/Don't/Verify）

### B1. 数据完整性 KPI"告警数=0"与图表"告警=6"自相矛盾

**What**: 顶部 KPI 卡数 `⚠️` emoji，图表数 `延迟` 关键字，而实际 `status_symbol="△延迟"` → KPI=0、图表=6，口径不一致。

**根因证据**:
- `_section_freshness.html` L30: `{% if '⚠️' in r.status_symbol %}` (KPI)
- 同文件 L84: `sym.includes('延迟')` (图表)
- 实测 `status_symbol` 值 = `△延迟`（浏览器渲染 + freshness_check.py 契约，R34 注释已写明 "✓正常/✗缺失/△延迟"）

**How**（统一为三态判定函数，模板内 Jinja 逻辑，web_ui 自包含）:
- 判定优先级（与图表 L82-84 完全对齐）:
  - 含 `缺失`/`失败`/`无日期`/`✗` → fail
  - 含 `延迟` → warn（告警）
  - 其余 → ok
- KPI `_n_warn` / `_n_fail` 改用上述判定（替代现有 `⚠️`/`❌` emoji 匹配）
- 表格徽章 `_cls`/`_txt`（L146-148, L170-172）同步改用同一判定

**Don't**: 不改 `summary/report/freshness_check.py`（H1.1 边界）；不新增 emoji 匹配分支（避免再次口径漂移）。

**Why**: 单一事实来源——三处（KPI/图表/徽章）共用同一判定逻辑，未来 status_symbol 新增取值只改一处。

**Verify**: 浏览器实测 KPI 告警数 == 图表告警数 == 表格 `△延迟` 行数（当前数据应为 6）。

---

### B2. 顶部 KPI"入选因子数 = 0 / —" 永远占位

**What**: `report.html` L1106 读 `txt_filter.selection_result.valid_count`，但该 key 不存在 → 兜底 `0 / —`。

**根因证据**: 实测 `parse_obq_filter()` 返回 keys = `['selected_factors', 'high_corr_threshold', 'excluded']`，无 `selection_result`。

**How**（复用同 section 已验证口径，零新数据假设）:
- `_kpi_selected` 改为 `(txt_filter.selected_factors | length)`（与 `_section_filter.html` L24 `n_selected` 完全一致）
- 分母 `total_count` 改为 `(txt_filter.selected_factors | length) + (txt_filter.excluded | length)`（与 `_section_filter.html` L23 `n_total` 一致）
- 无 `txt_filter` 时整卡显示 `— / —`（而非 `0 / —`），通过 E2 的语义占位区分"无数据" vs "零值"

**Don't**: 不改 `txt_parser.py` 去补 `selection_result`（web_ui 内部可改，但会造成 txt_parser 与模板双口径，违反 DRY）；不硬编码总数。

**Verify**: 顶部 KPI == section 四"选中/总候选"数值一致；`txt_filter=None` 时显示 `— / —`。

---

### B3. 数据完整性"文件数"列整列空白（基础数据源 5 行）

**What**: 基础数据源表 5 行"文件数"全空白（非 `—`）。

**根因证据**: 上游 `check_data_freshness()` 对基础数据源不返回 `file_count` key（dict 缺 key，非 None）。模板 L155 `{{ r.file_count if r.file_count is not none else '—' }}` 中 `r.file_count` undefined → Jinja 默认渲染空串，`is not none` 对 undefined 求值为 True → 走空串分支。

**How**（模板侧修，H1.1 不改上游）:
- L155/L179 改 `{{ r.file_count if (r.file_count is defined and r.file_count is not none) else '—' }}`
- E2 语义统一：缺 key（字段不存在）显示 `—`，与"值为 0"区分

**Don't**: 不改 `freshness_check.py` 补 `file_count=None`（H1.1 边界）。

**Verify**: 基础数据源 5 行"文件数"显示 `—`；衍生数据源 3 行仍显示 72/72/4。

---

### E1. 带背景色数据单元格对比度不足（系统性，48 处 class 使用）

**What**: `cell-pos-bg`/`cell-neg-bg`/`cell-strong-*`/`heatmap-*` 浅色文字配半透明彩色背景，实测对比度 1.17~2.24（AA 需 4.5）。

**影响面证据**（grep 实测 48 处）:
- `cell-pos-bg`10 / `cell-neg-bg`9 / `cell-strong-pos-bg`6 / `cell-strong-neg-bg`6 / `cell-warn-bg`1 / `cell-neutral-bg`11
- `heatmap-pos/neg/neutral/strong-*` 各 4~5
- 集中 section 一/二/三/五/六/七 数值表；普通 `data-table td`（无 bg 类）对比度 16.4 达标，**不在本次范围**

**How**（CSS 变量级调整，只改 `report.html` 样式块，数值全部经对比度公式推导 ≥4.5）:

原则：保持 Sentry 暗色语义（绿=正/橙=负/红=警示），提升文字亮度 + 背景不透明度至达标。

| class | 现状(bg/fg) | 新值(bg/fg) | 新对比度 |
|---|---|---|---|
| `.cell-pos-bg` | rgba(194,239,78,.18)/#3fb950 | rgba(63,185,80,.22)/#7ee787 | ≥4.5 |
| `.cell-neg-bg` | rgba(255,178,135,.18)/#f0883e | rgba(240,136,62,.22)/#ffa657 | ≥4.5 |
| `.cell-warn-bg` | rgba(250,127,170,.18)/#f85149 | rgba(248,81,73,.22)/#ff9b94 | ≥4.5 |
| `.cell-strong-pos-bg` | #3fb950/#0d1117 | #3fb950/#0d1117 (保持，文字已深色) | 复核 |
| `.cell-strong-neg-bg` | #f0883e/#0d1117 | #f0883e/#0d1117 (保持) | 复核 |
| `.heatmap-pos` | rgba(194,239,78,.5)/#3fb950 | 文字改 #0d1117 深底亮字 | ≥4.5 |
| `.heatmap-neg` | rgba(255,178,135,.5)/#f0883e | 文字改 #0d1117 | ≥4.5 |
| `.heatmap-neutral` | rgba(22,27,34,.5)/#f0f0f5 | 保持(已达标) | — |
| `.cell-neutral-bg` | rgba(22,27,34,.4)/#f0f0f5 | 保持(已达标) | — |

**具体数值在 Execute 阶段用对比度脚本逐一验证后定稿**（目标 AA 4.5，热力图大字可 3.0 但尽量 4.5）。

**Don't**: 不改变色相语义（绿/橙/红）；不动普通 td（已达标）；不为达标把背景改成不透明大块亮色（破坏暗色层次）。

**Verify**: 浏览器对比度脚本重测所有 cell-* 单元格 ≥4.5（strong 类深字亮底天然更高）。

---

### E2. `—` 占位符语义混乱

**What**: `—` 被用于 ①字段不存在 ②真实零值分母 ③日期未出，无法区分。

**How**（统一映射，模板层）:
- 字段不存在 / 数据未生成 → `—`（保持，表"无"）
- 真实数值 0 → 显示 `0`（不用 `—` 替代）
- 日期未到 → 已用 `-`（保持）
- B2 的 `total_count` 若无 `txt_filter` 显示 `—`（无数据），有则显示真实整数（含 0）

**Don't**: 不引入第三种占位符（如 `N/A`）避免口径膨胀——统一用 `—` 表"无"，`0` 表"零值"。

**Verify**: 抽查 5 处 `—` 展示，确认均为"字段缺失"而非"零值"。

---

### S1. `△延迟` 徽章误显绿色（ok 分支）

**What**: `_section_freshness.html` L146-148 只认 `❌`/`⚠️`，`△` 落 else=绿色"正常"。

**How**: 随 B1 统一判定函数一并修复（`延迟`→warn 黄色徽章）。**不单独改，与 B1 同 commit。**

**Verify**: `△延迟` 行徽章为黄色（warn），非绿色。

---

### S2. KPI"告警数"卡片在 0 告警时仍橙色边

**What**: L47 `kpi-card kpi-warn` 硬编码，告警=0 时仍橙边。

**How**: 改 `kpi-card {{ 'kpi-warn' if _n_warn > 0 else 'kpi-neutral' }}`。

**Verify**: 当前数据（告警 6）应为橙边；模拟告警 0 时为灰边。

---

### S3. 长页面快速定位

**What**: 曾建议 section 折叠。

**核实结论（降级，不做）**: grep 实测报告已有 **21 个 `<details>` 折叠**（report.html 4 + 各 section 17），section 内报告级折叠已存在。页面长是信息密度高的合理结果，sticky sidebar + 锚点 + 回到顶部已覆盖导航。**S3 判定为无需改动。**

---

## 改动文件清单（全在 web_ui/ 内，预估行数）

| 文件 | 改动 | 预估行 |
|---|---|---|
| `web_ui/templates/_section_freshness.html` | B1 统一判定 + B3 文件数 + S1 徽章 + S2 卡片色 | ~30 |
| `web_ui/templates/report.html` | B2 KPI 字段 + E1 CSS 变量 + E2 占位 | ~25 |
| `web_ui/test_cases/test_app.py` | 补充渲染断言（B1 口径一致 / B2 字段 / B3 文件数） | ~30 |

**合计 ≤ 3 文件、≤ 200 行**（符合任务粒度约束）。

## 不做的事（Out of Scope）

- 不改 `summary/` 任何文件（H1.1）
- 不改任何数据计算 / 选股 / 权重逻辑
- 不重构 section 排序（已确认为有意设计）
- 不做 S3 折叠（已有 21 个 details）

## 验证计划（Execute 后）

1. `pytest web_ui/test_cases/test_app.py` 全过
2. `ruff check`（仅 Python 文件；模板改动不涉及）
3. 浏览器实测：
   - B1: KPI 告警数 == 图表告警 == `△延迟` 行数
   - B2: 入选因子数显示真实值，与 section 四一致
   - B3: 基础数据源文件数显示 `—`，衍生显示 72/72/4
   - E1: 对比度脚本重测 cell-* ≥4.5
   - S1: `△延迟` 徽章黄色；S2: 告警卡 0 时灰边
