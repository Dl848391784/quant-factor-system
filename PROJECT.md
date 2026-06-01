# PROJECT.md - Factor IC Analyzer

量化因子 IC 分析系统项目级规范。

---

## 本文档与 AGENTS.md 的关系 [stable]

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

## 目录结构 [stable]

```
factor_ic_analyzer/
├── factor_ic/              # IC 计算模块
├── backtest/               # 分层回测模块
├── comprehensive_factor/   # 综合因子模块
├── data_fetchers/          # 数据获取模块
├── summary/                # 数据汇总模块
├── paths.py                # 跨模块路径单一来源 [必须 import]
├── schemas/                # JSON Schema 校验文件
├── temporary/              # 临时文件目录
└── PROJECT.md              # 本文件
```

---

## Design-First 流程 [experimental]（新增）

**涉及 2 个以上文件的改动必须先提交 design.md 通过审核才能动手。**

```
设计阶段：
□ 输出 design.md（改哪些文件、改哪些接口、加哪些测试）
□ 用户审核通过
□ 才能动手写代码

违反此规则 = 直接退回，不 review。
```

---

## 任务粒度指引 [experimental]（新增）

**单次任务必须改动不超过 3 个文件、不超过 200 行代码。**

超出必须拆分：
- 4+ 个文件 → 拆成 2 次任务
- 200+ 行代码 → 拆成 2 次任务

大任务幻觉率指数上升，拆分是硬规则。

**自动检查**：pre-commit hook 统计 `git diff --stat`，超阈值即阻止提交。

---

## 跨模块路径 [stable]

**所有代码必须 `from paths import ...` 获取路径，禁止字符串字面量。**

|| 路径常量 | 用途 | 检查工具 |
|---------|------|----------|
| FACTOR_IC_DATA | 统一数据源（行情+因子+收益） | import-linter |
| DATA_FETCHERS_RESULT | data_fetchers 输出目录 | import-linter |
| FACTOR_IC_RESULT | IC 输出目录 | import-linter |
| BACKTEST_RESULT | 回测输出目录 | import-linter |
| COMPREHENSIVE_FACTOR_RESULT | 综合因子输出目录 | import-linter |
| SUMMARY_RESULT | 汇总报告输出目录 | import-linter |

**违反检测**：grep 字符串字面量 `"result/"`、`"data_fetchers/result"` 等。

---

## 硬规则（违反即拒收）

|| # | 规则 | 检查工具 | 稳定性 |
|---|------|----------|--------|
| 1 | 模块边界：只能复用自己目录的 common/ | import-linter | [stable] |
| 2 | 输出位置：`<模块>/result/` | pre-commit grep | [stable] |
| 3 | 临时文件：放 `temporary/` | pre-commit grep | [stable] |
| 4 | 字段非空：None 必须显式设置 + 记录原因 | JSON Schema | [stable] |
| 5 | 因子方向：根据实际 IC 确定 | pytest 断言 | [stable] |
| 6 | 测试位置：`<模块>/test_cases/` | pytest 发现 | [stable] |
| 7 | 日志格式：使用模块 logger_config | ruff | [stable] |
| 8 | 异常链：`raise ... from e` | ruff B904 | [stable] |
| 9 | 路径导入：`from paths import` | import-linter | [stable] |

---

## 建议（软约束）

|| # | 建议 | 当前状态 | 未来自动化 |
|---|------|----------|------------|
| 1 | 退出码统一 0/1 | 手动检查 | 待 CI 脚本 |
| 2 | 配套文件同步创建 | 人工审核 | 待 PR 模板 |
| 3 | Design-First 流程 | 人工审核 | 待 PR 模板 |
| 4 | 任务粒度拆分 | 手动检查 | pre-commit hook（已配置） |

---

## 测试覆盖规范 [experimental]（新增）

**最低覆盖率阈值：pytest --cov-fail-under=70**

**必测场景清单（具体示例）：**

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

|| 模块 | Schema 文件路径 |
|------|----------------|
| factor_ic | `factor_ic/schemas/ic_analysis_result.schema.json` |
| backtest | `backtest/schemas/layered_backtest_result.schema.json` |
| comprehensive_factor | `comprehensive_factor/schemas/composite_factor.schema.json` |
| data_fetchers | `data_fetchers/schemas/factor_data.schema.json` |
| summary | `summary/schemas/summary_report.schema.json` |

保存结果前强制校验，失败即抛错。

---

## 模块边界规范 [stable]

```
✓ factor_ic 脚本复用 factor_ic/common/
✓ backtest 脚本复用 backtest/common/
✗ factor_ic 脚本复用 backtest/common/（禁止）
```

**检查工具**：import-linter 禁止跨模块 import。

---

## 历史教训 → 集成测试 [experimental]

|| 教训 | 集成测试文件 | CI 强制 |
|------|-------------|--------|
| 路径迁移未同步 | `tests/integration/test_path_migration_sync.py` | ✓ |
| 字段冗余设计 | `tests/integration/test_no_redundant_fields.py` | ✓ |
| 收益数据获取错误 | `tests/integration/test_return_data_source.py` | ✓ |
| 变更同步遗漏 | `tests/integration/test_change_sync.py` | ✓ |
| 向后兼容假设 | `tests/integration/test_backward_compat_assumption.py` | ✓ |
| 文档层级写错 | `tests/integration/test_doc_layer.py` | ✓ |

---

## 版本历史

|| 版本 | 日期 | 更新内容 | 稳定性标注 |
|------|------|---------|-----------|
| v3.0 | 2026-06-01 | 大重构 | [experimental] |
| v2.x | 2026-05-xx | 旧版本（已重构） | [deprecated] |

**稳定性定义：**
- `[stable]`：经过 2-4 周实战验证，规则可靠
- `[experimental]`：新增内容，待验证
- `[deprecated]`：已废弃

---

## 提交前模板

**强制执行：`.pre-commit-config.yaml` + `.github/workflows/ci.yml`**

```
lint → schema → test → commit
```

pre-commit hooks：
1. ruff check --fix
2. ruff format
3. 文件数/行数阈值检查
4. 路径字面量 grep

CI 任务：
1. pytest --cov-fail-under=70
2. JSON Schema 校验
3. import-linter

---

## PR 模板必填字段

**取证机制**：PR 模板强制填写，CI 校验引用规范存在。

```markdown
## 规范引用
- 本次改动涉及的规则编号：#1, #5, #9
- 对应 PROJECT.md 行号：XX-YY
- 验证方式：pytest / ruff / import-linter
```

CI 脚本校验：
1. 规则编号在硬规则表中存在
2. 行号在 PROJECT.md 中真实存在
3. 对应规则与本次 diff 涉及的文件类型匹配

---

*最后更新: 2026-06-01*