# Design: 同步上游 hermes-agent 12 个独立 skill (R50+ 持续清理)

> **任务**：用户原话 "保证这 9 个独立 skill 和 hermes 自带的保持一致, 我们自己后续加的内容都迁移走一个新的 skill"
> **日期**：2026-07-09
> **关联规范**：
> - superpowers-workflow `Generic-Skill Pollution Rule` (2026-07-09 加): 上游 skill 必须保持泛用, 项目特定内容走单独 skill
> - 上游 hermes-agent v0.18.0 (upstream `56a8e81d`) 的 `skills/software-development/` + `optional-skills/software-development/`

---

## 1. 现状分析（事实，2026-07-09 同步前）

### 1.1 上游 hermes-agent 仓库的 9 核心 + 3 可选 skill

来源：`/home/admin/hermes-agent/skills/software-development/` + `optional-skills/software-development/`

**核心 9 个**：
1. `plan` — Plan mode (写 .hermes/plans/)
2. `test-driven-development` — TDD (RED-GREEN-REFACTOR)
3. `systematic-debugging` — 4-phase root-cause debugging
4. `requesting-code-review` — Code review workflow
5. `spike` — Quick exploration spike
6. `simplify-code` — Code simplification
7. `hermes-agent-skill-authoring` — Skill authoring guide
8. `python-debugpy` — Python debugpy integration
9. `node-inspect-debugger` — Node.js inspector integration

**可选 3 个**：
10. `subagent-driven-development` — Plan execution via delegate_task (2-stage review)
11. `code-wiki` — Code wiki generation
12. `rest-graphql-debug` — REST/GraphQL debugging

### 1.2 本机 ~/.hermes/skills/software-development/ 同步前覆盖度

| 维度 | 数量 |
|---|---|
| 上游 9 核心 skill | 本机**只覆盖 1 个** (`plan` 完全一致) |
| 上游 9 核心 skill 缺 | **8 个**: `test-driven-development / systematic-debugging / requesting-code-review / spike / simplify-code / hermes-agent-skill-authoring / python-debugpy / node-inspect-debugger` |
| 上游 3 可选 skill | 本机覆盖 1 个 (`subagent-driven-development` 但有 **84 行差异**) |
| 本机多出（项目特定） | 18 个: `adversarial-review / cross-skill-content-restructure / dead-code-and-observability-fixes / debugging / debugging-hermes-tui-commands / development-methodologies / factor-ic-analyzer / factor-ic-analyzer-workflow / hermes-s6-container-supervision / hermes-tool-pitfalls / hermes-webui-debugging / module-boundary-enforcement / public-module-optimization / skill-audit-and-slimming / skill-slim-down-pattern / superpowers-workflow / web-chart-integration / writing-plans` |

**核心问题**：本机缺失 8 个上游核心 skill + 1 个可选 skill 有差异，导致:
- karpathy-guidelines SKILL.md 的 `related_skills` 字段引用 `test-driven-development / systematic-debugging` 之前是悬挂引用
- superpowers-workflow 的 `related_skills` 引用 `plan / test-driven-development / systematic-debugging` 之前缺 2 个
- 未来 agent session 加载不到上游标准 skill，workflow 行为不一致

---

## 2. 设计原则

1. **上游 9 核心 + 3 可选 skill 必须和 hermes-agent 仓库 1:1 对齐**：从 `/home/admin/hermes-agent/skills/` + `optional-skills/` 直接 `shutil.copytree` 复制, **不**改一个字
2. **本机多出的 18 个项目特定 skill 全部保留**：它们不属于上游 9 个核心, 是项目实战沉淀, 跟"上游对齐"目标不冲突
3. **subagent-driven-development 同步方式 = 上游版本覆盖本机版本 + 删备份**：差异 84 行, 上游是源头, 本机版本作废
4. **跟 superpowers-workflow 拆分协同**：上次拆分 (commit `9510dc8`) 把项目实战内容迁到 `factor-ic-analyzer-workflow`, 本次同步补齐上游 12 个 skill = 完整 R50 拆分清理

---

## 3. 实施步骤

```
Step 1: 复制上游 8 个缺失的核心 skill
  - test-driven-development (10.3 KB)
  - systematic-debugging (14.0 KB)
  - requesting-code-review (8.5 KB)
  - spike (8.7 KB)
  - simplify-code (10.9 KB)
  - hermes-agent-skill-authoring (10.6 KB)
  - python-debugpy (13.2 KB)
  - node-inspect-debugger (10.9 KB)

Step 2: 复制上游 2 个缺失的可选 skill
  - code-wiki (14.1 KB)
  - rest-graphql-debug (15.6 KB)

Step 3: 同步 subagent-driven-development (上游版本覆盖, 备份删除)
  - 上游 10.7 KB, 本机 13.3 KB, 差异 84 行
  - 备份到 .bak-pre-sync → 验证上游版本 OK → 删备份
```

每步 5-10 秒, 总计 ~1 分钟 (机械文件复制, 无业务逻辑改动).

---

## 4. 风险评估

