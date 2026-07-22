# Design: 接入 superpowers + karpathy-guidelines 全局 skill，CLAUDE.md 改路由

> **任务**：用户原话「superpower 的 github 下载地址 https://github.com/obra/superpowers.git，另一个是 https://github.com/multica-ai/andrej-karpathy-skills.git，claude.md 文档中就不要有这些 skill 的精华内容了」。
> **日期**：2026-07-22
> **授权依据**：用户确认走「官方 marketplace 装」+ CLAUDE.md 删内联精华改路由。
> **关联规范**：AGENTS.md 弱模型防御规则（Design-First：2+ 文件改动）；H8（2+ 文件先写 design.md）。

## 1. 事实（已逐项核实）

### 1.1 两个源 repo 的真实形态

| repo | 形态 | skill 名 | 依赖/hook |
|---|---|---|---|
| obra/superpowers | 14-skill plugin marketplace（`superpowers-dev` marketplace，plugin `superpowers` v6.1.1）| 编排入口 = **`using-superpowers`**（**无 `superpowers-workflow`**）；含 test-driven-development / systematic-debugging / brainstorming / requesting-code-review 等 14 个 | 带 `hooks/session-start`：SessionStart(startup\|clear\|compact) 时把整份 `using-superpowers/SKILL.md` 经 `hookSpecificOutput.additionalContext` 注入会话 |
| multica-ai/andrej-karpathy-skills | 1-skill marketplace（`karpathy-skills`，plugin `andrej-karpathy-skills` v1.0.0）| **`karpathy-guidelines`**（与旧 hermes 同名，1:1）| 无依赖、无 hook；单文件自包含 |

**karpathy-guidelines 内容 = Think Before Coding / Simplicity First / Surgical Changes / Goal-Driven Execution**——正是现在 CLAUDE.md §4 内联的「行为准则 4 原则」的源头，1:1 匹配。

### 1.2 命名差异（关键，影响文档怎么写）

AGENTS.md / 历史引用写的是 `superpowers-workflow`，但 obra 仓库**没有这个 skill**，编排入口叫 `using-superpowers`。故 CLAUDE.md / AGENTS.md 的路由名必须改成 `superpowers:using-superpowers`（plugin 命名空间）。

### 1.3 obra SessionStart 注入 = 旧「自动注入」说法重新成立

obra 的 `hooks/session-start` 在每个**新会话**（startup/clear/compact）自动注入 `using-superpowers` 全文。这与 AGENTS.md 旧说法「已由 plugin 自动注入，不需要重复加载」**重新吻合**，差异仅：
- 注入点：hermes 旧版 `pre_llm_call`（每次 LLM call）→ obra `SessionStart`（每会话）
- skill 名：`superpowers-workflow` → `using-superpowers`

故 AGENTS.md line 26/45 的「自动注入」不是删，而是**更名 + 校准注入点**。

### 1.4 Claude Code plugin 现状

`~/.claude.json`：`enabledPlugins: NONE`，仅官方 marketplace 自动装过。第三方 plugin 启用走交互式 `/plugin` consent，手改 JSON 不可靠——故安装由**用户跑 `/plugin` 命令**（我无法触发交互 consent）。

## 2. 设计原则

1. **CLAUDE.md = 纯路由层（删精华）**：§4 不再内联 4 阶段流程 + 4 原则精华（这俩是 skill 的内容），改为一句话路由指针。**仅保留「跨阶段铁律」**——它是项目特定行为约束（Read before write / verify before claiming done / no silent fallback / frequent small commits / commit 引用规范行号），不在任何通用 skill 里。
2. **AGENTS.md = 项目真源（校准引用，不全删）**：AGENTS.md 是真源层，允许定义项目规则。其「## 0. 开发流程」4 阶段表是**项目调味版**（Review = ruff→pytest→Spec Compliance→Code Quality 是项目工具链，非 obra 通用版），故**保留表格**；仅把 4 处过时引用（`superpowers-workflow` / `skill_view` / 自动注入点）校准为真实 skill 名 + 准确注入语义。
3. **obra 提供的 skill 让 AGENTS.md 既有路由重新生效**：obra 的 test-driven-development / systematic-debugging 恰好补齐 AGENTS.md 路由表里那两行（原本是 hermes skill 名、Claude Code 下悬空）。
4. **历史散落引用不动**：`designs/`、`docs/`、`*.py` 注释里 ~30+ 处 `superpowers-workflow`/`karpathy` 引用属已归档设计草稿/历史，保留（H13 边界外，低优先级）。
5. **安装与文档解耦**：文档先改好（路由指向 skill 名），用户再跑 `/plugin` 安装 + 重启生效；安装未完成期间路由指向尚未加载的 skill，属可接受瞬态。

## 3. 实施步骤

### Step 0：用户跑安装命令（用户侧，我给清单）

```
/plugin marketplace add obra/superpowers
/plugin install superpowers@superpowers-dev
/plugin marketplace add multica-ai/andrej-karpathy-skills
/plugin install andrej-karpathy-skills@karpathy-skills
```
装完**重启会话**（SessionStart hook + skill 注册需重启生效；与 CLAUDE.md §6 既有「重启生效」约定一致）。

> marketplace 名/plugin 名取自两 repo 的 `.claude-plugin/marketplace.json`：obra marketplace=`superpowers-dev` plugin=`superpowers`；karpathy marketplace=`karpathy-skills` plugin=`andrej-karpathy-skills`。

