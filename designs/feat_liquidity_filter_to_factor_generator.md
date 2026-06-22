# R1: 流动性过滤前置化（factor_generator）

**版本**: R1-v1
**作者**: 云瑶
**日期**: 2026-06-22
**状态**: Plan（Design-First）
**前置**: master_l1_l6_roadmap.md
**关联**: 部分回滚 v2.40 feat_family_weight_cap_and_liquidity_filter.md

---

## §1 What — 规范定义

把"成交额低分位"过滤从 `stock_selector` 后置补丁前置到 `factor_generator`，
作为数据层契约（与 `is_untradeable` 并列）。所有下游模块（factor_ic / backtest /
factor_selector / composite）直接读已清洗的 `factor_ic_data.json.gz`。

---

## §2 How — 实施方案

### 2.1 因子生成层（data_fetchers/factor_generator.py）

**新增函数** `_mark_low_liquidity()`，位置紧邻 `_mark_untradeable`（L780）：

```python
def _mark_low_liquidity(
    df: pd.DataFrame,
    min_amount_percentile: float = 0.05,
    logger: logging.Logger | None = None,
) -> pd.DataFrame:
    """标记低流动性股票（is_low_liquidity 列）

    第一性原理（设计依据，master_l1_l6_roadmap.md §2.1）:
        成交额 < 截面 P5 时, 涨/跌是少量交易噪声, IC 公式假设失效.
        使用截面自适应分位 (非固定数字) 适配任何市场环境.

    Args:
        df: 包含 date/volume/close 列的面板数据.
        min_amount_percentile: 截面成交额最低分位 (默认 0.05 = 切掉最低 5%).
        logger: 日志对象.

    Returns:
        df 加 'is_low_liquidity' 列 (1=低流动性, 0=正常).

    Raises:
        ValueError: 缺 volume 或 close 列时.
    """
    if "volume" not in df.columns or "close" not in df.columns:
        raise ValueError(
            "_mark_low_liquidity 需要 volume + close 列, "
            f"实际列={list(df.columns)[:10]}..."
        )

    # amount = volume × close (元)
    df = df.copy()
    df["_amount"] = df["volume"].astype(float) * df["close"].astype(float)

    # 截面分位 (per-date 自适应)
    def _flag_per_date(g: pd.DataFrame) -> pd.Series:
        valid = g["_amount"][g["_amount"].notna() & (g["_amount"] > 0)]
        if len(valid) < 10:
            # 截面样本不足, 不过滤 (避免极端日全过滤)
            return pd.Series(0, index=g.index, dtype=int)
        threshold = valid.quantile(min_amount_percentile)
        return ((g["_amount"] < threshold) | g["_amount"].isna()).astype(int)

    df["is_low_liquidity"] = (
        df.groupby("date", group_keys=False, sort=False).apply(_flag_per_date)
    )
    df = df.drop(columns=["_amount"])

    if logger is not None:
        n_total = len(df)
        n_low = int(df["is_low_liquidity"].sum())
        logger.info(
            "is_low_liquidity 标记: %d/%d (%.2f%%) (min_amount_percentile=%.2f)",
            n_low, n_total, n_low / n_total * 100, min_amount_percentile,
        )
    return df
```

**调用位置**: 与 `_mark_untradeable` 同处（`_format_and_write_output`），紧接其后。

**Schema 更新**: `factor_ic_data.json.gz` 的 `flag_cols` 由
```json
["is_untradeable"]
```
变为
```json
["is_untradeable", "is_low_liquidity"]
```

### 2.2 上游加载器（4 处）

**强制过滤**`is_low_liquidity=1`（与现有 `is_untradeable` 同样处理）：

| 文件 | 锚点 | 改动 |
|---|---|---|
| `factor_ic/common/data_loader.py` | L121-316 现有 is_untradeable 过滤 | 复制同模式加 is_low_liquidity 过滤 |
| `comprehensive_factor/common/factor_loader.py` | L105-230 现有 is_untradeable 过滤 | 同上 |
| `backtest/common/layered_backtest.py` | 类似位置 | 同上 |
| `weight_selector.py` | 加载 layered_backtest 结果，无需改 | — |

实现模式（统一）：
```python
# 在 is_untradeable 过滤之后立即加：
if "is_low_liquidity" in df.columns:
    low_liq_mask = df["is_low_liquidity"].fillna(0).astype(int) == 1
    low_liq_count = int(low_liq_mask.sum())
    if low_liq_count > 0:
        df = df[~low_liq_mask].reset_index(drop=True)
        logger.info("过滤低流动性股票 %d 行", low_liq_count)
else:
    logger.warning("数据缺少 is_low_liquidity 列，跳过流动性过滤")
```

### 2.3 后置过滤回滚（comprehensive_factor/stock_selector.py）

**改动**: L123-124 默认 `enable_liquidity_filter = False`（保留作紧急开关）。

```python
# v2.40 → R1: 流动性过滤已前置到 factor_generator, 此处保留作紧急开关
enable_liquidity_filter: bool = False  # 默认 False, 数据层已过滤
```

L482-512 的过滤逻辑**保留**（不删除），但默认不触发。日志加：
```python
if enable_liquidity_filter:
    logger.warning(
        "启用后置流动性过滤 (v2.40 兼容路径), 推荐用前置 is_low_liquidity 列"
    )
```