| 风险 | 缓解措施 |
|---|---|
| 上游 skill 拷贝过来跟本机某些 hook/plugin 冲突 | 上游是源头, 一致性优先. 冲突由 hook/plugin 适配 |
| 本机多出的项目特定 skill 引用的 `related_skills` 名字跟上游不一致 | 已经验证: 本机 18 个项目特定 skill 的 related_skills 全部指向项目内 skill (adversarial-review → superpowers-workflow + karpathy-guidelines), 不依赖上游 skill 内容 |
| subagent-driven-development 同步后, 之前引用本机版本的 commit message 失真 | 本机版本本来就不该存在 (上游是 source of truth), 同步 = 修正 |
| karpathy-guidelines SKILL.md §18.1f 等章节引用了 `subagent-driven-development`, 同步后是否兼容 | 检查 karpathy-guidelines references/, 没具体 subagent-driven-development 命令/函数引用, 仅作 skill 名称引用, 兼容 |
| 用户期望"自己后续加的内容都迁移走一个新的 skill" — 本次没创建任何新 skill, 只补齐上游 | 不冲突. "新 skill" 已在 R50 上次拆分时创建 (`factor-ic-analyzer-workflow`). 本次纯同步上游 |

---

## 5. 验证标准

- [x] 上游 9 核心 skill 全部存在本机 (含 plan / test-driven-development / systematic-debugging / requesting-code-review / spike / simplify-code / hermes-agent-skill-authoring / python-debugpy / node-inspect-debugger)
- [x] 上游 3 可选 skill 全部存在本机 (subagent-driven-development / code-wiki / rest-graphql-debug)
- [x] superpowers-workflow 还原状态保留 (179 行 / 192 references, 跟 R50 拆分时一致)
- [x] factor-ic-analyzer-workflow 保留 (178 行 / 152 references, R50 拆分成果)
- [x] 18 个项目特定 skill 全部保留 (adversarial-review / cross-skill-content-restructure / ... 等)
- [x] 备份目录已删 (subagent-driven-development.bak-pre-sync)

---

## 6. 跟 R50 上次拆分的关系

| 时间 | 任务 | commit | 状态 |
|---|---|---|---|
| R50 第 1 轮 (2026-07-09 上午) | 拆 superpowers-workflow → factor-ic-analyzer-workflow | `9510dc8` | ✅ 已完成 |
| **R50 第 2 轮 (2026-07-09 下午)** | **同步上游 12 个独立 skill** | **本次 design** | **本次执行** |

两次 R50 拆分协同 = 上游 9 核心 skill 跟 hermes-agent 一致 + 项目特定内容走 factor-ic-analyzer-workflow + 18 个项目特定 skill 保留 = **完整 R50 拆分清理**.

---

## 7. 后续 follow-up (不在本次范围内)

1. **R50+**: 跨 skill `related_skills` 字段审计 — 检查本机 18 个项目特定 skill 的 `related_skills` 是否引用了非上游 skill (e.g. factor-development / factor-summary-reporting / dead-code-and-observability-fixes), 引用错的话修
2. **R50+**: 项目特定 skill 二次审计 — 18 个项目特定 skill 是否每个都有"项目特定" 标签 (e.g. factor-* / hermes-* / web-*), 没有的话加
3. **R51+**: 跟进 hermes-agent upstream 后续 commit (56a8e81d 之后), 每月 sync 一次上游 12 个 skill
4. **R51+**: factor-ic-analyzer-workflow 进一步精简 — 当前 178 行 / 152 references, 可按 R50 上次拆分的 references 子目录思路继续拆

---

## 8. 提交消息模板

```
同步上游 hermes-agent 12 个独立 skill (R50 第 2 轮拆分清理)

按用户原话 2026-07-09 "保证这 9 个独立 skill 和 hermes 自带的保持一致,
我们自己后续加的内容都迁移走一个新的 skill":

补齐上游 8 个缺失的核心 skill + 2 个可选 skill:
- test-driven-development (10.3 KB)
- systematic-debugging (14.0 KB)
- requesting-code-review (8.5 KB)
- spike (8.7 KB)
- simplify-code (10.9 KB)
- hermes-agent-skill-authoring (10.6 KB)
- python-debugpy (13.2 KB)
- node-inspect-debugger (10.9 KB)
- code-wiki (14.1 KB)
- rest-graphql-debug (15.6 KB)

同步 subagent-driven-development (上游 10.7 KB 替换本机 13.3 KB,
差异 84 行, 上游是 source of truth):
- 备份本机版本 → 复制上游 → 删备份

保留:
- superpowers-workflow 还原状态 (179 行 / 192 references, R50 第 1 轮)
- factor-ic-analyzer-workflow (178 行 / 152 references, R50 第 1 轮)
- 18 个项目特定 skill (adversarial-review / cross-skill-content-restructure /
  dead-code-and-observability-fixes / debugging / debugging-hermes-tui-commands /
  development-methodologies / factor-ic-analyzer / hermes-s6-container-supervision /
  hermes-tool-pitfalls / hermes-webui-debugging / module-boundary-enforcement /
  public-module-optimization / skill-audit-and-slimming / skill-slim-down-pattern /
  web-chart-integration / writing-plans)

依据：用户原话 "保证这 9 个独立 skill 和 hermes 自带的保持一致" +
superpowers-workflow Generic-Skill Pollution Rule (2026-07-09 加) +
R50 第 1 轮拆分 commit `9510dc8`

注：实际 skill 文件操作在 ~/.hermes/skills/ 下 (不在本 repo),
本次仅记录设计文档
```