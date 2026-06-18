# reverse_discovery 模块规范文档创建 - design.md

> 创建时间：2026-06-18
> 任务来源：用户新建 reverse_discovery/ 目录（含空 common/docs/logs/result），需创建 MODULE.md，并评估 PROJECT.md / AGENTS.md 是否需要更新

---

## 1. 现状盘点

### 1.1 reverse_discovery 目录现状

```
reverse_discovery/
├── common/    （空）
├── docs/      （空）
├── logs/      （空）
└── result/    （空）
```

**关键事实：当前没有任何代码、没有任何脚本、没有任何流程文档。**

### 1.2 现有模块 MODULE.md 风格对比

| 模块 | 行数 | 文档风格 | 规范条目数 |
|------|------|---------|-----------|
| factor_ic | 2433 | 详尽规范 + 反例（M1~M40+） | 多 |
| comprehensive_factor | 1942 | 详尽规范 + 反例（M1~M30+） | 多 |
| backtest | 1647 | 详尽规范 + 反例（M1~M30+） | 多 |
| data_fetchers | 1167 | 代码规则为主 | 中 |
| **summary** | **590** | **职责 + 数据契约 + 流程规范** | **少** |

**核心观察**：成熟模块的 MODULE.md 是迭代沉淀的产物（每条规范背后都有踩过的坑）。而 summary/MODULE.md 较薄，正是因为它是较新模块。

### 1.3 reverse_discovery 与 PROJECT.md 现有规范的关系

PROJECT.md 第 66-82 行的目录结构枚举了 5 个业务模块，未包含 reverse_discovery。
PROJECT.md 第 84-87 行规定业务模块强制约定：`test_cases/` + `schemas/` + 产物输出到 `result/`。

AGENTS.md 第 47-58 行的"跨模块数据路径"表格列出 5 个模块的输入输出契约，未包含 reverse_discovery。

---

## 2. 核心设计决策（需用户确认）

### 决策 A：MODULE.md 该写多薄？

**问题**：reverse_discovery 目前 0 行代码，规范应该写到什么程度？

**三档方案**：

| 方案 | 内容范围 | 行数预估 | 适用场景 |
|------|---------|---------|---------|
| **A1：占位骨架** | 仅模块定位 + 目录结构 + 数据契约（输入/输出路径） | ~100 行 | 防止"未定义先实现"，开发时再补 |
| **A2：含初始约束**（推荐） | A1 + 前序对话已确认的硬约束（时间隔离 / 不修改正向流程 / 输出因子定义而非选股结果） | ~200 行 | 规范刚好够用，留迭代空间 |
| **A3：仿照 factor_ic 完整规范** | 完整 M1~Mxx 规范 + 反例 + 流程图 | 1000+ 行 | ❌ 不推荐：违反"先实现再规范化"原则，会写出空想规范 |

**我的建议：A2**。理由：
1. 前序对话已经确认了关键设计（数据隔离、Walk-Forward、不改现有 pipeline、复用 `--data-source`），这些是硬约束，写入 MODULE.md 防止后续迭代偏离
2. 但具体函数命名、参数细节都还没实现，写死会束缚开发
3. 与 summary/MODULE.md 风格匹配（590 行，新模块的合理体量）

**反方案理由（如果你选 A1 或 A3）**：
- 选 A1：你认为"前序对话讨论不算实现，规范应等首个脚本提交时再补"
- 选 A3：你想强制对齐 factor_ic 风格，宁可有部分空想规范

---

### 决策 B：PROJECT.md 该不该更新？该改哪些位置？

**需要改的位置**：

| 位置 | 当前内容 | 是否需改 | 改动方案 |
|------|---------|---------|---------|
| L66-82 目录结构 | 列出 5 个业务模块 | ✅ 必改 | 新增 `reverse_discovery/  # 逆向因子发现模块` |
| L84 业务模块约定句 | "factor_ic / backtest / comprehensive_factor / data_fetchers / summary" | ✅ 必改 | 加入 reverse_discovery |
| H1~H20 硬规则 | 通用规则（路径导入、日志格式、退出码等） | ❌ 不改 | reverse_discovery 自动遵守通用硬规则，无需为它新增 |
| 跨模块数据契约 | 5 模块的输入输出 | ⚠️ **取决于决策 D** | 见下方决策 D |

**核心问题：PROJECT.md 的修改是不是规范文档变更？需要先确认？**

参考用户偏好（"补充/修改 PROJECT.md、MODULE.md 等规范文档前必须先确认"），**这个 design.md 本身就是确认动作**。如果你确认 A2 + B 的目录结构更新方案，我就动手；否则等你的修正意见。

---

### 决策 C：AGENTS.md 该不该更新？

**AGENTS.md 第 47-58 行"跨模块数据路径"表格**：

```
| 模块 | 输出目录 | 输出文件 | 下游读取 |
| ... 现有 5 模块条目 ... |
```

**问题**：reverse_discovery 算不算这个表格的一员？

