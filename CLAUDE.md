# CLAUDE.md - factor_ic_analyzer 维护指南

> 本文件由 Claude Code 每次会话自动加载，作用 = 入口守门员 + skill 路由表 + 执行映射。
> 本项目由 Claude Code 维护。

## 0. 真源（不复制规则）
| 文档 | 何时读 |
|---|---|
| AGENTS.md | 每次自动读；硬规则速查 + 入口守门员 + 第一性原理 + 战略目标 + T+1 规则 |
| PROJECT.md | 主动读取触发：新增模块/脚本类型、改 paths.py/schema/跨模块数据契约、2+ 文件(Design-First)、讨论"为何这样设计" |
| `<模块>/MODULE.md` | 改该模块代码前必读 |

**铁律**：H1-H13 硬规则、M 规则完整定义只在 PROJECT.md/MODULE.md。本文件只放指针 + 一句话速查，绝不复制规则正文（项目 `check_doc_layer.py` 禁止跨层重复）。

## 1. 入口守门员（每次开发任务前必做）
1. 读规范：AGENTS.md + 命中触发读 PROJECT.md/MODULE.md
2. 查代码结构：codegraph CLI（见 §3）
3. 读规范内容：本文件已加载，仍需动手前对齐 PROJECT.md/MODULE.md 相关章节--未读直接改代码 = 流程违规（AGENTS.md 入口守门员）

## 2. Skill 路由表（触发 -> 加载哪个 skill）
| 触发关键词/场景 | 加载 skill |
|---|---|
| 开发因子/新增因子/IC脚本/分层回测/权重/选股 | `/factor-development` |
| 跑报告/出 summary/报告异常/基础数据源/freshness/§9 §10 | `/factor-summary-reporting` |
| 日内操作/开盘怎么卖/高开低开止损/9:25集合竞价/反抽 | `/intraday-strategy-design` |
| pipeline 没跑/X没落库/silent fallback/selection_date/trade_date/weight_method 切换断层 | `/factor-ic-analyzer-workflow` |
| 新增函数/脚本(写代码前) | TDD：先写测试再实现 |
| 测试失败/运行时错误 | 系统性调试：reproduce -> hypothesis -> test -> fix，禁猜 |
| 裁决类结论(给结论前)：根因/有效吗/选哪个/能上线吗 | 对抗性审视：尝试反驳自己的结论 |
| 死代码/静默失败/5+ bug 批量修复 | 见 PROJECT.md H13 死代码判定边界 |
| 任何编码任务(行为约束) | 4 原则（见 §4） |

加载纪律：命中触发才加载；不默认预读。skill 自包含（正文即要点）。

## 3. Claude Code 执行映射
| 任务 | 做法 |
|---|---|
| 查代码结构/callers/impact | Bash: `codegraph callers <symbol>` 或 `sqlite3 .codegraph/codegraph.db "..."`（CLI 在 `/home/admin/.npm-global/bin/codegraph`；db 用 `nodes` 表 + `kind` 字段；新鲜度 `SELECT datetime(MAX(indexed_at)/1000,'unixepoch','+8 hours') FROM files;`） |
| **跨文件调用/影响面断言**（H15 证据约定） | 凡说"X 调用了 Y / 改这个影响 Z"，必附 `codegraph callers/impact` 原始输出或 `file:line` 证据。伪造的断言经不起"贴行号"--用户怀疑时可要求"贴 codegraph 输出"即验真 |
| 改已有 .py 源码（H15 门禁） | PreToolUse hook 强制：本会话 audit log 无 codegraph 查询记录则阻断(exit 2)。先跑一次 `codegraph impact <symbol>` 留痕后放行。白名单跳过：非 .py / test_*.py / 新建文件 / scripts/check_*.py |
| 跑长 pipeline(15-30min) | 后台 Bash(`run_in_background:true`)，等通知收结果；**禁 `| tail`/pipe**（SIGPIPE 杀进程 exit 0 误判成功）；禁轮询；禁 kill 运行中的 pipeline |
| 读 parquet | Bash: `python3 -c "import pyarrow..."`（项目 venv 有 pyarrow） |
| 向用户确认方案 | AskUserQuestion |
| 大 JSON 验证 | 流式 `load_factor_values()`，禁 `json.load` 全量(OOM exit 137) |
| 跑测试/lint | `pytest` / `ruff check --fix . && ruff format . && ruff check . && mypy .` |

## 4. 4 阶段流程 + 行为准则（一句话速查）
**开发流程**（涉及代码改动必循）：`Plan -> Execute -> Review -> Debug`
- **Plan**：先探索再规划；读 PROJECT.md+MODULE.md；2+ 文件先写 `designs/<topic>_design.md` 停下等审核；任务粒度 ≤3 文件 ≤200 行
- **Execute**：分步验证；每步跑脚本看实际输出
- **Review**：ruff -> pytest -> Spec Compliance(对照规范) -> Code Quality
- **Debug**：测试失败先系统性调试找根因，**禁调参数式临时修复**(AGENTS.md §⚡)

**行为准则 4 原则**：
1. Think before coding：显式陈述假设；不确定就问
2. Simplicity first：最小可用代码；不写未要求的抽象/配置/容错
3. Surgical changes：只动该动的；匹配既有风格
4. Goal-driven：定义可验证成功标准；循环到验证通过

**跨阶段铁律**：Read before write；verify before claiming done（说"完成"必附证据）；no silent fallback（捕获异常必 log，默认值必标记，缺数据必暴露）；frequent small commits；commit message 引用规范行号。

## 5. 硬规则指针（不复制正文）
H1-H13 完整定义见 **PROJECT.md §硬规则**。最易踩：
- **H1/H1.1**：模块边界；web_ui 只读不改后端
- **H7**：路径只能 `from paths import`（改前核实 PROJECT.md 待确认项）
- **H8**：2+ 文件先写 design.md
- **H9**：单次 ≤3 文件 AND ≤200 行
- **H11**：日志 `%` 惰性格式化，禁 f-string / `exc_info=True`
- **H12**：退出码语义(0/1/3/4/5)，main 内禁 sys.exit
- **H13**：禁死代码兜底分支
- **H15**：codegraph 查证--改已有源码前强制查（PreToolUse hook 门禁）；跨文件断言必附证据。详见 `designs/codegraph_enforcement_gate_design.md`

## 6. 环境
本项目由 Claude Code 独占维护。4 个项目 skill 在 `.claude/skills/`（自包含）。`.codegraph/codegraph.db` 可用。完整规范见 AGENTS.md / PROJECT.md / MODULE.md。

**H15 门禁**（2026-07-22 起）：`.claude/hooks/` 下 codegraph_gate.py（PreToolUse 阻断）+ codegraph_audit.py（PostToolUse 留痕）+ codegraph_inject.py（UserPromptSubmit，瘦档注入真源；运行约定见 `designs/codegraph_auto_inject_design.md` §运行约定：重启生效后 assistant 每轮显式复述「## codegraph 自动注入」段落作证据源）已启用，注册于 `.claude/settings.json`。改已有 .py 源码前强制查 codegraph。

> ⚠️ `check_doc_layer.py` 被 PROJECT.md/CLAUDE.md/skills README 多处引用"禁止跨层重复"，但脚本未实现--该约束当前零强制（H15 检查工具列只引用真实存在的 hook 脚本，不引幽灵）。重建它属独立项。
> ⚠️ Claude Code 项目 skill 注册可能需**重启会话**才能 `/invoke`。未生效前读 `.claude/skills/<name>/SKILL.md`。
