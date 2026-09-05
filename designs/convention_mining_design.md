# 约定蒸馏层设计（convention mining）

> 2026-09-05。来源：用户目标「dl-workflow 可靠性的最直接标准是改动面准确；codegraph/LSP 已解决符号定位，但模型还缺对项目隐含规范的理解——层级规范、代码规范、封装工具类都埋在实现里；规范文档与最新实现漂移、规范间冲突时如何取舍」。
> 策略（用户已选）：**以当前项目为试验田**——先把「项目理解层」方法论在 factor_ic_analyzer 跑通验证，再外推几百万行无可靠文档的大项目。
> 方案（用户已选）：方案 A 约定蒸馏为主线；方案 B 范例检索二期增强；方案 C 理解探针等真实失败案例积累后再做。

## 问题结构

「理解项目」四类知识，获取难度递增：

1. 符号结构（谁调谁）——已由 codegraph/cgx/Serena 解决。
2. 显性规范（写下来的规则）——CLAUDE.md/PROJECT.md/MODULE.md，但面临漂移与冲突。
3. **隐性约定**（埋在实现里的：实际在用的工具函数、真实分层依赖方向、写法模式）——本设计靶点。
4. **仲裁规则**（2 与 3 冲突、规范互相冲突时信谁）——本设计靶点。

外推大项目的硬约束：**大项目往往没有可靠文档，唯一真源是代码本身**——故蒸馏必须纯代码驱动，不依赖文档先行。文档在此仅作对照源与 ground truth。

## 关键事实（动手前已查证）

- codegraph db 现成含 `edges(kind='calls')` + `nodes`，工具函数调用频次/调用方分布可直查，无需自建解析（同 cgx 路径，见 designs/precision_tiers_landing-design.md）。
- post-commit hook 主仓已装（commit 后后台 sync codegraph），蒸馏重跑可搭同一班车；hook 在 .git/hooks 不入库，换机需重装（既有约定）。
- 注入通道：codegraph_inject.py（UserPromptSubmit，项目专属）在 `.claude/hooks/`，注册于 `.claude/settings.json`，运行约定见 designs/codegraph_auto_inject_design.md。蒸馏瘦档**并列新 hook**，不改现有 inject。
- 本项目 H1-H13 显式硬规则 = 蒸馏器现成的 ground truth（试验田的核心优势）：蒸馏器连显性规则都挖不准，就谈不上挖隐性约定。
- 当前无「模型违反约定」失败案例库（仅有历史 2 例：web_ui 模板二次 ×100、stale fixture 绕过归一化），故效果验证后置，一期只验证蒸馏事实准确。

## 蒸馏维度（一期 4 个）

隐性约定 = **代码中统计上稳定重复的模式**。每条产出带样本量的统计事实，不只合规/违规二值。

| 维度 | 实证内容 | 本项目 ground truth | 大项目外推对应 |
|---|---|---|---|
| D1 共享工具使用图谱 | 公共工具函数调用频次 + 调用方分布（查 codegraph db） | H7「路径只能 from paths import」 | 自研工具类 vs 三方库直用的真实偏好 |
| D2 分层依赖方向 | 模块间实际 import 图 | H1 模块边界（web_ui 只读后端） | 声明分层架构 vs 实际依赖方向 |
| D3 写法模式 | 日志风格统计（%-惰性 vs f-string）、退出码使用分布 | H11/H12 | 代码规范的真实遵守度 |
| D4 骨架模式 | 同类脚本结构共性（main 结构、参数解析、落库函数命名） | scripts/ 现有脚本族 | 「新写一个 X 该长什么样」的统计答案 |

统计多数 ≠ 规范，但它是仲裁时的关键证据（如「f-string 日志 N 处集中于 web_ui/」指示漂移的局部性）。

## 产出物形态（两层，与 codegraph 系同构）

