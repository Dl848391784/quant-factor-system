# reverse_discovery 模块规范

> 版本: v1.0（骨架）
> 创建时间: 2026-06-18
> 最后更新: 2026-06-18
> 状态: [experimental] - 模块尚未实现脚本，规范持续迭代中

## 快速参考

### 模块职责

**reverse_discovery 模块负责"逆向因子发现"——从已实现收益反推可能驱动收益的特征模式，输出候选因子定义。**

核心定位：
1. **逆向发现工具**：观察赢家/输家股票在 T-1 时刻有哪些共同特征（数据驱动）
2. **不直接产出选股结果**：输出的是候选因子定义，需交回正向流程（factor_ic / backtest / comprehensive_factor）验证
3. **与正向流程互补**：发现 → 验证闭环（观察→假设→验证的科学方法）

**重要区分**：
- ✅ reverse_discovery：发现工具（哪些特征值得作为因子？）
- ❌ reverse_discovery：因子计算（已由 factor_ic 负责）
- ❌ reverse_discovery：选股推荐（已由 comprehensive_factor 负责）

### 目录结构

```
reverse_discovery/
├── MODULE.md           # 本文件（模块规范）
├── common/             # 模块内公共函数（待开发）
├── logs/               # 日志目录（按 PROJECT.md 日志规范）
├── result/             # 输出目录（候选因子定义、训练子集、发现报告）
├── schemas/            # JSON Schema 校验文件（待第一个输出脚本实现时创建）
└── test_cases/         # 测试用例（待开发）
```

### 模块定位（与现有 5 模块的关系）

```
正向流程（已有）：
  data_fetchers → factor_ic → backtest → comprehensive_factor → summary

逆向流程（本模块）：
  reverse_discovery
       ↓ 输出候选因子定义
  正向流程（在测试段验证）
```

---

## 设计哲学（核心硬约束）

### D1. 逆向发现 ≠ 正向逆运算，是因子发现工具

**What**: 逆向流程不是正向流程的数学逆运算，而是基于已实现收益的因子发现工具。最终必须通过正向流程在独立测试段验证才算闭环。

**How**:
1. 逆向阶段：在训练段收益数据上做归因分析（统计检验 / 互信息 / 树模型特征重要性等），找出与赢家/输家组显著关联的 T-1 特征
2. 因子构建：将显著特征落地为因子定义（公式、参数、列名）
3. 正向验证：把因子定义交给现有 factor_ic / backtest pipeline，在测试段计算 IC、分层回测

**Don't**: 在逆向模块内自行实现"选股推荐"逻辑——这违反了模块边界，且会跳过正向流程的独立验证（导致 train-on-test 循环论证）。

**Why**:
- 1 日持有期信噪比极低，从收益倒推因子在样本内几乎必然能找到"显著"特征，但样本外大概率失效
- 必须用独立测试段验证才能区分真信号与过拟合
- 正向流程已有完善的 IC / 分层回测 / 综合因子加权基础设施，复用即可，无需重造

**When**: 任何"从收益反推因子"的需求都走本模块，不要在 factor_ic 内嵌入归因逻辑。

**Verify**: `grep -rn '选股\|recommend\|stock_selection' reverse_discovery/` 应无业务实现代码（除非属于发现报告中的诊断输出）。

---

### D2. 时间隔离：训练段与验证段必须不重叠

**What**: 用于发现因子的时间段（训练段）与用于验证因子的时间段（测试段 / holdout）必须完全不重叠，且需考虑 purge 窗口隔离。

**How**:
- 采用 Walk-Forward 切分（详见"流程规范"章节 P1）
- 训练段末尾与验证段开头之间设置 purge 窗口（=2 天，覆盖预测窗口跨度）
- 留出 holdout 段（最后 50 天）只在最终评估时使用一次，不参与任何调参

**Don't**:
- ❌ 用全部 500 天数据既发现因子又验证 IC（train-on-test，循环论证）
- ❌ 在训练段和验证段之间不设 purge 窗口（T-1 因子可能"偷看"到验证段开头的信息）
- ❌ holdout 段反复评估（多次评估等于隐式调参，holdout 失效）

