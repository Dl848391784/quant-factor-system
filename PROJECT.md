# PROJECT.md - Factor IC Analyzer

量化因子 IC 分析系统项目级规范。

**命名风格说明**：项目对外名称使用 Title Case（Factor IC Analyzer），文件系统路径使用 snake_case（factor_ic_analyzer/），章节标题使用中文不受此约束。两者风格差异为设计意图。

---

## 本文档与 AGENTS.md 的关系 [reference]

| 文档 | 加载方式 | 内容定位 | 何时读取 |
|------|----------|----------|----------|
| AGENTS.md | agent 启动时由框架自动注入到上下文 | 精华索引、硬规则速查表 | 每次对话自动注入 |
| PROJECT.md | 按需主动读取 | 详细参考、背景说明、完整规范 | 下列触发条件 |

**必须主动读取 PROJECT.md 的触发条件（任一命中即触发）：**

| 触发场景 | 判定标准 |
|---------|---------|
| 新增模块 | 在 `factor_ic_analyzer/` 下新建顶级业务目录（与 factor_ic/ 同级） |
| 新增脚本类型 | 在 `scripts/` 下新建 `check_*.py` 或 `validate_*.py` |
| 修改跨模块数据契约 | 修改 `paths.py`、任一 `schemas/*.schema.json`、或被 2+ 模块读取的产物文件名/字段 |
| 涉及数据契约 / 路径 / 输出结构讨论 | 由 AI 根据语义判定（不依赖字面关键词匹配） |
| 涉及 2+ 文件改动 | 需写 design.md（见 Design-First 流程） |

---

## AI 协作模式 [stable]

**本规范由 AI 智能体执行。本节定义智能体在任务全周期中的行为，避免不同智能体 / 不同会话间行为不一致。**

**harness 中立约定**：本规范不绑定任何特定智能体平台（Claude Code / OpenClaude / Cursor / Cline / 自研框架均可）。本节描述的"加载文件、调用工具、与用户交互"均为通用语义，不依赖具体平台的专属功能（如特定的 hook 系统、内置 skill、自动化记忆等）。若某条流程在特定 harness 下不可直接执行，由智能体在保持等价语义的前提下用平台可用的能力实现。

### 任务启动 checklist（每次新任务必跑）

1. 加载 AGENTS.md / PROJECT.md → 拿到硬规则速查表
2. 判断本任务是否命中"主动读取 PROJECT.md 的触发条件"，命中则读本文件
3. 列出本任务预计触及的 H 规则编号（用于 PR 模板取证）
4. 判断是否触发 Design-First（2+ 文件）→ 若是，先写 design.md 并停下等审核

### 何时必须停下问用户（不要自行决策）

| 场景 | 行为 |
|------|------|
| 任务粒度超 H9 阈值（>3 文件 或 >200 行） | 停下问用户："是否拆分 / 走 Design-First / 申请豁免" |
| 检查脚本不存在或执行失败 | 停下问用户："脚本是否待实施？是否绕过？" |
| 规则之间发生冲突 | 按"规则冲突仲裁"节判断，无法判定则停下问用户 |
| 涉及破坏性操作（删除文件、修改 paths.py、改 schema） | 列出影响范围，等用户确认 |
| 任务描述与现有规范冲突 | 停下问用户："以规范为准还是以本次需求为准" |

### 工具缺失时的兜底

- 若某条 H 规则的检查脚本（如 `scripts/check_*.py`）尚未实现：
  - 不可假装已通过检查
  - 应在 PR 描述中显式标注"H? 检查脚本待实施，本次依赖人工 review"
  - 不可作为取证依据（同 [待实施] 规则）

### 自检流程（提交前）

- 列出本次触及的所有规则编号 → 逐条对照
- 跑一次本地 pre-commit → 若失败，先修复再继续，不可 `--no-verify`
- 在 PR 描述中按"PR 模板必填字段"格式填写规范引用

---

## 目录结构 [reference]

```
factor_ic_analyzer/
├── factor_ic/              # IC 计算模块
├── backtest/               # 分层回测模块
├── comprehensive_factor/   # 综合因子模块
├── data_fetchers/          # 数据获取模块
├── summary/                # 数据汇总模块
├── scripts/                # 自动化检查脚本
├── tests/integration/      # 跨模块集成测试
├── designs/                # design.md 存放目录
├── paths.py                # 跨模块路径单一来源（⚠️ 见下方导入说明）
├── temporary/              # 临时文件目录
├── pyproject.toml          # 项目配置（ruff/pytest/import-linter）
└── PROJECT.md              # 本文件
```

**业务模块统一约定**：每个业务模块（factor_ic / backtest / comprehensive_factor / data_fetchers / summary）必须包含：
- `test_cases/` —— 单元测试
- `schemas/` —— JSON Schema 校验文件
- 产物输出到 `result/`（见 H2）

**⚠️ paths.py 导入路径待确认**：
- 当前 H7 要求 `from paths import`，但 `paths.py` 位于 `factor_ic_analyzer/paths.py`，且 `pyproject.toml` 包名为 `factor_ic_analyzer`。
- `pip install -e .` 之后，顶层 `paths` 模块不在 site-packages 中，正确导入应为 `from factor_ic_analyzer.paths import ...`。
- **请验证**：当前代码库实际能 work 的导入语句是哪一种？确认后更新 H7 与 `scripts/check_path_import.py`。

**安装方式**：`pip install -e .`（需要 pyproject.toml 中的 `[project]` 配置）

**pyproject.toml [project] 最小配置示例**：
```toml
[project]
name = "factor_ic_analyzer"
version = "0.1.0"
dependencies = [
    "pandas>=2.0",
    "numpy>=1.24",
    "pytest>=7.0",
    "pytest-cov>=4.0",
    "ruff>=0.1.0",
    "import-linter>=1.0",
]
```

---

## Design-First 流程 [experimental]

**涉及 2 个以上文件的改动必须先提交 design.md 通过审核才能动手。**

**目的**：避免边写边改、推倒重来。让用户在动笔前对齐方案，减少返工。

```
设计阶段：
□ 在 designs/ 目录创建 design.md（改哪些文件、改哪些接口、加哪些测试）
□ 用户审核通过
□ 才能动手写代码

违反此规则 = 直接退回，不 review。
```

