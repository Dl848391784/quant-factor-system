# Design: T+1 契约语义对齐三件套 (SSOT + 触发扩展 + [CONTRACT] 门控)

> **触发**: 2026-07-19 freshness「△延迟」误判复盘——信息在 skill/AGENTS.md/MEMORY 三层都在场，agent 仍判错。
> **根因**: 冗余拷贝 ≠ 检索，在场 ≠ 应用；门控只查完备性不查语义对齐；状态判定类问句不触发门控。
> **用户已拍板方案**: A(触发扩展) + B+(强制 [CONTRACT]) + SSOT(文档分层) 三件套。
> **遵循**: AGENTS.md §6 规范结构模板 / hermes-plugin-hooks-context-injection / 用户门控哲学(磁盘结构化证据链·零验证 token·非 agent 自觉)

---

## 一、失败证据链（Why）

| 层 | 当时状态 | 问题 |
|---|---|---|
| skill `intraday-strategy-design` Overview 首行含完整契约 | 未加载 | 触发识别表无"数据延迟/新鲜度"条目 |
| AGENTS.md §⏰ / MEMORY 契约 | **在场未应用** | 被动提醒概率性失效（memory 自证：S13 教训录后仍再犯） |
| codegraph 注入 | 生效 | 注结构非语义，无法对齐业务契约 |
| evidence-chain-gate | **未触发** | `ANALYSIS_PATTERNS` 无"延迟/正常/怎么判断"状态判定词 |
| 门控完备性检查 | 即便触发也只查 [READ]/[COUNTER]/[VERIFY] | 完备≠正确：不验证结论是否与 T+1 契约对齐 |

## 二、三件套设计（What + How）

### P1 · SSOT 文档分层（单一权威源 + 指针）

**唯一权威定义落点**: `PROJECT.md` §实战交易规则（L215，已有 [stable] 标记）内新增子节"核心数据契约（T+1 日期语义）"，按 §6 模板写 What/How/Don't/Why/Verify，内容：

```
selection_date = T-1 数据日 (= master parquet 最大日期)
trade_date     = T 买入日 (T 日尾盘)
持有收益       = forward_return_1d[trade_date] (T→T+1 收盘)

各 parquet 应有最新日期 (报告日 R 清晨生成, R_prev=R 的上一个交易日):
  master (factor_ic_data)      → R_prev        (T-1 数据已拉取)
  segment_stock_details        → R_prev        (T 日写入, 不等收益, 见 segment_win_db.py:64)
  segment_win_rates            → prev_trading_day(prev_trading_day(R)) 
                                 (收益 T+1 闭环才可算胜率, 0715推荐→0716买→0717卖→0717后可写)
  ic_results                   → prev_trading_day(R_prev) (IC 需次日收益)
```

**其余三处改指针，不再持有全文**：
- `AGENTS.md` §⏰：压缩为硬规则一句话 + 指向 PROJECT.md 子节
- skill `intraday-strategy-design` Overview：保留一句话上下文 + 指针
- MEMORY：删契约全文，仅留教训（S13 + freshness 两次"在场未应用"实证）

### P2 · 门控触发扩展（A）—— `~/.hermes/plugins/evidence-chain-gate/gate.py`

`ANALYSIS_PATTERNS` 增加状态判定类（CJK 无 \b，纯子串/正则）：
```
延迟, 新鲜度, 是不是正常, 正常吗, 对么|对吗, 怎么判断, 如何判断, 准不准, 是不是.*最新, 数据.*(对|准)
```
负例测试集（不得触发）: `帮我写一个函数` / `优化下 UI` / `跑一下报告`

### P3 · [CONTRACT] 强制对齐（B+）—— 同 gate.py

- 新增 `_needs_contract(user_message)`: 命中"日期语义判定词"（延迟/新鲜度/最新日期/正常吗/对么/怎么判断 + data/freshness 类）时，该 turn 证据链额外要求 `[CONTRACT]` 标签
- `[CONTRACT]` 内容只写**指针一行**：对齐 PROJECT.md 哪条契约（机器校验：必须含 `PROJECT.md` 或契约关键词 `selection_date`/`T+1`，防空写）
- 缺失时 pre_llm_call 注入警告（与 [COUNTER] 同构），完备时仅一行状态（零验证 token）
- 警告文案注入契约锚点一行：`本结论依赖的契约: selection_date=T-1 数据日, trade_date=T 买入日 (PROJECT.md §实战交易规则-核心数据契约)`

## 三、改动文件清单

| 文件 | 改动 | 模块 |
|---|---|---|
| `PROJECT.md` | §实战交易规则 新增"核心数据契约"子节 | factor_ic_analyzer |
| `AGENTS.md` | §⏰ 压缩为指针 | factor_ic_analyzer |
| `~/.hermes/skills/intraday-strategy-design/SKILL.md` | Overview 加指针 | hermes skill |
| `~/.hermes/plugins/evidence-chain-gate/gate.py` | 触发扩展 + [CONTRACT] | hermes plugin (非 git) |
| MEMORY (memory tool) | 契约全文→教训 | user profile |

粒度：文档 3 + plugin 1，各自独立小改动，分 2 个 commit（项目仓库 1 个；~/.hermes 非 git 无法 commit，直接落盘 + 验证）。

## 四、Don't

- ❌ 不在四处重复契约全文（SSOT 唯一，其余指针）
- ❌ [CONTRACT] 不注入完整契约（只一行锚点，防 token 膨胀——用户"膨胀全文注入非解法"）
- ❌ 不用 agent 自觉式自检（必须 hook 强制）
- ❌ 不改 `check_data_freshness` 期望日期逻辑（那是后续独立 bug 修复，本任务只做语义对齐基建）
- ❌ 触发词不加 `\b`（CJK 失效 pitfall）

## 五、验证（Verify）

1. PROJECT.md 子节存在且四处指针一致（grep 契约关键词，确认全文仅 PROJECT.md 一处）
2. gate.py: 正向"基础数据源延迟怎么判断"→触发+[CONTRACT] 警告；负向"帮我写函数"→不触发
3. 新进程 import gate 验证（非仅注册——Failure Mode 1 静默 fail-soft）
4. 提示用户重启 gateway + WebUI（plugin 生效必须，Failure Mode 5）
5. `pytest web_ui/test_cases/` 不回归（本任务不动 web_ui，但确认无连带）
