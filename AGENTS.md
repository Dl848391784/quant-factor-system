# 项目：因子 IC 分析系统

> Python 量化因子分析项目。本文件是 agent 每次对话都会自动加载的"必备知识"，只放硬约束。
> 详细规范见 `PROJECT.md`（按需主动读取）。模块特定规范见 `<模块>/MODULE.md`。

---

## ⚠️ 入口守门员（每次必做）

**开始任何开发任务前，必须按顺序执行：**

```
1. 加载 skill：skill_view(name='superpowers-workflow')
2. 查询知识图谱：sqlite3 .codegraph/codegraph.db "SELECT ..."
```

**禁止跳过**：即使任务看似简单，也必须先了解代码结构和规范流程。
**违规后果**：未加载 skill 或未查询 codegraph 直接改代码 = 流程违规，必须回退重做。

---

## 0. 开发流程（必须遵循）

**涉及代码改动时，必须加载 `superpowers-workflow` skill 并遵循 4 阶段流程：**

```
Plan → Execute → Review → Debug
```

| 阶段 | 核心动作 | 必做项 |
|------|---------|--------|
| **Plan** | 先探索再规划 | 读 PROJECT.md + MODULE.md；涉及 2+ 文件先提交 design.md；任务粒度 ≤3 文件 ≤200 行 |
| **Execute** | 分步执行验证 | 每步完成后验证；运行脚本检查实际输出；同步更新流程文档 + 时间标注 |
| **Review** | 两阶段评审 | ruff → pytest → Spec Compliance（对照规范）→ Code Quality |
| **Debug** | 系统性调试 | 测试失败时加载 `systematic-debugging` skill，找根因再修复 |

**加载命令**：`skill_view(name='superpowers-workflow')`

**弱模型防御机制**（不可跳过）：
- Design-First：涉及 2+ 文件改动，必须先提交 design.md 通过审核才能动手
- 任务粒度约束：单次任务 ≤3 文件、≤200 行代码，超出必须拆分
- 规范引用取证：commit 消息必须引用规范行号（如"遵循 PROJECT.md 规则 #5（行 35-37）"）

---

## 1. 跨模块数据路径（不可违反）

| 模块 | 输出目录 | 输出文件 | 下游读取 |
|------|---------|---------|---------|
| data_fetchers/fetch_factor_cache | `data_fetchers/result/` | `factor_data.json.gz` | factor_generator |
| data_fetchers/fetch_turnover | `data_fetchers/result/` | `turnover_rate_data.json.gz` | factor_generator |
| data_fetchers/fetch_market_cap | `data_fetchers/result/` | `market_cap_data.json.gz` | factor_ic（市值中性化，待启用） |
| data_fetchers/factor_generator | `data_fetchers/result/` | `factor_ic_data.json.gz` | factor_ic, backtest, comprehensive_factor, summary |
| factor_ic | `factor_ic/result/` | `ic_<因子>_<周期>_analysis_result.json` | comprehensive_factor, summary |
| backtest | `backtest/result/` | `<因子>_layered_backtest.json` | summary |
| comprehensive_factor | `comprehensive_factor/result/` | `composite_<加权>_1d.json` | summary |
| summary | `summary/result/` | `factor_summary_report_YYYY-MM-DD.txt` | — |

**统一数据源**：`factor_ic_data.json.gz` 包含行情 + 基础因子 + 扩展因子 + 收益数据（`forward_return_1d/3d/5d`）。所有下游模块**只能**从此文件读取，禁止从 `return_data.json.gz` 读收益数据（仅备份）。

---

## 2. 硬规则（违反即拒收）

| # | 规则 | 检查工具 |
|---|------|----------|
| 1 | 模块边界：只能复用自己目录的 common/ | import-linter |
| 2 | 输出位置：`<模块>/result/` | grep `"result/"` |
| 3 | 临时文件：放 `temporary/` | grep 临时脚本 |
| 4 | 字段非空：None 必须显式设置 + 记录原因 | JSON Schema |
| 5 | 因子方向：根据实际 IC 确定 | pytest 断言 |
| 6 | 退出码：0=成功 / 1=运行时错误 / 2=import-time 配置或注册失败 | 手动检查 |
| 7 | 测试位置：`<模块>/test_cases/` | pytest 发现 |
| 8 | 配套文件：新建脚本同步创建流程文档 + pytest | 人工审核 |
| 9 | 日志格式：使用模块 logger_config | ruff |
| 10 | 异常链：`raise ... from e` | ruff B904 |
| 11 | 路径导入：`from paths import` | import-linter |
| 12 | Design-First：2+文件先提交 design.md | 人工审核 |
| 13 | 日志格式：% 惰性格式化（禁止 f-string / + 拼接 / `exc_info=True`）| ruff G004/G003/G201 |
| 14 | 死代码禁止：禁止永不触发的防御性兜底分支（如 `if result is None` 守卫面对永不返回 None 的 callee） | 人工 review |
| 15 | **第一性原理**：所有方案必须从基本原理推导，禁止调参数式临时修复。方案必须在数据分布变化时仍然成立（如调阈值到 2.5 让问题消失 = 违规；物理边界豁免 = 合规）。违反 = 退回重设计 | 人工 review |

