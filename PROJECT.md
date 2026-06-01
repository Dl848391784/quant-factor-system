# Project Context - Factor IC Analyzer

量化因子 IC 分析系统项目级规范。各模块规范详见各目录下的 MODULE.md。

---

## 目录结构

```
factor_ic_analyzer/
├── factor_ic/              # IC 计算模块
│   ├── MODULE.md           # IC 计算规范（命名、输出、增量模式等）
│   ├── common/             # 公共函数
│   ├── docs/               # 流程文档
│   ├── result/             # IC 计算结果输出
│   └── test_cases/         # 测试用例
│
├── backtest/               # 分层回测模块
│   ├── MODULE.md           # 分层回测规范
│   ├── common/             # 公共函数
│   ├── result/             # 回测结果输出
│   └── ...
│
├── comprehensive_factor/   # 综合因子模块（新增）
│   ├── MODULE.md           # 综合因子规范（加权方式、因子组合、输出格式）
│   ├── common/             # 公共函数
│   │   ├── factor_loader.py        # 因子数据加载
│   │   ├── weight_engine.py        # 加权计算引擎
│   │   ├── composite_runner.py     # 公共入口（调用backtest）
│   │   └── ...
│   ├── docs/               # 流程文档
│   ├── result/             # 综合因子结果输出
│   └── test_cases/         # 测试用例
│
├── data_fetchers/          # 数据获取模块
│   ├── MODULE.md           # 数据拉取规范
│   ├── common/             # 公共函数
│   ├── docs/               # 流程文档
│   ├── result/             # 数据拉取元信息输出
│   ├── logs/               # 日志目录
│   ├── test_cases/         # 测试用例
│   ├── factor_generator.py # 统一因子生成入口
│   ├── fetch_turnover.py   # 换手率数据拉取
│   ├── fetch_stock_list.py # 股票列表拉取
│
├── summary/                # 数据汇总模块
│   ├── MODULE.md           # 数据汇总规范
│   ├── docs/               # 流程文档
│   ├── logs/               # 日志目录
│   ├── result/             # 汇总报告输出目录
│   ├── test_cases/         # 测试用例
│   ├── generate_factor_summary_report.py  # 因子分析汇总报告
│   └── merge_factors.py                   # 因子数据合并
│
├── common/                 # 项目级公共模块
├── tests/                  # 项目级测试目录
├── temporary/              # 临时文件目录
│
└── PROJECT.md              # 本文件（项目级规范）
```

---

## 模块间依赖关系

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│ data_fetchers│────▶│   result    │────▶│  factor_ic  │
│  (数据拉取)  │     │  (统一数据)  │     │  (IC 计算)  │
└─────────────┘     └─────────────┘     └─────────────┘
                                              │
                      ┌───────────────────────┼───────────────────────┐
                      │                       │                       │
                      ▼                       ▼                       ▼
                ┌─────────────┐         ┌─────────────┐         ┌─────────────┐
                │   backtest  │         │comprehensive│         │  backtest   │
                │ (分层回测)  │◀────────│  _factor    │────────▶│ (分层回测)  │
                └─────────────┘         │ (综合因子)  │         └─────────────┘
                      │                 └─────────────┘                 │
                      │                       │                       │
                      └───────────────────────┼───────────────────────┘
                                              │
                                              ▼
                                      ┌─────────────┐
                                      │   summary   │
                                      │  (数据汇总) │
                                      └─────────────┘