**Why**:
- 数据隔离是逆向因子发现可信度的唯一保证
- 用户偏好（方法论严谨性）：阈值/结论必须有统计依据，禁凭直觉

**Examples**:
```
# ✓ 正确：500 天切分
训练段: 1-300 天   → 逆向发现因子
purge:  301-302 天 → 剔除（双侧各 1 天，对应 1d forward return + 1d 持仓）
测试段: 303-450 天 → 正向验证 IC / 分层回测
holdout: 451-500 天 → 最终一次性评估，不调参

# ✗ 错误：全量数据双重使用
1-500 天 → 逆向发现 → 1-500 天 → 正向验证（同一份数据）
```

**Verify**: 逆向发现脚本必须显式接受 `--train-end-date` 参数；正向 pipeline 必须用 `--data-source` 切换为测试段子集文件。

---

### D3. 不修改原则：不改主数据源、不改正向 pipeline

**What**: reverse_discovery 模块只生成训练子集文件（写入自己的 result/），不修改 `data_fetchers/result/factor_ic_data.parquet` 主数据源；不修改 factor_ic / backtest / comprehensive_factor 的计算逻辑。

**How**:
- 训练子集生成：从主数据源筛选日期范围 → 写到 `reverse_discovery/result/factor_ic_data_train_<train_end>.json.gz`
- 数据隔离实现：通过现有 `--data-source` CLI 参数将子集文件传给正向 pipeline（已在 factor_ic / backtest / comprehensive_factor 三模块统一支持）
- 候选因子集成：新因子先在 factor_generator 中注册计算逻辑，再走正向流程

**Don't**:
- ❌ 修改 `data_fetchers/result/factor_ic_data.parquet`（破坏正向流程）
- ❌ 在 factor_ic / backtest 内增加"训练/测试段"分支逻辑（侵入式修改）
- ❌ 在 reverse_discovery 内重复实现 IC 计算 / 分层回测（违反模块边界）

**Why**:
- 主数据源是跨模块共享资源，修改会污染正向流程
- 正向 pipeline 已通过 `--data-source` 参数提供数据隔离能力（2026-06-18 三模块对齐完成），不需要新增侵入式参数
- 模块边界清晰：reverse_discovery 只做"发现"，正向流程只做"计算+验证"

**Verify**: `git diff` 提交内容不应包含 data_fetchers / factor_ic / backtest / comprehensive_factor 的逻辑改动（仅允许新增因子定义注册）。

---

## 数据契约

### 输入数据

**reverse_discovery 与正向流程共享同一主数据源，通过日期范围切分实现数据隔离。**

| 数据类型 | 来源模块 | 数据路径 | 文件格式 |
|---------|---------|---------|---------|
| 统一行情/因子/收益数据 | data_fetchers | `data_fetchers/result/factor_ic_data.parquet` | gzip JSON（含行情、基础因子、扩展因子、`forward_return_1d/3d/5d`）|

**禁止**：
- 直接修改 `factor_ic_data.parquet`（违反 D3 不修改原则）
- 从 `return_data.json.gz` 读取收益数据（PROJECT.md §核心数据契约 / CLAUDE.md §1.5：统一数据源为 factor_ic_data.parquet，该文件仅备份）

### 输出数据

| 输出类型 | 路径 | 文件格式 | 用途 | 下游消费者 |
|---------|------|---------|------|-----------|
| 训练子集 | `reverse_discovery/result/factor_ic_data_train_<train_end>.json.gz` | 与主数据源完全相同的 gzip JSON | 给逆向发现脚本使用 | reverse_discovery 内部 |
| 测试子集 | `reverse_discovery/result/factor_ic_data_test_<train_end>.json.gz` | 与主数据源完全相同的 gzip JSON | 通过 `--data-source` 传给正向 pipeline 验证 | factor_ic / backtest / comprehensive_factor |
| 留出子集 | `reverse_discovery/result/factor_ic_data_holdout.json.gz` | 与主数据源完全相同的 gzip JSON | 最终一次性评估，永不参与调参（遵循 D2） | factor_ic / backtest（仅 Phase E 终极评估）|
| 候选因子定义 | `reverse_discovery/result/candidate_factors_<日期>.json` | JSON | 记录逆向发现的因子公式、参数、显著性指标 | 人工审核 → factor_generator 注册 |
| 发现报告 | `reverse_discovery/result/discovery_report_<日期>.txt` | 纯文本 | 归因分析结果、统计检验、特征重要性排序 | 人工阅读 |