**design.md 文件名映射规则（明确化）**：
- 取 PR 分支名，做以下转换：
  1. 所有 `/` 替换为 `_`
  2. 所有 `-` 替换为 `_`
  3. 转小写
- 示例：
  - `feat/add-cache` → `designs/feat_add_cache.md`
  - `feat/sub/cache-v2` → `designs/feat_sub_cache_v2.md`
  - `Fix-Bug-123` → `designs/fix_bug_123.md`
- PR 描述中显式引用 `designs/<文件名>.md` 也可作为匹配依据（优先级低于分支名映射）

**自动检查**：
- 脚本：`scripts/check_design_first.py`
- 检查逻辑：PR 涉及 2+ 文件改动时，仓库 designs/ 目录下必须存在对应的 design.md 文件
- pre-commit 软提示：pre-commit 无法读取 PR 信息，仅做轻量启发式——若本次提交涉及 2+ 文件且 designs/ 目录在 git 工作区中无任何新增 .md 文件，则 stderr 输出警告（不阻止提交）；最终对应规则匹配在 CI 强制检查
- CI 硬关卡：PR 创建时强制检查（可访问 PR 分支名/描述），缺少匹配的 design.md 则 CI 失败
- CI 调用：`python scripts/check_design_first.py`

---

## 硬规则（违反即拒收）[stable]

**命名空间**：H 前缀 = 硬规则（自动强制执行）

| 规则编号 | 规则 | 目的 | 检查工具 | 执行阶段 |
|---|------|------|----------|----------|
| H1 | 模块边界：只能复用自己目录的 `common/` | 防止模块间隐式耦合；重构单模块时不会牵连其他模块 | import-linter | CI |
| H2 | 输出位置：`<模块>/result/`（详见下方正反例） | 让产物可被清理/打包脚本统一处理，避免散落根目录 | AST 静态分析（`scripts/check_path_literals.py`） | pre-commit + CI |
| H3 | 临时文件：放 `temporary/` | 避免污染版本控制；统一清理入口 | AST 静态分析（`scripts/check_temp_file_path.py`） | pre-commit + CI |
| H5 | 因子方向：根据实际 IC 确定（不可硬编码方向） | 防止方向写反导致回测结论与实际相反 | pytest 断言 | CI |
| H6 | 异常链：`raise ... from e`（详见下方正反例） | 保留错误来源，调试时能追溯根因 | ruff B904 | pre-commit + CI |
| H7 | 路径导入：`from paths import`（⚠️ 见目录结构节导入说明） | 单一来源原则：路径变更只需改一处 | AST 静态分析（`scripts/check_path_import.py`） | pre-commit + CI |
| H8 | Design-First：2+ 文件需 design.md | 大改动先对齐再写，避免推倒重来 | CI `scripts/check_design_first.py` | CI |
| H9 | 任务粒度：≤3 文件 **AND** ≤200 行（两者都需满足，违反任一即超粒度） | 控制单次改动规模，便于 review 和回退；超粒度走 Design-First | pre-commit `scripts/check_task_size.py` | pre-commit |
| H10 | 测试覆盖率：不低于阶段性阈值（当前 60%，目标 70%） | 防止新代码无测试拉低基线 | pytest `--cov-fail-under=60`（当前阶段） | CI |
| H11 | 日志格式：% 惰性格式化（禁止 f-string / + 拼接 / `exc_info=True`） | 性能（高 verbosity 时跳过格式化）+ 风格统一 + 与标准库 logging 结构化处理器（如 JSON）兼容 | ruff G004 / G003 / G201 | pre-commit + CI |
| H12 | 退出码语义：0=成功 / 1=运行时错误 / 2=import-time 配置或注册失败 | CI / shell 脚本能区分"代码不能加载"（exit 2，立即告警停止流水线）vs"运行时失败"（exit 1，可重试 / 排查数据） | 人工 review + `scripts/check_exit_codes.py`（[待实施]） | pre-commit + CI |
| H13 | 死代码禁止：禁止永不触发的防御性兜底分支（如 `if result is None` 守卫面对永不返回 None 的 callee） | 死代码掩盖真实错误来源、误导维护者、增加噪音；必须删除而非保留 | 人工 review + `scripts/check_dead_branches.py`（[待实施]） | pre-commit + CI |

**H2 正反例**：
- ✅ 算输出（必须放 `<模块>/result/`）：分析结果 JSON、回测报告、汇总文件、对外暴露的数据产物
- ❌ 不算输出（不进 `result/`）：
  - 调试日志 → 走 stderr 或 `logger`
  - 中间缓存 → 放 `temporary/`（H3）
  - 测试夹具 → 放对应模块的 `test_cases/`

**H6 正反例**：
```python
# ❌ 反例：丢失根因
try:
    load(path)
except FileNotFoundError:
    raise RuntimeError("加载失败")  # 调试时看不到原始 FileNotFoundError

# ✅ 正例：保留链路
try:
    load(path)
except FileNotFoundError as e:
    raise RuntimeError("加载失败") from e
```

**H11 正反例**：
```python
# ❌ 反例 1：f-string（提前格式化，DEBUG 关闭时仍消耗 CPU）
logger.info(f"加载 {len(rows)} 行数据")
logger.error(f"读取失败 [{path}]: {e}")

# ❌ 反例 2：+ 拼接
logger.info("加载 " + str(len(rows)) + " 行数据")

# ❌ 反例 3：exc_info=True（应用 logger.exception 自动捕获）
logger.error("处理失败", exc_info=True)

# ✅ 正例 1：% 惰性格式化（位置参数，logger 在确认级别启用后才格式化）
logger.info("加载 %s 行数据", len(rows))
logger.error("读取失败 [%s]: %s", path, e)

# ✅ 正例 2：浮点数格式说明符
logger.info("IC 均值: %.4f, ICIR: %.2f", ic_mean, icir)

# ✅ 正例 3：异常自动捕获
try:
    process()
except Exception:
    logger.exception("处理失败")  # 自动附 traceback，等价于 error + exc_info=True

# ⚠️ 字面量 % 需转义为 %%
logger.info("Bollinger %%B 因子计算完成")
```