```

**数据流向：**
1. data_fetchers 拉取数据 → cache 存储（原始行情数据）
2. data_fetchers/factor_generator 计算 → result 存储（扩展因子数据）
3. factor_ic 读取 data_fetchers/result → 计算 IC → 输出 factor_ic/result
4. backtest 读取 cache → 分层回测 → 输出 result
5. comprehensive_factor 读取 factor_ic result + cache → 加权计算综合因子 → 调用 backtest 分层回测
6. summary 读取 factor_ic/result + backtest/result + comprehensive_factor/result → 生成汇总报告

### 跨模块数据路径规范（2026-05-26新增，2026-05-27更新）

**各模块数据输出/输入路径：**

|| 模块 | 输出目录 | 输出文件 | 依赖模块读取位置 |
||-----|---------|---------|----------------|
|| data_fetchers/fetch_factor_cache | **data_fetchers/result/** | **factor_data.json.gz, return_data.json.gz** | **factor_generator 统一输入源** |
|| data_fetchers/fetch_turnover | **data_fetchers/result/** | **turnover_rate_data.json.gz** | **factor_generator 统一输入源** |
|| data_fetchers/factor_generator | data_fetchers/result/ | factor_ic_data.json.gz | factor_ic, backtest, comprehensive_factor, summary 统一数据源 |
|| factor_ic | factor_ic/result/ | ic_<因子名>_analysis_result.json | comprehensive_factor, summary |
|| backtest | backtest/result/ | <因子名>_layered_backtest.json | summary |
|| comprehensive_factor | comprehensive_factor/result/ | composite_<加权方式>_1d.json | summary |
|| summary | summary/result/ | factor_summary_report_YYYY-MM-DD.txt | 读取各模块 result 目录 |

**数据架构迁移历史（2026-05-27）：**
- v2.6: 收益数据合并到 factor_ic_data.json.gz，实现单文件读取架构
- v2.7: fetch_factor_cache/fetch_turnover 输出路径统一迁移到 result 目录
  - 所有 data_fetchers 模块输出统一到 data_fetchers/result/
  - factor_generator.py 输入路径同步更新为 result 目录
  - 实现模块内数据闭环：fetch → result → generator → result
- 统一数据源：factor_ic_data.json.gz 包含行情+因子+收益数据
- 所有下游模块（factor_ic, backtest, comprehensive_factor）应读取同一数据源

**factor_ic_data.json.gz 数据结构（2026-05-27更新）：**
- 行情数据：open, close, high, low
- 基础因子：rsi_6, volume_ratio_5, turnover_rate
- 扩展因子：bollinger_pb, kdj_j, turnover_surge
- 收益数据：forward_return_1d, forward_return_3d, forward_return_5d（已合并）
- 索引字段：date, asset

**变更同步检查清单（强制）：**

```
□ 模块输出路径变更 → 同步更新 PROJECT.md 跨模块数据路径表
□ 模块输出路径变更 → 同步更新依赖模块的 MODULE.md 数据来源描述
□ 模块输出路径变更 → 同步更新依赖模块的代码路径配置（如 data_loader.py）
□ 【关键】修改路径配置前 → 先验证新数据文件结构（包含哪些列），避免冗余设计
□ 变更后在 PROJECT.md 版本历史记录此次跨模块同步
□ 变更后运行依赖模块的测试用例验证数据读取正常
```

**历史教训（2026-05-26）：**
- data_fetchers/factor_generator 输出路径从 cache 改为 result 目录
- 但 factor_ic/data_loader.py 未同步更新，导致 factor_ic 脚本读取旧路径数据
- 原因：PROJECT.md 缺少跨模块数据路径变更同步规范

**修改路径配置前必须验证数据结构（2026-05-26新增）：**
- 错误做法：修改路径配置时做"向后兼容"假设（假设某些列还在旧目录）
- 正确做法：先验证新数据文件包含哪些列，确认所有需要的数据都在新路径中
- 案例：factor_data_extended.json.gz 已包含 turnover_rate，但修改时仍保留 additional_factor_files 的冗余设计
- 原因：未先验证数据结构，直接做假设性设计

**数据架构语义统一（2026-05-27新增）：**
- factor_ic_data.json.gz = factor_ic 需要的统一数据源
- 不区分"原始数据"与"处理后数据"，统一为 factor_ic 提供所需数据
- close 等 OHLC 数据是原始行情，但 factor_ic 需要使用，因此也包含在内
- 收益数据 forward_return_1d/3d/5d 也合并进来，避免多文件读取

**收益数据获取规范（2026-05-31新增）：**
- ✅ 从 `factor_ic_data.json.gz` 获取收益数据（forward_return_1d/3d/5d）
- ❌ 禁止从 `return_data.json.gz` 获取收益数据（该文件仅用于数据备份/历史追溯）
- 原因：factor_ic_data.json.gz 是统一数据源，所有下游模块应读取同一文件

**模块边界规范（2026-05-23新增）：**

```
模块只能复用自己目录下的 common 模块，禁止跨模块复用。

✓ factor_ic 脚本复用 factor_ic/common/
✓ backtest 脚本复用 backtest/common/
✗ factor_ic 脚本复用 backtest/common/（禁止）
✗ backtest 脚本复用 factor_ic/common/（禁止）

