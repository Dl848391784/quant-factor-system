---
name: factor-ic-analyzer-workflow
description: factor-ic-analyzer 项目实战层（pipeline 静默失败诊断、selection_date/trade_date 三角语义、weight_method 切换断层、5 件套数据勘察反模式）。
version: 1.0
---

# factor-ic-analyzer-workflow

> 项目特定实战层。自包含方法论要点。核心 = Pipeline 勘察 5 件套反模式。

## 1. ⚠️ Pipeline 数据勘察工具/范围反模式 5 件套

任何"X 跑没跑 / X 数据末日期是什么"型调查，Plan 阶段第一动作必做：

| # | 反模式 | 修正 |
|---|---|---|
| 1 | 活跃管线 ≠ 看 default/ | 先确认 `PIPELINE_ALIAS`（default/ob_quality/...）：grep crontab + grep `paths.PIPELINE_ALIAS` + `ls result/<alias>/` 再断言 |
| 2 | 文件 mtime ≠ 数据日期 | parquet 写入时间 ≠ 内部最末 date。必读 `column='date'` 全量取 min/max（row group 局部查询会误判） |
| 3 | 跨 Bash 调用 cwd 持久 | `cd` 在 Bash 调用间持久，相对路径会错。用**绝对路径**双保险 |
| 4 | 读 parquet 用对 python | 项目 venv 有 pyarrow；缺则换有 pyarrow 的解释器 |
| 5 | 用户纠正 = 必显式承认 | 跨轮核对不能含糊带过：`[我前面判断错的点] = ...; 现按 <alias>/<全量 parquet> 复核` |

## 2. 三层 Silent Fallback 防御
Review 阶段必查三层：
- **数据层**：`except ValueError: return` 类静默吞
- **入口层**：`main()` 守卫掩盖真实错误
- **调度过程层**：进度日志戛然而止（可能 OOM/SIGKILL，配合 `dmesg` 验证 exit 137）

## 3. 日期语义（T/T-1/T+1 三角）
**权威定义 = PROJECT.md §实战交易规则 ->「核心数据契约（T+1 日期语义）」**。
判 freshness/延迟前必先对齐该契约（2026-07-19「△延迟」误报根因 = 未对齐契约就凭代码字面 `!=` 判延迟）。

核心：`selection_date = T-1 数据日 = prev_td(R)`；`segment_win_rates` 落后 2-3 交易日是 T+1 闭环物理必然（收益闭环才能算胜率），**不是延迟**。

## 4. weight_method 切换断层
weight_selector 日常切换 weight_method -> `segment_win_rates` 历史断层 -> §9 跳过 -> §10 缺"合并胜率" -> txt_parser 正则失败 -> WebUI §9/§10 空白。
**根治**：`_save_today_segment_details` 改为 4 种 weight_method 都落库 stock_details。

## 5. 触发关键词速查
- "X 没落库 / 不变化 / 空跑" -> 5 件套 + silent fallback 三层
- "selection_date / trade_date / T-1 / T+1" -> §3 日期语义 + PROJECT.md 契约
- "§9 §10 空白 / weight_method 切换" -> §4
- "composite_value 越负越好?" -> `factor_direction=negative` 时 composite_value 越负排名越靠前，全负是预期

## 6. 工作流
- **Plan**：查触发表路由；**不列 A/B/C 让用户拍**（先推断隐式倾向给默认值 + future work 标注）
- **Execute**：按方案实施 + commit
- **Review**：三层 silent fallback 检查
- **Debug**：沉默 fallback 4 步（grep 日志 -> pd.read_parquet -> 看代码 -> 列 3 方案）

## 7. 不要做的事
- ❌ Plan 阶段列 A/B/C 让用户拍
- ❌ 用户原话含"我也不知道"时反问（给默认值）
- ❌ 凭代码字面 `!=` 判延迟（先对齐 PROJECT.md 契约）
