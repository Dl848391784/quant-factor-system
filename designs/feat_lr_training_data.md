# Design: LR 训练数据积累 + 自适应过滤启用

> 版本: v3.10
> 日期: 2026-06-25
> 状态: [experimental]
> 关联: designs/feat_bottom30_overheat_filter.md (v3.9.2 被本设计取代)

---

## 1. 背景与第一性原理审核

### 1.1 v3.9.2 的根本缺陷

v3.9.2 的 `calibrate_lr_filter` 用 `return_5d` 降序 Top30 作为"强势股代理"构建训练样本，
但实际选股目标是 composite 得分最低的 30 只（弱势股端）。数据验证：

| 指标 | return_5d Top30 (训练) | composite Bottom30 (应用) |
|------|----------------------|--------------------------|
| return_5d 均值 | +30.07% | -8.63% |
| T+1 均值 | +0.5920% | +0.0056% |
| 重叠率 | 0.0% (1/15120) | — |
| Cohen's d 群体 | 强势股 | 弱势股 |

**训练分布 ≠ 应用分布**，违反第一性原理。模型在 A 人群学的规律不能应用到 B 人群。

### 1.2 修复方向

不再用任何代理。每天 pipeline 运行时，将**实际选股目标的 Bottom90**（composite 得分最低
90 只）及其完整上下文（权重、因子值、composite 得分）持久化到列式存储。次日补写 T+1 收益。
LR 模型在这些真实样本上训练，训练分布 = 应用分布。

### 1.3 Bottom90 作为训练样本的可行性（已验证）

| 指标 | 结果 | 评价 |
|------|------|------|
| Bottom30 ⊂ Bottom90 包含率 | 100% (504/504 天) | ✅ 完美包含 |
| T+1 均值差异 | 0.025%/天 | ✅ 可忽略 |
| return_5d 均值差异 | 1.71% | ✅ 同为弱势股端 |
| Cohen's d 符号一致 | 9/10 特征 | ✅ 特征方向稳定 |

### 1.4 数据积累策略

| 积累天数 | Bottom90 条数 | 状态 | 行为 |
|----------|--------------|------|------|
| 0-29 天 | 0-2610 | 冷启动 | 不过滤，Bottom30 等权输出 |
| 30-89 天 | 2700-8010 | 预热 | 不过滤（样本不足），开始积累 |
| 90+ 天 | 8100+ | 正式 | 启用 LR 过滤，walk-forward 验证 |

- `enable_overheat_filter` 默认改为 `False`
- 新增 `lr_min_training_days: int = 90` 配置项
- pipeline 运行时检查训练数据天数，≥90 天自动启用，<90 天跳过并记录日志

---

## 2. 数据存储设计

### 2.1 存储格式选择

**列式存储 (Parquet Hive 分区)**，与现有 `stock_selection_history/` 模式一致。

理由：
- 项目已有 Parquet 分区模式（AGENTS.md 跨模块数据路径表）
- 列式存储适合 LR 训练时按特征列读取
- Snappy 压缩，每天 ~50KB，120 天 ~6MB
- pyarrow 原生支持，无需引入新依赖

### 2.2 存储路径

```
comprehensive_factor/result/lr_training_data/
  weight_method=equal_weight/
    selection_date=YYYY-MM-DD/
      part-0.parquet
  weight_method=icir_weight/
    selection_date=YYYY-MM-DD/
      part-0.parquet
  weight_method=ic_weight/
    selection_date=YYYY-MM-DD/
      part-0.parquet
  weight_method=rolling_icir_weight/
    selection_date=YYYY-MM-DD/
      part-0.parquet
```

双重分区（weight_method × selection_date），与现有 `stock_selection_history/` 单分区模式
一致但扩展为双分区，因为四种权重方式各自需要独立的训练数据。

### 2.3 路径配置

`paths.py` 新增：

```python
# LR 训练数据 (Hive 分区 Parquet, v3.10)
LR_TRAINING_DATA_DIR = COMPREHENSIVE_FACTOR_RESULT / "lr_training_data"
```

并在 `__all__` 中导出。

### 2.4 Parquet Schema

