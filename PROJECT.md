# PROJECT.md - Factor IC Analyzer

量化因子 IC 分析系统项目级规范。

**命名风格说明**：项目对外名称使用 Title Case（Factor IC Analyzer），文件系统路径使用 snake_case（factor_ic_analyzer/），章节标题使用中文不受此约束。两者风格差异为设计意图。

---

## 本文档与 AGENTS.md 的关系 [reference]

| 文档 | 加载方式 | 内容定位 | 何时读取 |
|------|----------|----------|----------|
| AGENTS.md | agent 启动时由框架自动注入到上下文 | 精华索引、硬规则速查表 | 每次对话自动注入 |
| PROJECT.md | 按需主动读取 | 详细参考、背景说明、完整规范 | 下列触发条件 |

**必须主动读取 PROJECT.md 的触发条件：**
- 新增模块 / 新增脚本类型
- 修改跨模块数据契约（路径、文件名、字段）
- 涉及数据契约 / 路径 / 输出结构相关讨论（语义匹配，不依赖字面关键词）
- 任务描述包含路径变更、跨模块同步、模块新增等关键词
- 涉及 2+ 文件改动需要写 design.md

---

## 目录结构 [reference]

```
factor_ic_analyzer/
├── factor_ic/              # IC 计算模块
│   ├── test_cases/         # 单元测试
│   └── schemas/            # JSON Schema 校验文件
├── backtest/               # 分层回测模块
│   ├── test_cases/         # 单元测试
│   └── schemas/            # JSON Schema 校验文件
├── comprehensive_factor/   # 综合因子模块
│   ├── test_cases/         # 单元测试
│   └── schemas/            # JSON Schema 校验文件
├── data_fetchers/          # 数据获取模块
│   ├── test_cases/         # 单元测试
│   └── schemas/            # JSON Schema 校验文件
├── summary/                # 数据汇总模块
│   ├── test_cases/         # 单元测试
│   └── schemas/            # JSON Schema 校验文件
├── scripts/                # 自动化检查脚本
├── tests/                  # 测试目录
│   └── integration/        # 集成测试
├── designs/                # design.md 存放目录
├── paths.py                # 跨模块路径单一来源
├── temporary/              # 临时文件目录
├── pyproject.toml          # 项目配置（ruff/pytest/import-linter）
└── PROJECT.md              # 本文件
```

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

```
设计阶段：
□ 在 designs/ 目录创建 design.md（改哪些文件、改哪些接口、加哪些测试）
□ 用户审核通过
□ 才能动手写代码

违反此规则 = 直接退回，不 review。
```

**自动检查**：
- 脚本：`scripts/check_design_first.py`
- 检查逻辑：PR 涉及 2+ 文件改动时，仓库 designs/ 目录下必须存在对应的 design.md 文件
- 对应规则：design.md 文件名等于 PR 分支名（如分支 `feat/add-cache` 对应 `designs/feat_add_cache.md`），或 PR 描述中显式引用 `designs/<文件名>.md`
- pre-commit 软提示：pre-commit 无法读取 PR 信息，仅做轻量启发式——若本次提交涉及 2+ 文件且 designs/ 目录在 git 工作区中无任何新增 .md 文件，则 stderr 输出警告（不阻止提交）；最终对应规则匹配在 CI 强制检查
- CI 硬关卡：PR 创建时强制检查（可访问 PR 分支名/描述），缺少匹配的 design.md 则 CI 失败
- CI 调用：`python scripts/check_design_first.py`

---

## 硬规则（违反即拒收）[stable]

**命名空间**：H 前缀 = 硬规则（自动强制执行）

| 规则编号 | 规则 | 检查工具 | 执行阶段 |
|---|------|----------|----------|
| H1 | 模块边界：只能复用自己目录的 common/（见 H1 注释） | import-linter | CI |
| H2 | 输出位置：`<模块>/result/` | AST 静态分析（脚本：`scripts/check_path_literals.py`） | pre-commit |
| H3 | 临时文件：放 `temporary/` | AST 静态分析（脚本：`scripts/check_temp_file_path.py`） | pre-commit |
| H4 | [预留] 字段非空：详见建议 S4 | —（待 S4 升级后启用） | — |
| H5 | 因子方向：根据实际 IC 确定 | pytest 断言 | CI |
| H6 | 异常链：`raise ... from e` | ruff B904 | pre-commit + CI |
| H7 | 路径导入：`from paths import`（见 H7 注释） | AST 静态分析（脚本：`scripts/check_path_import.py`） | pre-commit |
| H8 | Design-First：2+文件需 design.md（见 H8 注释） | CI `scripts/check_design_first.py` | CI |
| H9 | 任务粒度：≤3 文件、≤200 行 | pre-commit `scripts/check_task_size.py` | pre-commit |
| H10 | 测试覆盖率：不低于阶段性阈值（当前 60%，目标 70%，见 H10 注释） | pytest `--cov-fail-under=60`（当前阶段） | CI |
| H11 | [待实施] 必测场景：每个场景至少一个可运行的测试函数（pytest --collect-only 可发现，见 H11 注释） | CI `scripts/check_required_test_scenarios.py` | CI |