如果需要复用其他模块的功能，将代码复制到本模块的 common/ 目录下。
```

**原因：**
- 模块边界清晰，便于独立测试和迁移
- 避免跨模块依赖导致的耦合问题
- 每个模块可以独立演进

---

## 模块规范文件

| 模块 | 规范文件 | 说明 |
|------|---------|------|
| factor_ic | factor_ic/MODULE.md | IC 计算脚本命名、输出格式、增量模式、参数传递 |
| backtest | backtest/MODULE.md | 分层回测规则、统计指标、公共模块复用 |
| comprehensive_factor | comprehensive_factor/MODULE.md | 综合因子加权方式、因子组合、输出格式、调用backtest规范 |
| data_fetchers | data_fetchers/MODULE.md | 数据源定义、缓存格式、脚本命名、公共模块复用、因子生成规范 |
| summary | summary/MODULE.md | 数据汇总、报告生成、因子合并、跨模块数据采集 |

---

## 开发前检查清单

执行开发任务前**必须阅读**：

```
□ 项目级：阅读 PROJECT.md（目录结构、模块依赖）
□ 模块级：阅读对应目录下的 MODULE.md
□ 流程级：阅读 docs/ 目录下的流程文档
□ 公共函数：检查 common/ 是否有可复用函数
```

---

## 临时文件规范（2026-05-31新增）

### 核心原则

**所有临时文件和脚本必须放在 `temporary/` 目录下。**

### 适用范围

```
✓ 实验性脚本（探索性分析、原型验证）
✓ 调试文件（临时日志、测试数据）
✓ 一次性脚本（数据迁移、格式转换）
✓ 不属于其他目录职责的文件
```

### 目录结构

```
factor_ic_analyzer/
├── temporary/              # 临时文件目录
│   ├── experiments/        # 实验性脚本
│   ├── debug/              # 调试文件
│   └── ...                 # 其他临时文件
```

### 禁止行为

```
❌ 在模块目录下创建临时脚本（如 factor_ic/temp_script.py）
❌ 在项目根目录下散落临时文件
❌ 将正式功能脚本放入 temporary/ 目录
```

### 版本管理

```
□ temporary/ 目录添加到 .gitignore，不纳入版本管理
```

---

## 文档层级规范（2026-05-22新增）

### 核心原则

**新增规范时必须判断层级，写入对应文档。**

| 规范类型 | 写入位置 | 示例 |
|---------|---------|------|
| 项目级（跨模块通用） | PROJECT.md | 代码风格、日志格式、目录结构 |
| 模块级（单模块特定） | MODULE.md | factor_ic公共模块复用、backtest分层规则 |
| 流程级（单脚本流程） | docs/<脚本>_flow.md | ic_rsi_1d 计算流程 |

### 新增规范时检查清单

```
□ 该规范是否仅适用于特定模块？（如 factor_ic、backtest）
□ 如果仅适用于特定模块 → 写入该模块的 MODULE.md
□ 如果适用于全项目 → 写入 PROJECT.md
□ 写入前检查目标文档是否已有类似规范（避免重复定义）
□ 写入后同步更新版本历史
```

### 常见错误

```
❌ factor_ic 特定规范写入 PROJECT.md（应写入 factor_ic/MODULE.md）
❌ backtest 特定规范写入 PROJECT.md（应写入 backtest/MODULE.md）
❌ 通用规范重复定义在多个 MODULE.md（应只在 PROJECT.md 定义一次）
```

---

## 开发后动作（必做）

完成开发后**必须执行**：

```
□ 代码修改 → 同步更新 MODULE.md（如有规范变更）
□ 代码修改 → 同步更新流程文档 docs/<脚本名>_flow.md
□ 流程文档时间标注 → 生成时间、实测数据时间、版本号递增
□ 运行脚本验证 → 输出数据结构符合规范
□ 运行测试用例 → test_cases/ 目录下测试通过
```

---

## 脚本配套文件规范（2026-05-20新增）

### 核心原则

**创建或更新脚本时，必须同步创建或更新相应的流程文档、测试用例。**

### 配套文件位置

| 文件类型 | 位置 | 命名规则 | 示例 |
|---------|------|---------|------|
| 流程文档 | `<模块目录>/docs/` | `<脚本名>_flow.md` | `factor_ic/docs/ic_rsi_1d_flow.md` |
| pytest 测试文件 | `<模块目录>/test_cases/` | `test_<脚本名>.py` | `factor_ic/test_cases/test_ic_rsi_1d.py` |

**命名说明：**
- `<脚本名>` = 脚本文件名去掉 `.py` 后缀
- 例如：`ic_rsi_1d.py` → 流程文档 `ic_rsi_1d_flow.md`，pytest 测试文件 `test_ic_rsi_1d.py`

### 测试代码规范（2026-05-27新增）

**核心原则：测试用例必须是 pytest 可执行文件，禁止在 `__main__` 块写测试代码。**

```
□ 禁止在脚本 `__main__` 块写测试代码
□ 测试用例必须是 pytest 可执行文件（.py 格式）
□ 修改代码后必须跑完整测试用例：pytest <模块>/test_cases/ -v
□ 新建脚本时同步创建 pytest 测试文件
□ pytest 测试文件使用 tempfile.TemporaryDirectory 管理临时文件
```

**历史教训（2026-05-27）：**
- `cache_manager.py` 的 `__main__` 块包含测试代码，无法自动运行、无法集成 CI
- 正确做法：将测试代码转换为 pytest 文件 `test_cases/test_cache_manager.py`

### 强制规则

**新建脚本时：**
```
□ 创建脚本文件（如 ic_xxx.py）
□ 同步创建流程文档（docs/ic_xxx_flow.md）
□ 同步创建测试用例（test_cases/ic_xxx_test_cases.md）
□ 流程文档包含：整体架构、详细流程步骤、输出结构、关键指标
□ 测试用例包含：输入验证、输出验证、边界条件、异常处理
```

**更新脚本时：**
```
□ 修改脚本代码
□ 同步更新流程文档（如有流程变更）
□ 同步更新测试用例（如有功能变更）
□ 流程文档时间标注同步更新（生成时间、实测时间、版本号、更新内容）
□ 运行验证 → 流程文档与实际执行一致
□ 运行验证 → 测试用例全部通过
```

### 禁止行为

```
❌ 只写代码不写流程文档
❌ 只写代码不写测试用例
❌ 流程文档滞后于代码修改
❌ 测试用例滞后于代码修改
❌ 流程文档只更新内容不更新时间标注
```

> 各模块目录结构详见上方"目录结构"章节。

---

## 输出数据规范（2026-05-23新增）

### 核心原则

| # | 约束 | 适用模块 | 说明 |
|---|------|---------|------|
| 1 | 输出结构必须统一 | factor_ic, backtest | 所有脚本输出相同结构，便于下游统一处理 |
| 2 | 字段值不可为 None | factor_ic, backtest | 输出前诊断原因，空数据显式标记 |
| 3 | 结果输出到 result 目录 | factor_ic, backtest | `模块目录/result/`，纳入版本管理 |
| 4 | 因子方向不可预判 | factor_ic, backtest | 根据实际 IC/回测结果确定，不能假设 |

### 输出目录规范

**所有模块的输出结果必须放在 `<模块目录>/result/` 目录。**

| 模块 | 输出目录 | 文件格式 |
|------|---------|---------|
| factor_ic | `factor_ic/result/` | `ic_<因子名>_<周期>_analysis_result.json` |
| backtest | `backtest/result/` | `<因子名>_layered_backtest.json` |

**禁止：**
```
❌ 输出到临时目录（临时缓存，不持久化）
❌ 输出到脚本同级目录（散乱，难管理）
```

### 输出结构一致性规范

**同一模块内所有脚本输出结构必须一致。**

**MODULE.md 职责：**
- 定义模块特定的输出结构模板（具体字段）
- 定义字段含义和必须非空的字段列表

**PROJECT.md 职责：**
- 定义跨模块通用原则（结构一致、字段非空）
- 各模块 MODULE.md 引用 PROJECT.md 通用原则

**示例：**
```json
// factor_ic 输出结构（MODULE.md 定义）
{
  "meta": {...},
  "ic_metrics": {...},
  "statistical_significance": {...},
  ...
}

