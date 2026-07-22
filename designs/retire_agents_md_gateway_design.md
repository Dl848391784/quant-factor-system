# Design: 退役 AGENTS.md 网关层（Hermes 遗留 -> Claude Code 两层架构）

> **任务**：把 `AGENTS.md` 从"Hermes 时代自动加载网关"退役，精华以指针并入 `CLAUDE.md`，确立 Claude Code 下干净的 **CLAUDE.md(自动·瘦) -> PROJECT.md / MODULE.md(触发读·全文)** 两层架构。
> **日期**：2026-07-22
> **授权依据**：用户 2026-07-22 会话确认退役方案 + 选定「分阶段(推荐)」退役策略。本会话已查证：AGENTS.md 在 Claude Code 下**无任何自动加载机制**（本会话只注入了 CLAUDE.md；`codegraph_inject.py:130-138` 只注入 codegraph 符号，不碰 .md；grep 无 SessionStart hook 读 AGENTS.md），而 `AGENTS.md:3` 仍自称"每次对话都会自动加载"=过时假声明。
> **关联规范**：PROJECT.md §9「本文档与 AGENTS.md 的关系」；CLAUDE.md §0/§1/§6；H8（Design-First：本次 2+ 文件）；H9（单批 ≤3 文件 ≤200 行）；H15（codegraph 查证 + 跨文件断言附证据）。

---

## What（改造定义）

**退役 AGENTS.md 的网关职责**：把"每会话必知"的 4 条精华以**指针**形式并入 `CLAUDE.md`（不复制正文，守 CLAUDE.md §0「不复制规则」铁律），删除 `AGENTS.md`，并修正所有描述"文档架构/加载关系"的章节使其反映两层模型。

**目标架构**（退役后）：

```
CLAUDE.md   ← 每会话自动加载（瘦路由 + 精华指针 + 硬规则编号速查 + skill 路由表 + 入口守门员）
   │  指针指向 ↓
   ├── PROJECT.md   ← 项目级真源（H1-H15 硬规则正文 / 第一性原理 / 战略 / T+1 数据契约 / 跨模块路径表），触发读
   └── <模块>/MODULE.md  ← 模块级真源（模块内规范），改该模块代码前必读
```

**不在本任务范围**（见 §范围边界）：散落在 `.py` 注释 / `MODULE.md` 里的 `AGENTS.md 规则 #N` 溯源引用迁移 → 独立后续任务（单独 design）。

---

## Why（根因 + 为何退役 + 为何分阶段）

### 根因：AGENTS.md 混淆了两个职责，其一在 Claude Code 下已死

AGENTS.md 实际承担两件事：

| 职责 | 状态 | 处置 |
|---|---|---|
| **(A) 自动加载网关**：入口守门员 / skill 路由 / 第一性原理 / 战略 / T+1 精华 | Claude Code 下**无自动加载机制**（本会话实证：未注入 AGENTS.md）+ 内容全是 PROJECT.md 副本（每行标"详见 PROJECT.md"） | **退役**：精华以指针并入 CLAUDE.md，删除文件 |
| **(B) `#1-#14` 硬规则速查表 + 编号命名空间** | 被 30+ 文件当溯源引用（`遵循 AGENTS.md 规则 #N`）；且编号与 PROJECT.md H 系列错位 | 速查表内容并入 CLAUDE.md §5（已有 H 指针）；散落 `#N` 溯源迁移留后续 |

### 为何退役（不是保留）

1. **假声明**：`AGENTS.md:3`「每次对话都会自动加载」在 Claude Code 下不成立（本会话只注入了 CLAUDE.md），保留 = 持续误导。
2. **冗余层**：`AGENTS.md:90/109/119/130` 等行均标"详见 PROJECT.md"，与 CLAUDE.md -> PROJECT.md 形成 **CLAUDE.md -> AGENTS.md -> PROJECT.md 三层跳转**，中间层既不自动加载又全是副本，违反项目「禁止跨层重复」纪律（CLAUDE.md §0）。
3. **Codex 退路不成立**：`AGENTS.md:41` 列「kanban-codex-lane」skill，但 `.claude/skills/` 下不存在该 skill（实测只有 4 个因子相关 skill）——AGENTS.md 作为 Codex 入口的唯一理由失效。

### 为何分阶段（用户已选「分阶段(推荐)」）