**H11 Why**：
- **性能**：`logger.debug(f"... {expensive_call()} ...")` 即使 DEBUG 级别关闭也会执行 `expensive_call()`；惰性格式化由 logger 内部判断级别后才格式化，跳过被禁用的级别开销
- **结构化日志**：标准库 logging 把 `msg` 和 `args` 分别保留在 `LogRecord` 上，下游 JSON Handler / 日志聚合系统可基于模板 + 参数做模板分组、参数提取；f-string 让模板和参数永久合并，丢失结构化能力
- **风格统一**：项目已统一为 % 风格（factor_ic/ 39 文件 219 处全清），新代码必须保持一致

**H11 Verify**：
```bash
ruff check --select G factor_ic/
# 期望：All checks passed!
```

**H11 当前覆盖范围**：
- ✅ 已强制：`factor_ic/`（含 31 个 ic_*.py + 8 个 common/*.py）
- ⏳ 迁移中（per-file-ignores 暂放行）：`backtest/`、`comprehensive_factor/`、`data_fetchers/`、`summary/`、`temporary/`、`run_pipeline.py`、`factor_definitions.py`
- 迁移路径：每模块完成后从 `pyproject.toml [tool.ruff.lint.per-file-ignores]` 中移除该模块的放行项

**硬规则补充注释**：
- H1：`factor_ic` 只能复用 `factor_ic/common/`，禁止复用 `backtest/common/` 等
- H7：路径常量清单详见"附录：路径常量清单"
- H8：详见"Design-First 流程"章节
- H9：超粒度时不可强拆为多次 commit 绕过，必须走 Design-First 走审核
- H10：阶段计划与设定依据见"测试覆盖规范"章节
- H11：当前仅 `factor_ic/` 强制；其他模块在 `pyproject.toml [tool.ruff.lint.per-file-ignores]` 中暂放行，迁移完成后逐步移除

**H12 正反例**：
```python
# ❌ 反例 1：所有失败统一 exit 1（无法区分代码 bug vs 运行时错误）
if __name__ == "__main__":
    try:
        SPEC = register_factor(...)  # import-time 注册失败也是 exit 1
        main()                        # 运行时数据缺失也是 exit 1
    except Exception:
        sys.exit(1)

# ❌ 反例 2：用 exit 0 表示"虽然失败但不影响"（CI 无法感知）
if not data_available:
    logger.warning("数据缺失，跳过")
    sys.exit(0)

# ❌ 反例 3（R16 修正）：模块顶层 except 直接 sys.exit(2)
# 该写法被 importlib.import_module 调用时会杀掉宿主进程（如 pytest 扫描注册）
try:
    SPEC = register_factor(...)
except (ValueError, TypeError):
    sys.exit(2)  # 杀掉 pytest 进程！

# ✅ 正例 1：import-time 配置/注册失败 → logger.critical + raise
# （让调用方决定行为：测试可捕获/skip，CLI 由 Python 默认 traceback+exit 1）
try:
    SPEC: FactorSpec = register_factor(
        factor_name="industry_xxx",
        factor_col="industry_xxx",
        required_columns=["date", "stock_code", "industry"],
        calc_func=calculate_industry_xxx,
    )
except (ValueError, TypeError) as e:
    err_msg = str(e)[:200]  # 截断防止超长异常淹没单行日志
    logger.critical("FactorSpec 注册失败: %s (%s)", err_msg, type(e).__name__)
    raise

# ✅ 正例 2：main() 运行时错误 → exit 1
if __name__ == "__main__":
    try:
        main()
    except (DataSchemaError, FactorCalcError) as e:
        logger.error("...IC 计算失败: %s (%s)", e, type(e).__name__)
        sys.exit(1)
    except Exception:
        logger.exception("未预期的错误")
        sys.exit(1)
```

**H12 Why**：
- **CI / pipeline 区分能力**：exit 1 = 数据/逻辑层面失败（可重试、可降级）；exit 0 = 成功
- **可观测性**：`run_pipeline.py` 等编排脚本可据 stderr+退出码决定后续动作
- **测试可隔离性（R16 修正）**：模块顶层 sys.exit 会被 importlib.import_module
  传染杀宿主进程；`factor_ic/common/test_factor_spec_consistency.py` 通过 importlib
  扫描所有 ic_*.py 触发 SPEC 注册，import-time exit 路径与该测试设计不兼容。
  改为 logger.critical + raise 后，测试框架可捕获 ValueError/TypeError 并合规断言/skip
- **trade-off**：放弃 import-time exit 2 / runtime exit 1 的退出码区分，
  换取 import-time 注册失败的可隔离性（CI 仍可通过 stderr 中的
  `CRITICAL ... FactorSpec 注册失败` 关键字 + traceback 区分错误来源）

**H12 Verify**：
```bash
# 检查 sys.exit 调用点是否符合语义
grep -rn "sys.exit(" factor_ic/ic_*.py
# 期望：
# - 模块顶层 try/except register_factor → logger.critical + raise（不应有 sys.exit）
# - __main__ 块 except → sys.exit(1)
# - main() 内部业务失败 → sys.exit(1)

# 自动化检查：
python scripts/check_exit_codes.py all
```

**H12 当前覆盖范围**：
- ✅ 已落地：`factor_ic/ic_industry_amplitude_trend_1d.py` / `ic_industry_earnings_growth_1d.py` / `ic_industry_momentum_5d_1d.py` / `ic_industry_turnover_trend_1d.py`
- ⏳ 待迁移：其他 `factor_ic/ic_*.py` 文件、`backtest/`、`comprehensive_factor/`、`data_fetchers/`、`summary/`
- 自动化：`scripts/check_exit_codes.py` ✅ 已交付（AST 分析，pre-commit + CI 模式，11 个 pytest 全过；R16 升级支持模块顶层"无 sys.exit + 必须 raise"模式校验）

**H13 正反例**：
```python
# ❌ 反例 1：callee 永不返回 None，caller 仍写守卫
result = run_factor_ic(...)  # 实现：失败走 build_error_result(返回 dict) 或 raise DataSchemaError
if result is None:            # 死分支，永不触发
    logger.error("run_factor_ic 返回 None")
    sys.exit(1)

# ❌ 反例 2：assert False 之后的代码
def parse(x):
    assert x > 0
    if x < 0:                 # 不可达
        return None
    return x

# ❌ 反例 3：if False 包裹的"备用方案"
if False:                     # 死代码
    use_legacy_path()
else:
    use_new_path()

# ✅ 正例 1：删除死守卫，让真实错误自然抛出
result = run_factor_ic(...)
log_factor_summary(result, "因子名", logger)  # 失败由上游 raise 触发，由 __main__ except 捕获

# ✅ 正例 2：callee 文档明确可能返回 None → 必须守卫（不是死代码）
config = load_config(path)    # 文档：找不到时返回 None
if config is None:
    logger.error("配置文件不存在: %s", path)
    sys.exit(1)

# ✅ 正例 3：第三方库返回值不确定 → 必须守卫（不是死代码）
response = requests.get(url)
if response.status_code != 200:
    raise RuntimeError(f"HTTP {response.status_code}")
```

**H13 Why**：
- **错误来源可追溯**：死代码兜底会用 generic 错误消息掩盖 callee 真实抛出的 DataSchemaError / FactorCalcError 上下文
- **维护者认知负担**：保留死分支让维护者误以为"该路径可能触发，需要思考"，实际是干扰
- **测试覆盖率假象**：死分支永远不会被测试触发，但工具不会标红，造成"覆盖率高但实际未测"假象
- **历史教训**：本次 R1-R3 把 `if result is None` 当"防御性守卫"保留，被用户纠正"应该彻底删除死代码"；R4-R6 修正

**H13 判定边界**（避免过度删除）：
- ✅ 应删：callee 实现明确"永不返回 None"（dict 失败 + raise 双路径）+ caller 仍写 `if result is None` 守卫
- ✅ 应删：`if False:` / `assert False` 之后的代码 / 不可达的 `else` 分支
- ❌ 不应删：callee 文档明确"可能返回 None"
- ❌ 不应删：callee 是 third-party 库（契约可能变化）
- ❌ 不应删：业务上可能进入但当前测试未覆盖（这是测试覆盖问题，不是死代码）
- 判定方法：必须能给出 callee 的具体行号证据（如 `factor_ic_runner.py:442` 返回 dict / `:461` raise），否则按"不应删"处理

**H13 Verify**：
```bash
# 检查 factor_ic/ic_*.py 是否仍有 None 死守卫
grep -rn "if result is None" factor_ic/ic_*.py
# 期望：零命中

# 检查不可达分支
grep -rn "assert False\|if False:" factor_ic/ comprehensive_factor/ backtest/
# 期望：零命中（除测试用例中的负向测试）
```

**H13 当前覆盖范围**：
- ✅ 已落地：4 个行业 IC 脚本（earnings_growth / momentum_5d / turnover_trend / amplitude_trend）`if result is None` 已删
- ⏳ 待审计：30 个 `factor_ic/ic_*.py` 文件已纳入 `scripts/check_dead_branches.py` allowlist 短路豁免，逐个迁移后从 allowlist 删除
- 自动化：`scripts/check_dead_branches.py` ✅ 已交付（AST + allowlist 渐进迁移，pre-commit + CI 模式，15 个 pytest 全过）

---

## 规则冲突仲裁 [stable]

**当多条规则同时触发且要求冲突时，按以下优先级判定：**

| 冲突场景 | 仲裁规则 |
|---------|---------|
| H 之间冲突 | 编号小的优先（H1 > H2 > ... > H10） |
| H vs S 冲突 | H 优先（硬规则必胜） |
| H9（粒度）vs H8（Design-First） | H8 优先：超粒度任务必须先走 Design-First，写好 design.md 通过审核后，可分批提交（每批仍受 H9 约束） |
| Hotfix 紧急通道 vs 任何 H 规则 | 无紧急通道；hotfix 也走完整流程。若用户明确声明"紧急豁免某条规则"，AI 须在 PR 描述中显著标注豁免项并 @维护者 |
| 规范未覆盖的场景 | AI 停下问用户，不自行决策 |

---

## 建议（软约束）[experimental]

**命名空间**：S 前缀 = 建议（软约束，依赖人工执行）

| 规则编号 | 建议 | 目的 | 当前状态 | 自动化计划 |
|---|------|------|----------|------------|
| S2 | 配套文件同步创建（新增 schema 时同步 test、新增 path 时同步 PROJECT.md） | 防止配套漂移 | 人工审核 | 待 PR 模板 + CI |
| S3 | 日志格式统一 | 便于日志聚合与 grep | 手动检查 | 待自定义 logger_config 模块 + AST 检查脚本 |

---

## 因子开发规范 [stable]

新增因子时必须修改的位置（按顺序执行）：

| 序号 | 文件 | 位置 | 作用 |
|------|------|------|------|
| 1 | `data_fetchers/factor_generator.py` | `_EXTENDED_FACTOR_COLS` | 数据源因子列定义 |
| 2 | `data_fetchers/factor_generator.py` | 因子计算函数 | 计算逻辑，结果存入 `factor_ic_data.json.gz`（统一数据源） |
| 3 | `comprehensive_factor/common/factor_selector.py` | `FACTOR_NAME_TO_COL_MAP` | 因子名→列名映射（筛选层） |
| 4 | `comprehensive_factor/common/weight_engine.py` | `FACTOR_NAME_TO_COL_MAP` | 因子名→列名映射（权重层） |
| 5 | `factor_definitions.py`（项目根目录） | `FACTOR_DEFINITIONS` | 因子定义（名称、公式、含义），汇总报告因子说明显示 |
| 6 | `PROJECT.md` | 因子列表章节（本表） | 项目级因子清单 |

**因子分类一览**（按领域维度）：

| 分类 | 因子名 | 列名 | 公式/含义 | IC方向 |
|------|--------|------|----------|--------|
| 基础因子 | rsi | rsi_6 | RSI(6日) | 负向(反转) |
| 基础因子 | volume_ratio | volume_ratio_5 | 量比(5日) | — |
| 扩展因子 | kdj_j | kdj_j | KDJ J值 | — |
| 扩展因子 | bollinger_pb | bollinger_pb | 布林带%B | 负向(反转) |
| 扩展因子 | turnover_surge | turnover_surge | 换手率突增 | 负向(反转) |
| 扩展因子 | amplitude | amplitude | 振幅 | 负向(反转) |
| 尾盘因子 | tail_price_position | tail_price_position | 尾盘价格位置 | — |
| 尾盘因子 | tail_price_slope | tail_price_slope | 尾盘趋势斜率 | — |
| 动量因子 | momentum_strength | momentum_strength | 动量强度 | — |
| 方向性因子 | volume_price_strength | volume_price_strength | 量价齐升强度 | 待定 |
| 方向性因子 | positive_day_ratio_5 | positive_day_ratio_5 | 近5日阳线比例 | 待定 |
| 方向性因子 | ma5_deviation | ma5_deviation | 5日均线偏离度 | 待定 |
| 方向性因子 | near_high_ratio_5 | near_high_ratio_5 | 近5日高低位置 | 待定 |
| **行业方向性因子** | **industry_momentum_5d** | **industry_momentum_5d** | **行业5日动量：按(行业,日期)分组→mean(past_return_1d)→5日滚动均值，实测IC=+0.026** | **正向(行业趋势)** |
| **行业方向性因子** | **industry_turnover_trend** | **industry_turnover_trend** | **行业换手率趋势：turnover_avg(t)/turnover_avg(t-1)-1，clip(lower=0.001)** | **待定** |
| **行业方向性因子** | **industry_amplitude_trend** | **industry_amplitude_trend** | **行业振幅趋势：amplitude_avg(t)/amplitude_avg(t-1)-1，clip(lower=0.001)** | **待定** |

**行业方向性因子说明**（v1.42 2026-06-12 新增）：
- **What**：行业层面趋势维度补充因子，衡量行业整体动量/换手率变化/振幅变化
- **Why**：个股因子只能捕捉截面差异，行业因子捕捉板块轮动信号（如行业整体上涨→行业配置偏向）
- **How**：按(行业,日期)分组聚合→行业均值→比率型/滚动型因子→同行业个股赋相同值
- **Don't**：不可假设行业因子IC方向——实测 industry_momentum_5d IC=+0.026（正向），但 turnover/amplitude_trend 方向待定（遵循 H5）
- **When**：综合因子组合需要行业维度补充时使用
- **Verify**：IC脚本实测IC值、回测分层单调性

**关键依赖**: 新增因子后必须重新运行 `factor_generator.py` 更新 `factor_ic_data.json.gz`，否则后续脚本无法读取新因子值。

---

## 路线图：待实施 / 预留规则 [reference]

**以下规则当前不在硬规则表中强制执行，不可作为 PR 取证依据。** 待对应工具交付或规则升级后，按 checklist 迁入 H 表。

| 编号 | 规则 | 状态 | 升级条件 |
|------|------|------|---------|
| H4 | 字段非空：None 必须显式设置 + 记录原因 | [预留]（规则定义见 S4） | 校验函数 `validate_and_save_output` 交付后，执行下方"S4 → H4 升级 checklist" |
| H14 | 必测场景：每个场景至少一个可运行的测试函数（pytest --collect-only 可发现） | [待实施]（规则定义已生效，工具未交付） | `scripts/check_required_test_scenarios.py` 交付后启用 CI 强制 |
| S4 | 字段非空：None 必须显式设置 + 记录原因（运行时校验） | [部分生效]：依赖人工 review；待 `validate_and_save_output` 交付后升级为 H4 | 见下方 checklist |

**S4 → H4 升级 checklist（升级时必须同步修改的位置）**：
- [ ] 路线图表移除 H4 / S4 行
- [ ] 硬规则表 H 表新增 H4 行（完整规则文字、目的、检查工具、执行阶段）
- [ ] 若 H4 需补充背景，新增"H4 注释"条目
- [ ] 输出结构校验章节"字段非空校验进度"：`详见路线图 S4` → `详见硬规则 H4`
- [ ] AGENTS.md 速查表同步更新
- [ ] PR 校验脚本 `scripts/validate_pr_reference.py`：将 H4 从"不可引用"列表移到"可引用"列表
- [ ] 校验失败示例：删除 H4 预留示例
- [ ] 在版本历史中记录升级时间与升级 PR

---

## 附录：路径常量清单 [reference]

| 路径常量 | 用途 | "未导入"检查（AST） | "硬编码字面量"检查（AST） |
|---------|------|---------------------|--------------------------|
| FACTOR_IC_DATA | 统一数据源 | scripts/check_path_import.py | scripts/check_path_literals.py |
| DATA_FETCHERS_RESULT | data_fetchers 输出目录 | scripts/check_path_import.py | scripts/check_path_literals.py |
| FACTOR_IC_RESULT | IC 输出目录 | scripts/check_path_import.py | scripts/check_path_literals.py |
| BACKTEST_RESULT | 回测输出目录 | scripts/check_path_import.py | scripts/check_path_literals.py |
| COMPREHENSIVE_FACTOR_RESULT | 综合因子输出目录 | scripts/check_path_import.py | scripts/check_path_literals.py |
| SUMMARY_RESULT | 汇总报告输出目录 | scripts/check_path_import.py | scripts/check_path_literals.py |

---

## 测试位置规范 [experimental]

| 测试类型 | 目录位置 | 用途 | pytest 发现 |
|---------|----------|------|-------------|
| 单元测试 | `<模块>/test_cases/` | 测试单个函数/类 | pytest `<模块>/test_cases/` |
| 集成测试 | `tests/integration/` | 测试跨模块交互 | pytest `tests/integration/` |

**历史教训防御表**（按防御机制分类，避免"测试 / CI 脚本 / 运行时校验"三种东西混杂）：

| 教训 | 防御类型 | 实施位置 | 防御内容 |
|------|---------|---------|---------|
| 路径迁移未同步 | pytest 集成测试 | `tests/integration/test_path_migration.py::test_no_legacy_path_in_loader` | 防止数据迁移后 loader 仍从旧路径读取（关联 H7） |
| 收益数据获取错误 | pytest 集成测试 | `tests/integration/test_return_data_source.py::test_return_data_from_factor_ic_data` | 防止下游从废弃 `return_data.json.gz` 读收益（关联 H7） |
| 字段冗余设计 | CI 脚本扫码 | `scripts/check_deprecated_config.py` | 扫描代码中 `additional_factor_files` 等已废弃配置项，命中即报错 |
| 变更同步遗漏 | CI git diff 校验 | `scripts/check_paths_md_sync.py` | git diff 若改动 `paths.py` 则要求同次 commit 含 PROJECT.md 改动 |
| 向后兼容假设 | 运行时 schema 强制 | 数据加载层 | 强制 schema 校验列存在，缺列直接抛错而非取默认值 |
| 文档层级写错 | CI 脚本扫码 | `scripts/check_doc_layer.py` | 扫描 PROJECT.md 是否出现单模块强制句式（如"factor_ic 必须 ..."、"backtest 不可 ..."），命中即报错；通用引用（目录结构表、路径表）不报错 |

---

## 测试覆盖规范 [experimental]

**两个独立要求，必须同时满足：**

### 1. 覆盖率阈值

- 当前阶段：`--cov-fail-under=60`（CI 硬强制，低于即失败）
- 目标：70%
- **目的**：先用 60% 锁定下限，防止覆盖率下降；待团队补测试自然提升至 70% 后升级阈值
- **设定依据**：基于当前代码库现状测算（基线 60%）
- **阶段计划**：基线 60% → 团队补测试至 ≥70% → 升级 H10 阈值至 70% → 同步修改 `pyproject.toml` 中 `addopts = --cov-fail-under=70`

### 2. 必测场景清单

- **单一来源**：`tests/required_scenarios.yaml`（PROJECT.md 不复制清单，避免双源漂移）
- CI 检查：`scripts/check_required_test_scenarios.py`
- 检查逻辑：扫描 `*/test_cases/test_*.py` 与 `tests/integration/test_*.py`，每个必测场景在全仓库至少有一个匹配函数（pytest --collect-only 可发现）
- **场景类别**（具体函数名见 yaml）：输入边界、输出 schema、异常路径

---

## 输出结构校验 [experimental]

**各模块输出必须通过 JSON Schema 校验。**

| 模块 | 输出文件 | Schema 文件路径 | Schema 约束说明 |
|------|---------|----------------|----------------|
| factor_ic | `ic_<因子>_<周期>_analysis_result.json` | `factor_ic/schemas/ic_analysis_result.schema.json` | 同 schema 多文件，schema 内必须包含 `factor_name` 和 `period` 字段约束 |
| backtest | `<因子>_layered_backtest.json` | `backtest/schemas/layered_backtest_result.schema.json` | 同 schema 多文件，schema 内必须包含 `factor_name` 字段约束 |
| comprehensive_factor | `composite_<加权>_1d.json` | `comprehensive_factor/schemas/composite_factor.schema.json` | 同 schema 多文件，schema 内必须包含 `weighting_method` 字段约束 |
| data_fetchers | `factor_data.json.gz` | `data_fetchers/schemas/factor_data.schema.json` | 单文件单 schema |
| data_fetchers | `turnover_rate_data.json.gz` | `data_fetchers/schemas/turnover_rate_data.schema.json` | 单文件单 schema |
| data_fetchers | `factor_ic_data.json.gz` | `data_fetchers/schemas/factor_ic_data.schema.json` | 单文件单 schema（统一数据源） |
| summary | `factor_summary_report_YYYY-MM-DD.txt` | `summary/schemas/summary_report.schema.json` | 单文件单 schema |

**校验工具与调用入口**：
- 工具：`jsonschema` Python 包
- 脚本：`scripts/validate_output_schemas.py`
- 脚本作用范围：（1）校验所有 `*.schema.json` 文件本身符合 JSON Schema meta-schema（CI 可独立运行，无依赖）；（2）若 result/ 目录有产物，则用对应 schema 校验产物（pytest 跑出的测试输出 + 任何 CI 步骤生成的输出）；（3）生产环境的输出由 `validate_and_save_output` 函数在保存时实时校验（详见路线图 S4）
- CI 调用：`python scripts/validate_output_schemas.py`

**字段非空校验进度**：详见路线图 S4。

---

## 版本历史 [reference]

|| 版本 | 日期 | 更新内容 | 稳定性标注 ||
||------|------|---------|-----------||
||| v1.42 | 2026-06-12 | 新增行业方向性因子（industry_momentum_5d / industry_turnover_trend / industry_amplitude_trend）；因子分类一览表；行业方向性因子说明（What/Why/How/Don't/When/Verify） | [experimental] ||
||| v3.4 | 2026-06-04 | 扩展"Run Pipeline 执行排查流程"步骤 3：检查所有时间序列数据文件日期新鲜度（factor_ic_data + turnover_rate + tail_trading），明确不需要检查的文件类型 | [stable] ||
|| v3.3 | 2026-06-04 | 补充"Run Pipeline 执行排查流程"中 data_fetchers 数据日期新鲜度检查（步骤 3），关联 Pitfall 162 | [stable] ||
|| v3.2 | 2026-06-04 | 新增"Run Pipeline 执行排查流程"章节：执行顺序与日志位置表、排查步骤（标准化流程）、常见异常快速定位表 | [stable] |
|| v3.1 | 2026-06-03 | 加 AI 协作模式（harness 中立）/ 规则冲突仲裁 / 路线图节；H 规则加目的行；歧义修正（H9 AND 语义、design.md 文件名映射、新增模块定义）；删除 PROJECT.md 中复制 yaml 的必测场景表；教训防御表按机制分类；flag paths.py 导入路径疑问 | [experimental] |
|| v3.0 | 2026-06-01 | 大重构 | [experimental] |
|| v2.x | 2026-05-xx | 旧版本（已重构） | [deprecated] |

**稳定性定义与升级流程：**

| 稳定性标签 | 适用范围 | 定义 | 参与升级流程 | 责任人 |
|-----------|---------|------|-------------|--------|
| `[stable]` | 规则类 | 经过 2-4 周实战验证，规则可靠 | 否（终态；可被回退为 experimental，详见下方"回退机制"） | 项目维护者 |
| `[experimental]` | 规则类 | 新增内容，待验证（按章节分别评估） | 是（默认初始状态，由维护者评估后可升级 stable） | 项目维护者 |
| `[deprecated]` | 规则类 | 已废弃 | 否（终态；进入条件：发现严重缺陷或被新规则替代） | 项目维护者 |
| `[reference]` | 附录/资料类 | 参考文档，作为单一来源 | 否（默认稳定，不参与升级流程） | — |

**升级评估流程**：
- 评估时点：每两周一次（每月 1 日、16 日）
- 评估流程：项目维护者审查 git log / issue / PR，确认无相关 bug 报告
- experimental → stable 判定标准：连续 2 周无相关 bug 报告 + 至少 1 次实际 PR 应用，或在合成测试场景中触发并通过
- 升级操作：维护者在 PROJECT.md 更新章节稳定性标签，并记录升级理由
- 回退机制：若升级后发现 bug，立即回退为 `[experimental]` 并记录原因

---

## 提交前模板 [experimental]

**强制执行：`.pre-commit-config.yaml` + `.github/workflows/ci.yml`**

```
pre-commit 流程：lint → 任务粒度检查 → 路径检查 → git commit
CI 流程：test → schema → import-linter → design-first → 必测场景 → AST 兜底
```

pre-commit hooks（具体实现）：
1. `ruff check --fix`（配置：`pyproject.toml` → `[tool.ruff]`）
2. `ruff format`（配置：`pyproject.toml` → `[tool.ruff.format]`）
3. 任务粒度检查（脚本：`scripts/check_task_size.py`，阈值：MAX_FILES=3, MAX_LINES=200，**两者 AND**）
4. 路径字面量检查（脚本：`scripts/check_path_literals.py`，AST 静态分析）
5. 路径导入检查（脚本：`scripts/check_path_import.py`，AST 静态分析）
6. 临时文件路径检查（脚本：`scripts/check_temp_file_path.py`，AST 静态分析）

**性能预算**：pre-commit 总耗时上限 < 3 秒（基准假设：< 500 个 .py 文件 + 4 核 CPU 环境）。超出基准规模或 AST 检查超时时，由维护者从 `.pre-commit-config.yaml` 中移除耗时 hook（pre-commit 工具本身无自动降级），CI 任务列表中已配置同名 AST 检查作为兜底（见下方 CI 任务 6）。

CI 任务（具体实现）：
1. `pytest`（覆盖率阈值由 `pyproject.toml` → `[tool.pytest.ini_options]` → `addopts = --cov-fail-under=60` 指定，当前阶段值，详见 H10 阶段计划）
2. JSON Schema 校验（脚本：`scripts/validate_output_schemas.py`）
3. `import-linter`（配置：`pyproject.toml` → `[tool.importlinter]`）
4. Design-First 检查（脚本：`scripts/check_design_first.py`）
5. 必测场景检查（脚本：`scripts/check_required_test_scenarios.py`）
6. AST 检查兜底（脚本：`scripts/check_path_literals.py`、`scripts/check_path_import.py`、`scripts/check_temp_file_path.py`）——双重防御，覆盖开发者用 `--no-verify` 跳过 pre-commit 或 pre-commit 因性能预算超时降级的场景

---

## PR 模板必填字段 [experimental]

**取证机制**：PR 模板强制填写，CI 校验引用规范存在。

```markdown
## 规范引用
- 本次改动涉及的规则编号：H2, H7, H9（硬规则）和/或 S1（建议）
- 验证方式：pytest / ruff / pre-commit 脚本
```

（以上为示例，H2=输出位置、H7=路径导入、H9=任务粒度为典型组合）

**可引用的规则编号**：以"硬规则（违反即拒收）"表和"建议（软约束）"表为唯一来源。"路线图：待实施 / 预留规则"表中的 H4、H14、S4 不可作为取证依据。

CI 脚本校验（`scripts/validate_pr_reference.py`）：
1. 规则编号格式正确：H1、H2、H3、H5、H6、H7、H8、H9、H10、H11、H12、H13、S1、S2、S3
2. 编号在硬规则表或建议表中真实存在
3. 路线图中的规则（当前 H4、H14、S4）不可作为取证依据

**校验失败示例**：
- 若 PR 描述写"引用 H14"，validate_pr_reference.py 抛错：`错误：H14 当前为待实施状态（见路线图），不可作为取证依据。`
- 若 PR 描述写"引用 H4"，validate_pr_reference.py 抛错：`错误：H4 为预留规则（见路线图，规则定义见 S4），不可作为取证依据。`

---

## Run Pipeline 执行排查流程 [stable]

**当用户询问 Run_pipeline 脚本执行情况时，按以下步骤排查：**

### 执行顺序与日志位置

Run_pipeline 按 8 个阶段顺序执行，每个阶段对应独立的日志目录：

|| 阶段 | 阶段名称 | 脚本数 | 日志目录 | 日志文件命名模式 |
||------|---------|--------|----------|-----------------|
|| Stage 0 | 基础数据拉取 | 5 | `logs/` + `data_fetchers/logs/` | `fetch_*_2026-MM-DD.log` |
|| Stage 1 | 数据整合 | 1 | `data_fetchers/logs/` | `factor_generator_2026-MM-DD.log` |
|| Stage 2 | IC计算 | 14 | `factor_ic/logs/` | `ic_*_2026-MM-DD.log`, `__main___2026-MM-DD.log` |
|| Stage 3 | 分层回测 | 14 | `backtest/logs/` | `*_2026-MM-DD.log` |
|| Stage 4 | 综合因子 | 4 | `comprehensive_factor/logs/` | `composite_*_2026-MM-DD.log` |
|| Stage 5 | 权重选择 | 1 | `comprehensive_factor/logs/` | `weight_selector_2026-MM-DD.log` |
|| Stage 6 | 股票选股 | 1 | `comprehensive_factor/logs/` | `stock_selector_2026-MM-DD.log` |
|| Stage 7 | 汇总报告 | 1 | `summary/logs/` | `generate_*_2026-MM-DD.log` |

### 排查步骤（标准化流程）

**步骤 1：确认执行日期**
- 获取当日日期（如 `2026-06-04`）
- 用户问"今天凌晨执行情况"→ 查询当天日志

**步骤 2：按阶段顺序检查日志**

依次检查以下日志目录中当日生成的日志文件：

```bash
# Stage 0: 基础数据拉取（logs/ 目录）
ls -la logs/*_2026-MM-DD.log
ls -la data_fetchers/logs/*_2026-MM-DD.log

# Stage 1: 数据整合
ls -la data_fetchers/logs/factor_generator_2026-MM-DD.log

# Stage 2: IC计算
ls -la factor_ic/logs/*_2026-MM-DD.log

# Stage 3: 分层回测
ls -la backtest/logs/*_2026-MM-DD.log

# Stage 4-6: 综合因子模块
ls -la comprehensive_factor/logs/*_2026-MM-DD.log

# Stage 7: 汇总报告
ls -la summary/logs/*_2026-MM-DD.log
```

**步骤 3：检查 data_fetchers 数据日期新鲜度**

**⚠️ 关键检查点**：必须验证每个 data_fetchers 脚本拉取的数据日期是否到了 T-1（前一日），否则后续模块可能使用过期数据。

检查方法（按脚本输出文件逐一检查）：

```bash
# 检查 factor_ic_data.json.gz 中最新日期（factor_generator.py 输出，依赖多个上游数据）
python -c "
import pandas as pd
import gzip
import json
from datetime import datetime, timedelta

with gzip.open('data_fetchers/result/factor_ic_data.json.gz', 'rt') as f:
    data = json.load(f)
df = pd.DataFrame(data['data'])
latest_date = df['date'].max()
yesterday = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
print(f'factor_ic_data.json.gz:')
print(f'  数据最新日期: {latest_date}')
print(f'  期望日期(T-1): {yesterday}')
print(f'  新鲜度判定: {\"✅ 符合\" if latest_date >= yesterday else \"❌ 过期\"}')
"

# 检查 turnover_rate_data.json.gz 中最新日期（fetch_turnover.py 输出）
python -c "
import pandas as pd
import gzip
import json
from datetime import datetime, timedelta

with gzip.open('data_fetchers/result/turnover_rate_data.json.gz', 'rt') as f:
    data = json.load(f)
df = pd.DataFrame(data['data'])
latest_date = df['date'].max()
yesterday = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
print(f'turnover_rate_data.json.gz:')
print(f'  数据最新日期: {latest_date}')
print(f'  期望日期(T-1): {yesterday}')
print(f'  新鲜度判定: {\"✅ 符合\" if latest_date >= yesterday else \"❌ 过期\"}')
"

# 检查 tail_trading_data.json.gz 中最新日期（fetch_tail_trading.py 输出）
python -c "
import pandas as pd
import gzip
import json
from datetime import datetime, timedelta

with gzip.open('data_fetchers/result/tail_trading_data.json.gz', 'rt') as f:
    data = json.load(f)
df = pd.DataFrame(data['data'])
latest_date = df['date'].max()
yesterday = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
print(f'tail_trading_data.json.gz:')
print(f'  数据最新日期: {latest_date}')
print(f'  期望日期(T-1): {yesterday}')
print(f'  新鲜度判定: {\"✅ 符合\" if latest_date >= yesterday else \"❌ 过期\"}')
"
```

**判定标准**：
- `latest_date >= T-1` → ✅ 数据新鲜，可继续排查后续模块
- `latest_date < T-1` → ❌ 数据过期，需检查对应 data_fetchers 脚本执行情况

**不需要检查日期新鲜度的文件**：
- `stock_list.json`（股票列表，非时间序列）
- `stock_industry.json`（行业分类，非时间序列）

**相关历史教训**：Pitfall 162（见 AGENTS.md）——跳过逻辑必须检查日期新鲜度（`latest_date >= T-1`），而非只检查实体存在。

**步骤 4：检索异常与警告**

使用 grep 扫描所有当日日志：

```bash
grep -r "ERROR\|Exception\|Traceback\|FAIL\|失败" \
  logs/*_2026-MM-DD.log \
  data_fetchers/logs/*_2026-MM-DD.log \
  factor_ic/logs/*_2026-MM-DD.log \
  backtest/logs/*_2026-MM-DD.log \
  comprehensive_factor/logs/*_2026-MM-DD.log \
  summary/logs/*_2026-MM-DD.log 2>/dev/null
```

**步骤 5：汇总报告**

输出格式：

| 模块 | 时间 | 状态 | 关键指标 |
|------|------|------|----------|
| 模块名 | HH:MM-HH:MM | ✅/⚠️/❌ | 耗时、记录数、验证结果 |

**异常分类**：
- **ERROR**：执行失败，需立即关注
- **WARNING**：数据缺失/不完整，需评估影响
- **INFO 级别的失败计数**：如 `失败 3` 通常在容忍范围内

### 常见异常快速定位

|| 异常信息 | 可能原因 | 排查方向 |
||---------|---------|----------|
|| `cannot reindex on an axis with duplicate labels` | 数据索引重复 | 检查数据文件中是否存在重复的 (date, stock_code) 组合 |
|| `SSL: CERTIFICATE_VERIFY_FAILED` | 外部数据源证书问题 | akshare 等外部 API 问题，不影响核心流程 |
|| `Max retries exceeded` | 网络超时/数据源不可达 | 检查网络连接或数据源状态 |
|| `数据完整性判断: full` | 无缓存/缓存过期 | 正常情况，全量计算模式 |
|| `缺失记录数: N (X%)` | 数据源部分缺失 | 评估缺失比例是否在容忍范围 |

### 执行顺序完整清单（run_pipeline.py v1.3）

详见 `run_pipeline.py` 文件头部注释或 `PIPELINE_SCRIPTS` 常量定义。

---

## 附录：pre-commit 与 CI 配置片段 [reference]

以下为 `.pre-commit-config.yaml` 和 `.github/workflows/ci.yml` 的核心配置，作为单一来源：

### pre-commit-config.yaml（核心片段）

```yaml
repos:
  - repo: local
    hooks:
      - id: ruff-check
        name: ruff check
        entry: ruff check --fix
        language: system
        types: [python]

      - id: ruff-format
        name: ruff format
        entry: ruff format
        language: system
        types: [python]

      - id: check-task-size
        name: task size check
        entry: python scripts/check_task_size.py
        language: system
        types: [python]

      - id: check-path-literals
        name: path literals check
        entry: python scripts/check_path_literals.py
        language: system
        types: [python]

      - id: check-path-import
        name: path import check
        entry: python scripts/check_path_import.py
        language: system
        types: [python]

      - id: check-temp-file-path
        name: temp file path check
        entry: python scripts/check_temp_file_path.py
        language: system
        types: [python]
```

### ci.yml（核心片段）

```yaml
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Install dependencies
        run: pip install -e .

      - name: Run pytest with coverage
        run: pytest

      - name: Validate output schemas
        run: python scripts/validate_output_schemas.py

      - name: Check import boundaries
        run: import-linter

      - name: Check design-first compliance
        run: python scripts/check_design_first.py

      - name: Check required test scenarios
        run: python scripts/check_required_test_scenarios.py

      - name: AST checks (fallback for skipped pre-commit)
        run: |
          python scripts/check_path_literals.py
          python scripts/check_path_import.py
          python scripts/check_temp_file_path.py
```

**注意**：以上为核心片段，完整配置见实际文件。修改 hooks 或 CI 任务时必须同步更新本附录。

---

*最后更新: 2026-06-12*