每天每个 weight_method 分区写入 90 行（Bottom90），每行字段：

| 字段 | 类型 | 说明 |
|------|------|------|
| selection_date | string (分区键) | 选股日期 YYYY-MM-DD |
| weight_method | string (分区键) | 权重方式 |
| rank | int16 | composite 排名（最低=1） |
| code | string | 股票代码 |
| stock_name | string | 股票名称（从 STOCK_LIST_DATA 查） |
| composite_value | float64 | composite 得分 |
| composite_score | float64 | 分层回测 composite_score（best_selection） |
| factor_direction | string | 因子方向 positive/negative |
| weight_{factor} × 33 | float64 | 各因子权重（列名: weight_amplitude 等） |
| factor_{factor} × 76 | float64 | 各因子原始值（列名: factor_amplitude 等） |
| forward_return_1d | float64 | T+1 收益（当天为 null，次日补写） |
| created_at | timestamp[us, UTC] | 写入时间 |
| run_id | string | 运行 ID |

**设计决策**：
- 权重和因子值用**独立列**而非 JSON 字符串。v3.7 的 `factor_values_json` 字段实际全为 nan
  （验证: stage=3 的 30/30 行均为 nan），说明 JSON 嵌套列实际未被使用。列式存储更利于
  LR 训练时按特征列读取。
- `stock_name` 从 `STOCK_LIST_DATA`（stock_list.json）查询，code→name 映射。

### 2.5 数据量估算

- 每天 90 行 × 4 权重方式 = 360 行
- 列数: 6 基础 + 33 权重 + 76 因子 + 1 收益 + 2 元 = ~118 列
- 每行 ~118 float × 8 bytes ≈ 944 bytes
- 每天: 360 × 944 ≈ 340KB (未压缩), Snappy 压缩后 ~50KB
- 120 天: ~6MB

---

## 3. 实施方案

### 3.1 改动范围

| 文件 | 改动 | 行数估算 |
|------|------|---------|
| `paths.py` | 新增 `LR_TRAINING_DATA_DIR` | +3 行 |
| `comprehensive_factor/stock_selector.py` | ① 新增 `save_lr_training_data()` 函数 ② 新增 `backfill_forward_return_1d()` 函数 ③ 改 `calibrate_lr_filter()` 从 lr_training_data 读取训练样本 ④ 改 `apply_lr_filter()` 适配新模型 ⑤ config 参数调整 ⑥ select_stocks 调用点改动 | ~250 行 |
| `comprehensive_factor/test_cases/test_two_stage_selector.py` | 新增测试 | ~80 行 |
| `comprehensive_factor/MODULE.md` | 新增 M 规则 | ~30 行 |

**任务拆分**（≤3 文件 ≤200 行/任务）：

- **Task 1**: `paths.py` + `save_lr_training_data()` + `backfill_forward_return_1d()` + 测试
- **Task 2**: `calibrate_lr_filter()` + `apply_lr_filter()` 改为从 lr_training_data 读取 + 测试
- **Task 3**: `select_stocks` 调用点 + config 参数 + MODULE.md + 测试

### 3.2 Task 1: 数据持久化

#### 3.2.1 `save_lr_training_data()`

```python
def save_lr_training_data(
    bottom90: list[dict[str, Any]],
    factor_df: pd.DataFrame,
    weight_config: dict[str, Any],
    config: StockSelectorConfig,
    selection_date: str,
    logger: logging.Logger | None = None,
) -> Path:
    """v3.10: 持久化 Bottom90 训练数据到 Parquet 双分区数据集.

    分区布局:
        lr_training_data/weight_method=<method>/selection_date=YYYY-MM-DD/part-0.parquet

    每天每个 weight_method 写 90 行, 含因子权重 + 因子原始值 + composite 得分.
    forward_return_1d 当天为 null, 次日由 backfill_forward_return_1d() 补写.
    同日重跑覆盖该分区.
    """
```

**数据来源**：
- `bottom90`: select_stocks 中 composite 升序最低 90 只（已有 `bottom_candidates` 取 top_n*2=60
  的逻辑，需改为 90）
