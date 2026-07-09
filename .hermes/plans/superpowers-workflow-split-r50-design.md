# Design: superpowers-workflow 拆分到 factor-ic-analyzer-workflow (R50)

> **任务**：将原 `superpowers-workflow` skill 中所有项目特定内容（v2.0.16~v2.0.21 changelog + 152 个项目特定 references）拆出到新 skill `factor-ic-analyzer-workflow`，还原 superpowers-workflow 为泛用 4 阶段框架
> **日期**：2026-07-09
> **关联规范**：
> - AGENTS.md §0 入口守门员 (skill_view 加载 superpowers-workflow 后再行动)
> - AGENTS.md §5 任务后必做 (commit + 简短报告)
> - superpowers-workflow/references/superpowers-injection-design-2026-06-30.md 设计原则（主文件只留骨架，references 按需加载）

---

## 1. 现状分析（事实，2026-07-09 拆分前）

| 指标 | 数值 | 说明 |
|---|---|---|
| superpowers-workflow/SKILL.md 字节数 | 28,225 (28 KB) | 被项目特定 changelog 段（v2.0.16~v2.0.21）污染 |
| superpowers-workflow/SKILL.md 行数 | 173 | 顶部 80% 是项目特定实战锚点 |
| superpowers-workflow/references/ 文件数 | 343 | 其中 **152 个项目特定**（带 factor/ob_quality/summary/web_ui 等关键字） |
| 真正泛用 references | 191 | 190 个 .md + 1 个 plugin-verification-template.py |

**核心问题**：本 skill 角色错位 — 它本应是 Hermes Agent 泛用的 4 阶段驱动开发流程框架（Plan→Execute→Review→Debug），但被项目特定实战锚点（v2.0.16~v2.0.21 changelog）污染，导致:
- 主文件加载即吞 28KB 项目内容，对非 factor-ic-analyzer 项目的 session 是噪音
- 152 个 references 是项目特定 pattern，污染 superpowers-workflow 作为"泛用 skill"的定位
- 上游 Hermes Agent 仓库根本没有 `superpowers-workflow` skill（已拆分为 plan / test-driven-development / systematic-debugging 等 sub-skill），本 skill 是项目本地污染产物

---

## 2. 设计原则

1. **还原 superpowers-workflow 为泛用 4 阶段框架**：参照上游 `plan` / `test-driven-development` skill 风格，写一个简洁的 4 阶段总览 + 引用上游已有的 sub-skill
2. **项目特定内容迁到新 skill `factor-ic-analyzer-workflow`**：保留所有 v2.0.16~v2.0.21 项目实战锚点 + 152 个项目特定 references
3. **保留泛用 references**：190 个泛用 references 留在原 superpowers-workflow，零内容丢失
4. **可逆 + 可审计**：在 superpowers-workflow/references/MIGRATED.md 留拆分记录，新 skill SKILL.md 留拆分历史段

---

## 3. 拆分方案

### 3.1 新建 skill `factor-ic-analyzer-workflow`

| 文件 | 内容 | 来源 |
|---|---|---|
| SKILL.md (146 行 / 11KB) | v2.0.16~v2.0.21 changelog 汇总 + Plan 阶段反模式 5 条 + 三层 silent fallback 防御图 + T/T-1/T+1 三角语义 + R49 commit 链 | 原 superpowers-workflow/SKILL.md 顶部 80% |
| references/ (152 个文件) | 项目特定 pattern | 原 superpowers-workflow/references/ 152 个 |

**判定标准（双重）**:
1. 文件名含强项目关键字 (`factor/ob_quality/summary/web_ui/composite/backtest/stock_selector/comprehensive_factor/data_fetchers/fetch-factor/project-md-refinement/design-md/agents-md/codegraph/r4/r5/session-2026-*`)
2. 或文件名不含 + 全文命中 ≥3 个项目标记 (`factor_ic_analyzer/stock_selector/comprehensive_factor/...`)

### 3.2 还原 superpowers-workflow

| 文件 | 内容 | 备注 |
|---|---|---|
| SKILL.md (162 行 / 8KB) | 4 阶段总览 (Plan→Execute→Review→Debug) + sub-skill 列表 + cross-phase rules + anti-patterns | 参照上游 `plan` / `test-driven-development` 风格 |
| references/MIGRATED.md (新文件) | 拆分记录 (动机 + 方案 + 判定标准 + 协同方式) | 给未来维护者看的 |
| references/ (191 个文件) | 190 泛用 .md + 1 plugin-verification-template.py | 零改动 |

---

## 4. 协同方式

- `superpowers-workflow` 是**泛用 4 阶段框架**，所有项目都可用
- `factor-ic-analyzer-workflow` 是**项目特定实战锚点层**，只 factor-ic-analyzer 项目使用
- 项目特定规则**覆盖**泛用规则（当冲突时以项目为准）
- 两个 skill 的 `related_skills` 字段互相引用，方便后续 session 自动加载