全量删 AGENTS.md 需同步迁移 30+ 处 `#N` 溯源引用，且 `#N` 与 `H{X}` 编号错位（已查证 4 处：`#14↔H13`、`#6↔H12`、`#11↔H7`、`#13↔H11`，证据见 `scripts/check_dead_branches.py:11` 等双引注释），一次迁移违反 H9 且编号映射易错。故：

- **本任务**：退役网关 + 修文档架构关系层（让 end-state 自洽）。
- **后续任务**：迁移散落 `#N` 溯源 -> `PROJECT.md H{X}`（需先建核实过的完整映射表，见 §范围边界）。

---

## How（编辑清单 · 分批 · 每批 ≤3 文件，H9 合规）

### B1 核心（3 文件）

#### B1.1 `CLAUDE.md` — 并入精华指针 + 抹去 AGENTS.md 自引用

| 位置 | 现状 | 改为 |
|---|---|---|
| §0 表（line 9） | 含 `AGENTS.md` 行："每次自动读；硬规则速查+入口守门员+第一性原理+战略+T+1" | **删除该行**；网关+精华职责并入本文件（见新增 §1.5） |
| §0 表后注 | （表为"真源"） | 补一句：CLAUDE.md 本身是自动加载路由层；表内两行才是真源全文 |
| §1 step1（line 16） | "读规范：AGENTS.md + 命中触发读 PROJECT.md/MODULE.md" | "读规范：CLAUDE.md（本文件，已自动加载，含精华指针）+ 命中触发读 PROJECT.md/MODULE.md" |
| §1 line 18 | "（AGENTS.md 入口守门员）" | "（CLAUDE.md §1 入口守门员）" |
| §6（line 68） | "完整规范见 AGENTS.md / PROJECT.md / MODULE.md" | "完整规范见 PROJECT.md / MODULE.md（本文件为路由入口）" |
| **新增 §1.5** | （无） | 见下方「CLAUDE.md 精华指针」 |

#### CLAUDE.md 精华指针（新增 §1.5，~12 行；指针不复制正文）

```markdown
## 1.5 每会话必知精华（指针；正文唯一定义在 PROJECT.md，不在此复制）

| 精华 | 一句话速查 | 真源（详读） |
|---|---|---|
| 第一性原理 | 方案从基本原理推导，禁调参数式临时修复（数据变化仍成立） | PROJECT.md §第一性原理 |
| 战略目标 | 量化产出 N=30~50 -> 人工决断 3~5；禁纯量化选 Top 3~5 | PROJECT.md §战略目标 |
| 数据驱动 | 方向/风格由实证 IC 涌现，禁贴"弱势反转/趋势跟随"叙事标签 | PROJECT.md §数据驱动原则 |
| T+1 持仓 | T-1 数据 -> T 尾盘买 -> T+1 卖；实战评估只用 forward_return_1d | PROJECT.md §实战交易规则 / §核心数据契约 |
```

#### B1.2 `AGENTS.md` — 删除文件

`git rm AGENTS.md`。内容已被 CLAUDE.md §1.5（精华指针）+ PROJECT.md（正文真源）完全承接。

#### B1.3 `PROJECT.md` — §9 改写 + 散落架构引用修正

| 行 | 现状 | 改为 |
|---|---|---|
| §9 标题（line 9） | "## 本文档与 AGENTS.md 的关系 [reference]" | "## 文档架构与加载关系（CLAUDE.md -> PROJECT.md / MODULE.md）[reference]" |
| §9 表（line 11-14） | 两行表：AGENTS.md(自动注入) / PROJECT.md(触发读) | 两行表：**CLAUDE.md**(自动加载·瘦路由+精华指针) / **PROJECT.md**(触发读·全文真源)；补一行 MODULE.md(改模块前必读) |
| line 36 | "1. 加载 AGENTS.md / PROJECT.md -> 拿到硬规则速查表" | "1. CLAUDE.md 已自动加载（含精华指针 + 硬规则速查）；命中触发读 PROJECT.md" |
| line 231 | "其它文档（AGENTS.md §⏰ / intraday-strategy-design skill / MEMORY）只放指针" | "其它文档（CLAUDE.md §1.5 / intraday-strategy-design skill / MEMORY）只放指针"（T+1 精华指针现归 CLAUDE.md §1.5） |
| line 264 | "❌ 在 AGENTS.md / skill / MEMORY 里重复本表全文" | "❌ 在 CLAUDE.md / skill / MEMORY 里重复本表全文"（prohibition 仍覆盖自动加载层） |
| line 1108 | "- [ ] AGENTS.md 速查表同步更新"（S4->H4 升级 checklist） | "- [ ] CLAUDE.md §5 硬规则速查同步更新"（硬规则速查现归 CLAUDE.md §5） |
| line 1470 | "Pitfall 162（见 AGENTS.md）" | **执行时核实**：grep `Pitfall 162` 找权威定义所在；若 PROJECT.md 有则改指 PROJECT.md §Pitfall 162，若无则标注 TODO 纳入后续溯源迁移（不伪造重定向） |

