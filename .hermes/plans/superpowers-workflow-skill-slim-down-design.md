# Design: superpowers-workflow Skill 精简方案

> **任务**：将 `~/.hermes/skills/software-development/superpowers-workflow/SKILL.md` 从 171KB/1568行 精简到 ~30KB/~300行（缩减 82%）
> **策略**：激进方向（拆分主文件 + 引用 references/）
> **日期**：2026-06-30
> **关联规范**：PROJECT.md 弱模型防御规则 #12（Design-First：涉及 2+ 文件改动必须先提交 design.md）

---

## 1. 现状分析（事实）

| 指标 | 数值 | 说明 |
|---|---|---|
| SKILL.md 字节数 | 171,053 (171 KB) | 单次任务加载即吞下 17 万字符 |
| SKILL.md 行数 | 1,568 | — |
| references/ 文件数 | 56 | 基础设施已存在但未被充分利用 |
| references/ 总行数 | 45,995 | 历史教训沉淀丰富 |
| templates/ 文件数 | 4 | pre-commit/PR 模板 |

**核心问题**：主文件平铺了所有内容，references/ 目录虽然有 56 个文件但只在主文件中以"详见 references/xxx.md"形式被引用，主文件本身又把同一内容的摘要完整展开——**重复 + 难以维护**。

---

## 2. 设计原则

1. **主文件 = 流程骨架**：只留触发条件 + 4 阶段流程图 + 关键速查表 + references 索引
2. **references = 主题详情**：每个文件聚焦一个主题，可独立 `skill_view(file_path=...)` 加载
3. **零内容丢失**：references 已存在的 56 个文件**完全不动**，主文件平铺的细节 1:1 拆到新 references
4. **零合并判断**：不合并任何已有 references 的内容（避免内容丢失风险），合并/去重留给后续轮次

---

## 3. 拆分方案（13 项具体动作）

### 3.1 新建 7 个 references 文件

| 新文件 | 来源（SKILL.md） | 预计行数 | 内容描述 |
|---|---|---|---|
| `references/workflow-phases-detail.md` | L293-871（579 行，4 阶段详细描述） | ~580 | PHASE 1 Plan/2 Execute/3 Review/4 Debug 的完整描述（启动检查、设计优先、任务粒度、Spec Compliance 详细清单、Stage 1-3 详情） |
| `references/spec-compliance-checklist-full.md` | L655-788（134 行，Spec Compliance 详细 30+ 项） | ~140 | Spec Compliance 完整 30+ 项检查清单（含 pitfall 说明、检查方法、典型案例） |
| `references/pitfall-catalog-by-topic.md` | L1164-1380（约 220 行，按主题分组的 pitfall 表） | ~240 | 按"Python/日志/数据/管道/导入/重构/性能"主题分组的 50+ pitfall，每条保留"标题 + 现象 + 修复 + 案例"格式 |
| `references/diagnostic-conclusion-types.md` | L590-624（35 行） | ~40 | 诊断结论类型（规范遗漏/代码 bug/混合问题/设计问题/冗余）详解 |
| `references/deprecated-code-lifecycle.md` | L1383-1409（27 行） | ~30 | 废弃代码生命周期管理规范（5 字段规范表 + 流程） |
| `references/workflow-self-discipline.md` | L1075-1145（70 行） | ~80 | Anti-Rationalization 借口反驳表 + Red Flags 违规信号 + Skill 协作矩阵 |
| `references/task-summary-format.md` | L1443-1460（18 行） | ~25 | 完成总结格式（修改清单 + 验证结果 + 规范合规 + 待后续处理） |

**合计新增**：~1135 行 → 平均每个文件 100-200 行，可独立加载

### 3.2 精简 SKILL.md 主文件（13 → 6 节）

| 节 | 标题 | 内容 | 预计行数 |
|---|---|---|---|
| §1 | ⚠️ 入口守门员（强制触发） | L13-36 不变 | 25 |
| §2 | Why Superpowers + 核心原则速查 | L38-44 + L1060-1072 合并精简 | 25 |
| §3 | 4 阶段流程骨架 | 精简版（每阶段 = 触发条件 + 核心动作 + 产物 + 加载哪个子 skill） | 100 |
| §4 | 关键 Pitfall 速查表（精选 ~15 条） | 从 50+ 精选最常踩的 15 条，每条 ≤3 行 | 50 |
| §5 | Skill 协作 + 何时加载哪个 skill | L1132-1145 + 精简 | 30 |
| §6 | references 完整目录（按主题分组） | 按 5-6 个主题分组列出所有 references 链接 | 50 |
| — | 文件头 + frontmatter | — | 15 |