### Step 1：改 CLAUDE.md §4（删精华 → 路由指针）

**现状 §4**：`4 阶段流程`（Plan→Execute→Review→Debug，4 行 bullet）+ `行为准则 4 原则`（Think before coding…）+ `跨阶段铁律`。

**改后 §4**：
- 删：4 阶段流程 bullet（→ `superpowers:using-superpowers`，SessionStart 自动注入）
- 删：行为准则 4 原则（→ `karpathy-guidelines` skill）
- **留**：跨阶段铁律（项目特定，非通用 skill 内容）
- 加：一句话路由——「开发流程方法论见 `superpowers:using-superpowers`（SessionStart 自动注入）；行为约束 4 原则见 `karpathy-guidelines`。下仅列项目特定铁律。」

### Step 2：改 CLAUDE.md §2 路由表（3 行校准 + 命名空间）

| 现行 | 改后 |
|---|---|
| 新增函数/脚本(写代码前) \| TDD：先写测试再实现 | 新增函数/脚本(写代码前) \| `superpowers:test-driven-development` |
| 测试失败/运行时错误 \| 系统性调试：reproduce→… | 测试失败/运行时错误 \| `superpowers:systematic-debugging` |
| 任何编码任务(行为约束) \| 4 原则（见 §4） | 任何编码任务(行为约束) \| `karpathy-guidelines` |

（obra 装上后这三行从「悬空 hermes 名」变「真实 plugin skill」。）

### Step 3：改 AGENTS.md 4 处过时引用（校准，不全删）

| 行 | 现状 | 改后 |
|---|---|---|
| 26 | 「见 `superpowers-workflow` skill 主文件 §🎯…（每次 LLM call 顶部已自动注入）」 | 「见 `superpowers:using-superpowers` skill（每个新会话由 superpowers plugin SessionStart 自动注入）」 |
| 38 | 任何编码任务 → `karpathy-guidelines` | 保留（plugin 装上即真实存在） |
| 45 | 「`superpowers-workflow` 唯一例外：已由 plugin 自动注入，不需要重复加载」 | 「`using-superpowers` 唯一例外：已由 superpowers plugin SessionStart 自动注入，不需要重复加载」 |
| 136 | 「必须加载 `superpowers-workflow` skill 并遵循 4 阶段流程」 | 「遵循 `superpowers:using-superpowers` 的 4 阶段流程（SessionStart 已自动注入）」 |
| 149 | `skill_view(name='superpowers-workflow')` | 删该行（Claude Code 无 `skill_view`；using-superpowers 已自动注入，无需手动加载命令） |

AGENTS.md「## 0. 开发流程」的 4 阶段表格 + 弱模型防御机制块**保留**（项目真源 + 项目调味版）。

## 4. 文件清单

| # | 文件 | 改动 |
|---|---|---|
| 1 | `CLAUDE.md` | §4 删 4 阶段+4 原则精华、留跨阶段铁律、加路由指针；§2 路由表 3 行校准 |
| 2 | `AGENTS.md` | 4 处引用校准（行 26/45/136/149），表格保留 |

2 文件，单批，符合 H9（≤3 文件）。文档改动非 .py 源码，**不触发 H15 codegraph 门禁**（白名单：非 .py）。

## 5. 需用户知晓的权衡（非阻断）

1. **obra 风格 vs 项目「不预读」张力**：obra `using-superpowers` 极强势（「1% 可能适用也必须 invoke、不可协商、强制 brainstorm」），与 CLAUDE.md §2 / skills README「命中触发才加载、不预读」相左。因 obra SessionStart 会自动注入它，启用后项目实质采纳 obra 的 eager 风格。用户已选装 obra，视为接受。
2. **全局 plugin 与 repo 文档耦合**：CLAUDE.md（提交进 repo）路由指向全局 plugin skill——文档假定维护者机器装了这俩 plugin。项目单维护者（CLAUDE.md §6），可接受；但换机/换人需先装 plugin。
3. **obra 全量带入**：装 superpowers plugin = 全 14 skill + SessionStart hook（每会话注入 using-superpowers 全文，有 token 成本，非瘦档）。与本项目 codegraph_inject「瘦档 ~150 token/次」不同路线，但二者正交（一个注入方法论，一个注入调用关系 ground truth）。
4. **AGENTS.md 更广的陈旧**：AGENTS.md 路由表另有 5 处 hermes-only skill 名（dead-code-and-observability-fixes / public-module-optimization / adversarial-review / hermes-webui-debugging / kanban-codex-lane）在 Claude Code 下仍悬空——**本次不动**（超范围），单列待清理。

## 6. 验证

- [ ] CLAUDE.md §4 不再含 4 阶段 bullet + 4 原则正文，仅留跨阶段铁律 + 路由指针
- [ ] CLAUDE.md §2 三行指向 `superpowers:*` / `karpathy-guidelines`
- [ ] AGENTS.md 无残留 `superpowers-workflow` / `skill_view` 字样（grep 验证）
- [ ] 用户跑完 4 条 `/plugin` 命令 + 重启后，新会话 SessionStart 注入 using-superpowers（可由会话顶部出现「You have superpowers」确认）
- [ ] `karpathy-guidelines` 可被路由/调用