**字段非空规则**（遵循 PROJECT.md H4）：
- 候选因子定义中 None 字段必须显式记录原因（如 `"correlation_with_existing": null, "reason": "新因子，无现有因子可比"`）

### 数据流向

```
┌──────────────────────────────────┐
│   data_fetchers/result/          │
│   factor_ic_data.parquet         │ ← 主数据源（500 天全量）
│   （只读，禁止修改）              │
└────────────┬─────────────────────┘
             │
             ▼
┌──────────────────────────────────┐
│   reverse_discovery (本模块)      │
│                                  │
│   Step 1: 数据切分               │
│   ├─ 训练子集（1~train_end）     │ → result/factor_ic_data_train_*.json.gz
│   ├─ 测试子集（test_start~end）  │ → result/factor_ic_data_test_*.json.gz
│   └─ holdout（end+1~500）        │ → 仅最终评估
│                                  │
│   Step 2: 逆向发现（仅训练子集） │
│   ├─ 收益画像                    │
│   ├─ 特征发现                    │
│   └─ 因子构建                    │ → result/candidate_factors_*.json
│                                  │
│   Step 3: 发现报告               │ → result/discovery_report_*.txt
└────────────┬─────────────────────┘
             │ candidate_factors.json（人工审核）
             ▼
┌──────────────────────────────────┐
│   factor_generator (data_fetchers)│ ← 注册新因子计算逻辑
└────────────┬─────────────────────┘
             │
             ▼
┌──────────────────────────────────┐
│   正向流程（在测试子集上验证）     │
│   factor_ic --data-source <test>  │
│   backtest   --data-source <test> │
│   composite  --data_source <test> │
└──────────────────────────────────┘
```

### 模块依赖

| 依赖项 | 用途 | 导入方式 |
|-------|------|---------|
| `paths.py` | 主数据源路径单一来源 | `from paths import ...`（遵循 PROJECT.md H7 路径导入）|
| `factor_definitions` | 现有因子定义（避免重复发现） | `from factor_definitions import FACTOR_DEFINITIONS` |

**禁止依赖**（违反模块边界）：
- ❌ `from factor_ic.common import ...`（不复用 IC 计算逻辑）
- ❌ `from backtest.common import ...`（不复用回测逻辑）
- ❌ `from comprehensive_factor.common import ...`（不复用加权逻辑）

理由：reverse_discovery 只负责"发现"，正向流程通过文件契约（`--data-source` + 候选因子定义）解耦。

---

## 流程规范

### P1. Walk-Forward 数据切分（500 天标准方案）

**What**: 采用滚动训练 + 验证窗口的方式切分数据，最终汇报多轮验证段拼接结果。最后保留 holdout 段做不调参的终极评估。

**How**（500 天数据的推荐配置）：

| 轮次 | 训练区间 | 验证区间 | 训练天数 | 验证天数 |
|------|---------|---------|---------|---------|
| 1 | 1-250 | 251-300 | 250 | 50 |
| 2 | 51-300 | 301-350 | 250 | 50 |
| 3 | 101-350 | 351-400 | 250 | 50 |
| 4 | 151-400 | 401-450 | 250 | 50 |
| **holdout** | — | **451-500** | — | **50** |

**核心纪律**：
- 验证区间绝对不能进入训练段
- 第 451-500 天的 holdout 调优结束后才一次性评估，**永不参与调参**
- 最终汇报指标 = 4 轮验证段拼接（200 天）+ holdout 段（50 天）

**Don't**:
- ❌ 用全 500 天做"训练→验证"（训练污染验证）
- ❌ holdout 段反复评估（多次评估等于隐式调参，holdout 失效）
- ❌ 不同轮次的因子定义在验证阶段还在调整（必须在训练阶段锁定）

**Why**:
- Walk-Forward 完全模拟实盘——每轮只用过去信息发现因子，在未来验证
- 4 轮一致性检验比单次切分更能识别"偶然显著"

