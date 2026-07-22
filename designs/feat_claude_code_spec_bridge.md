# Design: Claude Code 规范适配桥接层（AGENTS/PROJECT/MODULE → Claude Code）

> **任务**：把为 Hermes harness 编写的项目规范体系（AGENTS.md / PROJECT.md / `<模块>/MODULE.md`）适配到 Claude Code，建立等价的执行层与知识库，使 Claude Code 可作为本项目维护者。
> **日期**：2026-07-22
> **关联规范**：PROJECT.md「AI 协作模式 -> harness 中立约定」（明确授权：若某流程在特定 harness 下不可直接执行，由智能体在保持等价语义前提下用平台可用能力实现）；AGENTS.md §0 开发流程 / §🎯 Skill 触发识别；H8（Design-First：本次涉及 2+ 文件改动）
> **范围**：仅创建 `.claude/` 配置与记忆文件；**不改任何业务代码、不改 AGENTS.md/PROJECT.md/MODULE.md 规则文本、不改 check_*.py、不改 paths.py/schemas**。

> **⚠️ 状态更新（2026-07-22）**：用户随后决定**完整卸载 Hermes**。本文档记录适配设计过程；其中"保留 Hermes 原件 / 逐步迁移 / Hermes 原件作过渡参考 / 端口自 Hermes"等陈述**已被推翻**。最终状态：Hermes 已完整卸载（`systemctl --user stop+disable hermes-gateway`、进程全停、`~/.hermes` + `hermes-agent` + `hermes-webui` + CLI + systemd unit 全删，释放 ~4G），4 个 skill 重写为自包含。见 `CLAUDE.md` §6 与 `.claude/skills/README.md`。

---

## What（改造定义）

本项目规范分两层：

| 层 | 内容 | 可移植性 |
|---|---|---|
| **规则层** | H/M/S 规则、`scripts/check_*.py`（8 个 AST 检查器）、Design-First、退出码语义、JSON Schema、`paths.py`、多管线架构 | ✅ 100% harness 中立，纯散文 + Python 脚本，**原样保留** |
| **执行层** | ① `pre_llm_call` hook 自动注入 routing table + codegraph 模块图；② `skill_view(name=...)` 按需加载具名 skill；③ 10 个具名 skill 作为知识库 | ❌ Hermes 专属，在 Claude Code 下全部失效 |

**命门事实**：Hermes 知识库本体仍在磁盘（`~/.hermes/skills/`，gateway 仍在运行），所有具名 skill 的 SKILL.md + `references/`（factor-development 182 个、factor-ic-analyzer-workflow 296 个、factor-summary-reporting 46 个）均可读。`codegraph` CLI（`/home/admin/.npm-global/bin/codegraph`）+ `.codegraph/codegraph.db`（79MB）真实可用。

→ 因此本次是**搬运 + 去耦合**，不是重建。

---

## Why（为何这样设计 · 三大原则）

### 原则 1：de-Hermes-ify（去耦合 Hermes 运行时）

Hermes skill 深度耦合运行时机制：`skill_view(name, file_path)`、`linked_files` 自动索引、`execute_code` vs `terminal()`（pyarrow 可用性 / 持久 cwd）、Hermes cronjob。这些在 Claude Code 下需替换为等价能力：

| Hermes 机制 | Claude Code 等价 |
|---|---|
| `skill_view(name='X', file_path='references/Y.md')` | `Read ~/.hermes/skills/.../references/Y.md`（绝对路径） |
| `execute_code` / `terminal(python3 -c ...)` | Bash（项目 venv `/usr/bin/python3` 有 pyarrow） |
| `linked_files` 自动索引 | 端口 skill 内显式列触发表 + 绝对路径指针 |
| Hermes cronjob | 系统 crontab / `run_pipeline.py` 后台 |
| `clarify(question, choices=[...])` | AskUserQuestion |
| `pre_llm_call` hook 注入路由 | CLAUDE.md 常驻（Claude Code 自动加载，等价"零合规成本"） |

### 原则 2：双路径兜底（不赌 skill 注册）

不确定本 harness（ark-code-latest）是否会自动发现项目级 `.claude/skills/<name>/SKILL.md`。故 **CLAUDE.md 的路由表同时指向 Hermes 原件的绝对 Read 路径**——即使 skill 注册失败，`Read` 兜底永远可用。4 个 `.claude/skills` 是"已去耦合、可 `/invoke`"的便利层，非唯一通路。

### 原则 3：不复制（守项目自身反重复规则）

- **不把 H/M 规则复制进 CLAUDE.md**——项目 `scripts/check_doc_layer.py` 禁止跨层重复（PROJECT.md 出现单模块强制句式即报错），复制即触发漂移告警。CLAUDE.md 只放**指针 + 一句话速查**。
- **不复制 `references/`**——478 个文件 ~700K token，复制违反单一数据源、制造维护双份。深内容仍读 Hermes 原件。
- **剥离 skill 自编辑元噪声**——`factor-ic-analyzer-workflow` 的 14 条"skill 元数据腐烂反模式"是关于 Hermes skill 编写的 META，与因子开发无关，不端口。

