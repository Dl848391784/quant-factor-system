# PROJECT.md - Factor IC Analyzer

量化因子 IC 分析系统项目级规范。

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

## Design-First 流程 [stable]（新增）

**涉及 2 个以上文件的改动必须先提交 design.md 通过审核才能动手。**

```
设计阶段：
□ 输出 design.md（改哪些文件、改哪些接口、加哪些测试）
□ 用户审核通过
□ 才能动手写代码

违反此规则 = 直接退回，不 review。
```

---

## 任务粒度指引 [stable]（新增）

**单次任务建议改动不超过 3 个文件、不超过 200 行代码。**

超出必须拆分：
- 5 个文件 → 拆成 2 次任务
- 400 行代码 → 拆成 2 次任务

大任务幻觉率指数上升，拆分是硬规则。

---

## 跨模块路径 [stable]

**所有代码必须 `from paths import ...` 获取路径，禁止字符串字面量。**

| 路径常量 | 用途 | 检查工具 |
|---------|------|----------|
| FACTOR_IC_DATA | 统一数据源 | import-linter |
| FACTOR_IC_RESULT | IC 输出目录 | import-linter |
| BACKTEST_RESULT | 回测输出目录 | import-linter |

**违反检测**：grep 字符串字面量 `"result/"`、`"data_fetchers/result"` 等。

---

## 硬规则（违反即拒收）[stable]

| # | 规则 | 检查工具 | 稳定性 |
|---|------|----------|--------|
| 1 | 模块边界：只能复用自己目录的 common/ | import-linter | [stable] |
| 2 | 输出位置：`<模块>/result/` | grep `"result/"` | [stable] |
| 3 | 临时文件：放 `temporary/` | grep 临时脚本 | [stable] |
| 4 | 字段非空：None 必须显式设置 + 记录原因 | JSON Schema | [stable] |
| 5 | 因子方向：根据实际 IC 确定 | pytest 断言 | [stable] |
| 6 | 退出码：0/1 | 手动检查 | [stable] |
| 7 | 测试位置：`<模块>/test_cases/` | pytest 发现 | [stable] |
| 8 | 配套文件：新建脚本同步创建流程文档 + pytest | 人工审核 | [stable] |
| 9 | 日志格式：统一使用模块 logger_config | ruff | [stable] |
| 10 | 异常链：`raise ... from e` | ruff B904 | [stable] |
| 11 | 路径导入：`from paths import` | import-linter | [stable] |
| 12 | Design-First：2+文件先提交 design.md | 人工审核 | [stable] |

---

## 测试覆盖规范 [stable]（新增）

**最低覆盖率阈值：pytest --cov-fail-under=70**

**必测场景清单：**
- 输入边界（空数据、极端值）
- 输出 schema（JSON Schema 校验）
- 异常路径（FileNotFoundError、JSONDecodeError）

---

## 输出结构校验 [stable]

**各模块输出必须通过 JSON Schema 校验。**

```
factor_ic/schemas/ic_analysis_result.schema.json
backtest/schemas/layered_backtest_result.schema.json
```

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

## 历史教训 → 集成测试 [stable]

| 教训 | 集成测试 | CI 强制 |
|------|----------|--------|
| 路径迁移未同步 | test_path_migration_sync | ✓ |
| 字段冗余设计 | test_no_redundant_fields | ✓ |

---

## 版本历史

| 版本 | 日期 | 更新内容 | 稳定性标注 |
|------|------|---------|-----------|
| v3.0 | 2026-06-01 | 大重构：合并 checklist、绑定工具检查、新增 Design-First 和任务粒度、稳定性标注、paths.py、JSON Schema | [stable] |
| v2.x | 2026-05-xx | 旧版本（已重构） | [deprecated] |

---

## 提交前模板（合并版）[stable]

**执行顺序：lint → schema → test → commit**

```
□ ruff check --fix .                     [自动修复]
□ ruff format .                          [格式化]
□ ruff check .                           [检查剩余问题]
□ mypy .                                 [类型检查]
□ pytest --cov-fail-under=70             [测试覆盖率]
□ JSON Schema 校验输出                   [schema校验]
□ 引用本次任务相关规范行号               [取证]
□ git commit                             [提交]
```

**取证要求**：提交消息必须引用规范行号，如：
```
"修改因子方向逻辑，遵循 PROJECT.md 规则 #5（行号 35-37）"
```

答不出来 = 退回。

---

*最后更新: 2026-06-01*