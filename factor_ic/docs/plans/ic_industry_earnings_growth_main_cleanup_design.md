# ic_industry_earnings_growth_1d.py main/SPEC 职责清理 design

> 作者：云瑶
> 创建日期：2026-06-16
> 状态：✅ R4-R7b 完成（2026-06-16 切方案 B + H12/H13 升级硬规则）
> 历史状态：已审核（2026-06-16 用户确认 A / 2 / Q3=是）→ R3 收口后用户改方案 B
> 关联规范：PROJECT.md H8 Design-First / H9 任务粒度；factor_ic/MODULE.md M19-M23（异常与错误）；
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
> 与 PROJECT.md H12（退出码 0/1/2/3/4/5 语义）兼容性见 §6 待用户确认事项。

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
| Q2 | fix #5 用 exit code 2 还是仍用 1？ | **2**（与运行时错误区分） | PROJECT.md H12 是否需明确"2 = import-time 配置失败"语义 |
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

---

## 9. 方案 A → 方案 B 切换（追加于 R4-R8）

### 9.1 决策背景

R1-R3 已落地方案 A（保留 `if result is None` 死分支作为防御性守卫，注释说明
"上游契约破坏 → error 级别便于排查"）。**但用户在 R3 收口后明确表态**：
> "PROJECT.md H13 死代码禁止，需彻底删除死代码"

因此放弃方案 A，改方案 B（彻底删除 `if result is None` 死代码块），并将
"退出码 0/1/2" 与"删除死代码"上升为项目级硬规则。

### 9.2 方案 B 标准模板

以 `factor_ic/ic_industry_amplitude_trend_1d.py` v1.0o 为基准（已实测、ruff/pytest 通过）：

| 位置 | 改动 |
|---|---|
| import 区 | **新增** `DataSchemaError`（与 `FactorCalcError` 一起 from `factor_ic.common.exceptions`） |
| `main()` 内 `if result is None` 块 | **整块删除**（含 logger.error + sys.exit(1)） |
| `log_factor_summary` 调用前注释 | 改为透明性审阅说明：`run_factor_ic` 失败走 build_error_result 或抛 DataSchemaError，永不返回 None；冗余守卫掩盖真实错误来源；log_factor_summary 自身契约不抛异常 / 不 sys.exit |
| `__main__` 块 | 保留 `except FactorCalcError`，**新增** `except DataSchemaError as e`（在 FactorCalcError 之前），保留 `except Exception` 兜底；总计 3 段 except，附 5-7 行注释说明分支顺序依据（exceptions.py L27/46/60 平级关系） |

### 9.3 关键纠偏（重要）

❌ 错误理解：方案 B = 删除 `from factor_ic.common.exceptions import FactorCalcError` import + 删 `except FactorCalcError`
✅ 正确理解：方案 B = 删 `if result is None` 死分支 + 新增 DataSchemaError 显式 except；FactorCalcError 仍保留

依据：amplitude_trend v1.0o 实测保留 FactorCalcError import 和 except 分支（factor_ic/ic_industry_amplitude_trend_1d.py L30, L146-148）。

### 9.4 拆轮次（R4-R8）

| 轮次 | 范围 | 文件 | 预计行数 |
|---|---|---|---|
| R4 | earnings_growth 切方案 B | `factor_ic/ic_industry_earnings_growth_1d.py` | ~30 行变更 |
| R5 | momentum_5d 切方案 B | `factor_ic/ic_industry_momentum_5d_1d.py` | ~30 行变更 |
| R6 | turnover_trend 切方案 B | `factor_ic/ic_industry_turnover_trend_1d.py` | ~30 行变更 |
| R7 | 规范升级 | `PROJECT.md`（S1→H12）+ `PROJECT.md` H12 退出码语义 | ~15 行变更 |
| R8 | design.md 状态闭环 | 本文档（标记方案 B 完成 + 追加结果） | ~10 行变更 |

每轮独立 commit，每轮显式路径，每轮 ruff + pytest。

### 9.5 R7 规范升级方案

**PROJECT.md**：S1（L262）从软约束升级为 H12 硬规则，插入到 L163（H11 之后）；
同时新增 H13 死代码硬规则（紧随 H12）。

**新 H12（退出码语义）**：
- 规则：`退出码语义：0=成功 / 1=运行时错误 / 2=import-time 配置或注册失败`
- 目的：CI / shell 脚本能区分"代码不能加载"（exit 2）vs"运行时失败"（exit 1）
- 自动化检查：`scripts/check_exit_codes.py`（待交付，标 [待实施]）
- 删除 L262 旧 S1 行

**新 H13（死代码禁止）**：
- 规则：`禁止永不触发的防御性兜底分支（如 if result is None 兜底面对永不返回 None 的函数）`
- 目的：死代码掩盖真实错误来源、误导维护者、增加噪音；必须删除
- 验证方法：人工 review + `grep -rn "if result is None" factor_ic/ic_*.py` 应为零命中（非 amplitude_trend / 三脚本以外）
- 自动化检查：`scripts/check_dead_branches.py`（待交付，标 [待实施]）
- 历史教训：本次 R1-R3 误以为方案 A（保留死分支作为防御性守卫）合规，
  R4-R6 才修正为方案 B（彻底删除）。规则化后避免再次走偏。