**Verify**: 切分脚本必须在日志中明确输出每轮的训练/验证日期边界，便于审计。

---

### P2. Purge 窗口（防止时序信息泄露）

**What**: 训练段末尾与验证段开头之间剔除 N 天，N = 因子预测窗口跨度（本项目交易模型为 2 天）。

**How**:
```
原始切分：
训练段: 1-250 天
验证段: 251-300 天

加入 purge 后：
训练段: 1-248 天    （末尾剔除 2 天）
purge:   249-250 天 （隔离区，不参与任何计算）
验证段: 251-300 天
```

**预测窗口跨度计算**（本项目交易模型）：
- T-1 收盘后：计算因子（信息集 ≤ T-1 收盘）
- T 收盘：买入
- T+1 收盘：卖出
- 因子时刻 T-1 → 收益时刻 T+1：跨度 2 天

**Don't**:
- ❌ purge=0（训练段最后一天的 forward_return_1d 字段含 T+1 价格信息，等于偷看验证段）
- ❌ purge 只在单侧（必须双侧隔离，验证段结束后也需要 embargo 缓冲）

**Why**: 1d forward return 字段在生成时已包含未来 1 天信息，再加 1 天持仓 = 2 天泄露窗口。不设 purge 会导致训练 IC 虚高。

**Examples**:
```python
# ✓ 正确：双侧 purge
PURGE_DAYS = 2  # 1d forward return + 1d 持仓
train_dates = sorted_dates[train_start:train_end - PURGE_DAYS]
test_dates  = sorted_dates[train_end:test_end]

# ✗ 错误：无 purge
train_dates = sorted_dates[train_start:train_end]  # 末尾日期含 T+1 收益
test_dates  = sorted_dates[train_end:test_end]
```

**Verify**: 切分脚本断言 `set(train_dates) & set(purge_dates) & set(test_dates) == set()`，且 `min(test_dates) - max(train_dates) >= PURGE_DAYS`。

---

### P3. 时序对齐（避免 look-ahead bias）

**What**: 因子计算时刻必须严格 ≤ 对应收益窗口的起点，避免因子值"偷看"未来信息。

**How**（本项目交易模型）：

| 时刻 | 动作 | 信息集边界 |
|------|------|-----------|
| T-1 收盘后 | 计算因子 F(T-1) | 所有数据 ≤ T-1 收盘 |
| T 收盘 | 买入 | — |
| T+1 收盘 | 卖出 | — |
| **目标对齐** | **F(T-1) ↔ close(T+1)/close(T) - 1** | **= forward_return_1d 在 T 时刻的值** |

**关键陷阱**：
- 现有 `forward_return_1d@T-1` 表示 T-1→T 的收益（不匹配本交易模型）
- 本交易模型实际需要 `forward_return_1d@T`（即 T→T+1 的收益）
- 逆向归因时，应将 `factor@T-1` 与 `forward_return_1d@T` 对齐，而非 `forward_return_1d@T-1`

**Don't**:
- ❌ 把 `factor@T-1` 与 `forward_return_1d@T-1` 配对做归因（错位 1 天，结论无效）
- ❌ 在因子计算中用到 T 时刻或之后的数据（look-ahead bias）
- ❌ 用全样本计算的统计量（如均值/标准差）参与单日因子计算（隐式 look-ahead）

**Why**: 1 日窗口的信噪比极低，1 天的时序错位足以让"显著"特征失效或反向。

**Examples**:
```python
# ✓ 正确：因子@T-1 → 收益@T
factor_t_minus_1 = compute_factor(data.loc[:t_minus_1])  # 信息集 ≤ T-1
target_return    = data.loc[t, 'forward_return_1d']      # T 时刻的 forward = T→T+1
ic = spearmanr(factor_t_minus_1, target_return)

# ✗ 错误：错位对齐
factor_t_minus_1 = compute_factor(data.loc[:t_minus_1])
target_return    = data.loc[t_minus_1, 'forward_return_1d']  # T-1 时刻 = T-1→T
# 此 IC 计算的是 T-1 因子预测 T-1→T 收益，不匹配 T→T+1 持仓窗口
```

