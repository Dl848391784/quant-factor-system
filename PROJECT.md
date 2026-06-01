# PROJECT.md - Factor IC Analyzer

量化因子 IC 分析系统项目级规范。

---

## 本文档与 AGENTS.md 的关系 [experimental]

| 文档 | 加载方式 | 内容定位 | 何时读取 |
|------|----------|----------|----------|
| AGENTS.md | 对话自动加载（ambient） | 精华索引、硬规则速查表 | 每次对话自动注入 |
| PROJECT.md | 按需主动读取 | 详细参考、背景说明、完整规范 | 下列触发条件 |

**必须主动读取 PROJECT.md 的触发条件：**
- 新增模块 / 新增脚本类型
- 修改跨模块数据契约（路径、文件名、字段）
- 不确定规范应该写在哪一层
- 用户提到"为什么这样设计"
- 涉及 2+ 文件改动需要写 design.md

---

## 目录结构 [experimental]

```
factor_ic_analyzer/
├── factor_ic/              # IC 计算模块
├── backtest/               # 分层回测模块
├── comprehensive_factor/   # 综合因子模块
├── data_fetchers/          # 数据获取模块
├── summary/                # 数据汇总模块
├── paths.py                # 跨模块路径单一来源
├── schemas/                # JSON Schema 校验文件
├── temporary/              # 临时文件目录
├── designs/                # design.md 存放目录
└── PROJECT.md              # 本文件
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
- CI 调用：`python scripts/check_design_first.py`

---

## 任务粒度指引 [experimental]

**单次任务必须改动不超过 3 个文件、不超过 200 行代码。**

超出必须拆分：
- 4+ 个文件 → 拆成 2 次任务
- 200+ 行代码 → 拆成 2 次任务

大任务幻觉率指数上升，拆分是硬规则。

**自动检查配置**：
- 脚本：`scripts/check_task_size.py`
- 阈值硬编码：`MAX_FILES = 3`, `MAX_LINES = 200`
- pre-commit 调用：`python scripts/check_task_size.py`
- 配置位置：`.pre-commit-config.yaml`

---

## 跨模块路径 [experimental]

**所有代码必须 `from paths import ...` 获取路径，禁止字符串字面量。**

**正确导入方式**：
```python
# 方式 1：通过 pip install -e . 安装项目后使用包导入
from factor_ic_analyzer.paths import FACTOR_IC_DATA

# 方式 2：通过 PYTHONPATH 环境变量
# export PYTHONPATH=/path/to/factor_ic_analyzer
from paths import FACTOR_IC_DATA

# 方式 3：项目根目录下的脚本可直接导入
from paths import FACTOR_IC_DATA  # paths.py 在根目录
```

**注意**：绝对路径示例（如 `/home/admin/projects/...`）仅供本地开发参考，正式代码禁止硬编码。

| 路径常量 | 用途 | "未导入"检查 | "硬编码字面量"检查 |
|---------|------|-------------|-------------------|
| FACTOR_IC_DATA | 统一数据源 | import-linter | pre-commit grep |
| DATA_FETCHERS_RESULT | data_fetchers 输出目录 | import-linter | pre-commit grep |
| FACTOR_IC_RESULT | IC 输出目录 | import-linter | pre-commit grep |
| BACKTEST_RESULT | 回测输出目录 | import-linter | pre-commit grep |
| COMPREHENSIVE_FACTOR_RESULT | 综合因子输出目录 | import-linter | pre-commit grep |
| SUMMARY_RESULT | 汇总报告输出目录 | import-linter | pre-commit grep |

---

## 硬规则（违反即拒收）[experimental]

| # | 规则 | 检查工具 | 执行阶段 |
|---|------|----------|----------|
| 1 | 模块边界：只能复用自己目录的 common/ | import-linter | CI |
| 2 | 输出位置：`<模块>/result/` | pre-commit grep（pattern: `"[^"]*result/"`） | pre-commit |
| 3 | 临时文件：放 `temporary/` | pre-commit grep | pre-commit |
| 4 | 字段非空：None 必须显式设置 + 记录原因 | JSON Schema | CI |
| 5 | 因子方向：根据实际 IC 确定 | pytest 断言 | CI |
| 6 | 异常链：`raise ... from e` | ruff B904 | pre-commit + CI |
| 7 | 路径导入：`from paths import` | import-linter | CI |
| 8 | Design-First：2+文件需 design.md | CI check_design_first.py | CI |

---

## 建议（软约束）[experimental]

| # | 建议 | 当前状态 | 自动化计划 |
|---|------|----------|------------|
| 1 | 退出码统一 0/1 | 手动检查 | 待 CI 脚本 |
| 2 | 配套文件同步创建 | 人工审核 | 待 PR 模板 |
| 3 | 任务粒度拆分 | pre-commit hook | 已配置 |
| 4 | 日志格式统一 | 手动检查 | 待 import-linter |

---

## 测试位置规范 [experimental]