**PROJECT.md** H12：从 `0/1` 扩展为 `0/1/2/3/4/5`（语义细化）；
新增规则 #14（对应 PROJECT.md H13 死代码禁止）。

### 9.6 退出码 2 的语义边界（明确约定）

- exit 0 = 成功完成
- exit 1 = `main()` 运行时错误（DataSchemaError / FactorCalcError / 未预期 Exception / `assert` 失败 / 数据缺失）
- exit 2 = 模块 import-time 配置或注册失败（`register_factor` 重复、required_columns 非法、配置文件缺失等）

**为什么需要区分 1 与 2**：CI / pipeline 脚本可据此判断是"代码本身有 bug 不能加载"（exit 2，立即告警停止流水线）还是"数据/逻辑层面执行失败"（exit 1，可重试 / 排查数据）。

### 9.7 H13 死代码规则的判定边界（避免过度删除）

- ✅ 应删：callee 实现明确"永不返回 None"（dict 失败 + raise 双路径）+ caller 仍写 `if result is None` 守卫
- ✅ 应删：`if False:` / `assert False` 之后的代码 / 不可达的 `else` 分支
- ❌ 不应删：callee 文档不明确返回值是否可能为 None / callee 是 third-party 库（契约可能变化）
- ❌ 不应删：业务上可能进入但当前测试未覆盖的分支（这是测试覆盖问题，不是死代码）
- 判定方法：必须能给出 callee 的具体行号证据（如 factor_ic_runner.py L442 返回 dict / L461 raise），否则按"不应删"处理

---

## 10. R4-R7b 落地结果（2026-06-16 闭环）

### 10.1 commit 链

| 轮次 | commit | 范围 | 行数 |
|---|---|---|---|
| R4 | `3320601` | earnings_growth 切方案 B + design.md §9 落地 | 82+/12- |
| R5 | `ee3baee` | momentum_5d 切方案 B | 21+/12- |
| R6 | `0075237` | turnover_trend 切方案 B | 21+/12- |
| R7a | `68474b0` | S1→H12 退出码硬规则 + design.md §9.5/§9.6 | 27+/6- |
| R7b | `b26a51b` | 新增 H13 死代码禁止硬规则 | 2+/0- |

### 10.2 验证结果

- ruff check / format：3 个目标文件 + 2 个规范文件全部通过
- pytest：earnings_growth 6 passed/5 skipped；spec_consistency 2 passed；factor_spec 12 passed
- SPEC 注册：3 个文件 import 验证通过（`industry_earnings_growth` / `industry_momentum_5d` / `industry_turnover_trend`）
- 隔离性：每个 commit 显式路径，无其他 agent staged 文件被误带入（multi-agent-commit-isolation 遵循）

### 10.3 用户原始 5 项需求的最终落地状态

| 需求 | R1-R3（方案 A，已被 R4-R6 推翻） | R4-R6（方案 B，最终状态） |
|---|---|---|
| #1 result is None 借道异常 | logger.error + sys.exit(1) 保留分支 | **整块删除** |
| #2 main() return result | 已删 | 已删（沿用 R1） |
| #3 冗余"计算完成" logger | 已删 | 已删（沿用 R1） |
| #4 注释边界模糊 | 改为"None 检查由 main 提前退出" | 改为"run_factor_ic 永不返回 None + log_factor_summary 透明性审阅" |
| #5 SPEC 注册 import-time 失败 | try/except → sys.exit(2) | 保留 R3 实现（不属于死代码） |

### 10.4 后续待办闭环（已全部落地）

| 编号 | 待办 | 状态 | Commit |
|------|------|------|--------|
| R7c-1 | 补 H12 正反例段落（PROJECT.md H11 5 段式模板） | ✅ 已落地 | `809a1bd` |
| R7c-2 | 补 H13 正反例段落（含判定边界 6 段式） | ✅ 已落地 | `2fdfcb9` |
| R9 | `scripts/check_exit_codes.py` H12 自动化检查 + 11 pytest | ✅ 已落地 | `d08bdb6` |
| R10 | `scripts/check_dead_branches.py` H13 自动化检查 + 15 pytest + 30 文件 allowlist 渐进迁移 | ✅ 已落地 | `9a5caf6` |
| R11 | 路线图 H11（必测场景）→ H14 编号冲突修复 | ✅ 已落地 | `7f3709d` |

### 10.5 后续可选改进（不在本轮 scope）

- 把 30 个 allowlist 文件按 R4-R6 模板逐个迁移（每文件独立 commit），allowlist 清空后从 PROJECT.md H13 当前覆盖范围移除 ⏳ 标记
- 把 `scripts/check_exit_codes.py` 和 `scripts/check_dead_branches.py` 接入 pre-commit hook 与 CI workflow（当前可手工运行 `python scripts/check_*.py all`）
- PROJECT.md §硬规则速查表 + 项目根 README 补充 H12 / H13 说明