**Verify**: 测试用例必须断言因子时刻与收益对齐时刻的偏移正好等于交易模型规定的 holding period 起点。

---

## 模块复用规则

### M1. 模块边界与职责

**reverse_discovery 模块的职责限定为"逆向因子发现"**，不承担以下职责：

| 职责 | 归属模块 | reverse_discovery 是否做 |
|------|---------|------------------------|
| 因子计算 / IC 分析 | factor_ic | ❌ 不做（通过 `--data-source` 复用） |
| 分层回测 | backtest | ❌ 不做（通过 `--data-source` 复用） |
| 综合因子加权 | comprehensive_factor | ❌ 不做（通过 `--data_source` 复用） |
| 数据获取 / 行情拉取 | data_fetchers | ❌ 不做（只读主数据源） |
| 汇总报告生成 | summary | ❌ 不做（reverse_discovery 自己的发现报告除外） |
| **逆向归因 / 特征发现 / 候选因子构建** | **reverse_discovery** | ✅ 主职责 |
| **训练/测试子集切分** | **reverse_discovery** | ✅ 主职责 |

### M2. 模块内公共函数

**reverse_discovery 模块的公共函数放在 `reverse_discovery/common/`，仅本模块内复用，禁止跨模块调用。**

预期会抽取的公共组件（待开发时落地）：
- 数据切分（按日期范围 + purge 窗口生成训练/测试子集）
- 收益画像（按日期分组的赢家/输家组划分）
- 统计检验封装（t-test / Mann-Whitney U / FDR 多检验校正）
- 候选因子定义序列化

**遵循 PROJECT.md 公共模块规范**：
- 公共函数接收 `logger` 参数（不在公共模块内独立创建 logger）
- 公共模块仅在本模块内复用，禁止跨模块调用（违反 PROJECT.md H1 模块边界）

### M3. 跨模块协作方式

**reverse_discovery 与正向流程通过文件契约解耦，不通过 Python import**：

| 协作方向 | 方式 | 示例 |
|---------|------|------|
| 输出训练/测试子集 → 正向 pipeline | 文件 + CLI 参数 | `factor_ic --data-source reverse_discovery/result/factor_ic_data_test_*.json.gz` |
| 输出候选因子定义 → factor_generator | 人工审核 + JSON 文件 | 人工读取 `candidate_factors_*.json` → 在 factor_generator 注册因子 |

**禁止**：
- ❌ `from factor_ic.common.factor_ic_runner import run_factor_ic_analysis`（跨模块 Python 调用）
- ❌ 在 reverse_discovery 内自动触发正向 pipeline 子进程（破坏模块独立性）

**Why**: 文件契约的解耦让正向流程可以独立演进（IC 算法升级、回测逻辑优化）而不影响逆向模块。

### M4. paths.py 单一来源

遵循 PROJECT.md H7 路径导入，所有数据路径必须从 `paths.py` 导入：

```python
# ✓ 正确
from paths import DATA_FETCHERS_RESULT_DIR

main_data_source = DATA_FETCHERS_RESULT_DIR / 'factor_ic_data.parquet'

# ✗ 错误：路径字面量
main_data_source = Path('data_fetchers/result/factor_ic_data.parquet')
```

paths.py 中需新增的常量（待 reverse_discovery 首个脚本实现时添加）：
- `REVERSE_DISCOVERY_RESULT_DIR`：本模块输出目录
- `REVERSE_DISCOVERY_LOGS_DIR`：本模块日志目录

---

## 输出结构模板

### 训练/测试子集（gzip JSON）

**与主数据源 `factor_ic_data.parquet` schema 完全一致**，仅日期范围不同。这样正向 pipeline 不需要任何代码改动即可消费。