- `factor_df`: 当日全特征数据（从 `load_full_data` 加载，已有调用）
- `weight_config`: 从 `composite_<method>_1d.json` 的 `meta.weight_meta.last_day_weights` 读取
- `stock_name`: 从 `STOCK_LIST_DATA` 查询

**调用时机**：select_stocks 的 Step 12（写入选股历史）之后，新增 Step 13 写入 LR 训练数据。

#### 3.2.2 `backfill_forward_return_1d()`

```python
def backfill_forward_return_1d(
    data_source: str | Path,
    training_data_dir: Path,
    logger: logging.Logger | None = None,
) -> int:
    """v3.10: 补写前一天 lr_training_data 的 forward_return_1d.

    流程:
    1. 扫描 training_data_dir 下所有 selection_date 分区
    2. 找到 forward_return_1d 为 null 的分区
    3. 从 data_source 读取次日 forward_return_1d
    4. 回写到 Parquet (读 → 补值 → 原子覆盖)

    Returns: 补写的行数
    """
```

**调用时机**：select_stocks 的 Step 0（加载数据之前），先补写历史 T+1 收益。

#### 3.2.3 四种权重方式的处理

`save_lr_training_data` 只保存**当前运行使用的 weight_method** 的数据。
四种权重方式的训练数据在不同 pipeline run 中各自积累。

但用户可能只跑一种 weight_method。如果需要四种都积累，需要在 select_stocks 中对四种
weight_method 各跑一次 composite 计算 + 保存。这会改变 pipeline 结构。

**建议**：先只保存 `best_selection.method`（当前运行的权重方式），其他三种后续按需扩展。
LR 模型训练时也只用对应 weight_method 的训练数据。

### 3.3 Task 2: LR 训练改为从 lr_training_data 读取

#### 3.3.1 `calibrate_lr_filter()` 重写

```python
def calibrate_lr_filter(
    training_data_dir: Path,
    weight_method: str,
    top_n: int = 30,
    n_features: int = 10,
    train_window: int = 120,
    min_oos_auc: float = 0.55,
    min_training_days: int = 90,
    filter_quantile: float = 0.3,
    logger: logging.Logger | None = None,
) -> tuple[LogisticRegression | None, StandardScaler | None, list[str], float]:
    """v3.10: 从 lr_training_data 读取训练样本, 训练 LR 模型.

    与 v3.9.2 的区别:
    - 训练样本来自 lr_training_data (真实 Bottom90), 不再用 return_5d 代理
    - 需要检查训练天数 ≥ min_training_days, 不足则返回 None
    - forward_return_1d 为 null 的行跳过
    """
```

**流程**：
1. 读取 `lr_training_data/weight_method=<method>/` 下所有分区
2. 过滤 `forward_return_1d` 非 null 的行（已有 T+1 收益的）
3. 检查天数 ≥ `min_training_days`，不足返回 None
4. `_discover_features`: Cohen's d 选 top N（不变，但样本来自真实 Bottom90）
5. Walk-forward OOS 验证（不变）
6. 全样本训练最终模型

#### 3.3.2 `apply_lr_filter()` 不变

`apply_lr_filter` 的逻辑不变——从 `data_source` 加载当日特征，用模型打分，排除底 30%。
唯一变化：模型来自 `calibrate_lr_filter` 的新版本。

### 3.4 Task 3: select_stocks 调用点 + config

#### 3.4.1 config 参数调整

```python
# v3.10: LR 数据驱动过滤 (designs/feat_lr_training_data.md)
enable_overheat_filter: bool = False  # v3.10: 默认关闭, 需积累 90 天后自动启用
lr_min_training_days: int = 90  # 最小训练天数
lr_top_features: int = 10  # Cohen's d 排序取 top N 特征
lr_train_window: int = 120  # walk-forward 训练窗口 (天)
lr_min_oos_auc: float = 0.55  # OOS AUC 门槛
lr_filter_quantile: float = 0.3  # Bottom30 中打分最低 30% 排除
lr_bottom_pool_size: int = 90  # 训练数据保存的 Bottom 数量
```

#### 3.4.2 select_stocks 改动