### B2 skills（2 文件）

| 文件 | 行 | 现状 | 改为 |
|---|---|---|---|
| `.claude/skills/factor-development/SKILL.md` | 26 | "...(AGENTS.md §⚡)" | "...(CLAUDE.md §1.5 / PROJECT.md §第一性原理)" |
| 同上 | 42 | "禁调参数式修复(AGENTS.md §⚡)" | "禁调参数式修复(CLAUDE.md §1.5)" |
| 同上 | 52 | "❌ 改 AGENTS.md / PROJECT.md（除非任务本就是改规范）" | "❌ 改 PROJECT.md / MODULE.md（除非任务本就是改规范）" |
| `.claude/skills/factor-summary-reporting/SKILL.md` | 22 | "1. 读 AGENTS.md + CLAUDE.md" | "1. 读 CLAUDE.md（已含精华指针）" |

### B3 scripts（3 文件 · 双引注释，去悬空半边）

这 3 个文件均**双引**「PROJECT.md H{X} / AGENTS.md #N」，删 AGENTS.md 后 PROJECT.md 半边仍存，只需去掉 `/ AGENTS.md #N` 半边。

| 文件 | 行 | 现状 | 改为 |
|---|---|---|---|
| `scripts/check_dead_branches.py` | 11 | "PROJECT.md 规则 H13 / AGENTS.md 规则 #14" | "PROJECT.md 规则 H13" |
| `scripts/test_check_dead_branches.py` | 9 | 同上 | 同上 |
| `scripts/test_check_exit_codes.py` | 10 | "PROJECT.md 规则 H12 / AGENTS.md 规则 #6" | "PROJECT.md 规则 H12" |

> B3 均为 .py，但属 H15 白名单（`scripts/check_*.py` 与 `test_*.py`），门禁不阻断；且为注释单行改动，无逻辑变更，免 codegraph 查证。

### B3b scripts（1 文件 · B3 漏项补修）

执行时发现 `scripts/check_exit_codes.py:19` 与 `test_check_exit_codes.py` 同源双引注释，首轮 grep `head -60` 截断漏列（勘误见 §范围边界）。单独成批补修，H9 合规。

| 文件 | 行 | 现状 | 改为 |
|---|---|---|---|
| `scripts/check_exit_codes.py` | 19 | "PROJECT.md 规则 H12 / AGENTS.md 规则 #6" | "PROJECT.md 规则 H12" |

> 同 B3，H15 白名单（`scripts/check_*.py`），注释单行改，无逻辑变更。

---

## 范围边界（IN this task / DEFERRED follow-up）

### ✅ 本任务处理（架构关系层 + 网关退役）

`CLAUDE.md` / `AGENTS.md`(删) / `PROJECT.md` / 2×`SKILL.md` / 4×`scripts/*.py`(B3+B3b) = **8 文件，分 B1/B2/B3/B3b 四批提交**。
> B3b 为 B3 漏项补修：`scripts/check_exit_codes.py:19`（B3 漏列根因见下方勘误）。

### ⏸ DEFERRED 后续任务（散落 `AGENTS.md` 溯源迁移 -> `PROJECT.md H{X}` 或 `CLAUDE.md §1.5`）

> 显式列出，**不静默吞**（no silent cap）。后续任务需先建「AGENTS.md #N -> PROJECT.md H{X}」**核实过的完整映射表**再批量改。

**⚠️ 勘误（2026-07-22 执行时发现）**：本设计原 DEFERRED 清单只列 ~20 文件，**严重漏报**。根因 = 首轮调查 grep 加了 `head -60` 截断输出，`factor_ic/ic_interaction_*.py` 整族（27 个）被静默切掉，据此建清单时未察觉。执行时全量 grep 实测 **45 .py + 15 .md = 60 处**。下方为执行时全量核实后的完整清单（替换原不全清单）。

