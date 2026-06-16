# ic_industry_earnings_growth_1d.py main/SPEC 职责清理 design

> 作者：云瑶
> 创建日期：2026-06-16
> 状态：已审核（2026-06-16 用户确认 A / 2 / Q3=是）
> 关联规范：AGENTS.md §0 Design-First / 规则 #12；factor_ic/MODULE.md M19-M23（异常与错误）；
> 关联范例：`factor_ic/ic_industry_amplitude_trend_1d.py`（同类清理已落地）；
> 关联 skill：dead-code-and-observability-fixes 模式 E（防御 `is None` 兜底面对永不返回 None 的函数）

---

## 1. 背景

用户审查 `factor_ic/ic_industry_earnings_growth_1d.py` 列出 5 项问题（详见原始反馈），核心诉求：
正常路径与错误路径职责清晰、CLI 入口只负责副作用、注册失败必须可观测。

读完上下游契约后**额外发现的事实**（影响修复方案选型）：

| 检查点 | 结论 | 证据 |
|--------|------|------|
| `run_factor_ic` 返回类型 | `dict[str, Any]`，**永不返回 None** | `factor_ic_runner.py:442` |
| `run_factor_ic` 失败路径 | `build_error_result(...)`（返回 dict） 或 抛 `DataSchemaError` | `factor_ic_runner.py:215/224/251/300/332/461` |
| `run_factor_ic` 是否抛 `FactorCalcError` | **否**（全仓 `grep raise FactorCalcError` 在 `common/` 与 `data_fetchers/factor_calculator.py` 均无命中） | `grep -rn "raise FactorCalcError"` |
| `log_factor_summary` 契约 | "不抛异常、不调用 sys.exit、不影响调用方控制流"，且自带 None 字段告警 | `factor_summary_logger.py:40-44, 83-92` |
| 同类已清理范例 | `ic_industry_amplitude_trend_1d.py` 已在 v 注释 L117-119 解释为何**完全删除** None 兜底 + `FactorCalcError` 兜底 | 该文件 L116-152 |

---

## 2. 与用户原始措辞的分歧（需用户确认）

用户对**问题 1** 的修复指令是：

> 将 result is None 时的处理改为直接 logger.error + sys.exit(1)，不借道异常

**严格按字面执行**（方案 A）会产生一个事实矛盾：`run_factor_ic` 的实现契约保证不返回 None，
保留的 `if result is None:` 永远不可达——这正是 dead-code skill **模式 E** 描述的反模式。
同目录 `ic_industry_amplitude_trend_1d.py` 的处理是**彻底删除**该兜底（方案 B），并在注释中
解释"失败路径走 build_error_result（dict）或抛 DataSchemaError，冗余的 result is None 兜底
掩盖真实错误来源，已移除"。

| 维度 | 方案 A（按字面执行） | 方案 B（与 amplitude_trend 一致） |
|------|---------------------|---------------------------------|
| `if result is None` 分支 | 保留，改为 `logger.error + sys.exit(1)` | 删除 |
| `FactorCalcError` import | 保留（仍可能被 `__main__` except 捕获到第三方抛出） | 删除（除非另有用途） |
| `__main__` `except FactorCalcError` 块 | 保留 | 删除（依赖通用 `except Exception`） |
| 与 amplitude_trend 一致性 | 不一致（独此一份保留死分支） | 一致 |
| 满足用户"职责清晰"诉求 | ✓（错误路径不再借道异常） | ✓（彻底没有错误路径污染主流程） |
| 死代码风险 | 引入死分支 | 无 |

**默认执行方案 A**（严格按用户给出的修复方案）；如用户接受方案 B，请回复"切方案 B"，
本设计将同步调整 Round-2 的 patch 内容。

---

## 3. 修复一览（按用户原编号）

| # | 问题摘要 | 修复动作 | 影响行 |
|---|---------|---------|--------|
| 1 | None 借道 `FactorCalcError` 异常使正常/错误路径混淆 | 方案 A：改为 `logger.error + sys.exit(1)` | L67-68 + L80-82 |
| 2 | CLI 入口 `return result` 无意义 | 删除 `return result` | L74 |
| 3 | `logger.info("...计算完成")` 与 `log_factor_summary` 语义重叠 | 删除该 logger.info | L73 |
| 4 | 注释 "None 状态整合告警" 与上方 None 判断责任重叠 | 注释更新为"输出 IC 摘要（公共模块,M3.1）"；并明确"None 检查由 main 提前退出，log_factor_summary 只处理合法 dict 结果" | L70 |
| 5 | 模块顶层 SPEC = register_factor 异常无兜底 | 用 `try/except (ValueError, TypeError) as e: logger.critical(...); sys.exit(2)` 包裹模块顶层注册（exit code 2 用于 import-time 配置错误，与运行时 exit 1 区分） | L43-49 |

> 退出码约定：0 成功 / 1 运行时失败（数据/计算）/ 2 配置/注册期失败。当前文件原本只用 0/1，
> 引入 2 的理由：register_factor 失败属于"代码或配置 bug"，与运行时数据错误本质不同；
> 与 AGENTS.md 规则 #6（退出码 0/1）兼容性见 §6 待用户确认事项。

---

## 4. 轮次拆分（遵循 dead-code-and-observability-fixes skill）