1. **全量层**：`.conventions/conventions.db`（sqlite）。每条约定一记录：`{id, 维度, 陈述, 来源(文档声明/代码实证), 证据样本(file:line×N), 样本量, 合规率, 漂移标记}`。配 CLI `scripts/cvx.py query <主题>`（命名对齐 cgx），供模型按需深查，H11/H12 同守。
2. **瘦档层**：新 hook `.claude/hooks/conventions_inject.py`（UserPromptSubmit，注册于 `.claude/settings.json`），注入极瘦「项目约定摘要 + 活跃漂移点清单」。漂移点形如：`⚠️ H11 声明禁 f-string 日志，但 web_ui/ 存在 N 处实证违反——动手前先确认权威`。token 预算对齐 codegraph_inject 瘦档量级。

## 仲裁原则：不裁决，只呈证

- 默认权威 = 文档声明的 H 规则；实证与文档漂移时，「文档说的」与「代码实际干的」并列呈现，**升级给人决断**（规范该更新还是代码该整改是人的决策，契合 PROJECT.md 数据驱动原则——漂移暴露出来，模型不擅自站队）。
- 重构期「实现即规范」场景：一期不做自动翻转机制，漂移暴露即可；若需要，由人在 PROJECT.md 显式声明某条真源优先级翻转，蒸馏层读取该声明（二期按需）。

## 新鲜度维护

- 触发：post-commit hook 后台重跑蒸馏（搭 codegraph sync 同一班车）。本项目规模预计秒级；外推大项目时按维度增量（commit 触及的模块重挖对应维度）。
- 防呆：db 带 `generated_at` + 触发 commit hash；瘦档注入时落后超过 5 个 commit 则标注「约定索引过期」（同 codegraph 注入现有做法）。
- 降级：蒸馏失败不阻塞 commit；瘦档缺失静默跳过——知识供给是增强不是门禁，蒸馏器故障不得成为开发阻塞点。

## 文件清单与分批（H9：单批 ≤3 文件 AND ≤200 行）

| 批 | 文件 | 行数估 |
|---|---|---|
| B1 | designs/convention_mining_design.md（本文件） | ~110 |
| B2 | scripts/mine_conventions.py 骨架 + D1/D2 | ~180 |
| B3 | scripts/mine_conventions.py 增量 D3/D4 | ~150 |
| B4 | scripts/cvx.py | ~90 |
| B5 | test_cases/test_mine_conventions.py + test_cvx.py | ~160 |
| B6 | .claude/hooks/conventions_inject.py + .claude/settings.json 注册 + post-commit 挂接 | ~80 |
| B7 | CLAUDE.md §3 执行映射加 cvx 行 | ~5 |

## 验证方案

1. **对账验证（一期必做）**：人工 grep 复核蒸馏器对 H7/H11/H12 的实证统计（f-string 日志处数、路径硬编码处数、模块越界 import），两者必须一致。
2. **反证验证（一期必做）**：选一个文档未写、但代码有强模式的约定（候选：scripts/check_*.py 族的退出码用法或命名模式），看蒸馏器能否在无文档指引下挖出——模拟大项目无文档场景。
3. **效果验证（二期，等案例）**：此后每起「模型违反已有约定」类失败，复盘检查：该约定是否已被蒸馏覆盖？覆盖了但注入没拦住 → 改注入；没覆盖 → 补维度。**失败案例驱动维度扩充**，不一次铺满。
4. 验收数据回填本文件「验收记录」节。

## 风险

- 蒸馏维度误判（把巧合当模式）：靠样本量阈值 + 证据样本可人工复核缓解；宁可漏报不误报（误报污染瘦档，漏报等案例驱动补）。
- 瘦档 token 膨胀：漂移点清单设上限（如最多 5 条，按新近度/严重度排序），超出的进 db 由 cvx 按需查。
- 大项目外推时全量统计性能：一期不优化，设计已预留按维度增量路径。

## 验收记录

（待回填：对账数据 / 反证结果 / 瘦档 token 实测 / 案例复盘）