**关于 [预留] 和 [待实施] 标记**：H4 标 [预留] 表示预留编号占位（规则定义见 S4），H11 标 [待实施] 表示规则定义已生效但工具未交付。这两类规则当前不强制执行，仅占位/过渡用，**不可作为 PR 取证依据**（详见 PR 模板节）。H10 虽阈值仍在阶段性升级中，但当前阶段（60%）已硬强制，可作为取证依据。

**硬规则注释**：
- H1 注释：`factor_ic` 只能复用 `factor_ic/common/`，禁止复用 `backtest/common/` 等
- H7 注释：详见"附录：路径常量清单"
- H8 注释：详见"Design-First 流程"章节
- H10 注释：阶段计划与设定依据见"测试覆盖规范"章节
- H11 注释：必测场景清单见"测试覆盖规范"章节

---

## 建议（软约束）[experimental]

**命名空间**：S 前缀 = 建议（软约束，依赖人工执行）

| 规则编号 | 建议 | 当前状态 | 自动化计划 |
|---|------|----------|------------|
| S1 | 退出码统一 0/1 | 手动检查 | 待 CI 脚本 |
| S2 | 配套文件同步创建 | 人工审核 | 待 PR 模板 |
| S3 | 日志格式统一 | 手动检查 | 待自定义 logger_config 模块 + AST 检查脚本 |
| S4 | [待实施] 字段非空：None 必须显式设置 + 记录原因 | 当前生效部分：依赖人工 review；待实施部分：JSON Schema 自动校验 | 校验函数 `validate_and_save_output` 交付后执行下方"S4 → H4 升级 checklist"，编号迁移而非新建 |

**S4 → H4 升级 checklist（升级时必须同步修改的 8 处位置）**：
- [ ] 硬规则表 H4 行：`[预留] 字段非空：详见建议 S4` → 替换为完整规则文字、检查工具、执行阶段
- [ ] 硬规则表注释段：若 H4 规则需补充背景或具体场景，新增"H4 注释"条目；纯字段约束规则（仅 None 处理）无需补注释，可跳过
- [ ] 表后说明"关于 [预留] 和 [待实施] 标记"：从列表中移除 H4
- [ ] 输出结构校验章节"字段非空校验进度"：`详见建议 S4` → `详见硬规则 H4`
- [ ] 硬规则速查表：`H4=[预留]字段非空（待 S4 升级，不可作为取证依据）` → `H4=字段非空`
- [ ] PR 校验脚本注释：从"H4 预留"列表中移除 H4，将 H4 加入可引用规则
- [ ] 校验失败示例：删除 H4 预留示例
- [ ] 建议表 S4 行：升级完成后从建议表删除该行

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

**历史教训集成测试**：放在 `tests/integration/`，命名具体化：

| 教训 | 测试文件 | 测试函数 | 防御场景 | 防御机制（对应规则或独立实施方式） |
|------|----------|----------|----------|------------|
| 路径迁移未同步 | `tests/integration/test_path_migration.py` | `test_no_legacy_path_in_loader` | 防止数据迁移后 loader 仍从旧路径读取 | H7（路径导入） |
| 字段冗余设计 | `tests/integration/test_redundant_fields.py` | `test_no_legacy_additional_factor_files` | 防止 `factor_data_extended.json.gz` 已含 turnover_rate 仍保留 additional_factor_files 冗余读取 | 仅靠教训测试防御（实施方式：扫描代码中 `additional_factor_files` 等已废弃配置项，命中即报错） |
| 收益数据获取错误 | `tests/integration/test_return_data_source.py` | `test_return_data_from_factor_ic_data` | 防止下游模块从废弃的 `return_data.json.gz` 读收益而非统一数据源 | H7（路径导入） |
| 变更同步遗漏 | `tests/integration/test_change_sync.py` | `test_project_md_updated_on_path_change` | 防止路径变更后 PROJECT.md 未同步更新导致文档与代码不一致 | 仅靠教训测试防御（实施方式：CI 中扫描 git diff，若 paths.py 改动则要求同次 commit 含 PROJECT.md 改动） |
| 向后兼容假设 | `tests/integration/test_backward_compat.py` | `test_no_assumption_on_old_columns` | 防止假设旧列仍存在导致数据缺失时静默失败 | 仅靠教训测试防御（实施方式：在数据加载层强制 schema 校验列存在，缺列直接抛错而非取默认值） |
| 文档层级写错 | `tests/integration/test_doc_layer.py` | `test_module_md_for_module_specific` | 防止模块级规范写入 PROJECT.md 造成跨模块定义冲突 | 仅靠教训测试防御（实施方式：脚本扫描 PROJECT.md 中是否出现单模块规则定义句式如"factor_ic 必须 ..."、"backtest 不可 ..."等强制语气，命中即报错；通用引用如目录结构表、路径表中的模块名 mention 不报错） |

