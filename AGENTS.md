# 项目：因子 IC 分析系统

> Python 量化因子分析项目。本文件是 agent 每次对话都会自动加载的"必备知识"，只放硬约束。
> 详细规范见 `PROJECT.md`（按需主动读取）。模块特定规范见 `<模块>/MODULE.md`。

---

## ⚠️ 入口守门员（每次必做）

**开始任何开发任务前，必须按顺序执行：**

```
1. superpowers-workflow + karpathy-guidelines：已由 pre_llm_call hook 自动注入 routing table（无需主动 skill_view）
2. codegraph 上下文：已由 pre_llm_call hook 自动注入（模块地图 + 任务相关 symbols）
3. 如需更深层结构信息（callers/callees/impact）：主动执行 codegraph callers <symbol> 或 sqlite3 .codegraph/codegraph.db "SELECT ..."
```

**说明**：hook 注入的是"模块地图 + FTS5 匹配的 symbols"，覆盖了 80% 的"改代码前先看结构"场景。剩下 20% 需要更深层信息时（如"改 X 会影响哪些文件"），主动查询 codegraph callers/impact。

**禁止跳过**：即使 hook 已自动注入，agent 仍需**阅读注入内容**而非直接开始改代码。未读注入内容直接改代码 = 流程违规。

---

## 🎯 Skill 触发识别（按场景主动加载）

> **完整触发识别表见 `superpowers-workflow` skill 主文件 §🎯 Skill 触发识别表**（每次 LLM call 顶部已自动注入）。

**核心规则（精简版）**：

| 触发关键词 / 场景 | 必须加载的 skill |
|------------------|------------------|
| "开发因子"/"新增因子"/"IC 脚本"/"分层回测"/"权重"/"选股" | `factor-development` |
| "死代码"/"静默失败"/"5+ bug 批量修复" | `dead-code-and-observability-fixes` |
| "对 X.py 优化"/"按规范流程优化"/"common/ 公共模块" | `public-module-optimization` |
| "跑报告"/"出 summary"/"生成因子汇总报告" | `factor-summary-reporting` |
| 新增函数/脚本/API（**写代码前**） | `test-driven-development` |
| 测试失败/运行时错误（**先于猜测修复**） | `systematic-debugging` |
| 任何编码任务（行为约束） | `karpathy-guidelines` |
| 裁决类结论（**给结论前**）："根因"/"有效吗"/"选哪个方案"/"要不要废弃"/"能上线吗" | `adversarial-review` |
| WebUI bug / session 异常 | `hermes-webui-debugging` |
| 任务交给 Codex 执行 | `kanban-codex-lane` |

**违规检测**：用户追问"你没加载 skill 吗？"或"你没读 AGENTS.md？" = 你已经踩坑。

**superpowers-workflow 唯一例外**：已由 plugin 自动注入，不需要重复加载。

---

## ⚡ 第一性原理（元规则，高于一切硬规则）

**所有方案必须从基本原理推导，禁止调参数式临时修复。方案必须在数据分布变化时仍然成立。**

| | 调参数式修复（违规） | 第一性原理推导（合规） |
|---|---|---|
| 做法 | 调阈值让眼下的问题消失 | 从基本原理推导，找到问题本质 |
| 理论依据 | 无（任意数字） | 有（如支撑集理论、统计检验理论） |
| 健壮性 | 数据变化则失效 | 任何数据分布下都成立 |
| 示例 | 提高 z-score 门限到 2.5 让点质量消失 | 物理边界值=截面 min/max → 豁免 |

**违反 = 退回重设计。** 在 Plan 阶段就必须用第一性原理审视方案，不能等到 Review 阶段才发现。

---

## 🎯 战略目标（高于一切技术方案）

**项目最终产出 = 短名单 30~50 只（量化输出）→ 人工决断 3~5 只（用户决定）**

| 环节 | 谁负责 | N |
|------|--------|---|
| 全市场筛选 → Layer 1 | 量化 | 5000 → 549 |
| Layer 1 → 短名单 | 量化 | 549 → **30~50** ← 量化产出在此 |
| 短名单 → 持仓 | **人** | **30~50 → 3~5** |

**禁区**（这些方案违反战略目标，禁止提案）：

- ❌ "从 5000 只直接选 Top 3~5" 的纯量化方案——N=3~5 无统计支撑
- ❌ 用 Top 3~5 的 backtest 作为 weight_selector 评估指标——样本不足
- ❌ 用 Layer 1 年化收益替代 Top 3~5 期望收益——欺骗性指标
- ❌ 默认 N=10 作为 Top N 评估参数——真实约束是 N=3~5

**新方案提案模板**（必填）：