```json
{
  "metadata": {
    "source": "reverse_discovery/data_splitter.py",
    "split_type": "train",
    "split_train_end_date": "2026-03-15",
    "split_purge_days": 2,
    "date_range": {
      "start": "2024-06-18",
      "end": "2026-03-13"
    },
    "trading_days": 248,
    "parent_source": "data_fetchers/result/factor_ic_data.parquet",
    "generated_at": "2026-06-18T10:30:00"
  },
  "dates": ["2024-06-18", "2024-06-19", ...],
  "data": [
    {
      "date": "2024-06-18",
      "asset": "000001",
      "open": "10.50", "close": "10.65", "high": "10.70", "low": "10.40",
      "volume": "1234567",
      "rsi_6": 55.3, "volume_ratio_5": 1.12,
      "forward_return_1d": 0.0123,
      "forward_return_3d": 0.0250,
      "forward_return_5d": 0.0410
    }
  ]
}
```

**关键约束**：
- `metadata.split_type` 取值：`"train"` / `"test"` / `"holdout"`
- `metadata.split_purge_days` 必须 ≥ 2（遵循 P2 purge 规范）
- `data` 字段的 schema 与主数据源完全一致，列名 / 类型 / Decimal 字符串格式都不变

### 候选因子定义（JSON）

```json
{
  "metadata": {
    "discovery_script": "reverse_discovery/discover_features.py",
    "train_data_source": "reverse_discovery/result/factor_ic_data_train_2026-03-15.json.gz",
    "discovery_method": "winner_loser_t_test",
    "fdr_correction": "benjamini_hochberg",
    "fdr_alpha": 0.05,
    "generated_at": "2026-06-18T11:00:00"
  },
  "candidates": [
    {
      "factor_name": "示例占位_volume_zscore_5d",
      "factor_col": "示例占位_volume_zscore_5d",
      "formula_description": "5 日成交量 z-score（待具体脚本实现时定型）",
      "discovery_evidence": {
        "winner_loser_mean_diff": 0.45,
        "t_statistic": 3.21,
        "p_value": 0.0012,
        "p_value_adjusted": 0.018,
        "effective_days": 248
      },
      "expected_direction": "positive",
      "correlation_with_existing": null,
      "correlation_reason": "新因子，与现有因子无可比对象（候选阶段尚未集成入因子库）",
      "next_step": "在 factor_generator 中注册该因子的计算逻辑，然后走正向流程在测试段验证"
    }
  ]
}
```

**字段约束**：
- `discovery_evidence.p_value_adjusted` 必须有值（FDR 校正后的 p 值，遵循 D2 / 用户偏好"阈值需统计依据"）
- `expected_direction` 取值：`"positive"` / `"negative"` / `"unknown"`（不可省略，缺失即填 `"unknown"` + 注明原因）
- `correlation_with_existing` 为 None 时必须填 `correlation_reason`（遵循 PROJECT.md H4 字段非空）

### 发现报告（纯文本）

格式参考 summary 模块的报告结构，包含：

```
========================================
逆向因子发现报告 - 2026-06-18
========================================

[训练数据]
- 数据源: reverse_discovery/result/factor_ic_data_train_2026-03-15.json.gz
- 日期范围: 2024-06-18 ~ 2026-03-13（248 个交易日）
- 股票数: <实际值>

[Walk-Forward 配置]
- 总轮次: 4 轮
- 训练窗口: 250 天
- 验证窗口: 50 天
- Purge: 2 天
- Holdout: 第 451-500 天

[Step 1] 收益画像
- 赢家组（top 20%）: 日均收益 X.XX%
- 输家组（bottom 20%）: 日均收益 -X.XX%

[Step 2] 特征发现
- 候选特征数: N
- FDR 校正后显著特征数（α=0.05）: M
- Top 5 特征:
  1. <特征名> | t-stat: X.XX | p_adj: 0.0XXX
  ...

[Step 3] 候选因子
- 输出文件: result/candidate_factors_2026-06-18.json
- 候选因子数: K

[下一步]
将候选因子在 factor_generator 中注册，然后通过正向流程
（factor_ic / backtest）在测试段（reverse_discovery/result/
factor_ic_data_test_*.json.gz）验证。
```

---

## 测试规范

### T1. 测试目录与发现

**测试用例必须放在 `reverse_discovery/test_cases/`**（AGENTS.md 原硬规则 #7 测试位置；PROJECT.md 无 H 对应 -- 最近 H9 是任务粒度不是测试位置；按 MODULE 范围规则保留为模块内约定）。