---

## How（文件清单 · 共 10 个新文件）

### A. 桥接层（1）
| 文件 | 作用 |
|---|---|
| `CLAUDE.md` | Claude Code 自动加载的常驻层。含：真源指针（AGENTS/PROJECT/MODULE，列 PROJECT.md 主动读取触发条件）、de-Hermes-ify 后的 skill 路由表（触发→skill名+Hermes绝对路径兜底）、4 阶段一句话骨架、karpathy 4 原则一句话、Claude Code 执行映射、硬规则指针（不复制）、迁移状态 |

### B. 项目 skill 端口（4 + 1）
| 文件 | 源（Hermes） | 端口策略 |
|---|---|---|
| `.claude/skills/factor-development/SKILL.md` | `~/.hermes/skills/quant-development/factor-development/` | 13-bucket 触发表 + 深内容指针 |
| `.claude/skills/factor-ic-analyzer-workflow/SKILL.md` | `~/.hermes/skills/factor-development/factor-ic-analyzer-workflow/` | 项目实战触发表 + 5件套 pipeline勘察反模式（去 execute_code/terminal） |
| `.claude/skills/factor-summary-reporting/SKILL.md` | `~/.hermes/skills/quant-development/factor-summary-reporting/` | Trigger 表 + 23 类 known issues 路由 + Audit workflow 跨节核对 |
| `.claude/skills/intraday-strategy-design/SKILL.md` | `~/.hermes/skills/intraday-strategy-design/` | 三档信号 + 反模式 + 工程落地模式 |
| `.claude/skills/README.md` | - | 端口约定说明（de-Hermes-ify / Hermes 原件保留 / 为何不复制 references） |

每个端口 skill：frontmatter（name 与目录名一致、description）+ 触发表 + "深内容：`Read ~/.hermes/skills/.../references/<file>`" + 去耦合的工作流指令。

### C. 记忆（3）
| 文件 | 作用 |
|---|---|
| `~/.claude/projects/-home-admin/memory/MEMORY.md` | 记忆索引（一行一指针） |
| `~/.claude/projects/-home-admin/memory/project-factor-ic-analyzer.md` | 项目类型 + 我是维护者 + Hermes→CC 迁移进行中 |
| `~/.claude/projects/-home-admin/memory/spec-bridge-conventions.md` | 如何在此项目干活（读 AGENTS/PROJECT/MODULE、Design-First、invoke 4 skill、codegraph 走 Bash、Hermes refs 作过渡源） |

不复制 repo 已记录的 gotchas（T+1 语义、SIGPIPE、OOM 均在 PROJECT.md/skill references，记忆只放指针）。

---

## Don't（不做的事）

- ❌ 不改 AGENTS.md / PROJECT.md / MODULE.md 任何规则文本
- ❌ 不改业务代码 / check_*.py / paths.py / schemas
- ❌ 不删 Hermes 原件（`~/.hermes/skills/` 保留作过渡参考，符合"逐步迁移"决策）
- ❌ 不复制 H/M 规则或 references 进 CLAUDE.md / 端口 skill
- ❌ 不配 `UserPromptSubmit` hook（本次范围外；CLAUDE.md 常驻 + 手动 codegraph 已覆盖 80% 场景，真出现"忘记加载 skill"再评估，参考 `.hermes/plans/superpowers-injection-plugin-design.md` 的成本核算 38KB/call）

---

## When（适用场景）

- 任何由 Claude Code 维护本项目的会话

> 2026-07-22 更新：Hermes 已完整卸载，本项目由 Claude Code 独占维护。

---

## Verify（验证标准）

- [ ] `grep -rn "skill_view\|linked_files\|execute_code\|terminal(" .claude/skills/ CLAUDE.md` → 零命中（已去耦合，仅 README 的说明性引用除外）
- [ ] `grep -rEn "H[0-9]+|M[0-9]+" CLAUDE.md` → 仅指针引用（"详见 PROJECT.md §硬规则"），无规则正文复制
- [ ] 4 个端口 skill 的 frontmatter `name:` 与目录名一致
- [ ] CLAUDE.md 路由表每条 skill 都有 Hermes 绝对路径兜底
- [ ] 记忆文件 frontmatter 合法（type: project/feedback）
- [ ] `ls projects/factor_ic_analyzer/.claude/skills/` 列出 4 skill 目录 + README
- [ ] 提示用户：skill 注册可能需重启会话；CLAUDE.md 立即生效（下次会话自动加载）

---

## 关联规范引用

- **PROJECT.md §AI 协作模式 -> harness 中立约定**：本次迁移的授权依据
- **AGENTS.md §0 开发流程 / §🎯 Skill 触发识别**：路由表来源
- **H8（Design-First）**：本次 10 文件改动，先提交本 design.md
- （2026-07-22 更新）原 `.hermes/plans/` 下 superpowers-injection-plugin-design / superpowers-workflow-skill-slim-down-design 两份 Hermes skill 维护文档已随 Hermes 卸载删除。其结论（CLAUDE.md 常驻优于 hook 注入；薄路由器优于重建肥版）已体现在本设计里。