### 2.4 测试

新建 `data_fetchers/test_cases/test_mark_low_liquidity.py`:

```python
def test_one_low_amount_marked():
    """单日内 1 只成交额最低 → P5 切除 → is_low_liquidity=1"""
    # 构造 20 只股票, 1 只 amount=1, 其余 amount=1e8
    # 期望: amount=1 那只 is_low_liquidity=1, 其余=0

def test_sparse_day_skipped():
    """截面样本 < 10 → 不过滤, 全部 is_low_liquidity=0"""

def test_missing_volume_raises():
    """缺 volume 列 → ValueError"""

def test_per_date_threshold():
    """两个日期分布不同 → 各自计算阈值"""
```

新建/扩展 `factor_ic/test_cases/test_data_loader_low_liquidity.py`、
`comprehensive_factor/test_cases/test_factor_loader_low_liquidity.py`、
`backtest/test_cases/test_backtest_low_liquidity.py`，分别测：

- 含 `is_low_liquidity` 列 → 过滤生效
- 不含 `is_low_liquidity` 列 → 跳过过滤 + warning（向后兼容）

---

## §3 Don't — 禁止事项

| ❌ | 原因 |
|---|---|
| 用固定数字阈值（如 `amount < 5000 万`） | 不适配市场牛熊；2015 牛市 5000 万是低流动性，2018 熊市是中等 |
| 在 `apply_stabilization_filter` 后做流动性切除 | 流动性是数据层契约，不能依赖选股层 |
| 删除 stock_selector 的 v2.40 路径 | 紧急开关；万一前置过滤出 bug 可回切 |
| 跳过 factor_ic 和 backtest 的加载器改动 | 否则 ICIR/分层回测仍读含仙股池子 |
| 用 `volume × close` 之外的 amount 定义 | 项目其他模块统一这个公式，保持一致 |

---

## §4 Why — 设计理由

### 4.1 v2.40 后置过滤的根本缺陷

v2.40 在 stock_selector 最后一步切，但**前面所有指标已被仙股污染**：

1. `factor_ic` 计算 IC 时含仙股 → IC 失真
2. `factor_selector` 用失真 IC 筛因子 → 选错因子
3. `weight_selector` 用失真分层回测 → 选错 weight_method
4. `composite_runner` 用失真 ICIR → 综合因子失真
5. stock_selector 排序后再切流动性 → **排序已经错了**

### 4.2 与 is_untradeable 同源

涨停（不可买入）+ 低流动性（IC 假设失效）都是"数据层不可用"的物理边界，
应在同一层（factor_generator）处理，由同一类下游过滤代码（4 个加载器）消费。

### 4.3 性能影响

- factor_generator 增加一次 groupby('date') quantile → O(N log N)，<5s
- factor_ic_data.json.gz 增加 1 列 int → 文件大小 +0.2%

---

## §5 When — 适用场景

**必须前置**: 任何 IC / 分层回测 / 权重计算的数据加载。
**可豁免**: 纯单股票分析（如 stock_detail 查询某只股票指标），不参与截面排序。

---

## §6 Verify — 验证方法

```bash
# 1. 单元测试
pytest data_fetchers/test_cases/test_mark_low_liquidity.py -v
pytest factor_ic/test_cases/test_data_loader_low_liquidity.py -v
pytest comprehensive_factor/test_cases/test_factor_loader_low_liquidity.py -v
pytest backtest/test_cases/test_backtest_low_liquidity.py -v

# 2. Schema 校验
python -c "
import gzip, json
data = json.load(gzip.open('data_fetchers/result/factor_ic_data.json.gz'))
assert 'is_low_liquidity' in data['data'][0], '缺 is_low_liquidity 列'
print('PASS')
"

# 3. 选股回归（fin 阶段一并跑）
python comprehensive_factor/stock_selector.py
# 期望: top10 中阴跌股 < 5
```

---

## §7 实施批次拆分（H9 ≤3 文件 ≤200 行）

| 批 | 文件 | 行数 |
|---|---|---|
| r1a | `data_fetchers/factor_generator.py` + `data_fetchers/test_cases/test_mark_low_liquidity.py` + `data_fetchers/result/factor_ic_data_columns.json` | ~120 |
| r1b | `factor_ic/common/data_loader.py` + `comprehensive_factor/common/factor_loader.py` + `backtest/common/layered_backtest.py` + 3 个测试文件 | ~140 |
| r1c | `comprehensive_factor/stock_selector.py` | ~30 |

每批独立 commit，引用 AGENTS.md §1（数据路径）+ §2 规则 #2（输出位置）。

---

## §8 回滚预案

如发现 IC 大幅劣化：
```bash
# 单批回滚
git revert <commit_sha>

# 或：临时禁用前置过滤（暂时保留代码）
# factor_generator.py 调用处加 if FACTOR_GENERATOR_ENABLE_LOW_LIQ_FLAG: ...
# 通过环境变量 FACTOR_GENERATOR_ENABLE_LOW_LIQ_FLAG=0 关闭
```

stock_selector.py 的 v2.40 路径保留 → 应急可重新打开 `enable_liquidity_filter=True`。