**合计**：~295 行 / ~30 KB

### 3.3 新建 references/README.md（总索引）

按主题分组列出所有 56 个 references 文件：
- 通用方法论（Plan/Execute/Review/Debug 各阶段）
- 因子开发（factor IC、回测、composite、selector、weight）
- 数据架构（data layer、path、cache、incremental）
- 代码质量（公共模块、type/import/refactor）
- 测试 & 文档（pytest、test case sync、doc refinement）
- 实战陷阱（pitfall catalog、session 案例）

---

## 4. 不在本次范围内

明确**不做**的事：

1. ❌ **不合并任何已有 references**（round5/6/7/8 模式保留独立文件，避免合并判断风险）
2. ❌ **不动 templates/**（pre-commit-config.yaml、PR 模板等已合理）
3. ❌ **不修改任何其他 skill**（writing-plans、subagent-driven-development 等）
4. ❌ **不删除任何历史教训条目**（一字不丢原则）
5. ❌ **不动 PROJECT.md / AGENTS.md**（与 skill 精简无关）

---

## 5. 风险评估

| 风险 | 缓解措施 |
|---|---|
| 主文件引用某个新 references 但引用路径写错 | 完成后用 `grep "references/" SKILL.md` 全量核对每个引用 |
| 拆出的内容丢失上下文，导致独立加载时理解困难 | 在每个新 references 文件开头加 1-2 行"何时使用此文件"导引 |
| Agent 找不到某个主题的 references | 新增 README.md 提供多入口索引 |
| Skill 主文件太薄导致新人/弱模型缺失关键判断 | §4 精选 15 条最常踩 pitfall 速查表作为兜底 |

---

## 6. 执行步骤

```
Step 1: 创建 references/workflow-phases-detail.md（579 行，最大块）
Step 2: 创建 references/spec-compliance-checklist-full.md（140 行）
Step 3: 创建 references/pitfall-catalog-by-topic.md（240 行）
Step 4: 创建 references/diagnostic-conclusion-types.md（40 行）
Step 5: 创建 references/deprecated-code-lifecycle.md（30 行）
Step 6: 创建 references/workflow-self-discipline.md（80 行）
Step 7: 创建 references/task-summary-format.md（25 行）
Step 8: 精简 SKILL.md 主文件到 ~295 行
Step 9: 创建 references/README.md 总索引
Step 10: 验证（grep 引用、ruff、skill_view 加载）
```

预计每步 2-5 分钟，总计 30-50 分钟。

---

## 7. 验证标准

- [ ] SKILL.md ≤ 35 KB（缩减 ≥ 80%）
- [ ] SKILL.md ≤ 350 行（缩减 ≥ 78%）
- [ ] 所有 SKILL.md 中的 `references/xxx.md` 引用都能在新文件/已有文件中找到
- [ ] 7 个新 references 文件都通过 `read_file` 可正常读取
- [ ] `references/README.md` 按主题列出所有 56+7 = 63 个文件
- [ ] ruff check SKILL.md（虽然 .md 不强制，但确认无明显 markdown 错误）

---

## 8. 提交消息模板

```
精简 superpowers-workflow skill：SKILL.md 171KB → 30KB

按激进拆分方向：
- 主文件只保留流程骨架 + 关键 pitfall 速查 + references 索引
- 7 个主题文件拆出到 references/（按需加载）
- 新增 references/README.md 总索引（按主题分组）
- 不合并任何已有 references，所有历史教训一字不丢

变更文件：
- SKILL.md: 1568 → ~300 行
- 新增 7 个 references/*.md
- 新增 references/README.md

验证：
- SKILL.md 字节数：171053 → ~30000（缩减 82%）
- 所有 references 引用路径已 grep 核对
- skill_view 加载正常
```

---

## 9. 关联规范引用

- **PROJECT.md 弱模型防御规则 #12（Design-First）**：本次涉及 1+7+1 = 9 个文件改动，先提交 design.md 审核（本文）
- **AGENTS.md 入口守门员**：本次编辑 skill 文件不需要查询 codegraph（skill 系统不属于项目代码），但仍需遵循 ruff + pytest 流程
- **superpowers-workflow L562/L1219**：每轮 ruff+pytest 通过后立即 git commit，本设计文档作为提交参考