5 项 fix 跨"main 函数体内"和"模块顶层"两个结构层面，按风险/作用域分 3 轮，每轮独立 commit：

### Round 1 — main() 函数体内简单清理（fix #2 / #3 / #4）

- 删除 `return result`
- 删除 `logger.info("行业盈利增长因子IC计算完成")`
- 更新 `log_factor_summary` 调用前注释（去掉"None 状态整合告警"措辞，明确职责边界）

特征：纯局部、不改控制流、不改 import。

### Round 2 — 错误路径职责分离（fix #1，方案 A）

- `if result is None` 分支改为 `logger.error + sys.exit(1)`，不再 raise
- `FactorCalcError` import 保留（防御未来 calculation 抛该异常）
- `__main__` 的 `except FactorCalcError as e:` 保留（同上）

特征：改控制流，但作用域仍在函数内。

### Round 3 — 模块顶层注册兜底（fix #5）

- 在模块顶层 `SPEC = register_factor(...)` 包 try/except，捕获 `(ValueError, TypeError)`
  （`register_factor` 文档声明 `Raises: ValueError`；TypeError 用于防御 `FactorSpec` 构造期类型错误）
- 失败 → `logger.critical("FactorSpec 注册失败...")` + `sys.exit(2)`
- 不在 main() 内部完成注册：保持模块级 SPEC 单例契约（同目录其他 ic_*.py 一致）；
  且 `factor_ic/common/test_factor_spec_consistency.py:29` 通过 `importlib` + `pkgutil` 扫描所有
  `ic_*.py` 触发 SPEC 注册，**main() 内注册会破坏该测试**。

特征：模块顶层副作用变更，需单独 commit + 单独验证。

> **为什么 fix #5 不放进 main()**：完整理由 = (1) `test_factor_spec_consistency` 依赖 import 触发；
> (2) `factor_ic.common.__init__` 的 `__all__` 导出 `FACTOR_REGISTRY`，外部消费者期望 import 完成
> 即可读取注册表；(3) 把注册下移到 main() 等于把"配置错误"和"运行时错误"混在同一退出码下，
> 反而更糟。

---

## 5. 验证矩阵

每轮强制：

```
ruff check factor_ic/ic_industry_earnings_growth_1d.py
ruff format factor_ic/ic_industry_earnings_growth_1d.py
ruff check factor_ic/ic_industry_earnings_growth_1d.py     # 复查
pytest factor_ic/test_cases/test_ic_industry_earnings_growth_1d.py -x
git status --short | wc -l                                  # 隔离别人 staged 文件
git commit factor_ic/ic_industry_earnings_growth_1d.py -m   # 显式路径
git show --stat HEAD | tail
```

Round 3 额外：

```
pytest factor_ic/common/test_factor_spec_consistency.py -x  # 确认 importlib 扫描仍通过
python -c "import factor_ic.ic_industry_earnings_growth_1d; print('OK')"
```

---

## 6. 待用户确认事项

| ID | 问题 | 默认决定 | 影响 |
|----|------|---------|------|
| Q1 | fix #1 选方案 A（保留死分支按字面修）还是方案 B（彻底删，与 amplitude_trend 一致）？ | **A**（严格按用户措辞） | Round-2 patch 内容 |
| Q2 | fix #5 用 exit code 2 还是仍用 1？ | **2**（与运行时错误区分） | AGENTS.md 规则 #6 是否需补"2 = import-time 配置失败" |
| Q3 | 是否同步把 `ic_industry_momentum_5d_1d.py` / `ic_industry_turnover_trend_1d.py` 也按本方案清理？（这俩是同时期写的姊妹脚本，结构与本次目标文件一模一样） | **是**（用户确认） | 三脚本每轮一起 patch + 一起 commit |

---

## 8. 确认后的最终执行计划（2026-06-16 用户审核通过）

- 决策：**A / 2 / Q3=是**
- 范围：3 个文件
  1. `factor_ic/ic_industry_earnings_growth_1d.py`（用户指定）
  2. `factor_ic/ic_industry_momentum_5d_1d.py`（同结构姊妹）
  3. `factor_ic/ic_industry_turnover_trend_1d.py`（同结构姊妹）
- 排除：`factor_ic/ic_industry_amplitude_trend_1d.py`（已自行清理为 v1.0o 风格，不动）
- 每轮 commit 一次，单次 commit 含 3 个文件的同类修复（**显式列 3 个文件路径**，
  防止 staged 区其他 agent 的 D 文件被误带入；遵循 multi-agent-commit-isolation）。
- commit message 引用规范：
  - "遵循 PROJECT.md 规则 #6（退出码 0/1/2）"
  - "遵循 factor_ic/MODULE.md M19-M23"
  - "遵循 dead-code-and-observability-fixes 模式 E"

---

## 7. 不在本次范围

- amplitude_trend 已落地的 debug 字段追踪（`isinstance(result, dict)` 块）：本次**不引入**，
  因为问题列表未提及，引入会扩大 scope。
- 流程文档 `factor_ic/docs/ic_industry_earnings_growth_1d_flow.md` **不存在**（grep 已确认），
  本次也**不新建**（避免与用户原始 5 项要求脱节）。如用户要求补流程文档，单独一轮处理。
- 版本历史 docstring 不升版本号：本次属于职责边界清理，不涉及计算逻辑变化；
  若用户要求升版本，按 v1.0 → v1.1 + 追加版本块处理。
