# PROJECT.md 重构计划 v1

**创建日期**: 2026-06-01
**状态**: 执行中

---

## 问题清单（10项）

| # | 问题 | 位置 | 解决方案 |
|---|------|------|----------|
| 3 | 7个重叠 checklist | 多处 | 合并成单一"提交前模板" |
| 4 | 软约束无机器强制 | 全文 | 绑定工具检查 |
| 5 | 历史教训只活在文档 | 行 73-83 | 转为集成测试 |
| 6 | 路径硬编码 | 行 36-44 | 集中到 paths.py |
| 7 | 无取证机制 | 行 95-112 | 提交时引用具体行号 |
| 8 | 缺少 design-first | 全文 | 新增一节 |
| 9 | 输出结构无校验 | 行 322-374 | JSON Schema 强制校验 |
| 10 | 规范无稳定性标注 | 版本历史 | 加 [stable]/[evolving] |
| 11 | 测试覆盖未规范 | 行 244-269 | 加阈值和必测场景 |
| 12 | 任务粒度无指引 | 全文 | 新增建议 |

---

## 执行步骤

### Step 1: 创建 paths.py（问题 6）

**目标**: 跨模块路径集中管理

**操作**: 创建 `common/paths.py`（或项目根目录 `paths.py`）

```python
# paths.py - 跨模块路径单一来源
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent

# 各模块输出目录
DATA_FETCHERS_RESULT = PROJECT_ROOT / "data_fetchers" / "result"
FACTOR_IC_RESULT = PROJECT_ROOT / "factor_ic" / "result"
BACKTEST_RESULT = PROJECT_ROOT / "backtest" / "result"
COMPREHENSIVE_FACTOR_RESULT = PROJECT_ROOT / "comprehensive_factor" / "result"
SUMMARY_RESULT = PROJECT_ROOT / "summary" / "result"

# 统一数据源
FACTOR_IC_DATA = DATA_FETCHERS_RESULT / "factor_ic_data.json.gz"
```

---

### Step 2: 创建 JSON Schema 文件（问题 9）

**目标**: 输出结构强制校验

**操作**: 在各模块创建 `schemas/<输出名>.schema.json`

示例：`factor_ic/schemas/ic_analysis_result.schema.json`

---

### Step 3: 合并 checklist（问题 3）

**目标**: 单一"提交前模板"

**操作**: 
1. 收集所有 checklist 内容
2. 合并去重
3. 放到文档末尾

---

### Step 4: 绑定工具检查（问题 4）

**目标**: 硬规则有机器强制

**操作**: 在每条硬规则后标注检查工具

示例：
```
□ 日志格式必须统一 [ruff: logging-format]
□ 导入顺序必须规范 [ruff: I]
□ 类型注解必须完整 [mypy: strict]
```

---

### Step 5: 新增章节（问题 8、12）

**新增章节**:
- "Design-First 流程"
- "任务粒度指引"

---

### Step 6: 稳定性标注（问题 10）

**操作**: 给每条规则加标签

```
[stable] 目录结构规范（2026-05-07，稳定）
[evolving] 跨模块数据路径（2026-05-27，待验证）
```

---

### Step 7: 更新 AGENTS.md

**操作**: 同步更新 AGENTS.md 的硬规则部分

---

## 文件变更清单

| 文件 | 操作 |
|------|------|
| PROJECT.md | 重构 |
| AGENTS.md | 更新 |
| paths.py | 新建 |
| schemas/*.schema.json | 新建 |
| pyproject.toml | 更新（pytest 配置） |

---

## 验证

```
□ PROJECT.md 行数 < 400（精简）
□ 单一提交前模板存在
□ paths.py 可导入
□ JSON Schema 可校验
□ pyproject.toml 有 cov-fail-under
```