```
影响范围：
  □ 短名单 (30~50) ← 量化职责
  □ 最终持仓 (3~5) ← 用户职责（量化不应越界）
  □ Layer 1 候选池 (549) ← 量化基础设施
```

详见 PROJECT.md "战略目标：量化辅助 + 人工决断"。

---

## 📊 数据驱动原则：禁贴叙事标签

**系统的方向/风格/属性由实证数据涌现，不由设计者预设。**

| ❌ 错误叙事 | ✅ 正确数据描述 |
|---|---|
| "做弱势反转策略" | "composite 方向=negative，Layer 1 年化+24%" |
| "改成趋势跟随" | "需重跑 factor_direction='positive' 的 backtest 验证" |
| "我们是动量风格" | "RSI/momentum 因子的 IC 值与权重占比是 XX" |

**禁词**（无具体实证数据时禁止使用）：
- 弱势反转 / 趋势跟随 / 反弹捕获 / 价值投资 / 动量风格 / 选股逻辑应该...

**强制要求**：方向性建议必须**先展数据，再下结论**，不允许"概念先行，数据补证"。

详见 PROJECT.md "数据驱动原则：禁止给系统贴叙事标签"。

---

## ⏰ 实战交易规则：T+1 持仓

**T-1 日数据 → T 日 09:25 算 → T 日尾盘买 → T+1 日卖**

**持仓周期 = 1 日 → 评估指标必须用 `forward_return_1d`，禁用 5d/10d 评估实战表现。**

> **📌 日期语义权威定义（判"数据是否最新/延迟"必读）**：`selection_date`、各 parquet 应有最新日期、segment_win_rates 为何"看着旧"非延迟等，**唯一定义在 PROJECT.md §实战交易规则 →「核心数据契约（T+1 日期语义）」**。本处不重复，判 freshness/延迟前先对齐该节。

| 场景 | 评估指标 |
|---|---|
| 因子 IC / 分层回测 | 多周期都跑（看因子稳定性） |
| **短名单 / Top N 实战评估** | **只用 1d**（含 0.1% 成本扣减） |

**Don't**:
- ❌ 用 5d/10d 反弹率评估短名单"质量"——持仓 1 日就卖了，5 日后无关
- ❌ 用 Layer 1 分层回测年化估"实战年化"——分层回测是 549 只等权 ≠ Top 3~5 集中

详见 PROJECT.md "实战交易规则：T 日尾盘买入 T+1 日卖出"。

---

## 0. 开发流程（必须遵循）

**涉及代码改动时，必须加载 `superpowers-workflow` skill 并遵循 4 阶段流程：**

```
Plan → Execute → Review → Debug
```

| 阶段 | 核心动作 | 必做项 |
|------|---------|--------|
| **Plan** | 先探索再规划 | 读 PROJECT.md + MODULE.md；涉及 2+ 文件先提交 design.md；任务粒度 ≤3 文件 ≤200 行 |
| **Execute** | 分步执行验证 | 每步完成后验证；运行脚本检查实际输出 |
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
| data_fetchers/factor_generator | `data_fetchers/result/` | `factor_ic_data.parquet` | factor_ic, backtest, comprehensive_factor, summary |
| factor_ic | `factor_ic/result/` | `ic_<因子>_<周期>_analysis_result.json` | comprehensive_factor, summary |
| backtest | `backtest/result/` | `<因子>_layered_backtest.json` | summary |
| comprehensive_factor | `comprehensive_factor/result/` | `composite_<加权>_1d.json` | summary |
| stock_selector | `comprehensive_factor/result/stock_selection_history/` | `selection_date=YYYY-MM-DD/part-0.parquet`（Hive 分区数据集，含 Stage 1/2/3 三段 ~90 行/天）| summary |
| summary | `summary/result/` | `factor_summary_report_YYYY-MM-DD.txt` | — |

**统一数据源**：`factor_ic_data.parquet` 包含行情 + 基础因子 + 扩展因子 + 收益数据（`forward_return_1d/3d/5d`）。所有下游模块**只能**从此文件读取，禁止从 `return_data.json.gz` 读收益数据（仅备份）。

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
| 8 | 配套文件：新建脚本同步创建 pytest | 人工审核 |
| 9 | 日志格式：使用模块 logger_config | ruff |
| 10 | 异常链：`raise ... from e` | ruff B904 |
| 11 | 路径导入：`from paths import` | import-linter |
| 12 | Design-First：2+文件先提交 design.md | 人工审核 |
| 13 | 日志格式：% 惰性格式化（禁止 f-string / + 拼接 / `exc_info=True`）| ruff G004/G003/G201 |
| 14 | 死代码禁止：禁止永不触发的防御性兜底分支（如 `if result is None` 守卫面对永不返回 None 的 callee） | 人工 review |

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