```
reverse_discovery/test_cases/
├── test_data_splitter.py          # 数据切分边界测试（首批必备）
├── test_purge_window.py            # Purge 窗口正确性测试（首批必备）
├── test_winner_loser_grouping.py   # 收益分组测试（待开发）
└── test_candidate_factor_schema.py # 候选因子定义 schema 校验（待开发）
```

### T2. 必须覆盖的测试场景（首批最小集）

| 场景 | 断言要点 |
|------|---------|
| 数据切分日期边界 | 训练段日期 ⊆ \[start, train_end - PURGE\]；测试段日期 ⊆ \[train_end, test_end\] |
| Purge 窗口隔离 | `set(train_dates) ∩ set(test_dates) == set()` 且 `min(test) - max(train) ≥ PURGE_DAYS` |
| 子集 schema 一致性 | 切分后 JSON 的列名、类型与主数据源完全一致 |
| metadata 完整性 | `split_type` / `split_train_end_date` / `split_purge_days` 字段非空 |
| 候选因子定义 schema | `p_value_adjusted` 非空；`expected_direction` ∈ {positive, negative, unknown} |

### T3. 测试覆盖率要求

遵循项目根目录 `pyproject.toml` 的 `--cov-fail-under=70` 配置。reverse_discovery 模块新增脚本必须保证覆盖率不低于此阈值。

### T4. 集成测试占位

待第一个端到端脚本（数据切分 → 逆向发现 → 候选因子输出）实现后，应在 `tests/integration/` 添加跨模块集成测试，验证：
- reverse_discovery 切分的测试子集能被 factor_ic / backtest 正常消费
- Walk-Forward 多轮切分的边界连续性

---

## 待补充（首次实现脚本时定型）

以下规范条目在当前模块"零代码"状态下尚不能确定，待开发首个脚本（建议从 `data_splitter.py` 起步）时同步补充：

| 待定项 | 触发补充时机 | 预计写入章节 |
|-------|------------|------------|
| **M5+ 脚本命名规则** | 首个脚本 PR | "脚本规范"新章节 |
| **schemas/*.schema.json** | 首个输出文件类型确定 | `reverse_discovery/schemas/` 目录创建 |
| **paths.py 常量** | 首个输出脚本 PR | `paths.py` + PROJECT.md §跨模块数据路径表 |
| **CLI 参数规范** | 首个 CLI 入口脚本 | "CLI 入口设计"新章节（参考 backtest M8） |
| **logger_config.py** | 首个脚本 PR | `reverse_discovery/common/logger_config.py` |
| **PROJECT.md §跨模块数据路径表 条目** | 首个输出文件契约稳定 | PROJECT.md §1 跨模块数据路径表 |
| **具体特征发现算法（t-test / 互信息 / 树模型）选型** | Phase 1 收益画像探索后 | "发现方法"新章节 |
| **FDR 校正方法选型** | 同上 | 同上 |

**触发流程**（遵循 PROJECT.md 陷阱 1 路径迁移未同步）：每补充一项，必须同步检查：
1. 本 MODULE.md 对应章节
2. 依赖的 PROJECT.md 表格
3. 测试用例（`test_cases/test_<脚本名>.py`）
4. 时间标注（用户偏好：改动后更新时间标注）

---

## 更新记录

1. v1.0（2026-06-18）：
   - 首次创建模块规范（骨架 + 设计哲学 + 数据契约 + 流程规范 + 复用规则 + 输出模板 + 测试规范）
   - 状态标注 `[experimental]` —— 模块尚未实现脚本，规范持续迭代
   - 设计哲学（D1/D2/D3）：发现工具定位、时间隔离、不修改原则
   - 流程规范（P1/P2/P3）：Walk-Forward 切分、Purge 窗口、时序对齐
   - 模块复用规则（M1~M4）：模块边界、公共函数、跨模块协作、paths.py 单一来源
   - 输出结构模板：训练/测试子集 + 候选因子定义 + 发现报告
   - 测试规范（T1~T4）：测试目录、首批最小集、覆盖率、集成测试
   - 同步更新 PROJECT.md 目录结构 + 业务模块约定句
   - 关联 design.md：`designs/reverse_discovery_module_md_design.md`