---

## §11 R13-R17：用户第二轮 5 个问题修复 + H12 规范修正（trade-off 决策）

### 11.1 用户原话与 5 个问题

用户在 R12 落地后给出第二轮反馈（针对 `factor_ic/ic_industry_earnings_growth_1d.py`）：

| # | 问题（用户原话精炼） | 位置 | 修复方案 |
|---|----|---|---|
| 1 | 顶层 `sys.exit(2)` 与"importlib 扫描触发注册"路径自相矛盾 | L52-68 顶层 except | logger.critical + raise（R13） |
| 2 | `SPEC: FactorSpec` 仅注解无初值，UnboundLocalError 风险 | L43 类型注解 | 保留无初值 + noqa 注释（R13） |
| 3 | DataSchemaError + FactorCalcError 两个 except 前缀+退出码相同 | `__main__` 块 | 合并 except (DataSchemaError, FactorCalcError)（R14） |
| 4 | main() 末尾缺流程完成标记日志 | main() 末尾 | 补 `logger.info("...计算完成")`（R15） |
| 5 | `str(e)[:200]` 内联截断 + 魔法数 200 无来源 | L65 logger.critical 参数位 | 提取 `err_msg = str(e)[:200]` + 注释（R13） |

### 11.2 核心 trade-off：放弃 import-time exit 2

**冲突点**：用户原话"__main__ 块捕获该异常后再做 sys.exit(2)" 在 Python 模块加载语义上**不可达**——import-time `raise` 会让整个文件加载失败，`if __name__ == "__main__":` 块根本执行不到。

**两个备选**：
- A. 顶层 except → `raise`（执行用户原意中"raise"部分），放弃 exit 2 语义
- B. 顶层 except → `sys.exit(2)`（保留 H12 原规范），承认与"importlib 扫描"自相矛盾

**决策（选 A）**：
1. `factor_ic/common/test_factor_spec_consistency.py:31-33` 通过 `pkgutil.iter_modules` + `importlib.import_module(f"factor_ic.{mod.name}")` 扫描所有 ic_*.py 触发 SPEC 注册
2. `sys.exit(2)` 在 importlib 路径上会**杀掉 pytest 宿主进程**，与"测试通过 importlib 扫描"路径根本矛盾
3. `raise` 让调用方决定行为：测试可捕获 ValueError/TypeError，CLI 由 Python 默认 traceback + exit 1 兜底
4. 代价：放弃 import-time（exit 2）/ runtime（exit 1）的退出码区分；CI 仍可通过 stderr `CRITICAL ... FactorSpec 注册失败` 关键字 + traceback 区分错误来源

### 11.3 R13-R17 落地状态

| 编号 | 内容 | 状态 | Commit |
|------|------|------|--------|
| R13 | earnings_growth 顶层 try/except 改 raise + err_msg 提取 + SPEC noqa 注释（问题 1+2+5） | ✅ 已落地 | `4871460` |
| R14 | earnings_growth `__main__` 合并 except (DataSchemaError, FactorCalcError)（问题 3） | ✅ 已落地 | `d185545` |
| R15 | earnings_growth main() 末尾补"计算完成"流程日志（问题 4，回滚 R1 决策） | ✅ 已落地 | `0e586e0` |
| R16 | PROJECT.md H12 规范修正（exit 2 → raise）+ check_exit_codes.py 升级 + 14 pytest | ✅ 已落地 | `436f4c4` |
| R17 | 三姊妹脚本（momentum_5d / turnover_trend）同步迁移到 raise 模式 | ✅ 已落地 | `bf3e2ee` |

### 11.4 R1 决策回滚说明（问题 4）

R1 阶段曾以"与 log_factor_summary 重叠"为由删除 `logger.info("...计算完成")`，本轮 R15 回滚。

**认知修正**：数据摘要日志 ≠ 流程完成标记日志：
- `log_factor_summary`：描述"算了什么"（数据维度，因子值统计）
- `logger.info("...计算完成")`：描述"走到了哪一步"（控制流维度，main() 末尾边界）

两者职责正交。R15 在该日志上方注释中显式标记"上一轮 R1 曾以'重叠'为由删除"+ 职责区分，**防止未来再次被误删**。

### 11.5 全量验证

- **ruff check**：All checks passed
- **ruff format**：无未格式化文件
- **pytest factor_ic/**：269 passed / 66 skipped
- **pytest scripts/**：14 passed（test_check_exit_codes 11 → 14，新增 raise 模式正反例）
- **scripts/check_exit_codes.py all**：34 文件通过（R17 后所有 ic_industry_*.py 合规）
- **scripts/check_dead_branches.py all**：227 文件通过
- **SPEC import 验证**：earnings_growth / momentum_5d / turnover_trend 三脚本均 OK


