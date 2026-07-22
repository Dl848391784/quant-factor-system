# .claude/skills/ - Claude Code 项目 skill

本目录 5 个 skill 是 factor_ic_analyzer 项目的方法论 skill，**自包含**（正文即要点，不依赖外部文件）。

## 清单
| skill | 覆盖 |
|---|---|
| `factor-development` | 因子开发全流程（新增因子 / IC / 回测 / composite / 权重 / 选股） |
| `factor-ic-analyzer-workflow` | pipeline 静默失败诊断、日期语义、weight_method 断层、5 件套勘察反模式 |
| `factor-summary-reporting` | summary 报告完整性、基础数据源新鲜度、跨节一致性核对 |
| `intraday-strategy-design` | T+1 日内操作三档信号、β 暴露误诊、连选前视偏差、Day1 三层过滤 |
| `workflow-creation` | 建工作流系统 + 运行诊断（ac-ark --workflow、注入/推进/wf 报错、worktree 快照陷阱） |

## 设计原则
1. **自包含**：每个 skill 正文即方法论要点，不依赖外部 reference 文件。
2. **真源分层**：H/M 规则完整定义在 PROJECT.md / MODULE.md；skill 只放触发识别 + 方法论要点 + 验证清单，**不复制规则正文**（`check_doc_layer.py` 禁止跨层重复）。
3. **不预读**：命中触发才加载。

## 使用
- **注册后**（可能需重启会话）：`/factor-development` 等 invoke
- **未生效前**：`Read .claude/skills/<name>/SKILL.md`

## 维护
- 改 skill 触发表 / 方法论 = 改本目录 `SKILL.md`
- 完整规范以 `PROJECT.md` / `<模块>/MODULE.md` 为准

> 2026-07-22：Hermes 已完整卸载。原 Hermes skill 的历史 case 细节（references）已随卸载删除，精华方法论已沉淀进本目录 4 个自包含 skill。业务设计草稿归档于 `designs/archive/from_hermes/`。
