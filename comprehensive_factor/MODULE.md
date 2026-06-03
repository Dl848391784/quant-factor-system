# comprehensive_factor 模块规范

> 版本: v2.4
> 最后更新: 2026-06-03
>
> 本规范由 AI 智能体或人类开发者执行。每条规则采用统一框架:**What / Why / How / Don't / When / Verify**。
>
> **harness 中立**:不绑定特定智能体平台,描述均为通用语义。

---

## 目录

### 一、模块概况
- [模块概述](#模块概述)
- [综合因子构建完整流程](#综合因子构建完整流程)
- [权重选择脚本](#权重选择脚本)
- [股票选股脚本](#股票选股脚本)
- [输出结构模板](#输出结构模板)

### 二、规则索引 (M1-M55,按类别)

| 类别 | 编号 | 主题 |
|------|------|------|
| **A. 模块基础** | M1-M4 | 模块职责 / 公共模块复用 / 脚本命名 / 输出与日志 |
| **B. 加权方式** | M5-M8 | 4 种加权 / 静态权重 / 滚动 ICIR / 向量化实现 |
| **C. 标准化** | M9-M11 | 截面标准化 / `_std` 列接口约定 / NaN 处理 |
| **D. 因子筛选** | M12-M16 | 无效判定 / 高相关组 Union-Find / 关键指标缺失 / ICIR 缺失 / 完整性标记 |
| **E. 命名映射与正则** | M17-M20 | 因子名映射表 / 反向映射 / 正则预编译+贪婪 / 跳过非标准 |
| **F. 数据加载与校验** | M21-M26 | 数据来源 / 必需列 / 返回值解包 / 空值检查 / 类型校验 / 一致性强校验 |
| **G. NaN 与权重处理** | M27-M30 | NaN 相关性 / composite NaN / 动态权重归一化 / 除零保护 |
| **H. 防御性校验** | M31-M34 | 校验前置 / 前置条件 / 父类 validate / 校验层级 |
| **I. 缺失与字段回退** | M35-M37 | 缺失因子返回 / 字段回退验证 / 死代码移除 |
| **J. 动态权重与时间轴** | M38-M40 | 动态权重保存 / 元信息分离 / 滚动 ICIR 时间轴 |
| **K. CLI 与异常** | M41-M45 | 退出码 / 堆栈保留 / 最小导入 / 文件读取异常 / logger 传递 |
| **L. Config 设计** | M46-M48 | Config 类 + 继承 / 单一数据源 / List 必须 field |
| **M. 代码风格与性能** | M49-M55 | 模块级代码 / PEP8 / Union-Find 迭代 / set 替代 list / lambda 延迟绑定 / rolling_std ddof / 注释数据来源 |

### 三、附录
- [更新记录](#更新记录)
- [引用说明](#引用说明)

---

## 模块概述

comprehensive_factor 模块负责将多个**单因子**按加权方式组合成**综合因子**,并调用 backtest 模块进行分层回测。

**模块定位**:
- **输入**:`factor_ic` 的 IC 结果 + 单因子值 (从 `data_fetchers/result/factor_ic_data.json.gz`)
- **处理**:加权计算综合因子值
- **输出**:`comprehensive_factor/result/<脚本名>.json` (综合因子分层回测结果)
- **依赖方向**:`data_fetchers → factor_ic → comprehensive_factor → backtest (调用)`

**脚本命名**:`composite_<加权方式>_<收益周期>.py`

| 加权方式 | 标识 | 示例脚本 |
|---------|------|---------|
| 等权 | equal_weight | `composite_equal_weight_1d.py` |
| ICIR 加权 | icir_weight | `composite_icir_weight_1d.py` |
| 滚动 ICIR 加权 | rolling_icir_weight | `composite_rolling_icir_weight_1d.py` |
| IC 加权 | ic_weight | `composite_ic_weight_1d.py` |

**统一数据源 (2026-05-27 起)**:所有因子、行情、收益数据均在 `factor_ic_data.json.gz` 中。参数 `cache_dir` 已改为 `data_source`。

---

## 综合因子构建完整流程

```
Step 1: 单一因子分析
  ├─ Percentile 分层回测 → 多空年化、夏普、单调性
  └─ 计算 IC 序列 → IC 均值、ICIR、每日 IC 值
                              ↓
Step 2: 因子筛选 (自动化,见 D 类规则)
  ├─ 计算所有因子两两相关性矩阵
  ├─ 无效因子 (IC 不显著/单调性差) → 直接丢弃
  ├─ 高相关组 (|corr|>0.7) → 只保留最强的 (按 |ICIR|)
  └─ 保留下来的因子 → 两两低相关
                              ↓
Step 3: 标准化 (M9)
  每日截面标准化: factor_std = (factor - μ) / σ
                              ↓
Step 4: 加权计算综合因子 (B 类规则)
  ├─ 等权 (equal_weight)
  ├─ ICIR 加权 (icir_weight)
  ├─ IC 加权 (ic_weight)
  └─ 滚动 ICIR 加权 (rolling_icir_weight)
  → 得到 4 个综合因子
                              ↓
Step 5: 综合因子分层回测
  对 4 个综合因子分别做分层回测
                              ↓
Step 6: 权重方式选择 (weight_selector.py)
  ├─ 提取评价指标（收益、稳定性、成本风险）
  ├─ Min-Max归一化（方向统一化）
  ├─ 等权综合得分
  └─ 输出最优权重方法
                              ↓
Step 7: 股票选股 (stock_selector.py)
  ├─ 加载最优权重配置（weight_selection_result.json）
  ├─ 加载当日因子数据（factor_ic_data.json.gz）
  ├─ 标准化因子值
  ├─ 加载 IC 每日序列（滚动ICIR需要）
  ├─ 计算综合因子值（使用最优权重方法）
  ├─ 按因子方向排序（反向升序/正向降序）
  └─ 输出 Top N 股票列表
```

---

## 权重选择脚本

**脚本**: `weight_selector.py`

**功能**: 从4种权重方式中选择最优方案

| 类别 | 指标 | 方向 |
|------|------|------|
| **收益类** | 多空年化收益、多空夏普比率、多头年化收益、多头夏普比率、成本后日收益 | 越大越好 |
| **稳定性** | 单调性相关性绝对值 | 越大越好 |
| **成本风险** | 多头换手率、空头换手率、最大回撤 | 越小越好 |

**打分流程**:
```
1. 提取9个指标值
2. 方向统一化（单调性取绝对值，回撤/换手反转）
3. Min-Max归一化到[0, 1]
4. 等权平均得到综合得分
5. 排序选出最优方法
```

**输出**: `result/weight_selection_result.json`

---

## 股票选股脚本

**脚本**: `stock_selector.py`

**功能**: 使用最优权重方法计算股票综合因子值并选出 Top N

**流程**:
```
1. 加载最优权重配置（weight_selection_result.json）
2. 加载当日因子数据（factor_ic_data.json.gz）
3. 确定选股日期（默认取最新日期）
4. 过滤数据（只保留选股日期）
5. 标准化因子（截面标准化）
6. 加载 IC 数据（根据权重方法）
7. 计算综合因子（使用最优权重方法）
8. 排序选出 Top N
9. 输出结果
```

**排序规则**:
- **反向因子** (`factor_direction=negative`): 升序排序（综合因子值越小越好）
- **正向因子** (`factor_direction=positive`): 降序排序（综合因子值越大越好）

**输出**: `result/stock_selection_result.json`

```json
{
  "meta": {
    "selection_date": "2026-06-01",
    "weight_method": "rolling_icir_weight",
    "composite_score": 0.8137,
    "factor_direction": "negative",
    "top_n": 10,
    "total_stocks": 3006,
    "valid_stocks": 10,
    "created_at": "2026-06-03T17:56:28"
  },
  "top_stocks": [
    {
      "rank": 1,
      "code": "002173",
      "composite_value": -1.802,
      "factor_values": {"rsi_6": 12.58, "volume_ratio_5": 0.2}
    },
    ...
  ],
  "weight_config": {
    "method": "rolling_icir_weight",
    "window": 60,
    "factor_list": ["rsi", "volume_ratio"],
    "factor_cols": ["rsi_6", "volume_ratio_5"]
  }
}
```

**CLI 参数**:
```bash
python stock_selector.py \
    --top_n 10 \
    --selection_date 2026-06-01 \
    --factor_direction negative \
    --rolling_window 60
```

---

## 输出结构模板

```json
{
  "meta": {
    "weight_method": "icir_weight",
    "return_period": "1d",
    "factor_list": ["rsi", "volume_ratio"],
    "weights": {"rsi": 0.35, "volume_ratio": 0.65},
    "weight_meta": {"is_dynamic": false, "method": "icir_weight"},
    "ic_results": {"rsi": {...}, "volume_ratio": {...}},
    "correlation_matrix": {"rsi_vs_volume_ratio": 0.30},
    "n_factors": 2,
    "composite_factor_range": [-2.5, 2.8]
  },
  "backtest_result": {<复用 backtest 输出结构>},
  "config": {
    "n_layers": 5, "factor_direction": "negative",
    "long_layers": [1, 2], "short_layers": [4, 5],
    "trade_cost_rate": 0.003
  },
  "created_at": "<ISO时间>"
}
```

**动态权重的 weight_meta** (rolling_icir_weight 专用):

```json
{
  "weights": {},
  "weight_meta": {
    "is_dynamic": true,
    "method": "rolling_icir_weight",
    "window": 60,
    "note": "权重每日动态计算,不保存静态值"
  }
}
```

---

# A. 模块基础

## M1. 模块职责

**What**:`comprehensive_factor/` 只做**组合因子**(加权聚合)和**调用 backtest**,禁止重新实现 backtest 的分层逻辑或拉取数据。

**Why**:模块边界清晰才能维护单向依赖 `data_fetchers → factor_ic → comprehensive_factor → backtest`。

**How / Don't**:

```
✅ 调用 run_layered_backtest() 做分层
✅ 调用 run_composite_backtest() 入口做组合
✗ 自行实现分层引擎逻辑
✗ 跨模块复用其他业务模块的 common/
```

**Verify**:import-linter;`grep` 应无 `from factor_ic.common`、`from backtest.common.layered_backtest import LayeredBacktestEngine`。

---

## M2. 公共模块强制复用

**What**:`comprehensive_factor/common/` 已封装的功能必须直接调用,禁止脚本自行实现。

**How / Don't**:

| 功能 | 公共模块 | 禁止自行实现 |
|------|---------|------------|
| 因子数据加载 | `factor_loader.load_factor_values()` | gzip.open + json.load |
| IC 结果加载 | `factor_loader.load_ic_results()` | json.load 手写 |
| IC 每日序列加载 | `factor_loader.load_ic_daily()` | 手写读 daily.json.gz |
| 加权计算 | `WeightEngine.calculate()` | 手写权重循环 |
| 公共入口 | `composite_runner.run_composite_backtest()` / `create_cli_entrypoint()` | 手写主流程 |
| 日志配置 | `logger_config.get_logger()` | 手写 logging.getLogger |
| 类型转换 | `convert_types` | 手写 numpy → Python 转换 |

**调用 backtest 的方式** (M2 例外:跨模块调用上层入口允许):

```python
from backtest.common.layered_backtest_runner import run_layered_backtest

factor_df['composite_factor'] = composite_factor_values
result = run_layered_backtest(
    factor_name=f'{weight_method}_composite',
    factor_col='composite_factor',
    config=config,
    data_source=data_source,
    output_dir=output_dir,
    logger=logger,
)
```

---

## M3. 脚本命名

**What**:综合因子分层回测脚本统一命名为 `composite_<加权方式>_<收益周期>.py`。

**Why**:与 factor_ic (`ic_<因子>_<周期>.py`) 和 backtest (`layered_backtest_<因子>_<周期>.py`) 模块命名规则保持一致。

**示例**:`composite_equal_weight_1d.py`、`composite_rolling_icir_weight_1d.py`。

---

## M4. 输出目录与日志路径

**What**:
- 结果输出到 `comprehensive_factor/result/<脚本名>.json`
- 日志输出到 `comprehensive_factor/logs/*.log`,通过 `from comprehensive_factor.common.logger_config import get_logger`

**新加权方式扩展 checklist**:
```
□ 在 weight_engine.py 新增加权方法类 (继承 WeightMethodBase)
□ 在 MODULE.md 新加权方式章节增说明
□ 新建脚本 composite_<新方式>_1d.py
□ 新建测试用例 test_cases/<新方式>_test_cases.py
□ 运行脚本验证
□ 更新 MODULE.md 版本号
```

---

# B. 加权方式

## M5. 4 种加权方式总览

**What**:综合因子支持 4 种加权方式,分类为**静态权重** (权重不随时间变化) 和**动态权重** (权重每日重算)。

| 方式 | 类型 | 权重公式 | 数据来源 |
|------|------|---------|---------|
| equal_weight | 静态 | `w_i = 1/n` | — |
| icir_weight | 静态 | `w_i = ICIR_i / Σ ICIR_j` | `factor_ic/result/*.json` 的 `icir` 字段 |
| ic_weight | 静态 | `w_i = ic_mean_i / Σ ic_mean_j` | `factor_ic/result/*.json` 的 `ic_mean` 字段 |
| rolling_icir_weight | **动态** | 每日 = 滚动 ICIR / Σ 滚动 ICIR | `factor_ic/result/*_daily.json.gz` 每日 IC 序列 |

**适用场景**:
- 等权:因子数量少、无先验 IC 信息
- ICIR 静态:已知历史 ICIR,全样本静态
- 滚动 ICIR 动态:因子有效性随时间变化
- IC 静态:简化版 ICIR,忽略波动

---

## M6. 静态权重计算 + 反向映射

**What**:静态权重 (equal/icir/ic) 通过 `WeightEngine.calculate()` 在加权前一次性计算,保存为固定字典 `{factor_name: weight}`。计算时需通过**反向映射**把列名 (如 `rsi_6`) 映射回因子名 (如 `rsi`) 以查 IC 结果。

**Why**:IC 结果按因子名索引,但加权输入是列名,必须建立映射。硬编码后缀 (`_5`、`_6`) 不可扩展。

**How**:

```python
class WeightMethodBase(ABC):
    FACTOR_NAME_TO_COL_MAP = {
        'rsi': 'rsi_6',
        'volume_ratio': 'volume_ratio_5',
        'kdj_j': 'kdj_j_9',
        'bollinger_pb': 'bollinger_pb_20',
        'turnover_surge': 'turnover_surge_5',
        'main_inflow_ratio': 'main_inflow_ratio_1d',
    }
    COL_TO_FACTOR_NAME_MAP = {v: k for k, v in FACTOR_NAME_TO_COL_MAP.items()}

    # 预编译正则 (M20)
    _FACTOR_SUFFIX_PATTERN = re.compile(r'(.+)_(?:\d+[a-z]?|\d+)$')

    def _get_factor_name_from_col(self, col: str) -> str:
        if col in self.COL_TO_FACTOR_NAME_MAP:
            return self.COL_TO_FACTOR_NAME_MAP[col]
        match = self._FACTOR_SUFFIX_PATTERN.match(col)  # 贪婪 (M20)
        if match:
            return match.group(1)
        return col  # 最终回退原列名
```

**Don't**:

```python
# ❌ 硬编码后缀
factor_name = col.replace('_5', '').replace('_6', '')
```

---

## M7. 滚动 ICIR 时间轴计算

**What**:`rolling_icir_weight` 必须**直接在时间轴上**滚动计算,**禁止按 `asset` 分组**。

**Why**:
- IC 是每日截面相关性,同一日所有股票 IC 值相同
- 按 asset 分组是多余的 (所有股票 IC 序列相同),且语义错误
- 滚动应在时间序列上做

**How**:

```python
# 时间轴上滚动
ic_series = ic_df.set_index('date')['ic'].sort_index()

min_periods = max(1, self.window // 3)  # 避免 window=1 时为 0
rolling_mean = ic_series.rolling(window=self.window, min_periods=min_periods).mean()
rolling_std = ic_series.rolling(window=self.window, min_periods=min_periods).std(ddof=0)  # M53
rolling_icir = rolling_mean / rolling_std.replace(0, np.nan)
```

**Don't**:

```python
# ❌ 按 asset 分组,逻辑错误
factor_df.groupby('asset')[ic_col].transform(
    lambda x: x.rolling(window).mean() / x.rolling(window).std()
)
```

---

## M8. 向量化加权实现

**What**:加权用 `DataFrame.multiply(weight_vector, axis=1).sum(axis=1)` 一次完成,禁止逐列循环 `composite + factor_df[col] * weight`。

**Why**:循环 O(n) 次拼接,向量化是单次矩阵运算,性能差距显著。

**How**:

```python
def _apply_weights(
    self, factor_df: pd.DataFrame, factor_cols: List[str],
    weights: Dict[str, float], logger, method_name: str = "加权",
) -> pd.Series:
    std_cols = [f'{col}_std' for col in factor_cols]
    weight_values = np.array([weights[col] for col in factor_cols])
    std_df = factor_df[std_cols]
    composite = std_df.multiply(weight_values, axis=1).sum(axis=1)
    return composite
```

**注意**:静态权重适用此方式;动态权重 (滚动 ICIR) 需配合 M29 (NaN 动态权重归一化)。

---

# C. 标准化

## M9. 每日截面标准化

**What**:加权前对**每日每个因子**做截面标准化:`factor_std = (factor - μ) / σ`。

**Why**:不同因子值范围悬殊 (RSI 0-100, Volume_Ratio 0.1-5),未标准化会让高值因子主导组合。

**How**:在 `composite_runner` 中统一处理,生成 `<col>_std` 列。

---

## M10. 标准化列名接口约定 (`_std` 后缀)

**What**:`standardize_factors` 输入原始列名 (`factor_cols=['rsi_6']`),输出新增 `_std` 后缀列 (`rsi_6_std`)。`WeightEngine.calculate()` 接收**原始** `factor_cols`,**内部自动转换**为 `_std` 列。

**Why**:用户视角传因子名简洁;内部转换让标准化对调用方透明。**这不是 bug**,是设计约定。

**How**:

```python
class EqualWeightMethod(WeightMethodBase):
    def calculate(self, factor_df, factor_cols, ...):
        std_cols = [f'{col}_std' for col in factor_cols]  # 内部转换
        composite = factor_df[std_cols[0]] * weight
```

**维护提醒**:不要在调用方预先转换列名,也不要修改 `WeightEngine.calculate()` 接口。

---

## M11. 标准化 NaN 处理 (单样本返回 NaN)

**What**:截面标准化时:
1. 原始 NaN → 标准化后保持 NaN
2. 单样本场景 (count ≤ 1) → 返回 NaN (样本标准差未定义),并记录 warning
3. **不要**用 `if x.std() > 0 else 0` 把单样本组置 0

**Why**:
- `x.std(ddof=1)` 单样本返回 NaN (不是 0)
- 条件 `x.std() > 0` 对 NaN 返回 False → 整组被置 0
- 单样本结果置 0 在统计上是错的;返回 NaN 才符合语义

**How**:

```python
# 检查有效值数量
daily_stats = factor_df.groupby('date')[col].agg(['mean', 'std', 'count'])
low_count_mask = daily_stats['count'] <= 1
if low_count_mask.any():
    logger.warning(
        "因子 %s 在 %d 个日期有效值 <=1,标准化结果将为 NaN: %s",
        col, low_count_mask.sum(), list(daily_stats.index[low_count_mask])[:5],
    )

# 标准化 (x.std(ddof=1) 单样本返回 NaN 是正确的)
factor_df[std_col] = factor_df.groupby('date')[col].transform(
    lambda x: (x - x.mean()) / x.std() if x.std() > 0 else np.nan
)

# 原始 NaN 保持
factor_df.loc[factor_df[col].isna(), std_col] = np.nan
```

---

# D. 因子筛选

## M12. 无效因子判定标准 (5 个阈值)

**What**:因子无效判定:任一指标不满足即判无效。

| 指标 | 阈值 | 理由 |
|-----|------|------|
| \|ic_mean\| | < 0.03 | IC 均值太低,无预测能力 |
| p_value | > 0.05 | 统计不显著 |
| \|icir\| | < 0.15 | 稳定性差 (波动大) |
| \|monotonicity_corr\| | < 0.4 | 分层收益不单调 |
| long_short_return_annual | < 3% | 经济意义弱 (扣除双边成本 1% 后负收益) |

**Why** (阈值依据):
- ≥ 0.03:业界公认最低有效阈值
- p ≤ 0.05:统计显著性 95% 置信
- \|ICIR\| ≥ 0.15:IC 均值/标准差 ≥ 0.03/0.2 最低水平
- \|mono_corr\| ≥ 0.4:一般单调性标准 (0.5 强单调)
- LS ≥ 3%:扣除成本后仍正收益

**关键指标缺失** (`ic_mean` / `icir` 缺失):**视为无效**,不能视为"未达标"。

```python
ic_mean = ic_metrics.get('ic_mean', None)
if ic_mean is None:
    reasons.append("ic_mean 缺失 (数据不完整)")
elif abs(ic_mean) < thresholds['ic_mean_abs_min']:
    reasons.append(f"|ic_mean|={abs(ic_mean):.3f}<{thresholds['ic_mean_abs_min']}")
```

---

## M13. 高相关组识别用 Union-Find (并查集) + 迭代实现

**What**:识别高相关 (|corr| > 0.7) 因子组**必须用 Union-Find** (并查集) 算法,且 `find()` 用**迭代实现**避免大规模因子库栈溢出。

**Why**:
- 朴素"遍历 pair 合并到第一个组"会漏跨组合并 (A-B、B-C、C-D 可能产生 [A,B,C] + [D] 而非 [A,B,C,D])
- 递归 `find()` 在 10000+ 因子时栈溢出

**How**:

```python
parent = {name: name for name in factor_names}

def find(x: str) -> str:
    """迭代实现 + 路径压缩"""
    root = x
    while parent[root] != root:
        root = parent[root]
    # 路径压缩
    current = x
    while parent[current] != root:
        next_node = parent[current]
        parent[current] = root
        current = next_node
    return root

def union(x: str, y: str) -> None:
    rx, ry = find(x), find(y)
    if rx != ry:
        parent[rx] = ry

for (name_i, name_j, _) in high_corr_pairs:
    union(name_i, name_j)

# 按 root 分组
groups_dict = {}
for name in factor_names:
    groups_dict.setdefault(find(name), []).append(name)
groups = [g for g in groups_dict.values() if len(g) > 1]
```

---

## M14. 高相关组选择 - ICIR 缺失处理

**What**:高相关组内选 |ICIR| 最高的因子保留时,**ICIR 缺失的因子不参与比较**,不要默认为 0。

**Why**:默认为 0 会让"缺失"的因子可能被选中而真正高 ICIR 的被丢。

**How**:

```python
icir_values = {}
for factor_name in group:
    icir = ic_metrics.get('icir', None)
    icir_values[factor_name] = abs(icir) if icir is not None else None

valid_icir_values = {k: v for k, v in icir_values.items() if v is not None}

if not valid_icir_values:
    # 所有 ICIR 都缺失,无法比较,保留第一个
    best_factor = group[0]
    logger.warning("高相关组 %s 所有因子 icir 缺失,无法比较", group)
else:
    best_factor = max(valid_icir_values.keys(), key=lambda k: valid_icir_values[k])
```

---

## M15. 因子名匹配相关性矩阵

**What**:进入高相关组识别前,必须在入口校验所有因子名都在 `corr_matrix.index/columns` 中;不匹配的因子记录 warning 并跳过。

**How**:

```python
factor_names = list(valid_factors.keys())
missing_in_index = [n for n in factor_names if n not in corr_matrix.index]
missing_in_columns = [n for n in factor_names if n not in corr_matrix.columns]

if missing_in_index or missing_in_columns:
    logger.warning(
        "因子名与相关性矩阵不匹配: 缺失 index=%s, 缺失 columns=%s,跳过",
        missing_in_index[:5], missing_in_columns[:5],
    )
    factor_names = [n for n in factor_names
                    if n in corr_matrix.index and n in corr_matrix.columns]
    if not factor_names:
        logger.error("所有因子都不在相关性矩阵中,返回空组")
        return []
```

---

## M16. 筛选完整性标记

**What**:`select_factors` 返回结构必须含 `selection_complete: bool` 和 `selection_warnings: List[str]`,标记筛选是否完整 (例如 corr_matrix 缺失时跳过高相关筛选)。

**Why**:调用方需要知道筛选是否完整,以决定是否补充相关性矩阵重新筛选。

**返回结构**:

```json
{
  "selected": [...],
  "factor_cols": [...],
  "valid_count": 4,
  "total_count": 5,
  "invalid": {"kdj_j": ["|ic_mean|=0.015<0.03"]},
  "high_corr_dropped": {"turnover_surge": "与 volume_ratio 高相关 (0.99),ICIR 较低"},
  "nan_corr_pairs": [{"factor_a": "...", "factor_b": "...", "reason": "..."}],
  "unmapped_factors": [],
  "selection_complete": true,
  "selection_warnings": []
}
```

---

# E. 命名映射与正则

## M17. 因子名到列名映射表

**What**:`factor_list` (逻辑名,如 `rsi`) 和 `factor_cols` (数据列名,如 `rsi_6`) 通过 `FACTOR_NAME_TO_COL_MAP` 映射,定义在 `comprehensive_factor/common/factor_selector.py`。

**Why**:命名差异 (逻辑名不带参数,列名带参数) 导致 `auto_select` 无法直接对应数据列。

**How**:

```python
FACTOR_NAME_TO_COL_MAP = {
    'rsi': 'rsi_6',
    'volume_ratio': 'volume_ratio_5',
    'kdj_j': 'kdj_j_9',
    'bollinger_pb': 'bollinger_pb_20',
    'turnover_surge': 'turnover_surge_5',
    'main_inflow_ratio': 'main_inflow_ratio_1d',
}
```

**未映射因子**:用因子名作列名 (兼容),记录到 `unmapped_factors` 并 warning;调用方决定是否终止。

**后续改进**:从配置文件读取 (`config/factor_mapping.yaml`)、支持动态参数 (`rsi_{window}`)、支持版本管理 (`rsi_v2_6`)。

---

## M18. 因子名反向映射 (列名 → 因子名)

**What**:见 M6,反向映射 `COL_TO_FACTOR_NAME_MAP` 由 `FACTOR_NAME_TO_COL_MAP` 反转得到。

**优先级**:精确映射 → 正则提取 (M20) → 原列名兜底。

---

## M19. 文件名正则解析 + 跳过非标准

**What**:解析 IC/回测文件名时:
1. 用预编译正则 (类属性) 提取因子名
2. 不匹配时**跳过文件**并 warning,**不要**用 replace 回退 (可能复现已修复的解析 bug)
3. 单文件读取失败 (JSON 错误/编码错误/IO 错误) 也跳过该文件

**How**:

```python
# 文件顶部
import re

class FactorLoader:
    # 预编译,一次编译多次使用
    IC_PATTERN = re.compile(rf'^ic_(.+?)_{return_period}_analysis_result$')
    BACKTEST_PATTERN = re.compile(r'^(.+?)_layered_backtest$')

    def load_all_factor_results(self, ic_result_dir):
        all_factors = {}
        for ic_file in ic_result_dir.glob('*.json'):
            match = self.IC_PATTERN.match(ic_file.stem)
            if not match:
                logger.warning(
                    "文件名格式非标准,跳过: %s (期望格式: ic_<因子>_%s_analysis_result.json)",
                    ic_file.name, self.return_period,
                )
                continue

            try:
                with open(ic_file, 'r', encoding='utf-8') as f:
                    ic_data = json.load(f)
                all_factors[match.group(1)] = ...
            except (json.JSONDecodeError, UnicodeDecodeError, IOError) as e:
                logger.error(
                    "文件加载失败,跳过: %s,错误类型: %s,详情: %s",
                    ic_file.name, type(e).__name__, str(e),
                )
                continue
```

---

## M20. 正则贪婪匹配 (避免误截断)

**What**:从列名提取因子名的正则用**贪婪匹配** `(.+)_(?:\d+[a-z]?|\d+)$`,不用非贪婪 `(.+?)_\d+[a-z]?$`。

**Why**:非贪婪会把 `main_inflow_ratio_1d` 截断为 `main_inflow` (应是 `main_inflow_ratio`)。

**How**:

```python
# ✅ 贪婪
_FACTOR_SUFFIX_PATTERN = re.compile(r'(.+)_(?:\d+[a-z]?|\d+)$')
# main_inflow_ratio_1d → main_inflow_ratio
```

**Don't**:

```python
# ❌ 非贪婪
_FACTOR_SUFFIX_PATTERN = re.compile(r'(.+?)_\d+[a-z]?$')
# main_inflow_ratio_1d → main_inflow (错误)
```

---

# F. 数据加载与校验

## M21. 数据来源

**What**:

| 数据类型 | 来源路径 | 公共函数 |
|---------|---------|---------|
| 因子原始值 | `data_fetchers/result/factor_ic_data.json.gz` | `factor_loader.load_factor_values()` |
| IC 统计结果 | `factor_ic/result/*.json` | `factor_loader.load_ic_results()` |
| IC 每日序列 | `factor_ic/result/*_daily.json.gz` | `factor_loader.load_ic_daily()` |

---

## M22. 必需列校验 (date / asset / factor_cols)

**What**:加载因子数据后立即校验:`date`、`asset` 列存在 + `factor_cols` 列存在 + 输出必需列。错误信息包含**缺失列名 + 当前列列表**。

**Why**:列不存在时直接 `df['col']` 抛 KeyError,消息只含列名,不友好;延迟到 calculate 暴露浪费计算。

**How**:

```python
required_cols = ['date', 'asset']
for col in required_cols:
    if col not in factor_df.columns:
        raise ValueError(
            f"factor_df 缺少必需列 '{col}',当前列: {list(factor_df.columns)}"
        )

for col in factor_cols:
    if col not in factor_df.columns:
        raise ValueError(
            f"factor_df 缺少因子列 '{col}',当前列: {list(factor_df.columns)}"
        )
```

**校验时机**:数据加载后立即校验 → standardize 之后校验 `_std` 列 → 保存前校验输出列。

---

## M23. 返回值解包校验

**What**:`load_factor_return_data` 等跨模块函数返回值在解包前必须校验:**None 检查 → tuple/len 检查 → 解包后值校验**。

**How**:

```python
result = load_factor_return_data(data_source=data_source, logger=logger)

# 1. None
if result is None:
    raise ValueError("函数返回 None,期望 (factor_df, return_df)")

# 2. 类型 + 数量
if not isinstance(result, tuple) or len(result) != 2:
    raise ValueError(
        f"返回值数量错误,期望 2 个,实际: {len(result) if isinstance(result, tuple) else '非tuple'}"
    )

# 3. 解包后值
_, return_df = result
if return_df is None:
    raise ValueError("return_df 为 None,数据加载失败")
if 'forward_return_1d' not in return_df.columns:
    raise ValueError(
        f"return_df 缺少 'forward_return_1d' 列,当前列: {list(return_df.columns)}"
    )
```

---

## M24. DataFrame 空值三类检查

**What**:DataFrame 空值检查必须区分**三类**:`None`、空 DataFrame (有列名但 0 行)、缺失列。

| 类型 | 检查 | 说明 |
|------|------|------|
| None | `df is None` | 数据加载失败 |
| 空 DataFrame | `len(df) == 0` | 有列名但无数据 (**静默问题**) |
| 缺失列 | `col not in df.columns` | 列不存在 |

**Why**:只检查 None 和列存在会漏空 DataFrame,导致回测引擎静默产生空结果。

**How**:

```python
if return_df is None:
    raise ValueError("return_df 为 None,收益数据加载失败")

if len(return_df) == 0:
    raise ValueError(
        "return_df 为空 DataFrame (有列名但无数据),无法进行分层回测\n"
        "可能原因:1. 缓存数据文件为空;2. 数据加载异常"
    )

if 'forward_return_1d' not in return_df.columns:
    raise ValueError("return_df 缺少 'forward_return_1d' 列")
```

---

## M25. 数据类型校验 (date / asset 必须 str)

**What**:`load_factor_values` 返回 DataFrame 前必须校验 `date` 和 `asset` 列是 `str` 类型,不一致时抛 TypeError 含可能原因。

**Why**:类型不一致导致 `groupby('date')` 失败或 `merge on='asset'` 失败。

**How**:

```python
factor_df = pd.DataFrame(factor_data['data'])

if len(factor_df) > 0:
    first_date = factor_df['date'].iloc[0]
    if not isinstance(first_date, str):
        raise TypeError(
            f"date 列应为 str,实际为 {type(first_date).__name__}\n"
            f"首行值: {first_date}\n"
            "可能原因: JSON 文件中 date 字段为数字而非字符串"
        )

    first_asset = factor_df['asset'].iloc[0]
    if not isinstance(first_asset, str):
        raise TypeError(...)
```

---

## M26. 数据一致性强校验 (不静默截断)

**What**:加载 IC 每日序列时,若 `dates` 与 `ic_values` 数量不一致,**抛 ValueError 而非静默截断**。

**Why**:截断会让错位数据对齐到错误日期,产生静默错误的回测结果。

**How**:

```python
if len(dates) != len(ic_values):
    raise ValueError(
        f"日期与 IC 值数量不一致: dates={len(dates)}, ic_values={len(ic_values)}\n"
        "可能原因:\n"
        "  1. IC 计算过程中部分日期缺失数据\n"
        "  2. JSON 文件写入异常\n"
        "建议:重新运行 IC 分析脚本生成完整的 IC 结果文件"
    )
```

---

# G. NaN 与权重处理

## M27. NaN 相关性显式处理 (不静默跳过)

**What**:计算两两相关性时,NaN 相关系数 (缺失值过多导致) 必须**显式记录到 `nan_corr_pairs`** 并 warning,不要静默跳过 (因为 `abs(NaN) > 0.7` 返回 False)。

**How**:

```python
if pd.isna(corr_val):
    nan_corr_pairs.append({
        'factor_a': factor_cols[i],
        'factor_b': factor_cols[j],
        'reason': 'NaN (缺失值过多导致相关性无法计算)',
    })
    logger.warning(
        "相关性 NaN 警告: %s vs %s,缺失值过多",
        factor_cols[i], factor_cols[j],
    )
    continue
```

**处理建议**:覆盖率 < 60% 的因子标记为无效,提前从筛选中排除。

---

## M28. composite_factor 全 NaN 检查

**What**:计算综合因子后必须检查 `composite_factor.notna().sum() == 0`,全 NaN 时抛 ValueError 含三类可能原因。

**Why**:全 NaN 时分层回测无法 percentile 排序,会静默产生空结果。

**How**:

```python
factor_df['composite_factor'] = composite_factor

valid_composite_count = factor_df['composite_factor'].notna().sum()
if valid_composite_count == 0:
    raise ValueError(
        "composite_factor 全为 NaN,无法进行分层回测\n"
        "可能原因:\n"
        "  1. 所有因子值缺失 (检查 factor_cols 是否正确)\n"
        "  2. 标准化后全为 NaN (检查原始数据覆盖率)\n"
        "  3. 加权计算异常 (检查 weight_engine.calculate())"
    )
```

---

## M29. NaN 动态权重归一化 (避免权重稀释)

**What**:`_apply_weights` 中遇到因子值缺失时,必须**按行重新归一化权重**,确保有效因子的权重之和始终为 1,不让缺失列被 `sum(axis=1)` 当作 0 稀释结果。

**Why**:3 个因子各 1/3 权重,若因子 1 缺失,默认 `sum(skipna=True)` 会得到 `0 + factor2*1/3 + factor3*1/3 = 2/3 < 1`,综合因子被稀释。

**How**:

```python
# 识别有效值位置
valid_mask = ~std_df.isna()

# 每行的有效权重之和
valid_weight_sum = (valid_mask.multiply(weight_values, axis=1)).sum(axis=1)

# 加权后归一化
weighted_df = std_df.multiply(weight_values, axis=1)
composite = weighted_df.divide(
    valid_weight_sum.replace(0, np.nan), axis=0
).sum(axis=1, skipna=False)

# 全 NaN 行保持 NaN
composite = composite.where(valid_weight_sum > 0, np.nan)
```

**Don't**:

```python
# ❌ 默认 sum(skipna=True) 把 NaN 计 0
composite = std_df.multiply(weight_values, axis=1).sum(axis=1)
```

---

## M30. 除零保护 + ICIR 缺失回退等权

**What**:`ICIRWeightMethod` / `ICWeightMethod` 计算权重时,若 `total_icir == 0` (所有因子 ICIR 绝对值都为 0) 必须**回退等权**并 warning。

**Why**:除零会抛 ZeroDivisionError;回退等权是合理降级。

**How**:

```python
total_icir = sum(icir_values.values())
if total_icir == 0:
    logger.warning("所有因子 ICIR 绝对值均为 0,回退等权")
    n_factors = len(factor_cols)
    return {col: 1.0 / n_factors for col in factor_cols}

weights = {col: icir_values[col] / total_icir for col in factor_cols}
```

**触发条件**:仅当所有因子 ICIR 绝对值为 0 时触发 (若部分缺失被置 1.0,total > 0 不触发)。

---

# H. 防御性校验

## M31. 校验前置 (列校验在 calculate 之前)

**What**:`_std` 列等中间产物校验**必须前置**到 calculate 之前,不要等到 calculate 失败再暴露。

**Why**:列不存在时 calculate 已执行但结果无效,浪费计算 + 暴露慢。

**校验顺序**:

```
加载因子数据 → 标准化因子 → 【列校验】 → 计算相关性 → 计算综合因子 → ...
```

**How**:

```python
# 4. 标准化
factor_df = standardize_factors(factor_df, factor_cols, logger)

# 校验前置:在 calculate 之前
required_cols = ['date', 'asset']
for col in required_cols:
    if col not in factor_df.columns:
        raise ValueError(f"factor_df 缺少必需列 '{col}'")

for col in factor_cols:
    if col not in factor_df.columns:
        raise ValueError(f"factor_df 缺少因子列 '{col}'")

std_cols = [f'{col}_std' for col in factor_cols]
for col in std_cols:
    if col not in factor_df.columns:
        raise ValueError(f"factor_df 缺少标准化因子列 '{col}'")

# 5. 计算相关性 (校验通过后才执行)
```

---

## M32. 函数前置条件校验 (依赖列必须显式校验)

**What**:函数依赖其他函数生成的列时,必须在入口校验存在;错误信息含**可能原因 + 正确调用顺序**。

**How**:

```python
def calc_factor_correlation(factor_df, factor_cols, logger):
    std_cols = [f'{col}_std' for col in factor_cols]

    for std_col in std_cols:
        if std_col not in factor_df.columns:
            raise ValueError(
                f"factor_df 缺少标准化因子列 '{std_col}'\n"
                "可能原因:\n"
                "  1. 调用方未先调用 standardize_factors()\n"
                "  2. standardize_factors 参数 factor_cols 与本函数不一致\n"
                "调用顺序: load_factor_values → standardize_factors → calc_factor_correlation"
            )
```

---

## M33. 父类 validate() 调用

**What**:`CompositeLayerConfig.validate()` 必须显式调用 `super().validate()`,确保父类 `LayerConfigBase` 的基础校验 (n_layers ≥ 2、factor_direction 合法、layer 编号范围) 不被遗漏。

**How**:

```python
def validate(self) -> None:
    super().validate()  # 父类基础校验

    if not self.factor_list:
        raise ValueError("factor_list 不能为空")
    if len(self.factor_list) != len(self.factor_cols):
        raise ValueError("factor_list 与 factor_cols 数量不一致")
```

---

## M34. 校验层级 (入口统一,子类信任)

**What**:`_validate_factor_cols` 只在 `WeightEngine.calculate` (入口层) 调用一次,子类 `calculate` 信任已校验,**不重复校验**。

**How**:

```python
# WeightEngine.calculate (入口层)
def calculate(self, factor_df, factor_cols, ...):
    self.method._validate_factor_cols(factor_cols, self.logger)  # 入口统一校验
    return self.method.calculate(factor_df, factor_cols, ...)

# 子类 calculate (实现层)
def calculate(self, factor_df, factor_cols, ...):
    # 不校验,信任入口
    weights = self.get_weights(factor_cols, ic_results)
    return self._apply_weights(...)
```

**校验位置原则**:基类公共方法在 `WeightEngine.__init__` 或 `calculate` 入口校验一次;子类信任。

---

# I. 缺失与字段回退

## M35. 缺失因子返回列表

**What**:`load_ic_results` / `load_ic_daily` 静默跳过缺失因子时,必须返回 `Tuple[结果, missing_factors]`,让调用方决定如何处理 (warning / 报错 / 回退等权)。

**Why**:静默跳过让下游 WeightEngine 在因子缺失时 KeyError。

**How**:

```python
def load_ic_results(factor_names, ...) -> Tuple[Dict[str, Dict], List[str]]:
    ic_results = {}
    missing_factors = []
    for factor_name in factor_names:
        if not ic_file.exists():
            missing_factors.append(factor_name)
            continue
        ic_results[factor_name] = ...
    return ic_results, missing_factors

# 调用方
ic_results, missing_ic_factors = load_ic_results(...)
if missing_ic_factors:
    logger.warning("部分因子 IC 结果缺失,权重计算将回退等权: %s", missing_ic_factors)
```

---

## M36. 字段回退验证

**What**:从 `ic_metrics` 回退到 `summary` 时必须验证 `summary` 含必需字段 (`ic_mean`、`icir`),缺失时 warning。

**Why**:回退字段结构可能不同,缺失关键字段下游会出错。

**How**:

```python
REQUIRED_IC_FIELDS = ['ic_mean', 'icir']

if 'ic_metrics' in ic_data:
    extracted_data = ic_data['ic_metrics']
elif 'summary' in ic_data:
    extracted_data = ic_data['summary']
    missing_fields = [f for f in REQUIRED_IC_FIELDS if f not in extracted_data]
    if missing_fields:
        logger.warning("summary 字段缺失必需字段: %s", missing_fields)
```

---

## M37. 死代码移除 (识别 + 移除标准)

**What**:未被下游使用的列/参数是死代码,必须**移除**而非保留 (尤其当代码有健壮性问题时,移除优于修复)。

**识别方法**:
1. 搜索列名/函数名使用 (`grep`)
2. 确认计算逻辑有问题且无下游需求 → 移除

**How**:

```python
# 原代码 (死代码 + TypeError 风险)
daily_df = pd.DataFrame({
    'date': dates,
    'ic': ic_values,
    'ic_sign': [1 if v > 0 else -1 if v < 0 else 0 for v in ic_values],  # 死代码 + v 可能 None
})

# 修复后:移除 ic_sign
ic_values_cleaned = [v if v is not None else np.nan for v in ic_values]
daily_df = pd.DataFrame({
    'date': dates,
    'ic': ic_values_cleaned,
})
```

**注释说明移除原因**:防止后续重复添加。

---

# J. 动态权重与时间轴

## M38. 动态权重保存为元信息

**What**:`rolling_icir_weight` 等动态权重**不保存静态值**,只保存"动态标记" + 元信息;后续从 daily 输出中提取每日权重。

**Why**:静态权重和动态权重语义不同,保存动态权重的"等权默认值"会误导用户。

**How** (见 M39 权重元信息分离):

```python
if weight_method == 'rolling_icir_weight':
    weights = {}  # 不保存静态值
    weight_meta = {
        'is_dynamic': True,
        'method': 'rolling_icir_weight',
        'window': 60,
        'note': '权重每日动态计算,不保存静态值',
    }
else:
    weights = weight_engine.get_weights(factor_cols, ic_results)
    weight_meta = {'is_dynamic': False, 'method': weight_method}
```

---

## M39. 权重元信息与权重数据分离

**What**:权重字典 (`weights`) 只放因子权重数据 `{factor_name: weight}`,元信息 (动态标记、方法、窗口等) 放独立的 `weight_meta` 字段,**不要**用 `_dynamic` / `_method` 等 `_` 前缀键混入 `weights`。

**Why**:字典字段语义清晰;序列化无需特殊处理 `_` 前缀;下游解析简单。

**输出结构**:

```json
{
  "weights": {"rsi": 0.4, "volume_ratio": 0.6},
  "weight_meta": {
    "is_dynamic": false,
    "method": "icir_weight"
  }
}
```

---

## M40. 滚动 ICIR 时间轴计算 (见 M7)

**重申**:`rolling_icir_weight` **直接在时间轴上** rolling,**禁止按 `asset` 分组**(已在 M7 详述)。

---

# K. CLI 与异常

## M41. CLI 退出码显式设置

**What**:`main()` 必须**显式 `sys.exit(0)`** 成功和 **`sys.exit(N)`** 失败,不依赖 `raise` 的隐式退出码。

**Why**:`raise` 后进程退出码取决于调用方 shell 行为,不确定;显式退出码让 shell 能正确识别执行状态。

**退出码语义**:

| 码 | 含义 |
|----|------|
| 0 | 成功 |
| 1 | 异常终止 (通用) |
| 2 | 参数错误 (可选) |

**How**:

```python
try:
    result = run_composite_backtest(...)
    logger.info("回测完成,退出码 0")
    sys.exit(0)
except Exception as e:
    logger.error("回测执行异常: %s", e)
    logger.error("退出码 1 (异常终止)")
    sys.exit(1)
```

---

## M42. CLI 异常堆栈保留

**What**:CLI 异常处理用 `logger.exception()` 或 `traceback.format_exc()` 保留完整堆栈,**不要**只 `logger.error("异常: %s", e)`。

**Why**:只打异常消息丢失堆栈,无法定位发生位置。

**How**:

```python
# 方式 1: traceback.format_exc()
import traceback
try:
    result = run_composite_backtest(...)
except Exception as e:
    logger.error("回测执行异常: %s", e)
    logger.error("异常堆栈:\n%s", traceback.format_exc())
    sys.exit(1)

# 方式 2: logger.exception() (推荐,简洁)
try:
    result = run_composite_backtest(...)
except Exception as e:
    logger.exception("回测执行异常")  # 自动附加堆栈
    sys.exit(1)
```

---

## M43. CLI 最小导入原则

**What**:CLI 脚本只导入实际使用的模块,**不导入** `create_cli_entrypoint` 内部已封装的依赖 (如 `run_composite_backtest`、`logger`)。

**Why**:多余导入误导读者,违反最小导入原则。

**How**:

```python
# ✅ 只导入实际使用
from comprehensive_factor.common.composite_runner import (
    create_cli_entrypoint, CompositeLayerConfig,
)
from comprehensive_factor.common.data_loader import DEFAULT_DATA_SOURCE
# 不导入 logger (create_cli_entrypoint 内部处理)
```

**Don't**:

```python
# ❌ 导入但未直接使用
from comprehensive_factor.common.composite_runner import (
    run_composite_backtest,  # 未直接调用,被封装
    create_cli_entrypoint, CompositeLayerConfig,
)
from comprehensive_factor.common.logger_config import get_logger
logger = get_logger(__name__)  # 未使用
```

---

## M44. 文件读取异常处理 (单文件不影响整体)

**What**:多文件加载场景下,单文件读取异常 (JSON / 编码 / IO) 必须捕获并跳过,继续加载其他文件;**不要**让单文件损坏导致整体失败。

**捕获异常类型**:`json.JSONDecodeError`、`UnicodeDecodeError`、`IOError`。

**How** (见 M19 代码示例)。

---

## M45. logger 参数传递与使用

**What**:
1. 函数签名新增 `logger` 参数 → **所有调用方必须传入**
2. 子函数需要日志 → 传递父函数的 logger
3. logger 参数接收 + 初始化后 → 必须在关键分支**实际使用** (debug/warning/error),否则是死代码

**How**:

```python
def validate_factor(..., logger: Optional[logging.Logger] = None):
    if logger is None:
        logger = get_logger(__name__)

    if ic_mean is None:
        reasons.append("ic_mean 缺失")
        logger.debug("因子 %s: ic_mean 缺失", factor_name)  # 必须使用
    elif abs(ic_mean) < thresholds['ic_mean_abs_min']:
        reasons.append(f"|ic_mean|={abs(ic_mean):.3f}<...")
        logger.debug("因子 %s: |ic_mean|=%.3f 不达标", factor_name, abs(ic_mean))

# 调用方传入
is_valid, reasons = validate_factor(
    factor_name, factor_data, thresholds, logger
)
```

**日志级别选择**:

| 情况 | 级别 |
|------|------|
| 正常检查过程 | debug |
| 指标缺失/不达标 | debug |
| 因子无效 | warning (调用方处理) |

---

# L. Config 设计

## M46. Config 配置规范 + 继承

**What**:Config 子类只定义**因子特有参数** + **覆盖父类默认值**,**禁止重复定义**父类已有字段。

**Why**:父类已定义的字段重复定义违反 DRY,改一处易遗漏另一处。

**继承层级**:

| 字段 | 定义层级 |
|------|---------|
| `n_layers` / `factor_direction` / `long_layers` / `short_layers` / `trade_cost_rate` / `min_stocks_per_layer` | `LayerConfigBase` |
| `factor_list` / `factor_cols` / `rolling_window` | `CompositeLayerConfig` |
| 子类特有参数 | 子类 |

**How**:

```python
@dataclass
class ICIRWeightLayerConfig(CompositeLayerConfig):
    """ICIR 加权配置

    继承 CompositeLayerConfig:
    - factor_list: ['rsi', 'volume_ratio']
    - factor_cols: ['rsi_6', 'volume_ratio_5']
    """
    # 只定义本类特有 / 覆盖父类默认值
    n_layers: int = 5
    factor_direction: str = 'negative'
    long_layers: List[int] = field(default_factory=lambda: [1, 2])  # M48
    short_layers: List[int] = field(default_factory=lambda: [4, 5])
```

---

## M47. Config 默认值单一数据源

**What**:CLI 入口从 **Config 实例**读取默认值,**禁止**重复硬编码与 Config 相同的配置。

**Why**:两处配置必然漂移,Config 改了 CLI 未同步会静默错误。

**How**:

```python
_default_config = EqualWeightLayerConfig()

main = create_cli_entrypoint(
    factor_list=_default_config.factor_list,   # 从 Config 读
    factor_cols=_default_config.factor_cols,
    config_class=EqualWeightLayerConfig,
)
```

**Don't**:

```python
main = create_cli_entrypoint(
    factor_list=['rsi', 'volume_ratio'],       # ❌ 与 Config 重复
    factor_cols=['rsi_6', 'volume_ratio_5'],
    config_class=EqualWeightLayerConfig,
)
```

---

## M48. List 类型必须用 `field(default_factory)`

**What**:dataclass 中 `List` / `Dict` 等可变类型默认值**必须**用 `field(default_factory=lambda: [...])`,**不能**直接 `= [1, 2]`。

**Why**:Python dataclass 禁止可变默认值 (所有实例会共享同一个 list 对象,修改一个影响所有)。

**How**:

```python
long_layers: List[int] = field(default_factory=lambda: [1, 2])  # ✓
layer_names: Dict[str, str] = field(default_factory=lambda: {'1': '低值层'})  # ✓
```

**Don't**:

```python
long_layers: List[int] = [1, 2]  # ❌ ValueError
```

---

# M. 代码风格与性能

## M49. 模块级 sys.path.insert 去重

**What**:`sys.path.insert` 必须先检查路径不存在,避免多次 import 时重复污染。

**How**:

```python
_project_root = str(Path(__file__).parent.parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)
```

---

## M50. PEP 8 import 位置 + 函数入口类型统一

**What**:
1. 所有 import 在文件顶部,按"标准库 → 第三方 → 本地"分组 (PEP 8)
2. 路径参数 (`output_dir` / `cache_dir`) 签名声明 `Union[str, Path, None]`,**入口统一转 Path**,后续无需重复 `Path()` 转换

**How** (类型统一):

```python
def run_composite_backtest(
    output_dir: Union[str, Path, None] = None,  # 支持两种类型
):
    if output_dir is not None:
        output_dir = Path(output_dir)  # 入口统一

    # 后续直接用 Path 方法
    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = output_dir / 'xxx.json'
```

---

## M51. set 替代 list (性能)

**What**:嵌套循环中需要频繁 `in` 检查 + 删除时,用 `set` 替代 `list`,把 O(n²) 降为 O(n)。

| 操作 | list | set |
|------|------|-----|
| `in` 检查 | O(n) | O(1) |
| remove/discard | O(n) | O(1) |
| 嵌套循环 | O(n²) | O(n) |

**How**:

```python
selected_factors_set = set(valid_factors.keys())

for group in high_corr_groups:
    for factor_name in group:
        if factor_name != best_factor:
            if factor_name in selected_factors_set:    # O(1)
                selected_factors_set.discard(factor_name)  # O(1)

return list(selected_factors_set), dropped_factors
```

**适用**:因子数量可能增长到 100+ 的场景。

---

## M52. lambda 延迟绑定避免 (用 Series.map 替代)

**What**:循环中 `lambda` 捕获循环变量是**延迟绑定**的,所有 lambda 最终引用循环最后一次的值。要么用 `Series.map(Series)` 替代 lambda,要么用默认参数固定。

**Why**:`map` 是惰性的,循环结束后所有 lambda 中的变量指向最后一次赋值。

**How** (推荐:用 `Series.map(Series)` 替代 lambda):

```python
for col in factor_cols:
    if col in rolling_icir_dict and len(rolling_icir_dict[col]) > 0:
        rolling_icir_series = rolling_icir_dict[col]
        # Series.map(Series) 直接索引查找,无 lambda
        factor_df[f'{col}_rolling_icir'] = factor_df['date_sorted'].map(rolling_icir_series)
```

**Don't**:

```python
# ❌ lambda 延迟绑定
for col in factor_cols:
    rolling_icir_series = rolling_icir_dict[col]
    factor_df[f'{col}_rolling_icir'] = factor_df['date_sorted'].map(
        lambda d: rolling_icir_series.get(pd.Timestamp(d), np.nan)  # 全部 → 最后一个 factor
    )
```

**备选** (用默认参数固定,不推荐):

```python
lambda d, series=rolling_icir_series: series.get(pd.Timestamp(d), np.nan)
```

---

## M53. rolling_std 用 ddof=0 + min_periods 保护

**What**:`rolling().std()` 在样本数少时不稳定,必须:
1. 用 `ddof=0` (总体标准差),不用默认 `ddof=1`
2. `min_periods` 用 `max(1, window // 3)` 避免 `window=1` 时为 0

**How**:

```python
min_periods = max(1, self.window // 3)
rolling_std = ic_series.rolling(
    window=self.window, min_periods=min_periods
).std(ddof=0)
```

---

## M54. 常量替代硬编码

**What**:阈值/默认值/魔数等用模块级或类级常量替代,**不硬编码**到代码字符串里。

**How**:

```python
class WeightEngine:
    DEFAULT_WINDOW = 60
    WINDOW_VALID_METHODS = ['rolling_icir_weight']

    def __init__(self, weight_method, window=DEFAULT_WINDOW, ...):
        # window 对非滚动方式无效时 warning (M55)
        if window != self.DEFAULT_WINDOW and weight_method not in self.WINDOW_VALID_METHODS:
            self.logger.warning(
                "window=%d 参数对 %s 无效 (默认 %d)",
                window, weight_method, self.DEFAULT_WINDOW,
            )
```

**Don't**:

```python
if window != 60 and weight_method not in self.WINDOW_VALID_METHODS:  # ❌ 硬编码 60
    self.logger.warning("window=%d 参数无效...", window)
```

---

## M55. 无效参数警告 + thresholds 入口统一 + 条件冗余 + 注释数据来源

**What** (4 个小规则合并):

### 55.1 无效参数警告
对方法不支持的参数 (如 `window` 对非滚动方法) 给出 warning,不要静默忽略。已在 M54 示例。

### 55.2 thresholds 入口统一处理
可选参数 `thresholds=None` 在入口统一替换为默认值,后续无需反复判断 None。

```python
def select_factors(..., thresholds: Optional[Dict] = None, ...):
    if thresholds is None:
        thresholds = DEFAULT_THRESHOLDS  # 入口统一

    # 后续直接用
    identify_high_corr_groups(threshold=thresholds['high_corr_threshold'], ...)
```

### 55.3 条件冗余删除
`not factor_cols or len(factor_cols) == 0` 中 `or len(...) == 0` 完全冗余 (`not []` 已涵盖)。

```python
# ✓ 简洁
if not factor_cols:
    raise ValueError(...)

# ❌ 冗余
if not factor_cols or len(factor_cols) == 0:
    raise ValueError(...)
```

### 55.4 注释数据来源
注释中引用统计值 (ICIR / IC 均值) 必须**说明来源 + 时间范围**,不要硬编码裸数字。

```python
"""获取 ICIR 权重

实际 ICIR 值 (见 factor_ic/result/*.json):  ← 来源说明
- volume_ratio: ICIR=0.3058 (2024-03-27~2026-05-14)
- rsi: ICIR=0.2519

注: 权重动态计算,如需最新值请查看 IC 结果文件
"""
```

**Don't**:

```python
"""
- 反向因子 ICIR 为负 (如 volume_ratio ICIR ≈ -1.97)  ← ❌ 无来源,数据可能过时
"""
```

| 场景 | 要求 | 示例 |
|------|------|------|
| 引用统计值 | 数据来源 + 时间范围 | `ICIR=0.3058 (见 factor_ic/result/*.json, 2024-03~2026-05)` |
| 引用阈值 | 业界标准/统计依据 | `|ic_mean|>0.03 (业界公认最低有效阈值)` |
| 引用公式 | 语义而非只写公式 | `ICIR = IC 均值/IC 标准差,反映预测稳定性` |

---

## 更新记录

| 版本 | 日期 | 主要变更 |
|------|------|---------|
| v2.4 | 2026-06-03 | run_pipeline.py v1.3: 新增 Stage 5 权重选择 + Stage 6 股票选股；generate_factor_summary_report.py v2.2: 新增第七、八部分 |
| v2.3 | 2026-06-03 | stock_selector.py v1.1: 添加版本历史、模块级 logger、完善类型注解 |
| v2.2 | 2026-06-03 | Step 7 股票选股流程图 + stock_selector.py v1.0 开发完成 |
| v2.1 | 2026-06-03 | weight_selector.py v1.3: print→logger迁移、类型注解完善、异常处理优化（JSONDecodeError捕获、EPSILON精度容差） |
| v2.0 | 2026-06-03 | 大重构:65 章节去重合并为 55 条 M 编号规则,按 13 类别 (A-M) 组织;统一 W/W/H/D/W/V 框架;加目录索引;精简更新记录 |
| v1.16 | 2026-05-26 | `--auto_select` CLI 参数 (自动因子筛选);修复 `FACTOR_NAME_TO_COL_MAP` 列名映射 |
| v1.10-v1.15 | 2026-05-24 | 累积补充:滚动 ICIR 时间轴 / 因子名反向映射 / 除零保护 / 向量化加权 / lambda 延迟绑定 / NaN 动态权重归一化 / 正则预编译与贪婪 / 校验层级 / Config 继承 / 注释数据来源 |
| v1.7-v1.9 | 2026-05-24 | Union-Find 算法 + 迭代实现 / 正则因子名解析 / 关键指标缺失判定 / ICIR 缺失处理 / 文件读取异常 / set 替代 list / import 位置 / thresholds 入口统一 |
| v1.1-v1.6 | 2026-05-24 | 公共入口防御性编程 / 因子名映射 / 动态权重保存 / NaN 相关性 / 模块级代码 / 函数入口类型统一 / composite NaN 检查 / CLI 异常退出码 / 校验前置 / DataFrame 空值 / 权重元信息分离 / 标准化 NaN / 数据类型/一致性校验 / 死代码移除 |
| v1.0 | 2026-05-24 | 初始设计:目录结构、脚本命名、加权方式、公共模块、输出规范 |

---

## 引用说明

本文档定义 `comprehensive_factor/` 目录下综合因子计算脚本的开发规范。

**相关文档**:
- 项目级规范:`PROJECT.md` (目录结构、开发检查清单)
- 上游 IC 计算:`factor_ic/MODULE.md`
- 下游分层回测:`backtest/MODULE.md`
- 流程文档:`comprehensive_factor/docs/<脚本>_flow.md`
- 测试用例:`comprehensive_factor/test_cases/<脚本>_test_cases.py`
- 公共模块:`comprehensive_factor/common/` 各模块

---

*最后更新: 2026-06-03*