**已查证的 4 处 `#N -> H{X}` 映射种子**（证据：`scripts/*.py` 双引注释 + `reverse_discovery/MODULE.md:202` + CLAUDE.md §5）：

| AGENTS.md #N | PROJECT.md H{X} | 规则 |
|---|---|---|
| #14 | H13 | 死代码禁止 |
| #6 | H12 | 退出码 |
| #11 | H7 | 路径从 paths.py 导入 |
| #13 | H11 | 日志 % 惰性格式化 |

> 注：多数 `.py` 注释引用的是「AGENTS.md 数据驱动原则」「AGENTS.md 规则 #N」等，**不一定都带 `#N` 编号**；带 `#N` 的需查上表映射，不带编号的（如"数据驱动原则"）直接重指 `CLAUDE.md §1.5 / PROJECT.md §数据驱动原则`。后续任务须**逐处核实**引用形式，不可机械套映射。

**⚠️ 勘误（2026-07-22 后续迁移启动时发现）**：原"4 处映射种子"声明经全量核实**严重不完整**：

| 情况 | 详情 |
|---|---|
| **#7->H9 是错的** | AGENTS.md #7 = "测试位置 <模块>/test_cases/"，但 PROJECT.md H9 = "任务粒度 ≤3 文件"（不是测试位置）。**H{X} 与 #N 非一一对应**。 |
| **#8->H8 是错的** | #8 = "配套测试"，H8 = "Design-First"，不同。 |
| **#9->H10 是错的** | #9 = "日志格式 logger_config"，H10 = 异常链。 |
| **#10 #9 都映射到 H10** | 一对多冲突。 |
| **#15 不存在** | `factor_loader.py:839` 引 "AGENTS.md 规则 #15（第一性原理）"，但 AGENTS.md 只到 #14。#15 是凭空捏造。 |
| **#14 被乱用** | `ic_intraday_intensity_1d.py` 三处引用 #14 含义分别为"同名变量伪装作用域"、"禁止先算 inf 再覆盖" -- **与 AGENTS.md #14 原定义（死代码禁止）不符**。原注释张冠李戴。 |

**结论**：散落 `#N` 引用**不可机械映射**。后续迁移必须**逐处语义判断**，看注释实际表达的规则，重指到 PROJECT.md 对应章节或 CLAUDE.md §1.5。

**A 族勘误**：原列 27 ic_interaction_*.py + ic_intraday_intensity_1d.py + ic_calculator.py = 29，实际 A 族（统一模式 `AGENTS.md "数据驱动原则" + backtest/MODULE.md v2.5 M17`，27 个）。`ic_intraday_intensity_1d.py` 和 `ic_calculator.py` **不是 A 族**，各自有不同引用模式，需单独语义判断（归入后续"逐处语义"批）。

**修正后的待迁移完整清单（60 文件 · 2026-07-22 全量核实）**：

**A. `factor_ic/ic_interaction_*.py` 族（27 文件，统一机械模式）**——均引用 `遵循 AGENTS.md "数据驱动原则" + backtest/MODULE.md v2.5 M17`，line 11：

```
factor_ic/ic_interaction_amp_compression__ret3d_{abs,neg,pos}_1d.py
factor_ic/ic_interaction_amplitude__ret3d_{abs,neg,pos}_1d.py
factor_ic/ic_interaction_bollinger__ret5d_{abs,neg,pos}_1d.py
factor_ic/ic_interaction_intraday__ret1d_{abs,neg,pos}_1d.py
factor_ic/ic_interaction_kdj__ret5d_{abs,neg,pos}_1d.py
factor_ic/ic_interaction_ma5_dev__ret3d_{abs,neg,pos}_1d.py
factor_ic/ic_interaction_near_high__ret3d_{abs,neg,pos}_1d.py
factor_ic/ic_interaction_price_pos__ret1d_{abs,neg,pos}_1d.py
factor_ic/ic_interaction_turnover__ret3d_{abs,neg,pos}_1d.py
```

**B. 其余 `.py` 生产代码（17 文件）**：