```python
# Step 0: 补写前一天 T+1 收益 (v3.10)
backfill_forward_return_1d(config.data_source, LR_TRAINING_DATA_DIR, logger)

# ... 现有 Step 1-12 不变 ...

# Step 13: 保存 LR 训练数据 (v3.10)
save_lr_training_data(
    bottom90=bottom_pool[:config.lr_bottom_pool_size],
    factor_df=factor_df_full,  # 全特征 (不只是 factor_cols)
    weight_config=weight_config,
    config=config,
    selection_date=selection_date,
    logger=logger,
)

# Step 14: LR 过滤 (v3.10: 从训练数据读取)
if config.enable_overheat_filter:
    lr_model, lr_scaler, lr_features, lr_auc = calibrate_lr_filter(
        LR_TRAINING_DATA_DIR,
        weight_method=best_selection["method"],
        top_n=config.top_n,
        n_features=config.lr_top_features,
        train_window=config.lr_train_window,
        min_oos_auc=config.lr_min_oos_auc,
        min_training_days=config.lr_min_training_days,
        filter_quantile=config.lr_filter_quantile,
        logger=logger,
    )
    # ... 后续 apply_lr_filter 不变 ...
```

#### 3.4.3 bottom_pool 改为 90

现有 `bottom_candidates = valid_cf.nsmallest(config.top_n * 2)` 取 60 只。
改为 `valid_cf.nsmallest(config.lr_bottom_pool_size)` 取 90 只。
Top 30 过滤逻辑不变（从 90 中选 30）。

---

## 4. 冷启动行为

| 阶段 | 训练天数 | enable_overheat_filter | 行为 |
|------|---------|----------------------|------|
| 冷启动 | 0-29 | False (默认) | 只保存训练数据，不过滤 |
| 预热 | 30-89 | False (默认) | 继续保存，不过滤 |
| 正式 | 90+ | False→可手动改 True | 保存 + 过滤 |

用户可随时 `config.enable_overheat_filter = True` 提前启用，但 `calibrate_lr_filter`
会检查训练天数，<90 天返回 None 并记录日志。

---

## 5. 测试计划

### 5.1 Task 1 测试

```python
def test_save_lr_training_data_basic():
    """保存 90 行, 验证分区路径和 schema"""

def test_save_lr_training_data_overwrite():
    """同日重跑覆盖, 不产生重复分区"""

def test_backfill_forward_return_1d():
    """补写前一天 T+1 收益, 验证 null 被填充"""

def test_backfill_no_null():
    """已补写的分区不重复处理"""
```

### 5.2 Task 2 测试

```python
def test_calibrate_lr_filter_insufficient_days():
    """训练天数 < 90, 返回 None"""

def test_calibrate_lr_filter_null_return_skipped():
    """forward_return_1d 为 null 的行被跳过"""

def test_calibrate_lr_filter_oos_validation():
    """足够训练数据时, 返回有效模型"""
```

### 5.3 Task 3 测试

```python
def test_select_stocks_saves_lr_training_data():
    """select_stocks 运行后, lr_training_data 目录有当天分区"""

def test_select_stocks_skips_filter_when_disabled():
    """enable_overheat_filter=False 时不调用 calibrate_lr_filter"""
```

---

## 6. 规范引用

- AGENTS.md §1 跨模块数据路径: 新增 lr_training_data 行
- AGENTS.md 硬规则 #2: 输出位置 `<模块>/result/`
- AGENTS.md 硬规则 #12: Design-First (2+ 文件改动)
- MODULE.md M1: 模块职责
- MODULE.md M38: 动态权重保存
- paths.py: 所有路径从 paths.py 导入

---

## 7. 风险与缓解

| 风险 | 缓解 |
|------|------|
| 四种 weight_method 只跑一种 | 先只保存 best_selection.method, 后续按需扩展 |
| T+1 收益补写失败 | backfill 记录日志, 不阻塞 pipeline |
| 训练数据 schema 变更 | Parquet schema 显式定义, 跨日稳定 |
| 底层因子列表变化 | 权重/因子列动态从 composite 结果读取, 不硬编码 |