// backtest 输出结构（MODULE.md 定义）
{
  "meta": {...},
  "layer_stats": {...},
  "long_short": {...},
  ...
}
```

### 字段不能为空规范

**输出字段为 None 说明有问题，必须诊断原因。**

**诊断步骤：**
1. 检查数据加载是否正确
2. 检查计算逻辑是否正确
3. 检查边界条件处理是否正确

**正确处理：**
```python
# 空数据时显式设置 None，并记录原因
if len(data) == 0:
    result['sharpe_ratio'] = None  # 明确标记
    logger.warning("数据不足，sharpe_ratio 设为 None")
```

**禁止：**
```python
# 计算错误导致隐式 None
result['sharpe_ratio'] = data['return'].mean() / data['return'].std()
# 空数据时除零错误，result['sharpe_ratio'] 未设置
```

### 因子方向不可预判规范

**因子方向必须根据实际结果确定，不能根据因子类型假设。**

**正确做法：**
```python
# 根据 IC 结果判断
ic_mean = result['ic_metrics']['ic_mean']
factor_direction = 'negative' if ic_mean < 0 else 'positive'
```

**禁止：**
```python
# 根据因子类型假设（错误！）
# RSI 是反向因子？不一定，要看实际 IC
factor_direction = 'negative'  # 预判，错误
```

**原因：**
- 同类型因子在不同市场/时间段可能方向不同
- IC 结果是唯一可靠的判断依据

---

## 文档一致性规范

### 跨文档同步原则

**修改代码时，必须同步更新以下文档：**

| 修改内容 | 需同步更新的文档 |
|---------|----------------|
| factor_ic/ic_xxx.py | docs/ic_xxx_flow.md + MODULE.md（如有规范变更） |
| factor_ic/common/*.py | 所有引用该模块的流程文档 |
| MODULE.md 规范变更 | 所有相关流程文档示例 |
| PROJECT.md 规范变更 | 所有相关 MODULE.md |

### 流程文档时间标注规范

流程文档更新时**必须同步更新**：

```
□ 生成时间：文档头部的时间标注
□ 实测数据时间：示例数据的运行时间
□ 版本号：递增（如 v1.0 → v1.1）
□ 更新内容：说明本次修改的内容
```

**禁止行为：** 只更新文档内容不更新时间标注。

---

### 脚本退出码规范（2026-05-26新增）

**所有脚本统一使用 0/1 退出码：**

```
0 = 成功
1 = 失败
```

**错误定位方式：** 查看脚本执行日志（stdout/stderr），日志系统会记录详细错误信息。

```python
# ✓ 正确：简单退出码 + 详细日志
import sys
import logging