```
comprehensive_factor/common/factor_loader.py
comprehensive_factor/composite_decision_card.py
comprehensive_factor/test_cases/test_composite_decision_card.py
comprehensive_factor/test_cases/test_composite_weight_selector.py
data_fetchers/factor_calculator/_common.py
data_fetchers/factor_calculator/industry_financial.py
data_fetchers/factor_calculator/momentum.py
data_fetchers/fetch_market_cap.py
factor_definitions.py
reverse_discovery/data_splitter.py
stock_selector/stock_selector_config.py
summary/report/llm_provider.py
summary/report/segment_ai_db.py
web_ui/common/pl_ratio_db.py
web_ui/common/segment_ai_db.py
web_ui/common/segment_win_db.py
```
（注：B 类 + A 类 = 45 .py，与全量 grep 计数一致）

**C. MODULE.md（4 文件）**：`backtest/MODULE.md`、`comprehensive_factor/MODULE.md`、`pipelines/MODULE.md`、`reverse_discovery/MODULE.md`（后者 8 处，最密集）

**D. 历史/流程文档（11 文件，低优先，多为已完成项溯源）**：

```
comprehensive_factor/docs/composite_runner_eliminate_duplicate_data_loading_design.md
data_fetchers/docs/fetch_market_cap_flow.md
docs/plans/ic_tail_price_slope_1d_plan.md
docs/project_md_refactor_plan_v1.md
factor_ic/docs/plans/factor_ic_startup_log_dedup_design.md
factor_ic/docs/plans/factor_ic_warning_unification_design.md
factor_ic/docs/plans/ic_industry_earnings_growth_main_cleanup_design.md
factor_ic/docs/plans/logger_style_unification_v1.0.md
summary/docs/generate_factor_summary_report_flow.md
```
（注：全量 grep 的 15 .md 含 CLAUDE.md + PROJECT.md，但这两处是本任务有意保留的退役说明注记，非 DEFERRED，故 D 类实际 13 文件...复核：15 - 2 有意 = 13；上列 9 + 4 MODULE.md = 13 ✓）

**后续任务建议拆分**（按 H9 ≤3 文件）：
- 子任务 1：A 族 27 文件机械迁移（同一模式「数据驱动原则」-> `CLAUDE.md §1.5`），可脚本辅助但须逐文件 verify。
- 子任务 2-4：B 类按模块分组（comprehensive_factor / data_fetchers / web_ui+summary+stock_selector）。
- 子任务 5：C 类 MODULE.md（带编号，需查映射表）。
- 子任务 6：D 类历史文档（可选，低优先）。


---

## Verify（验收 · 说"完成"必附证据）

1. **架构自洽**：`grep -rn "AGENTS" CLAUDE.md PROJECT.md .claude/skills/*/SKILL.md scripts/*.py` 应**零命中**（本任务范围内的文件不再引用已删文件）。
2. **无悬空 AGENTS.md 引用（本任务范围）**：`grep -rn "AGENTS\.md" --include="*.md" . | grep -v "designs/" | grep -v DEFERRED 清单中的文件` -> 仅剩 DEFERRED 清单内文件（已显式登记，非静默遗漏）。
3. **CLAUDE.md 精华指针到位**：`grep -n "第一性原理\|战略目标\|数据驱动\|forward_return_1d" CLAUDE.md` 命中 §1.5 四行。
4. **PROJECT.md §9 反映两层**：`grep -n "本文档与 AGENTS" PROJECT.md` 零命中（标题已改）；`grep -n "CLAUDE.md" PROJECT.md` 命中新 §9。
5. **H9 批次合规**：每批 git commit diff ≤3 文件、≤200 行。
6. **DEFERRED 已登记**：本 design §范围边界显式列出全部待迁移文件（执行时全量核实 60 处，含勘误说明原 ~20 漏报根因）+ 4 处映射种子，后续任务可据此启动。

---

## 批次与提交计划

| 批 | 文件 | 行为 | H9 |
|---|---|---|---|
| B0 | `designs/retire_agents_md_gateway_design.md` | 本文件（Design-First 审核） | — |
| B1 | `CLAUDE.md` / `AGENTS.md`(rm) / `PROJECT.md` | 核心退役 + §9 改写 | 3 文件 ✓ |
| B2 | 2×`.claude/skills/*/SKILL.md` | skill 引用重指 | 2 文件 ✓ |
| B3 | 3×`scripts/*.py` | 双引注释去悬空半边 | 3 文件 ✓ |
| B3b | `scripts/check_exit_codes.py` | B3 漏项补修（首轮 grep head 截断漏列） | 1 文件 ✓ |

**执行状态**（2026-07-22）：B0/B1/B2/B3/B3b 均已提交。DEFERRED 60 处已登记（见 §范围边界勘误），留后续独立任务。