---

## 5. 风险评估

| 风险 | 缓解措施 |
|---|---|
| 已迁移的 152 个 references 在 R49 commit 链路的引用路径断链 | 在新 skill `factor-ic-analyzer-workflow/SKILL.md` 中明确标注 "本 skill 收录 R49 commit 链实战记录"，并指向对应 references 子目录 |
| 190 个泛用 references 留在原 skill，对其他项目 session 仍是噪音 | 后续可考虑进一步拆分到独立 skill (e.g. python-pipeline-patterns)，留作 R50+ |
| 用户之前用 `superpowers-workflow` 的方式变化 (e.g. 引用 v2.0.16 changelog 段) | 在原 skill SKILL.md 顶部加 "2026-07-09 拆分说明" 段，明确指向新 skill |
| 新 skill 加载路径不熟 | 新 skill `related_skills` 字段明确包含 `superpowers-workflow` + `factor-ic-analyzer-workflow` 互引 |

---

## 6. 验证标准

- [x] superpowers-workflow/SKILL.md ≤ 10 KB（28 KB → 8 KB）
- [x] superpowers-workflow/SKILL.md 不含项目特定关键词（v2.0.16/v2.0.17/v2.0.20/v2.0.21/R47/R48/R49/2026-07-08 等）
- [x] factor-ic-analyzer-workflow/SKILL.md 收录全部项目实战锚点（v2.0.16~v2.0.21 changelog + 三层 silent fallback 图 + T/T-1/T+1 三角）
- [x] 152 个项目特定 references 全部迁移（无丢失）
- [x] 190 个泛用 references 全部保留在原目录
- [x] 原 references/MIGRATED.md 说明文件就位

---

## 7. 与 2026-06-30 拆分设计的关系

`.hermes/plans/superpowers-workflow-skill-slim-down-design.md`（2026-06-30 设计，未实施）的目标是"SKILL.md 171KB → 30KB"，当时设计是"主文件保留骨架 + 7 个 references 拆出"，但**未实施**。

本次拆分（2026-07-09）是不同思路：
- 2026-06-30 思路：在 superpowers-workflow 内拆分（references 拆分）
- 2026-07-09 思路：跨 skill 拆分（项目特定内容 → 新 skill，superpowers-workflow 还原泛用版）

两次设计**互补不冲突**：本次拆分后，superpowers-workflow 已足够精简（8KB / 162 行），2026-06-30 设计的"主文件骨架"目标已达成。如未来需要进一步拆分 references 到子主题 skill，可参考 2026-06-30 设计的 references/README.md 索引方案。

---

## 8. 后续 follow-up（不在本次范围内）

1. **R50+**: 把 190 个泛用 references 按主题再拆分到独立 skill (e.g. python-pipeline-patterns / git-workflow-patterns / data-fetching-patterns 等)，进一步精简单个 skill 加载体积
2. **R50+**: factor-ic-analyzer-workflow 的 references/ 按子主题分子目录 (e.g. references/r47-silent-fallback/、references/r49-step-by-step/、references/factor-development/)，方便按需加载
3. **R50+**: 在 AGENTS.md / PROJECT.md 中引用 factor-ic-analyzer-workflow 替代 superpowers-workflow 的项目特定段（之前引用 v2.0.16~v2.0.21 的地方改引用 factor-ic-analyzer-workflow）

---

## 9. 提交消息模板

```
拆分 superpowers-workflow skill (R50 拆分清理)

按用户原话 "我想将 superpowers-workflow 还原成原本 hermes 自己带的"：

- 新建 skill `factor-ic-analyzer-workflow`：收录所有项目特定实战锚点
  (v2.0.16~v2.0.21 changelog + 三层 silent fallback 图 + T/T-1/T+1 三角 +
   R49 完整 commit 链 + 152 个项目特定 references)
- 还原 `superpowers-workflow` 为泛用 4 阶段框架 (162 行 / 8KB)，
  参照上游 hermes-agent `plan` / `test-driven-development` 风格
- 190 个泛用 references 保留在 superpowers-workflow/references/

变更：
- 新建: ~/.hermes/skills/software-development/factor-ic-analyzer-workflow/
  - SKILL.md (146 行 / 11KB)
  - references/ (152 文件)
- 改写: ~/.hermes/skills/software-development/superpowers-workflow/
  - SKILL.md (173 行 / 28KB → 162 行 / 8KB)
  - references/MIGRATED.md (新文件, 拆分记录)

验证：
- superpowers-workflow/SKILL.md 无项目特定关键词
- 152 references 完整迁移 (无丢失)
- 190 references 保留完整

依据：AGENTS.md §5 任务后必做 + superpowers-workflow/references/
superpowers-injection-design-2026-06-30.md 主文件骨架原则
```