**两种立场**：

- **立场 1（建议）**：现在不加。reverse_discovery 还没确定输出格式，加上去就是占位。等到第一个脚本（如 `discover_features.py`）实现并确定输出契约（如 `reverse_discovery/result/feature_discovery_<日期>.json`）时，再同步更新 AGENTS.md + MODULE.md + PROJECT.md（这正是 AGENTS.md 陷阱 1 强制要求的"路径迁移同步流程"）

- **立场 2**：现在就加占位条目（如"输出格式待定"），让人一眼看到模块存在

**我的建议：立场 1**。理由：AGENTS.md 是 agent 每次都加载的硬约束清单，不该有"待定"占位——会让 agent 困惑该不该读这条规则。

---

### 决策 D：reverse_discovery 与 factor_ic_data.json.gz 的关系？

**前序对话已确认**：reverse_discovery 通过传 `--data-source` 切换数据子集，**不修改主数据源**。

**MODULE.md 应明确写入的硬约束**：

| 项 | 规则 |
|----|------|
| 输入 | `data_fetchers/result/factor_ic_data.json.gz`（与正向流程同源） |
| 数据隔离方式 | 生成训练子集文件（如 `reverse_discovery/result/factor_ic_data_train.json.gz`），通过 `--data-source` 传给现有 pipeline |
| 禁止 | 修改 `data_fetchers/result/factor_ic_data.json.gz`、修改正向 pipeline 模块代码 |
| 输出 | 候选因子定义（不是选股结果），交回正向流程在测试段验证 |

**这是核心设计哲学**，必须在 MODULE.md 第一节明确，防止后续开发偏离。

---

## 3. 拟定的 MODULE.md 骨架（A2 方案）

如果你确认 A2，MODULE.md 大致结构：

```
# reverse_discovery 模块规范

## 快速参考
  - 模块职责（逆向因子发现 ≠ 因子计算 ≠ 选股）
  - 目录结构（含尚未创建的脚本占位）
  - 模块定位（发现工具，输出候选因子定义）

## 设计哲学（核心硬约束）
  - 与正向流程的关系：发现 → 验证闭环
  - 数据隔离：训练段 / 测试段 / holdout 三段切分
  - 不修改原则：不改 data_fetchers 主数据源、不改正向 pipeline

## 数据契约
  - 输入：data_fetchers/result/factor_ic_data.json.gz
  - 输出（待具体脚本实现时补充字段细节）：
    - 训练数据子集：reverse_discovery/result/factor_ic_data_train.json.gz
    - 候选因子定义：reverse_discovery/result/candidate_factors_<日期>.json
    - 发现报告：reverse_discovery/result/discovery_report_<日期>.txt

## 流程规范
  - Walk-Forward 切分规则（500 天 → 4 轮训练 + 50 天 holdout）
  - Purge 窗口（=2 天，对应预测窗口跨度）
  - 时序对齐（因子@T-1 → 收益@T，避免 look-ahead bias）

## 模块复用规则
  - 复用 paths.py（统一路径来源）
  - 复用 data_fetchers 数据加载函数（如已有公共加载工具）
  - 不复用 factor_ic / backtest 内部逻辑（保持独立）

## 输出结构模板
  - 训练子集 JSON 格式（与 factor_ic_data.json.gz 完全一致，仅日期范围不同）
  - 候选因子定义 JSON 格式（占位，待脚本实现时定型）

## 测试规范
  - test_cases/ 必备（项目硬规则 #7）
  - 必须测试：数据切分日期边界、purge 窗口正确性

## 待补充（明确标注）
  - 具体脚本实现后补充：M1, M2, M3...
  - schemas/*.schema.json 待第一个输出脚本实现后创建
```

---

## 4. 改动清单

| 文件 | 操作 | 改动量预估 |
|------|------|-----------|
| reverse_discovery/MODULE.md | 新建 | ~200 行（A2） |
| PROJECT.md | 改 L66-82 目录结构 + L84 业务模块约定 | ~3 行 |
| AGENTS.md | 不改（立场 1） | 0 行 |

**任务粒度**：2 文件、~203 行 → 符合 ≤3 文件 ≤200 行约束（PROJECT.md 改动只 3 行，主体在 MODULE.md，整体在边缘但可接受）。

**触发 Design-First**：是的，2+ 文件改动 → 需 design.md → 即本文档。

---

## 5. 等待用户确认的问题

1. **MODULE.md 详尽程度**：选 A1 / A2 / A3？（建议 A2）
2. **PROJECT.md 是否更新目录结构与业务模块约定句**？（建议是）
3. **AGENTS.md 是否更新跨模块数据路径表**？（建议否，等首个输出脚本实现时再同步）
4. **MODULE.md 中"设计哲学"章节是否包含前序对话的核心结论**（数据隔离 / Walk-Forward / 不改正向流程）？（建议是）

确认后我直接动笔，按 A2 + B（建议方案）执行。