| 测试类型 | 目录位置 | 用途 | pytest 发现 |
|---------|----------|------|-------------|
| 单元测试 | `<模块>/test_cases/` | 测试单个函数/类 | pytest `<模块>/test_cases/` |
| 集成测试 | `tests/integration/` | 测试跨模块交互 | pytest `tests/integration/` |

**历史教训集成测试**：放在 `tests/integration/`，命名具体化：

| 教训 | 测试文件 | 测试函数 |
|------|----------|----------|
| 路径迁移未同步 | `tests/integration/test_path_migration.py` | `test_no_legacy_path_in_loader` |
| 字段冗余设计 | `tests/integration/test_redundant_fields.py` | `test_no_legacy_additional_factor_files` |
| 收益数据获取错误 | `tests/integration/test_return_data_source.py` | `test_return_data_from_factor_ic_data` |
| 变更同步遗漏 | `tests/integration/test_change_sync.py` | `test_project_md_updated_on_path_change` |
| 向后兼容假设 | `tests/integration/test_backward_compat.py` | `test_no_assumption_on_old_columns` |
| 文档层级写错 | `tests/integration/test_doc_layer.py` | `test_module_md_for_module_specific` |

---

## 测试覆盖规范 [experimental]

**两个独立要求，必须同时满足：**

1. **覆盖率阈值**：`pytest --cov-fail-under=70`
   - 这是整体代码覆盖率要求，低于 70% CI 失败

2. **必测场景清单**：必须全部存在对应测试函数
   - CI 检查函数名清单存在（非 100% 实现，但必须存在函数定义）
   - 每个场景至少有一个测试函数覆盖

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

| 模块 | Schema 文件路径 |
|------|----------------|
| factor_ic | `factor_ic/schemas/ic_analysis_result.schema.json` |
| backtest | `backtest/schemas/layered_backtest_result.schema.json` |
| comprehensive_factor | `comprehensive_factor/schemas/composite_factor.schema.json` |
| data_fetchers | `data_fetchers/schemas/factor_data.schema.json` |
| summary | `summary/schemas/summary_report.schema.json` |

**校验工具与调用入口**：
- 工具：`jsonschema` Python 包
- 脚本：`scripts/validate_output_schemas.py`
- CI 调用：`python scripts/validate_output_schemas.py`

**状态**：规则 #4 当前标记为"实施中"，校验函数 `validate_and_save_output` 待创建。
- 创建前：规则生效但无自动检查，依赖人工 review
- 创建后：所有输出保存必须调用 `validate_and_save_output(data, schema_path, output_path)`

---

## 模块边界规范 [experimental]

```
✓ factor_ic 脚本复用 factor_ic/common/
✓ backtest 脚本复用 backtest/common/
✗ factor_ic 脚本复用 backtest/common/（禁止）
```

**检查工具**：import-linter（配置：`.pyproject.toml` → `[tool.importlinter]`）

---

## 版本历史

| 版本 | 日期 | 更新内容 | 稳定性标注 |
|------|------|---------|-----------|
| v3.0 | 2026-06-01 | 大重构 | [experimental] |
| v2.x | 2026-05-xx | 旧版本（已重构） | [deprecated] |

**稳定性定义：**
- `[stable]`：经过 2-4 周实战验证，规则可靠
- `[experimental]`：新增内容，待验证（当前 v3.0 全部章节）
- `[deprecated]`：已废弃

---

## 提交前模板 [experimental]

**强制执行：`.pre-commit-config.yaml` + `.github/workflows/ci.yml`**

```
lint → schema → test → commit
```

pre-commit hooks（具体实现）：
1. `ruff check --fix`（配置：`.pyproject.toml` → `[tool.ruff]`）
2. `ruff format`（配置：`.pyproject.toml` → `[tool.ruff.format]`）
3. 文件数/行数阈值检查（脚本：`scripts/check_task_size.py`，阈值：MAX_FILES=3, MAX_LINES=200）
4. 路径字面量 grep（脚本：`scripts/check_path_literals.py`，pattern：`['"]\w+/result/`）

CI 任务（具体实现）：
1. `pytest --cov-fail-under=70`（配置：`.pyproject.toml` → `[tool.pytest]`）
2. JSON Schema 校验（脚本：`scripts/validate_output_schemas.py`）
3. `import-linter`（配置：`.pyproject.toml` → `[tool.importlinter]`）
4. Design-First 检查（脚本：`scripts/check_design_first.py`）

---

## PR 模板必填字段 [experimental]

**取证机制**：PR 模板强制填写，CI 校验引用规范存在。

```markdown
## 规范引用
- 本次改动涉及的规则编号：#1, #5, #7
- 对应 PROJECT.md 行号：86-99（硬规则表）
- 验证方式：pytest / ruff / import-linter
```

（以上为示例，请替换为实际行号）

CI 脚本校验（`scripts/validate_pr_reference.py`）：
1. 规则编号在硬规则表中存在（1-8）
2. 行号在 PROJECT.md 中真实存在

---

*最后更新: 2026-06-01*