---

## 测试覆盖规范 [experimental]

**两个独立要求，必须同时满足：**

1. **覆盖率阈值**：阶段性升级（当前 `--cov-fail-under=60`，目标 70%）
   - 当前阶段：阈值 60% 匹配代码库基线，已在 CI 硬强制（低于 60% CI 失败），先防止覆盖率下降
   - 设定依据：基于当前代码库现状测算（基线 60%），先用 60% 锁定下限，待团队补测试自然提升至 70% 后再升级阈值
   - 阶段计划：基线 60% → 团队补测试至 ≥70% → 升级 H10 阈值至 70% → 同步修改 `pyproject.toml` 中 `addopts = --cov-fail-under=70`

2. **必测场景清单**：必须全部存在对应测试函数
   - CI 检查：`scripts/check_required_test_scenarios.py`
   - 数据来源：脚本读取独立清单文件 `tests/required_scenarios.yaml`
   - PROJECT.md 本表仅作为人类可读视图，与 yaml 清单内容一致
   - 检查逻辑：扫描 `*/test_cases/test_*.py` 与 `tests/integration/test_*.py`，每个必测场景在全仓库至少有一个匹配函数（pytest --collect-only 可发现）

| 类别 | 具体测试场景 | pytest 函数名示例 |
|------|-------------|------------------|
| 输入边界 | 空 DataFrame（0 行） | `test_empty_df` |
| 输入边界 | 单股票 DataFrame（1 asset） | `test_single_stock_df` |
| 输入边界 | 单日 DataFrame（1 date） | `test_single_date_df` |
| 输入边界 | 全 NaN DataFrame | `test_nan_only_df` |
| 输出 schema | JSON Schema 校验通过 | `test_output_schema_valid` |
| 输出 schema | 必须字段存在 | `test_required_fields_present` |
| 异常路径 | FileNotFoundError | `test_file_not_found` |
| 异常路径 | JSONDecodeError | `test_invalid_json` |
| 异常路径 | 数据列缺失 | `test_missing_column` |

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
- 脚本作用范围：（1）校验所有 `*.schema.json` 文件本身符合 JSON Schema meta-schema（CI 可独立运行，无依赖）；（2）若 result/ 目录有产物，则用对应 schema 校验产物（pytest 跑出的测试输出 + 任何 CI 步骤生成的输出）；（3）生产环境的输出由 `validate_and_save_output` 函数在保存时实时校验（详见建议 S4）
- CI 调用：`python scripts/validate_output_schemas.py`

**字段非空校验进度**：详见建议 S4。

---

## 版本历史 [reference]

| 版本 | 日期 | 更新内容 | 稳定性标注 |
|------|------|---------|-----------|
| v3.0 | 2026-06-01 | 大重构 | [experimental] |
| v2.x | 2026-05-xx | 旧版本（已重构） | [deprecated] |

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
3. 任务粒度检查（脚本：`scripts/check_task_size.py`，阈值：MAX_FILES=3, MAX_LINES=200）
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

**硬规则速查表**：
- H1=模块边界、H2=输出位置、H3=临时文件
- H4=[预留]字段非空（待 S4 升级，不可作为取证依据）
- H5=因子方向、H6=异常链、H7=路径导入、H8=Design-First
- H9=任务粒度、H10=测试覆盖率（当前 60% 阶段性阈值，可取证）、H11=[待实施]必测场景（不可作为取证依据）

CI 脚本校验（`scripts/validate_pr_reference.py`）：
1. 规则编号格式正确：可引用硬规则 H1、H2、H3、H5、H6、H7、H8、H9、H10（H4 预留、H11 待实施暂不可引用），建议 S1-S4
2. 编号在对应表中真实存在
3. "[待实施]"和"[预留]"规则不可作为取证依据

**校验失败示例**：
- 若 PR 描述写"引用 H11"，validate_pr_reference.py 抛错：`错误：H11 当前为待实施状态，不可作为取证依据。请改用已实施规则或留空。`
- 若 PR 描述写"引用 H4"，validate_pr_reference.py 抛错：`错误：H4 为预留规则，不可作为取证依据。详见建议 S4。`

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

*最后更新: 2026-06-01*