logger = logging.getLogger(__name__)

def main():
    try:
        # 业务逻辑
        result = process_data()
        logger.info("处理完成")
        return 0
    except FileNotFoundError as e:
        logger.error(f"数据文件不存在: {e}")
        return 1
    except Exception as e:
        logger.exception(f"执行失败: {e}")  # 记录完整堆栈
        return 1

if __name__ == '__main__':
    sys.exit(main())
```

**为何只用 0/1：**
- 日志系统已提供详细错误信息
- 复杂退出码增加脚本实现负担
- 失败原因通过日志定位更准确

---

## 版本历史

| 版本 | 日期 | 更新内容 |
|------|------|---------|
| v2.8 | 2026-05-26 | comprehensive_factor 新增 --auto_select CLI 参数，支持自动因子筛选（基于 ICIR 和高相关性）；修复 FACTOR_NAME_TO_COL_MAP 列名映射；修正 create_cli_entrypoint 参数顺序 |
| v2.7 | 2026-05-27 | 扩展跨模块数据路径规范表：添加 backtest 和 comprehensive_factor 数据来源；明确统一数据源架构迁移历史 |
| v2.6 | 2026-05-27 | 重构数据架构：factor_data_extended → factor_ic_data（统一数据源语义）；合并收益数据到 factor_ic_data.json.gz；更新跨模块数据路径规范、数据结构说明、语义统一原则 |
| v2.5 | 2026-05-26 | 新增"跨模块数据路径规范"：数据输出/输入路径表、变更同步检查清单、历史教训；同步更新数据流向描述 |
| v2.4 | 2026-05-22 | 迁移 factor_ic 特定规范至 MODULE.md（公共模块强制复用、公共模块日志传递），新增文档层级规范 |
| v2.3 | 2026-05-20 | 新增"日志规范"章节：框架选择（logging）、级别规范、路径规范、命名规范、格式规范、异常记录规范、使用姿势示例 |
| v2.2 | 2026-05-20 | 新增"代码风格规范"章节（import、注释缩进、异常链、死代码清理等） |
| v2.1 | 2026-05-20 | 新增"脚本配套文件规范"：流程文档位置、测试用例位置、强制规则 |
| v2.0 | 2026-05-19 | 重构：factor_ic 规范移至 MODULE.md，精简项目级规范 |
| v1.x | 2026-05-07~19 | factor_ic 规范逐步完善（已移至 MODULE.md） |

---

*最后更新: 2026-05-27*