**所有路径必须从 `paths.py` 导入，禁止字符串字面量。**

---

## 3. 已知陷阱 → 集成测试（CI 强制）

### 陷阱 1：路径迁移未同步（集成测试：test_path_migration_sync）
修改任何模块的输出路径前，**必须**：
- 先验证新文件实际包含哪些列
- 同步更新所有依赖模块的代码
- 同步更新 PROJECT.md + 依赖模块 MODULE.md
- 改完跑一遍依赖模块的测试

### 陷阱 2：冗余的"向后兼容"假设（集成测试：test_no_redundant_fields）
路径迁移时**禁止做"某些列还在旧目录"的假设**。
- 正确做法：先验证新数据结构，确认所有需要的数据都在新路径
- 错误案例：保留 additional_factor_files 的冗余读取逻辑

### 陷阱 3：跨规范层级写错位置
- 项目级规范 → PROJECT.md
- 模块级规范 → `<模块>/MODULE.md`
- 流程级规范 → `<模块>/docs/<脚本名>_flow.md`

写错层级 = 重复定义 / 遗漏更新。

---

## 4. 任务前必做（引用规范行号）

- [ ] 读 PROJECT.md（首次接触项目时）
- [ ] 读对应 `<模块>/MODULE.md`
- [ ] 涉及 2 个以上文件 → 先提交 design.md（遵循 PROJECT.md Design-First 流程）
- [ ] 涉及路径变更 → 陷阱 1 的完整流程
- [ ] **提交消息必须引用规范行号**（如："修改因子方向，遵循 PROJECT.md 规则 #5"）

---

## 5. 任务后必做（提交前模板）

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

答不出来 = 退回。

---

## 6. 规范补充结构模板

补充 PROJECT.md / MODULE.md 规范时，必须按以下结构撰写：

| 章节 | 内容 | 必要性 |
|------|------|--------|
| **What** | 规范定义（是什么） | 必须 |
| **How** | 实现方式（怎么做） | 必须 |
| **Don't** | 禁止事项（反面案例） | 必须 |
| **Why** | 设计理由（为什么这样设计） | 推荐 |
| **When** | 适用场景（何时使用） | 推荐 |
| **Examples** | 正反面代码示例 | 推荐 |
| **Verify** | 验证方法（如何检查合规） | 推荐 |

**示例**：
```markdown
### #N: 规范名称

**What**: 规范的明确定义（一句话概括）。

**How**: 具体实现步骤或代码模式。

**Don't**: 反面案例（禁止的做法，附带原因）。

**Why**: 设计理由（历史教训 / 业界实践 / 技术原理）。

**When**: 适用场景（何时必须遵守 / 何时可豁免）。

**Examples**:
```python
# ✓ 正确
正确代码示例

# ✗ 错误
错误代码示例
```

**Verify**: `pytest test_xxx.py` / `ruff check` / grep 检查命令
```

---

## 7. 代码风格 / 日志

由 `pyproject.toml` 中的 ruff + mypy 强制执行。**本文件不重复**这些机器能管的规则。

日志使用各模块的 `common/logger_config.py`：
- **路径**：`<模块>/logs/`
- **命名**：`<脚本名>_YYYY-MM-DD.log`（或固定文件名）
- **格式**：`%(asctime)s | %(levelname)-8s | %(name)s | %(message)s`
- **级别**：INFO（生产），DEBUG（开发）
- **导入**：`from <模块>.common.logger_config import get_logger` 或 `setup_logger`

异常处理两条铁律：
- 异常链必须 `raise ... from e`，不能丢弃原始异常
- 捕获后必须 `logger.exception(...)`，不能只 `logger.error(str(e))`

---

## 8. 何时回头读 PROJECT.md

下列场景必须主动读 `PROJECT.md`：
- 新增模块 / 新增脚本类型
- 修改跨模块数据契约（路径、文件名、字段）
- 不确定规范应该写在哪一层
- 用户提到"为什么这样设计"——背景在 PROJECT.md

