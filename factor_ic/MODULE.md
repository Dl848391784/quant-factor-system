# factor_ic 模块规范

> 本文档定义 factor_ic/ 目录下 IC 计算脚本的开发规范。
> 创建时间: 2026-05-19
> 版本: v1.0

---

## 概述

factor_ic 模块负责计算各类因子的 IC（Information Coefficient）值，用于评估因子对未来收益的预测能力。

**模块定位：**
- 输入：来自 data_fetchers 的缓存数据（cache/factor_data/）
- 输出：IC 分析结果（factor_ic/result/）
- 依赖：不自行拉取数据，只处理已缓存数据

---

## factor_ic/ 目录规范

以下规范**仅适用于 `factor_ic/` 目录**，其他目录另有规范。

### 脚本命名

**格式：** `ic_<因子名>_<收益周期>.py`

| 收益周期 | 后缀 | 含义 |
|---------|------|------|
| T+1 收益 | `1d` | 次日收益率 |
| T+3 收益 | `3d` | 3日后收益率 |
| T+5 收益 | `5d` | 5日后收益率 |

**示例：**
```
ic_rsi_1d.py        # RSI因子，T+1收益
ic_rsi_3d.py        # RSI因子，T+3收益
ic_volume_ratio_1d.py  # 量比因子，T+1收益
```

**命名约定：**
- 因子名使用小写+下划线：`rsi`、`kdj_j`、`bollinger_pb`、`volume_ratio`
- 一个因子可有多个收益周期版本（1d、3d、5d等）

---

### 数据依赖

**数据来源：** 所有因子计算脚本的数据必须来自 `data_fetchers/` 目录的拉取脚本。

**禁止行为：**
- ❌ 在 factor_ic 脚本中直接调用外部 API 拉取数据
- ❌ 在 factor_ic 脚本中定义数据拉取逻辑

**正确做法：**
```python
# 因子计算脚本只读取缓存数据
factor_df = pd.read_csv('cache/factor_data/rsi/rsi_1d.csv')
# 计算 IC，不涉及数据拉取
```

---

### 输出目录规范

**输出路径：** `factor_ic/result/ic_<因子名>_<周期>_analysis_result.json`

**示例：**
```
factor_ic/result/ic_rsi_1d_analysis_result.json
factor_ic/result/ic_bollinger_pb_1d_analysis_result.json
factor_ic/result/ic_volume_ratio_1d_analysis_result.json
```

**禁止行为：**
- ❌ 输出到其他目录（如 cache/、backtest/）
- ❌ 使用非标准命名格式

---

## IC 计算规范

### IC 值计算

**定义：** IC = Spearman秩相关系数（因子值与未来收益的秩相关性）

**公式：**
```
IC(d) = spearman_correlation(factor_values_on_day_d, returns_on_day_d+period)
```

**选择 Spearman 的原因：**
1. 对异常值不敏感（Rank变换后）
2. 不要求线性关系
3. 适用于非线性因子（如技术指标）

---

### IC 统计指标

**必须输出的统计指标：**

| 字段 | 含义 | 计算方式 |
|------|------|---------|
| ic_mean | IC均值 | 所有有效日期IC值的算术平均 |
| ic_std | IC标准差 | 所有有效日期IC值的标准差 |
| ICIR | 信息比率 | abs(ic_mean) / ic_std |
| t_stat | t统计量 | ic_mean * sqrt(valid_days) / ic_std |
| p_value | 显著性p值 | 双尾t检验的p值 |
| valid_days | 有效IC天数 | 实际参与统计的日期数 |
| total_days | 总天数 | 原始缓存覆盖的日期数 |

**注意：**
- ICIR 使用 `abs(ic_mean)`，因为负IC和正IC同等重要
- p < 0.05 表示统计显著（与 |t| > 1.96 等价）

---

### 打印信息规范

**核心原则：** 打印信息必须准确反映实际计算结果，不得误导用户。

**完成信息规范：**
```
# ✓ 正确：同时显示有效天数和原始天数
print(f"完成！共计算 {valid_days} 天有效 IC 数据（原始数据 {total_days} 天）")

# ❌ 禁止：只显示原始天数，误导用户认为所有日期都有有效IC
print(f"完成！共计算 {total_days} 天 IC 数据")  # 错误！
```

**字段选择规则：**
| 场景 | 正确字段 | 禁止字段 |
|------|---------|---------|
| "共计算 X 天 IC 数据" | `valid_days` | `total_days` |
| "原始数据覆盖 X 天" | `total_days` | `valid_days` |
| 统计检验样本量 | `valid_days` | `total_days` |

**语义说明：**
- `valid_days`：实际计算出有效IC的天数（参与统计检验）
- `total_days`：原始缓存覆盖的日期数（可能包含NaN/跳过）
- 差距原因：计算周期等待（如布林带前N-1天NaN）、股票数不足跳过

---

### 因子方向判断规范

**核心原则：** 因子方向必须根据实际IC测试结果确定，不能根据因子类型假设。

**判断规则：**

| IC特征 | 因子方向 | 说明 |
|--------|---------|------|
| ic_mean > 0.03 且 p < 0.05 | 正向因子 | 高因子值预测高收益 |
| ic_mean < -0.03 且 p < 0.05 | 反向因子 | 高因子值预测低收益 |
| |t| < 1.96 或 p > 0.05 | 无效因子 | 无预测能力 |

**禁止行为：**
- ❌ 根据因子类型假设方向（如"RSI超买区应该是反向因子"）
- ❌ 不做IC测试就预设 factor_direction 参数

**正确做法：**
```python
# 先运行IC计算脚本，根据 ic_mean 和 p_value 确定方向
python factor_ic/ic_rsi_1d.py
# 查看结果中的 ic_mean 和 p_value
# 根据结果设置分层回测的 factor_direction 参数
```

---

### 输出格式规范

**JSON输出结构：**
```json
{
  "metadata": {
    "factor_name": "rsi",
    "return_period": "1d",
    "calculation_date": "2026-05-19T10:30:00",
    "data_source": "cache/factor_data/rsi/rsi_1d.csv",
    "total_days": 545,
    "valid_days": 513,
    "avg_stocks_per_day": 4235.2,
    "avg_stocks_period": {
      "start": "2024-01-01",
      "end": "2024-12-31",
      "description": "平均每日有效股票数统计范围"
    }
  },
  "statistics": {
    "ic_mean": -0.0348,
    "ic_std": 0.1377,
    "ICIR": 0.252,
    "t_stat": -5.99,
    "p_value": 3.2e-9,
    "significance": "significant"
  },
  "daily_ic": [
    {"date": "2024-01-02", "ic": -0.0412, "stocks_count": 4210},
    ...
  ],
  "period": {
    "start": "2024-01-01",
    "end": "2024-12-31",
    "description": "IC计算覆盖日期范围"
  }
}
```

**字段说明：**

| 字段路径 | 类型 | 必填 | 说明 |
|---------|------|------|------|
| metadata.factor_name | str | ✓ | 因子名称（小写） |
| metadata.return_period | str | ✓ | 收益周期（如 "1d"） |
| metadata.calculation_date | str | ✓ | 计算时间（ISO格式） |
| metadata.data_source | str | ✓ | 数据来源路径 |
| metadata.total_days | int | ✓ | 原始缓存日期数 |
| metadata.valid_days | int | ✓ | 有效IC天数 |
| metadata.avg_stocks_per_day | float | ✓ | 平均每日有效股票数 |
| metadata.avg_stocks_period | object | ✓ | 口径范围说明 |
| statistics.ic_mean | float | ✓ | IC均值 |
| statistics.ic_std | float | ✓ | IC标准差 |
| statistics.ICIR | float | ✓ | 信息比率 |
| statistics.t_stat | float | ✓ | t统计量 |
| statistics.p_value | float | ✓ | 显著性p值 |
| statistics.significance | str | ✓ | 显著性判断（"significant"/"not_significant"） |
| daily_ic | array | ✓ | 每日IC值数组 |
| daily_ic[].date | str | ✓ | 日期 |
| daily_ic[].ic | float | ✓ | 当日IC值 |
| daily_ic[].stocks_count | int | ✓ | 当日有效股票数 |
| period.start | str | ✓ | 覆盖起始日期 |
| period.end | str | ✓ | 覆盖结束日期 |

---

## 增量更新规范

### 增量模式定义

**增量模式 = 追加新日期的IC值，保留历史IC值，重新计算统计指标**

**公式：**
```
增量模式：新IC值 + 历史IC值 → 重算统计指标
全量模式：全部日期 → 全新计算
```

**触发条件：**
- 缓存存在 → 尝试增量更新
- 缓存不存在 → 执行全量计算
- 命令行参数 `--force-full` → 强制全量计算

---

### 增量判断流程

```
┌─────────────────────────────────────────────────────┐
│ 1. 检查缓存文件是否存在                               │
│    ├─ 不存在 → full 模式（全量计算）                   │
│    └─ 存在 → 读取 existing_dates                      │
└─────────────────────────────────────────────────────┘
          ↓
┌─────────────────────────────────────────────────────┐
│ 2. 读取因子数据，获取 factor_df['date'].unique()      │
│    → new_dates                                         │
└─────────────────────────────────────────────────────┘
          ↓
┌─────────────────────────────────────────────────────┐
│ 3. 比较 existing_dates vs new_dates                   │
│    ├─ new_dates ⊆ existing_dates → skip 模式         │
│    │   （无需更新，返回缓存）                          │
│    ├─ new_dates == existing_dates → skip 模式        │
│    │   （数据完全一致）                                │
│    └─ new_dates 有缺失日期 → incremental 模式        │
│    │   （计算缺失日期IC，合并后重算统计）              │
└─────────────────────────────────────────────────────┘
          ↓
┌─────────────────────────────────────────────────────┐
│ 4. incremental 模式执行                                │
│    ├─ 只计算 missing_dates 的IC值                     │
│    ├─ 合并：新IC值 + 历史IC值                          │
│    ├─ 重算统计指标（ic_mean, ic_std, ICIR等）         │
│    └─ 更新 metadata（valid_days, total_days等）      │
└─────────────────────────────────────────────────────┘
```

---

### 缺失日期诊断规范

**核心原则：** 增量更新时必须诊断缺失日期的数据覆盖情况，区分"数据源无数据"和"缓存缺失"。

**诊断场景：**

| 场景 | 诊断信息 | 用户行动 |
|------|---------|---------|
| 缺失日期不在缓存范围 | `[警告] N 个缺失日期不在当前因子缓存范围` | 检查数据源日期范围，或执行全量重算 |
| 缺失日期在缓存范围但无有效数据 | `[诊断] 缺失日期在缓存范围内，但筛选后无有效数据` | 检查股票过滤条件 |
| 所有缺失日期均不在缓存范围 | `[诊断] 无法增量更新` | 执行全量重算 (force_full=True) |

**正确实现：**
```python
# 筛选缺失日期的数据
missing_set = set(missing_dates)
factor_df_new = factor_df_full[factor_df_full['date'].isin(missing_set)]

# 诊断：检查缺失日期的数据覆盖情况
dates_in_cache = set(factor_df_full['date'].unique())
dates_not_in_cache = missing_set - dates_in_cache

if dates_not_in_cache:
    print(f"  [警告] {len(dates_not_in_cache)} 个缺失日期不在当前因子缓存范围")
    print(f"  [警告] 可能原因: 数据源未覆盖这些日期，或因子缓存已过期清理")
    examples = sorted(dates_not_in_cache)[:5]
    print(f"  [警告] 示例日期: {examples}")

if factor_df_new.empty:
    if dates_not_in_cache:
        print("  [诊断] 所有缺失日期均不在当前缓存范围，无法增量更新")
        print("  [建议] 检查数据源日期范围，或执行全量重算 (force_full=True)")
    else:
        print("  [诊断] 缺失日期在缓存范围内，但筛选后无有效数据")
    print("  - 跳过增量计算，返回现有缓存")
    return existing_data
```

---

## 参数传递规范

### 默认参数常量

**必须定义的默认参数：**
```python
DEFAULT_MIN_STOCKS = 10  # 每日最少股票数阈值
DEFAULT_IC_THRESHOLD = 0.03  # IC显著性阈值
DEFAULT_P_THRESHOLD = 0.05  # p值显著性阈值
```

**参数传递方式：**
```python
def calculate_ic(factor_df: pd.DataFrame, 
                 return_period: str,
                 min_stocks: int = DEFAULT_MIN_STOCKS) -> dict:
    # 参数通过函数签名传递，不使用全局变量
    pass
```

**禁止行为：**
- ❌ 在函数内部硬编码参数值（如 `min_stocks = 10`）
- ❌ 使用全局变量传递参数

---

## 异常处理规范

### 异常类型保留

**原则：** 异常类型必须准确反映错误原因，不随意包装。

| 异常类型 | 使用场景 | 是否包装 |
|---------|---------|---------|
| ValueError | 数据验证错误（缺失列、格式错误） | ❌ 直接 raise |
| RuntimeError | 基础设施错误（API失败、网络异常） | ✓ 可包装 |
| KeyError | 必需字段缺失 | ❌ 直接 raise |
| TypeError | 类型错误 | ❌ 直接 raise |

**正确示例：**
```python
if 'rsi' not in factor_df.columns:
    raise ValueError(f"因子数据缺少必需列 'rsi'，现有列: {list(factor_df.columns)}")
```

**禁止行为：**
```python
# ❌ 禁止：ValueError包装为RuntimeError
try:
    validate_data(factor_df)
except ValueError as e:
    raise RuntimeError(f"数据验证失败: {e}")  # 错误！
```

---

## 日期类型一致性规范

### 日期格式断言

**强制格式：** 所有日期字符串必须为 `YYYY-MM-DD` 格式。

**必须添加的断言：**
```python
import re

DATE_FORMAT_PATTERN = re.compile(r'^\d{4}-\d{2}-\d{2}$')

def validate_date_format(date_str: str) -> None:
    # 验证日期格式为 YYYY-MM-DD
    if not DATE_FORMAT_PATTERN.match(date_str):
        raise ValueError(f"日期格式错误: '{date_str}'，期望 YYYY-MM-DD")

# 在使用日期前调用
for date in dates:
    validate_date_format(date)
```

**应用场景：**
1. 读取缓存数据时，验证 date 列格式
2. 读取现有IC结果时，验证 existing_dates 格式
3. 生成 period.start/end 时，确保格式一致

**禁止行为：**
- ❌ 依赖字符串比较的隐式约定（如 `"2024-01-01" < "2024-02-01"`）
- ❌ 不验证格式就使用 min/max 比较日期

---

## 输入验证规范

### 列存在检查

**必须验证的列：**
```python
REQUIRED_COLUMNS = ['date', 'symbol', 'factor_value', 'future_return']

def validate_columns(df: pd.DataFrame) -> None:
    # 验证必需列存在
    missing = [col for col in REQUIRED_COLUMNS if col not in df.columns]
    if missing:
        available = list(df.columns)
        raise ValueError(
            f"数据缺少必需列: {missing}\n"
            f"可用列: {available}"
        )
```

---

## 公共函数复用规范

### 必须复用的公共函数

**factor_ic/common/ 目录下的公共函数：**

| 函数 | 文件 | 用途 |
|------|------|------|
| calculate_rank_ic | reverse_rank_ic.py | 计算Spearman秩IC |
| validate_date_format | （待创建） | 验证日期格式 |
| calculate_ic_statistics | （待创建） | 计算统计指标 |

**复用规范：**
```python
from factor_ic.common.reverse_rank_ic import calculate_rank_ic

# ❌ 禁止：在脚本中重新实现
def my_calculate_ic(df):
    return df.corr(method='spearman')  # 错误！

# ✓ 正确：复用公共函数
ic = calculate_rank_ic(df['factor_value'], df['future_return'])
```

---

### 数据传递规范（calculate_ic_with_direction_verification）

**核心原则：** calculate_ic_with_direction_verification 接收未合并的 factor_df 和 return_df，内部负责合并。

**函数设计意图：**

```
calculate_ic_with_direction_verification(factor_df, return_df, ...)
    ↓
内部执行：
    1. 验证列存在性
    2. 选择必要列 [date, asset, factor_col] 和 [date, asset, return_col]
    3. 执行 pd.merge(..., how='inner')
    4. dropna 处理
    5. 计算每日 IC
```

**禁止行为：**
```python
# ❌ 禁止：在调用前合并数据（死代码）
merged_df = pd.merge(factor_df, return_df, on=['date', 'asset'], how='inner')
result = calculate_ic_with_direction_verification(factor_df, return_df, ...)
# merged_df 未被使用，是死代码
```

**正确做法:**
```python
# ✓ 正确：直接传递未合并的数据
factor_df = factor_df[['date', 'asset', 'factor_col']].copy()
result = calculate_ic_with_direction_verification(factor_df, return_df, ...)
# 合并在函数内部完成
```

**为何禁止提前合并:**
1. 函数设计意图明确：接收未合并数据,内部负责合并
2. 提前合并的 merged_df 无法传递给函数（函数需要两个独立 DataFrame）

---

## 增量更新返回数据规范

### _incremental_update 返回数据结构
**核心原则:** _incremental_update 返回数据必须包含 `rolling_ic_mean` 字段, 与 `_full_recalculate` 返回值结构一致.

**必须包含的字段:**
```python
{
    'factor_name': str,
    'calculation_date': str,
    'period': {'start': str, 'end': str},
    'ic_metrics': {
        'ic_mean': float,
        'ic_std': float,
        'icir': float
    },
    'sample_stats': {
        'total_days': int,
        'valid_days': int,
        'avg_stocks_per_day': int,
        'avg_stocks_period': dict
    },
    'statistical_significance': {
        't_stat': float,
        'p_value': float,
        'is_significant': bool
    },
    'factor_direction': dict,
    'economic_significance': dict,
    'dates': list,
    'ic_values': list,
    'rolling_ic_mean': list,  # 必须！用于绘制滚动IC均值趋势图
    'positive_ratio': float,
    'n_assets': int,
    'summary': dict,
    'update_mode': str,
    'incremental_days': int
}
```

**为何必须包含 rolling_ic_mean:**
1. 增量更新合并历史数据和新增数据后,需要重新计算滚动IC均值
2. 前端依赖该字段绘制滚动IC均值趋势图
3. 缺失该字段会导致前端功能异常

4. 数据结构不一致会破坏保存数据的完整性

---

## 流程文档规范

## 流程文档规范

### 流程文档创建时机

**强制规则：** 新建 `ic_xxx.py` 脚本时，必须同步创建 `docs/ic_xxx_flow.md`。

**禁止行为：**
- ❌ 只写代码不写流程文档
- ❌ 流程文档滞后于代码修改

---

### 流程文档位置

**路径：** `factor_ic/docs/ic_<因子名>_<周期>_flow.md`

**示例：**
```
factor_ic/docs/ic_rsi_1d_flow.md
factor_ic/docs/ic_bollinger_pb_1d_flow.md
factor_ic/docs/ic_volume_ratio_1d_flow.md
```

---

### 流程文档时间标注

**必须包含的时间标注：**
```markdown
> 生成时间: 2026-05-19 10:30
> 实测数据时间: 2026-05-19 10:35
> 版本: v1.2
> 更新内容: 添加增量模式说明，修复日期类型转换
```

**更新规则：**
- 代码修改 → 版本号递增（v1.0 → v1.1）
- 规范变更 → 更新内容说明
- 每次更新 → 同步更新所有时间标注

---

## NaN 处理规范

**核心原则：** NaN → None 转换应在数据生成阶段完成。

**正确实现：**
```python
# 使用 pd.isna(v) 检查 NaN
# NaN → None（语义转换："无有效数据"）
rolling_ic_mean = [
    round(v, 6) if not pd.isna(v) else None
    for v in rolling_mean.values
]
```

**为何必须在数据生成阶段处理：**
1. 语义一致性：None 表示"无有效数据"，nan 是浮点数运算结果
2. 增量路径用 None 填充无效日期，全量路径用 NaN 填充不满 min_periods 的日期
3. 若延迟到 convert_to_native_types 处理，语义不一致
4. JSON 序列化时 None → null，标准 JSON 不支持 nan

**两条路径一致性要求：**
```python
# ✓ 全量路径（calculate_daily_ic_series）：数据生成阶段处理
rolling_mean = ic_series.rolling(window=20, min_periods=10).mean()
rolling_ic_mean = [
    round(v, 6) if not pd.isna(v) else None
    for v in rolling_mean.values
]

# ✓ 增量路径（_incremental_update）：数据生成阶段处理（必须与全量路径一致）
rolling_ic_mean_series = ic_series.rolling(window=20, min_periods=10).mean()
rolling_ic_mean = [
    round(v, 6) if not pd.isna(v) else None
    for v in rolling_ic_mean_series.values
]

# ❌ 禁止：延迟到 convert_to_native_types 处理
rolling_ic_mean = ic_series.rolling(window=20, min_periods=10).mean()  # pd.Series
# 延迟到 json.dump 时才通过 convert_to_native_types 转换（违反规范）
```

---

## ic_series 排序规范

**核心原则：** ic_series.index 必须按日期升序排列。

**显式排序：**
```python
ic_series = ic_series.sort_index()
```

**防御性校验：**
```python
if dates != sorted(dates):
    raise RuntimeError("dates 未按升序排列")
```

**为何必须显式排序:**
1. rolling 计算按位置顺序，而非 index 值顺序
2. 若 ic_series.index 乱序 → dates 与 rolling_ic_mean 对应错误
3. pandas groupby 默认 sort=True，但不应依赖隐式行为
4. 版本升级风险: pandas 可能改变默认行为
5. 增量路径合并后可能乱序

6. **两条路径一致性:**
   - 全量路径: `load_data_from_cache` 第124行显式转换为字符串
   - 增量路径: JSON 缓存存储字符串，读取后直接使用
   - 当前一致，但依赖隐式实现，缺乏规范保障

---

## ic_series.index 类型规范

### 核心原则
**ic_series.index 必须是字符串类型（格式为 "YYYY-MM-DD"），禁止使用 datetime 对象。**

### 类型约束
```python
# ✓ 正确: index 为字符串 "YYYY-MM-DD"
ic_series.index  # 类型: pandas.Index with dtype='object' (字符串)
# 示例: Index(['2024-01-01', '2024-01-02', ...], dtype='object')

```

**禁止行为:**
```python
# ❌ 禁止: index 为 datetime 对象
ic_series.index  # 类型: pandas.DatetimeIndex
# 问题:
# 1. rolling 计算无法处理 datetime index（可能报错）
# 2. JSON 序列化失败（datetime 无法直接序列化）
# 3. 日期比较逻辑不一致（datetime vs 字符串）
```

### 全量路径实现
**`load_data_from_cache` 负责显式转换:**
```python
# 第124行: 显式转换为字符串格式
factor_df['date'] = date_series.dt.strftime('%Y-%m-%d')
```

**`calculate_daily_ic_series` 返回时:**
```python
# 第376行: 转换为 JSON 友好格式
dates = [str(d) for d in ic_series.index]
```

### 增量路径实现
**`_incremental_update` 直接使用字符串 index:**
```python
# 第660行: 直接使用 valid_dates (字符串)
ic_series = pd.Series(valid_ic, index=valid_dates)
```

### 一致性验证
**两条路径必须确保 index 类型一致（字符串 "YYYY-MM-DD"）：**

| 路径 | index 来源 | 类型 | 保障机制 |
|------|------------|------|----------|
| 全量 | `load_data_from_cache` 第124行转换 | 字符串 | 显式转换规范 |
| 增量 | `existing_dates` (JSON 缓存) + `new_dates` (strftime) | 字符串 | JSON 缓存格式规范 |

---

## 函数参数设计规范

### 核心原则
**函数签名不应有冗余参数，每个参数必须有实际用途。**

### 冗余参数判定规则
```python
# ❌ 禁止：参数永远不被传入，永远使用默认值
def calculate_daily_ic_series(
    factor_df,
    return_df,
    raw_metadata,
    min_stocks=10,
    period_start=None,  # 永远不传入
    period_end=None     # 永远不传入
):
    if period_start is None:  # 永远为 True
        period_start = str(factor_df['date'].min())

# ✓ 正确：删除冗余参数，直接使用已有数据
def calculate_daily_ic_series(
    factor_df,
    return_df,
    raw_metadata,
    min_stocks=10
):
    period_start = raw_metadata['period_start']  # 直接使用
```

### 设计原则
1. **参数必要性：** 每个参数必须被实际传入或有明确的默认值语义
2. **数据源优先：** 如果已有数据结构包含所需信息，应直接使用，不应添加额外参数
3. **语义一致性：** 参数语义应与数据源语义一致，不应混用不同来源的数据
4. **接口简洁：** 函数签名应尽可能简洁，避免不必要的复杂度

---

## period.start/end 语义规范

### 核心原则
**period.start/end 表示原始缓存范围（dropna 前），而非过滤后范围。**

### 语义定义

| 字段 | 来源 | 语义 | 示例 |
|------|------|------|------|
| `raw_metadata['period_start']` | 原始缓存 dropna 前 | 原始数据最小日期 | 2024-01-01 |
| `raw_metadata['period_end']` | 原始缓存 dropna 前 | 原始数据最大日期 | 2026-05-15 |
| `factor_df['date'].min()` | 过滤后数据 | 过滤后最小日期 | 2024-01-20 |
| `factor_df['date'].max()` | 过滤后数据 | 过滤后最大日期 | 2026-05-15 |

### 差异原因
```
原始缓存范围：2024-01-01 ~ 2026-05-15
dropna 后范围：2024-01-20 ~ 2026-05-15

差异：前19天布林带 NaN 被过滤
```

### 正确使用
```python
# ✓ 正确：使用 raw_metadata 表示原始缓存范围
period_start = raw_metadata['period_start']  # 2024-01-01
period_end = raw_metadata['period_end']      # 2026-05-15

# ❌ 禁止：使用 factor_df 表示原始缓存范围（语义错误）
period_start = str(factor_df['date'].min())  # 2024-01-20（错误！）
```

### 输出规范
**IC 计算结果的 period 字段应表示原始缓存范围：**
```json
{
  "period": {
    "start": "2024-01-01",  // 原始缓存最小日期
    "end": "2026-05-15"     // 原始缓存最大日期
  }
}
```

### total_days 使用规范
**核心原则：** total_days 直接使用 raw_metadata，不与过滤后数据做比较。

**禁止行为：**
```python
# ❌ 禁止：冗余的 max 比较
'total_days': max(raw_metadata.get('total_days', 0), factor_df_full['date'].nunique())

# 理由：
# 1. raw_metadata['total_days'] 表示原始缓存天数（dropna 前）
# 2. factor_df_full['date'].nunique() 表示过滤后天数（dropna 后）
# 3. 过滤后天数 ≤ 原始天数，max 永远返回原始天数
# 4. 冗余操作，增加代码复杂度
```

**正确实现：**
```python
# ✓ 正确：直接使用 raw_metadata
'total_days': raw_metadata.get('total_days', 0)  # 原始缓存天数
```

---

## 字典结构缩进规范

### 核心原则
**JSON 字典结构必须保持一致的缩进层级，缩进不一致会导致 IndentationError。**

### 缩进层级定义
```python
# ✓ 正确：多层级字典缩进
merged_data = {
    'factor_name': 'bollinger_pb_1d',      # 第1层：8空格
    'ic_metrics': {                        # 第1层：8空格
        'ic_mean': 0.05,                   # 第2层：12空格
        'ic_std': 0.15                     # 第2层：12空格
    },                                     # 第1层闭合：8空格
    'sample_stats': {                      # 第1层：8空格
        'total_days': 545                  # 第2层：12空格
    }                                      # 第1层闭合：8空格
}

# ❌ 禁止：缩进不一致（IndentationError）
merged_data = {
    'factor_name': 'bollinger_pb_1d',
    'ic_metrics': {
        'ic_mean': 0.05,
        'ic_std': 0.15
    },
'sample_stats': {  # ❌ 缺少缩进
    'total_days': 545
}
```

### 缩进规则
1. **第1层字段：** 8空格缩进（函数体内字典）
2. **第2层字段：** 12空格缩进（嵌套字典内）
3. **第3层字段：** 16空格缩进（三层嵌套）
4. **闭合括号：** 与同级字段对齐（同级缩进）

### 常见错误
```python
# ❌ 错误：字典字段缩进缺失
'sample_stats': {  # 应有8空格缩进

# ❌ 错误：嵌套字段缩进不一致
'icir': round(result['icir'], 4)  # 应有12空格缩进

# ✓ 正确：所有字段缩进一致
        'icir': round(result['icir'], 4)  # 12空格缩进
```

---

## 函数返回值契约规范

**核心原则:** 调用方必须校验返回值字段存在性。

---

## ic_metrics 字段规范

### 核心原则
**ic_metrics 字段结构在两条路径（全量/增量）中必须完全一致。**

### 字段定义

| 字段 | 类型 | 来源 | 用途 |
|------|------|------|------|
| `ic_mean` | float | `result['ic_mean']` | IC 均值（核心指标） |
| `ic_std` | float | `result['ic_std']` | IC 标准差 |
| `icir` | float | `result['icir']` | ICIR（信息系数比率） |
| `p_value` | float | `result['p_value']` | p 值（统计显著性） |
| `p_value_display` | str | `result['p_value_display']` | p 值显示格式（科学计数法或小数） |

### 正确实现（两条路径一致）
```python
# ✓ 全量路径（calculate_daily_ic_series）
'ic_metrics': {
    'ic_mean': round(result['ic_mean'], 6),
    'ic_std': round(result['ic_std'], 6),
    'icir': round(result['icir'], 4),
    'p_value': round(result['p_value'], 6),
    'p_value_display': result.get('p_value_display', str(round(result['p_value'], 6)))
}

# ✓ 增量路径（_incremental_update）：必须与全量路径完全一致
'ic_metrics': {
    'ic_mean': round(result['ic_mean'], 6),
    'ic_std': round(result['ic_std'], 6),
    'icir': round(result['icir'], 4),
    'p_value': round(result['p_value'], 6),
    'p_value_display': result.get('p_value_display', str(round(result['p_value'], 6)))
}

# ❌ 禁止：增量路径缺少字段
'ic_metrics': {
    'ic_mean': round(result['ic_mean'], 6),
    'ic_std': round(result['ic_std'], 6),
    'icir': round(result['icir'], 4)  # 缺少 p_value 和 p_value_display
}
```

### 下游依赖
**下游代码可能读取以下字段：**
```python
# 前端或分析代码
ic_mean = ic_data['ic_metrics']['ic_mean']
p_value = ic_data['ic_metrics']['p_value']  # 必须存在
p_value_display = ic_data['ic_metrics']['p_value_display']  # 必须存在
```

---

## factor_direction 字段规范

### 核心原则
**factor_direction 字段结构在两条路径（全量/增量）中必须完全一致。**

### 字段映射（原始字段名 → 输出字段名）

| 原始字段名（ic_calculator.py） | 输出字段名 | 类型 | 用途 |
|------------------------------|----------|------|------|
| `ic_mean_sign` | `direction` | str | 因子方向（'positive'/'negative'/'zero') |
| `ic_mean` | `ic_mean` | float | IC 均值 |
| `conclusion` | `conclusion` | str | 方向判断结论 |

### 正确实现（两条路径一致）
```python
# ✓ 全量路径（calculate_daily_ic_series）：重映射字段名
'factor_direction': {
    'direction': result['factor_direction']['ic_mean_sign'],
    'ic_mean': result['factor_direction']['ic_mean'],
    'conclusion': result['factor_direction']['conclusion']
}

# ✓ 增量路径（_incremental_update）：重映射字段名（必须与全量路径一致）
'factor_direction': {
    'direction': result['factor_direction']['ic_mean_sign'],
    'ic_mean': result['factor_direction']['ic_mean'],
    'conclusion': result['factor_direction']['conclusion']
}

# ❌ 禁止：直接透传原始字段名
'factor_direction': result['factor_direction']  # 字段名是 ic_mean_sign，不是 direction
```

---

## economic_significance 字段规范

### 核心原则
**economic_significance 字段结构在两条路径（全量/增量）中必须完全一致。**

### 字段映射（原始字段名 → 输出字段名）

| 原始字段名（ic_calculator.py） | 输出字段名 | 类型 | 用途 |
|------------------------------|----------|------|------|
| `level` | `ic_strength` | str | IC 强度（'strong'/'weak'/'none') |
| `abs_ic_mean` | `ic_mean_abs` | float | IC 均值绝对值 |
| `conclusion` | `conclusion` | str | 经济显著性判断结论 |

### 正确实现（两条路径一致）
```python
# ✓ 全量路径（calculate_daily_ic_series）：重映射字段名
'economic_significance': {
    'ic_strength': result['economic_significance']['level'],
    'ic_mean_abs': result['economic_significance']['abs_ic_mean'],
    'conclusion': result['economic_significance']['conclusion']
}

# ✓ 增量路径（_incremental_update）：重映射字段名（必须与全量路径一致）
'economic_significance': {
    'ic_strength': result['economic_significance']['level'],
    'ic_mean_abs': result['economic_significance']['abs_ic_mean'],
    'conclusion': result['economic_significance']['conclusion']
}

# ❌ 禁止：直接透传原始字段名
'economic_significance': result['economic_significance']  # 字段名是 level，不是 ic_strength
```

---

## statistical_significance 字段规范

### 核心原则
**statistical_significance 字段结构在两条路径中可直接透传（字段名一致）。**

### 字段定义（无需重映射）

| 字段名 | 类型 | 来源 | 用途 |
|--------|------|------|------|
| `is_significant` | bool | `result['statistical_significance']['is_significant']` | 统计显著性标志 |
| `p_value` | float | `result['statistical_significance']['p_value']` | p 值 |
| `p_value_display` | str | `result['statistical_significance']['p_value_display']` | p 值显示格式 |
| `t_stat` | float | `result['statistical_significance']['t_stat']` | t 统计量 |
| `conclusion` | str | `result['statistical_significance']['conclusion']` | 统计显著性判断结论 |

### 正确实现（两条路径一致）
```python
# ✓ 全量路径和增量路径：均可直接透传（字段名一致）
'statistical_significance': result['statistical_significance']
```

---

**校验示例:**
# 定义必需字段列表
required_fields = [
    'ic_series', 'ic_mean', 'ic_std', 'icir',
    'statistical_significance', 'factor_direction',
    'economic_significance', 'icir_stability',
    'ic_distribution_consistency', 'positive_ratio', 'summary'
]

# 检查缺失字段
missing_fields = [f for f in required_fields if f not in result]

# 若缺失字段 → 抛出 RuntimeError
if missing_fields:
    raise RuntimeError(
        f"calculate_ic_with_direction_verification 返回值缺少必需字段\n"
        f"缺失字段: {missing_fields}\n"
        f"问题定位: factor_ic/common/ic_calculator.py\n"
        f"期望字段: {required_fields}"
    )
```

**为何必须校验返回值字段：**
1. 直接下标访问 result['field'] 会抛出 KeyError
2. KeyError 错误信息无法判断问题模块
3. 函数返回值结构变更时，调用方静默失败
4. 校验后的 RuntimeError 包含：缺失字段列表、问题定位、期望字段列表

---

## 增量计算 None 处理规范

**核心原则：** 增量计算中 None（股票数不足）的处理必须与全量计算保持一致。

**None 语义定义：**

| None 来源 | 语义 | 是否存储 |
|----------|------|---------|
| `calculate_single_day_ic` 返回 None | 股票数 < min_stocks | **不存储**（过滤） |
| 全量计算中 ic_series.index | 只有有效 IC 日期 | 不含 None |
| 增量计算中 new_ic_values | 可能含 None | **过滤后存储** |

**正确实现：**
```python
# 合并数据时过滤 None
date_ic_map = {}
for date, ic in zip(existing_dates, existing_ic_values):
    if ic is not None:  # 兼容旧缓存：过滤可能存在的 None
        date_ic_map[date] = ic

for date, ic in zip(new_dates, new_ic_values):
    if ic is not None:  # 只写入有效 IC 值
        date_ic_map[date] = ic
```

---

## 全量/增量 IC 计算等价性规范

**核心原则：** 全量计算与增量计算必须使用同一核心函数（calculate_single_day_ic）。

**等价性验证三重保障机制：**

| 保障层 | 机制 | 说明 |
|-------|------|------|
| 第一层：代码架构 | 设计原则 | 全量/增量调用同一函数，无法独立演化 |
| 第二层：单元测试 | TestAlgorithmEquivalence | 验证单日期、多日期、边界情况等价性 |
| 第三层：文档规范 | Step 4.5 规范 | 修改核心函数时必须检查等价性 |

**禁止行为：**
```python
# ❌ 禁止：增量计算不使用 calculate_single_day_ic
for date in missing_dates:
    ic_value = scipy.stats.spearmanr(factor_values, return_values)[0]  # 错误！

# ✓ 正确：增量计算使用 calculate_single_day_ic
for date in missing_dates:
    ic_value = calculate_single_day_ic(
        daily_data,
        factor_col='rsi_6',
        return_col='forward_return',
        min_stocks=10
    )
```

---

## 旧缓存兼容性处理规范

**核心原则：** 增量计算读取现有缓存时，必须兼容旧版本缓存数据。

**问题背景：**
- v1.32 之前版本：ic_values 可能包含 None（未过滤股票数不足）
- 增量更新读取现有缓存 → existing_ic_values 可能包含 None

**兼容性处理：**
```python
# 合并数据时，existing 和 new 都过滤 None（语义一致）
for date, ic in zip(existing_dates, existing_ic_values):
    if ic is not None:  # 兼容旧缓存：过滤可能存在的 None
        date_ic_map[date] = ic
```

---

## 返回值标记规范

**核心原则：** 三种模式返回值必须标记 update_mode 字段。

**返回值标记设计：**

| 场景 | update_mode | 附加字段 | 调用方判断逻辑 |
|------|------------|---------|---------------|
| 正常 skip | `'skip'` | 无 | `update_mode == 'skip'` → 从缓存读取 |
| skip-fallback | `'full'` | `fallback_event` | `update_mode == 'full' && 'fallback_event' in result` → 意外触发全量 |
| 正常 incremental | `'incremental'` | `incremental_events` | `update_mode == 'incremental'` → 增量更新 |
| 正常 full | `'full'` | 无 | `update_mode == 'full' && 'fallback_event' not in result` → 正常全量 |

**为何必须标记返回值：**
1. mode='skip' 时读取缓存失败会 fallback 到全量计算
2. fallback 后返回值与正常全量计算返回值结构相同
3. 调用方无法区分来源
4. 若全量计算耗时很长，调用方毫不知情

---

## 错误信息格式规范

**核心原则：** 枚举类错误必须包含合法值列表。

**正确示例：**
```python
raise RuntimeError(
    f"未知模式: {mode}\n"
    f"合法值: ['skip', 'incremental', 'full']"
)
```

**错误信息对比：**

| 场景 | 未校验（KeyError） | 已校验（RuntimeError） |
|-----|-------------------|----------------------|
| 错误信息 | `KeyError: 'ic_mean'` | `缺少必需字段: ['ic_mean']\n问题定位: factor_ic/common/ic_calculator.py` |
| 问题定位 | 无法判断 | 明确模块路径 |
| 排查效率 | 低 | 高 |

---

## 字典构建规范

**核心原则：** 字段应集中定义在构建阶段，避免分散赋值。

**禁止行为：**
```python
# ❌ 禁止：分散赋值
result = {}
result['ic_mean'] = ic_mean
result['ic_std'] = ic_std
# ... 后面又赋值
result['update_mode'] = 'full'  # 分散，容易重复
```

**正确做法：**
```python
# ✓ 正确：集中定义
result = {
    'ic_mean': ic_mean,
    'ic_std': ic_std,
    'icir': icir,
    'update_mode': 'full',  # 集中定义
}
```

---

## 输出字段口径规范

**核心原则：** 统计字段必须明确口径范围。

**正确实现：**
```json
{
  "avg_stocks_per_day": 4235.2,
  "avg_stocks_period": {
    "start": "2024-01-01",
    "end": "2024-12-31",
    "description": "平均每日有效股票数统计范围"
  }
}
```

**为何必须明确口径：**
- avg_stocks_per_day 基于 dropna 后数据
- total_days 基于 dropna 前数据
- 口径不同导致数值差异，必须通过字段说明

---

## 代码维护同步检查规范

**核心原则：** 添加新代码后必须检查旧代码是否冗余。

**检查清单：**
```
□ 新增字段 → 检查是否有重复赋值
□ 新增函数 → 检查是否有类似功能函数可合并
□ 新增逻辑 → 检查是否有冗余分支
□ 新增参数 → 检查是否有硬编码值可替换
```

---

## 设计演进清理规范

**核心原则：** 新实现替代旧实现后，必须删除旧代码，禁止保留死代码。

---

## 技术指标参数规范

### 布林带 rolling 窗口参数

**核心原则：** min_periods 必须等于 window，遵循技术指标标准定义。

**布林带标准定义：**
```
布林带需要满 N 个周期的数据才能计算：
- Middle Band = SMA(Close, N)，需要 N 个数据点
- Upper/Lower Band = Middle + K × StdDev，标准差也需要 N 个数据点
- 前 N-1 个周期的布林带值应为 NaN（等待足够数据）
```

**正确实现：**
```python
# ✓ 正确：min_periods=n，遵循标准定义
factor_df['middle_band'] = factor_df.groupby('asset')['close'].transform(
    lambda x: x.rolling(window=n, min_periods=n).mean()
)
factor_df['std_dev'] = factor_df.groupby('asset')['close'].transform(
    lambda x: x.rolling(window=n, min_periods=n).std()
)
```

**禁止行为：**
```python
# ❌ 禁止：min_periods=1，违反标准定义
factor_df['middle_band'] = factor_df.groupby('asset')['close'].transform(
    lambda x: x.rolling(window=n, min_periods=1).mean()  # 错误！
)
factor_df['std_dev'] = factor_df.groupby('asset')['close'].transform(
    lambda x: x.rolling(window=n, min_periods=1).std()  # 错误！
)

# 问题：
# - 第1个数据点：std=NaN（单点无法计算样本标准差）
# - 第2-4个数据点：std有值（基于不足N个数据点）
# - 违反布林带"满N周期才计算"的标准定义
```

**为何 min_periods=n 是标准：**
1. 布林带业界定义：需要满 N 个周期才产生有效值
2. 技术分析软件（TradingView、MetaTrader）均采用此定义
3. min_periods=1 会在前 N-1 周期产生非标准值，误导分析
4. 前N-1周期的NaN表示"数据不足，暂不计算"，语义清晰

### 布林带标准差 ddof 参数

**核心原则：** 布林带标准差必须使用总体标准差（ddof=0），而非样本标准差（ddof=1）。

**布林带标准定义：**
```
布林带是对固定窗口内所有价格数据的标准差计算：
- Upper Band = Middle + K × StdDev(Close, N)
- StdDev = Population Standard Deviation（总体标准差）
- 公式：σ = sqrt(Σ(xi - μ)^2 / N)
- 不是对未知总体的样本估计，而是对固定窗口数据的完整统计
```

**正确实现：**
```python
# ✓ 正确：ddof=0，使用总体标准差
factor_df['std_dev'] = factor_df.groupby('asset')['close'].transform(
    lambda x: x.rolling(window=n, min_periods=n).std(ddof=0)
)
```

**禁止行为：**
```python
# ❌ 禁止：默认 ddof=1（样本标准差），系统性高估布林带宽度
factor_df['std_dev'] = factor_df.groupby('asset')['close'].transform(
    lambda x: x.rolling(window=n, min_periods=n).std()  # 默认 ddof=1，错误！
)

# 问题：
# - 样本标准差公式：σ_sample = sqrt(Σ(xi-μ)^2 / (N-1))
# - 总体标准差公式：σ_population = sqrt(Σ(xi-μ)^2 / N)
# - 偏差系数：σ_sample = σ_population × sqrt(N/(N-1))
# - 对于 N=20：偏差约 2.5%（sqrt(20/19) ≈ 1.025）
# - 结果：布林带宽度系统性高估，%B 值系统性偏小
```

**为何 ddof=0 是标准：**
1. 布林带定义：对固定窗口内所有价格数据的完整统计，非样本估计
2. TradingView、MetaTrader 等业界软件均使用总体标准差
3. Bollinger 本人定义：Population Standard Deviation
4. ddof=1 会系统性高估带宽，导致 %B 指标失真

---

## 浮点数等值比较规范

### 核心原则

**浮点数等值比较必须使用精度容差，禁止直接使用 == 比较。**

### 问题背景

```
浮点数运算精度问题：
- IEEE 754 浮点数无法精确表示某些数值
- 运算结果可能产生微小误差（如 1e-15）
- 直接 == 0 比较会漏判极小值
- 极小值作为除数会产生极端结果（如 1e15）
```

### 正确实现

```python
# ✓ 正确：使用精度容差判断
import numpy as np

EPSILON = 1e-10  # 浮点数精度容差

# 除零判断
diff = upper_band - lower_band
result = np.where(
    np.abs(diff) < EPSILON,  # 精度容差判断
    0.5,  # 默认值
    (close - lower_band) / diff
)
```

### 禁止行为

```python
# ❌ 禁止：直接 == 0 比较（浮点精度问题）
diff = upper_band - lower_band
result = np.where(
    diff == 0,  # 可能漏判 1e-15 等极小值
    0.5,
    (close - lower_band) / diff  # 可能产生极端值
)

# 问题示例：
# diff = 1e-15（浮点误差）
# diff == 0 → False（漏判）
# %B = 1.0 / 1e-15 = 1e15（极端值）
```

### 精度容差选择原则

```
| 场景 | 推荐容差 | 说明 |
|------|---------|------|
| 价格数据除零判断 | 1e-10 | 价格精度通常到小数点后2-4位 |
| 数值计算通用 | 1e-9 | 适合大多数浮点运算场景 |
| 高精度计算 | 1e-12 | 需要更高精度的特殊场景 |
```

### 适用场景

1. **布林带 %B 计算**：`diff = upper_band - lower_band` 除零判断
2. **RSI 计算**：`diff = max_gain - max_loss` 除零判断
3. **任何浮点数除法**：除数为运算结果时需精度容差判断

### 为何必须使用精度容差

1. IEEE 754 标准无法精确表示所有数值
2. 浮点运算累积误差可能导致极小值
3. 直接 == 比较会漏判，产生极端结果
4. 精度容差是业界标准做法（numpy、scipy 均采用）

---

## 增量路径 rolling_ic_mean 规范

### 核心原则

**增量路径 `rolling_ic_mean` 必须基于 `all_dates` 计算，与 `dates` 和 `ic_values` 长度完全一致。**

### 问题背景

```
增量路径数据合并流程：
1. existing_dates + existing_ic_values（来自缓存）
2. new_dates + new_ic_values（新计算）
3. 合并 → date_ic_map（过滤None）
4. all_dates = sorted(date_ic_map.keys())
5. all_ic_values = [date_ic_map[d] for d in all_dates]

关键问题：
- 若 rolling_ic_mean 基于 valid_dates（子集）计算
- len(rolling_ic_mean) = len(valid_dates) ≠ len(all_dates)
- 前端按索引对应 dates[i] → rolling_ic_mean[i] 会错位
```

### 正确实现

```python
# ✓ 正确：rolling_ic_mean 基于 all_dates 计算
from factor_ic.common.ic_calculator import calculate_ic_statistics

# 使用 all_dates 和 all_ic_values 构建 ic_series
ic_series = pd.Series(all_ic_values, index=all_dates)
result = calculate_ic_statistics(ic_series)

# rolling_ic_mean 基于 all_dates（与全量路径一致）
rolling_ic_mean_series = ic_series.rolling(window=20, min_periods=10).mean()
rolling_ic_mean = [
    round(v, 6) if not pd.isna(v) else None
    for v in rolling_ic_mean_series.values
]

# 输出：dates, ic_values, rolling_ic_mean 长度一致
merged_data = {
    'dates': all_dates,           # len = N
    'ic_values': all_ic_values,   # len = N
    'rolling_ic_mean': rolling_ic_mean,  # len = N ✓
}
```

### 禁止行为

```python
# ❌ 禁止：rolling_ic_mean 基于 valid_dates（子集）计算
valid_indices = [i for i, ic in enumerate(all_ic_values) if ic is not None]
valid_dates = [all_dates[i] for i in valid_indices]
valid_ic = [all_ic_values[i] for i in valid_indices]

ic_series = pd.Series(valid_ic, index=valid_dates)  # 基于 valid_dates
rolling_ic_mean_series = ic_series.rolling(window=20, min_periods=10).mean()
rolling_ic_mean = [round(v, 6) if not pd.isna(v) else None for v in rolling_ic_mean_series.values]

# 输出：dates, ic_values, rolling_ic_mean 长度不一致
merged_data = {
    'dates': all_dates,           # len = N
    'ic_values': all_ic_values,   # len = N
    'rolling_ic_mean': rolling_ic_mean,  # len = M (M < N) ✗ 错误！
}

# 问题：
# - all_dates 和 all_ic_values 长度 = N
# - rolling_ic_mean 长度 = M（M < N）
# - 前端 dates[i] → rolling_ic_mean[i] 索引错位
# - 第 M 个日期之后的数据无 rolling_ic_mean 对应
```

### 为何必须长度一致

1. 前端图表按索引对应：`dates[i] → ic_values[i] → rolling_ic_mean[i]`
2. 长度不一致会导致索引错位，图表显示错误
3. 全量路径已经保证长度一致，增量路径必须遵循相同原则
4. JSON 数据结构一致性要求：三条数组长度相等

### 全量/增量路径一致性验证

| 路径 | dates来源 | ic_values来源 | rolling_ic_mean来源 | 长度一致性 |
|------|----------|--------------|-------------------|-----------|
| 全量 | ic_series.index | ic_series.values | ic_series.rolling() | ✓ N=N=N |
| 增量 | all_dates | all_ic_values | ic_series.rolling()（基于all_dates） | ✓ N=N=N |

**关键：** 增量路径的 `ic_series` 必须使用 `all_dates` 和 `all_ic_values` 构建，而非 `valid_dates` 子集。

---

## 增量路径 period 字段规范

### 核心原则

**增量路径 `period.start/end` 必须直接使用 `raw_metadata`，与全量路径语义完全一致。**

### 语义定义

**period 字段表示原始缓存范围（dropna前），而非合并后有效IC日期范围。**

```
| 数据源 | 语义 | 示例 |
|--------|------|------|
| raw_metadata['period_start'] | 原始缓存最小日期（dropna前） | 2024-01-01 |
| raw_metadata['period_end'] | 原始缓存最大日期（dropna前） | 2026-05-15 |
| all_dates[0] | 合并后有效IC最小日期 | 2024-01-20 |
| all_dates[-1] | 合并后有效IC最大日期 | 2026-05-15 |

差异原因：
- 原始缓存范围：2024-01-01 ~ 2026-05-15（545天）
- 有效IC范围：2024-01-20 ~ 2026-05-15（526天）
- 前19天布林带值NaN（等待足够数据）
```

### 正确实现

```python
# ✓ 正确：period 直接使用 raw_metadata（与全量路径一致）
merged_data = {
    'period': {
        'start': raw_metadata['period_start'],  # 原始缓存范围
        'end': raw_metadata['period_end']       # 原始缓存范围
    },
    'sample_stats': {
        'total_days': raw_metadata.get('total_days', 0),  # 原始缓存天数
        'valid_days': len(all_dates),  # 有效IC天数
    }
}
```

### 禁止行为

```python
# ❌ 禁止：混合不同语义的范围
merged_data = {
    'period': {
        'start': min(all_dates[0], raw_metadata['period_start']),  # 混合语义
        'end': max(all_dates[-1], raw_metadata['period_end'])      # 混合语义
    }
}

# 问题：
# - all_dates[0] 和 raw_metadata['period_start'] 语义不同
# - min/max 混合两个不同范围，语义模糊
# - 无法解释 period 表示什么范围
# - 与全量路径不一致（全量路径直接使用 raw_metadata）
```

### 为何必须使用 raw_metadata

1. **语义一致性：** period 表示原始缓存范围，而非有效IC范围
2. **两条路径一致：** 全量路径使用 raw_metadata，增量路径必须一致
3. **数据源稳定性：** raw_metadata 表示数据源范围，不受计算过程影响
4. **下游依赖明确：** 前端显示 period 时期望原始数据范围，而非计算后范围

### 全量/增量路径一致性验证

| 路径 | period.start来源 | period.end来源 | 语义 |
|------|-----------------|----------------|------|
| 全量 | raw_metadata['period_start'] | raw_metadata['period_end'] | 原始缓存范围 ✓ |
| 增量 | raw_metadata['period_start'] | raw_metadata['period_end'] | 原始缓存范围 ✓ |

**关键：** 增量模式追加数据不改变原始缓存范围，`period` 应始终表示数据源范围。

---

## 增量路径返回结构一致性规范

### 核心原则

**增量路径返回结构必须与全量路径完全一致，禁止遗漏字段。**

### 问题背景

```
两条路径返回结构对比：

全量路径返回字段：
- factor_name ✓
- calculation_date ✓
- period ✓
- ic_metrics ✓
- sample_stats ✓
- statistical_significance ✓
- factor_direction ✓
- economic_significance ✓
- dates ✓
- ic_values ✓
- rolling_ic_mean ✓
- positive_ratio ✓
- n_assets ✓
- summary ✓
- factor_stats ✓  ← 全量路径包含
- update_mode ✓

增量路径返回字段：
- ...（与全量相同）
- factor_stats ✗  ← 增量路径可能缺失！
- update_mode ✓
- incremental_days ✓
```

### 正确实现

```python
# ✓ 正确：增量路径包含所有字段（与全量路径一致）
merged_data = {
    'factor_name': 'xxx',
    'calculation_date': 'xxx',
    'period': {...},
    'ic_metrics': {...},
    'sample_stats': {...},
    'statistical_significance': {...},
    'factor_direction': {...},
    'economic_significance': {...},
    'dates': all_dates,
    'ic_values': all_ic_values,
    'rolling_ic_mean': rolling_ic_mean,
    'positive_ratio': xxx,
    'n_assets': xxx,
    'summary': {...},
    'factor_stats': factor_stats,  # ✓ 必须包含（与全量路径一致）
    'update_mode': 'incremental',
    'incremental_days': xxx
}
```

### 禁止行为

```python
# ❌ 禁止：增量路径缺少 factor_stats
merged_data = {
    'factor_name': 'xxx',
    # ... 其他字段 ...
    'summary': {...},
    'update_mode': 'incremental',  # 缺少 factor_stats！
    'incremental_days': xxx
}

# 问题：
# - 全量路径包含 factor_stats（因子计算统计信息）
# - 增量路径缺失 factor_stats
# - 两种模式返回结构不一致
# - 下游代码读取 factor_stats 时在增量模式下会 KeyError
```

### 为何必须结构一致

1. **下游依赖：** 前端或其他分析代码可能读取 `factor_stats` 字段
2. **接口一致性：** 同一函数的两种模式应返回相同结构
3. **类型安全：** 避免 KeyError 或字段缺失导致的运行时错误
4. **维护成本：** 结构一致降低代码复杂度和排查难度

### 全量/增量路径字段一致性验证

| 字段 | 全量路径 | 增量路径 | 是否必须 |
|------|---------|---------|---------|
| factor_name | ✓ | ✓ | ✓ |
| calculation_date | ✓ | ✓ | ✓ |
| period | ✓ | ✓ | ✓ |
| ic_metrics | ✓ | ✓ | ✓ |
| sample_stats | ✓ | ✓ | ✓ |
| statistical_significance | ✓ | ✓ | ✓ |
| factor_direction | ✓ | ✓ | ✓ |
| economic_significance | ✓ | ✓ | ✓ |
| dates | ✓ | ✓ | ✓ |
| ic_values | ✓ | ✓ | ✓ |
| rolling_ic_mean | ✓ | ✓ | ✓ |
| positive_ratio | ✓ | ✓ | ✓ |
| n_assets | ✓ | ✓ | ✓ |
| summary | ✓ | ✓ | ✓ |
| factor_stats | ✓ | ✓ | ✓ 必须包含！ |
| update_mode | ✓ | ✓ | ✓ |
| incremental_days | ✗ | ✓ | 增量路径特有 |

**关键：** 增量路径必须在构建 `merged_data` 时添加 `factor_stats` 字段，与全量路径保持结构一致。

---

## 函数返回值契约校验规范

### 核心原则

**`required_fields` 校验列表必须包含所有后续直接访问的字段，禁止遗漏。**

### 问题背景

```
校验列表 vs 实际访问字段：

校验列表（required_fields）：
- ic_series ✓
- ic_mean ✓
- ic_std ✓
- icir ✓
- p_value ✗  ← 校验列表缺少！
- p_value_display ✗  ← 校验列表缺少！
- statistical_significance ✓
- factor_direction ✓
- economic_significance ✓
- positive_ratio ✓
- summary ✓

后续代码直接访问：
- result['p_value']  ← 未校验，若缺失会 KeyError
- result['p_value_display']  ← 使用 .get()，有默认值，但仍依赖 p_value
```

### 正确实现

```python
# ✓ 正确：校验列表包含所有直接访问的字段
required_fields = [
    'ic_series', 'ic_mean', 'ic_std', 'icir',
    'p_value', 'p_value_display',  # ✓ 必须包含！
    'statistical_significance', 'factor_direction',
    'economic_significance', 'positive_ratio', 'summary'
]

missing_fields = [f for f in required_fields if f not in result]
if missing_fields:
    raise RuntimeError(
        f"calculate_ic_with_direction_verification 返回值缺少必需字段\n"
        f"缺失字段: {missing_fields}\n"
        f"问题定位: factor_ic/common/ic_calculator.py\n"
        f"期望字段: {required_fields}"
    )

# 校验后可以安全访问
'p_value': round(result['p_value'], 6)  # ✓ 已校验，不会 KeyError
```

### 禁止行为

```python
# ❌ 禁止：校验列表缺少 p_value
required_fields = [
    'ic_series', 'ic_mean', 'ic_std', 'icir',
    'statistical_significance', 'factor_direction',
    'economic_significance', 'positive_ratio', 'summary'
]

# 后续直接访问 p_value
'p_value': round(result['p_value'], 6)  # ✗ 未校验，可能 KeyError！

# 问题：
# - 若 calculate_ic_with_direction_verification 返回值缺少 p_value
# - 第406行会抛出 KeyError: 'p_value'
# - 错误信息不友好，无法定位问题模块
# - 与校验机制设计初衷矛盾
```

### 为何必须校验所有字段

1. **错误信息友好：** RuntimeError 包含缺失字段列表、问题定位、期望字段列表
2. **问题定位快速：** 明确指出哪个模块返回值不符合契约
3. **维护成本低：** 契约校验是统一入口，一处修改全局生效
4. **代码健壮性：** 避免 KeyError 在运行时突然出现

### 校验列表完整性检查清单

```
□ 检查所有 result['field'] 直接访问的字段
□ 检查所有 result.get('field') 有默认值但仍依赖的字段
□ 检查嵌套字段父级（如 statistical_significance）
□ 确保校验列表与实际访问一致
□ 新增字段访问时同步更新校验列表
```

---

## 增量路径因子值有效性检查规范

### 核心原则

**增量路径必须检查缺失日期的因子值是否有效，避免静默产生大量 None IC值。**

### 问题背景

```
布林带预热期问题：

布林带计算需要前N-1日数据预热：
- N=20，需要前19日数据
- rolling(window=n, min_periods=n) 确保 前19天为 NaN
- 缺失日期如果是缓存范围的前19天
- bollinger_pb_1d 全为 NaN（即使 factor_df_new 不为空）

示例场景：
- 缓存范围：2024-01-01 ~ 2026-05-15
- 缺失日期：2024-01-02（缓存范围第2天）
- factor_df_new 有数据（日期、股票、close）
- 但 bollinger_pb_1d 全为 NaN（只有1天历史数据，无法计算20日布林带）
- calculate_single_day_ic 返回 None
- 用户看不到诊断信息，不知道为什么跳过

问题后果：
- 静默产生大量 None IC值
- 用户不知道跳过原因
- 无法区分"股票数不足"和"因子值NaN"
```

### 正确实现

```python
# ✓ 正确：检查因子值有效性
# 篛选缺失日期的数据
factor_df_new = factor_df_full[factor_df_full['date'].isin(missing_set)]

# 检查因子值有效性
valid_factor_count = factor_df_new['bollinger_pb_1d'].notna().sum()
total_factor_count = len(factor_df_new)

if valid_factor_count == 0:
    # 缺失日期的因子值全为 NaN（布林带预热期）
    print(f"  [诊断] 缺失日期的因子值全为 NaN（可能因布林带预热期）")
    print(f"  [诊断] 缺失日期: {sorted(factor_df_new['date'].unique())[:5]}")
    print(f"  [建议] 这些日期需要更多历史数据才能计算布林带，跳过增量计算")
    return existing_data

print(f"  - 篛选后: {len(factor_df_new)} 行，其中 {valid_factor_count} 行有效因子值")
if total_factor_count - valid_factor_count > 0:
    print(f"  - {total_factor_count - valid_factor_count} 行因子值为 NaN（布林带预热期）")
```

### 禁止行为

```python
# ❌ 禁止：只检查 factor_df_new 是否为空，不检查因子值有效性
if factor_df_new.empty:
    return existing_data

print(f"  - 篛选后: {len(factor_df_new)} 行")  # ✗ 没有检查因子值是否有效！

# 问题：
# - factor_df_new 不为空，但 bollinger_pb_1d 可能全为 NaN
# - 后续 calculate_single_day_ic 返回 None
# - 用户看不到诊断信息，不知道跳过原因
```

### 为何必须检查因子值有效性

1. **布林带预热期：** 技术指标需要历史数据预热，前N-1天因子值为 NaN
2. **诊断信息清晰：** 告知用户跳过原因，而非静默产生 None
3. **区分跳过原因：** 区分"数据缺失"、"股票数不足"、"因子值NaN"
4. **提前返回：** 若全为 NaN，直接返回缓存，避免无效计算

### 适用场景

1. **布林带 %B**：N=20，前19天预热期
2. **RSI**：N=6/14，前N-1天预热期
3. **KDJ**：N=9，前N-1天预热期
4. **任何需要历史数据的技术指标**

### 检查清单

```
□ 检查 factor_df_new 是否为空（数据缺失）
□ 检查因子值是否有效（notna().sum() > 0）
□ 提供诊断信息（缺失日期示例）
□ 区分不同跳过原因（数据缺失/因子值NaN/股票数不足）
□ 提前返回缓存（避免无效计算）
```

---

## 增量路径 None 值保留规范

### 核心原则

**增量路径合并时必须保留所有日期（包括 None IC 值的日期），不过滤 None，确保 total_days 与 valid_days 的差值语义正确。**

### 问题背景

```
逻辑矛盾问题：

旧代码（错误）：
```python
date_ic_map = {}
for date, ic in zip(existing_dates, existing_ic_values):
    if ic is not None:  # ✗ 过滤了 None
        date_ic_map[date] = ic
for date, ic in zip(new_dates, new_ic_values):
    if ic is not None:  # ✗ 过滤了 None
        date_ic_map[date] = ic

all_dates = sorted(date_ic_map.keys())  # ✗ 只包含有效 IC 的日期
all_ic_values = [date_ic_map[d] for d in all_dates]  # ✗ 不包含 None
```

问题后果：
- 丢失了"股票数不足跳过"的日期（IC=None）
- total_days = len(all_dates) 只计算有效 IC 的日期数
- valid_days 也只计算有效 IC 的日期数
- 两者相等，无法区分跳过的日期
- 语义失真：用户不知道有多少天因股票数不足跳过

示例场景：
- 现有缓存：dates=['2024-01-01', '2024-01-02'], ic_values=[0.05, None]
- 增量计算：new_dates=['2024-01-03'], new_ic_values=[None]
- 合并后：all_dates=['2024-01-01'], all_ic_values=[0.05]
- ✗ 丢失了 2024-01-02, 2024-01-03（都因股票数不足跳过）
- total_days=1, valid_days=1，但实际应有 total_days=3, valid_days=1
```

### 正确实现

```python
# ✓ 正确：保留所有日期，不过滤 None
# 使用字典去重，保留 None 值
date_ic_map = {}
for date, ic in zip(existing_dates, existing_ic_values):
    date_ic_map[date] = ic  # 保留 None 值，不过滤
for date, ic in zip(new_dates, new_ic_values):
    date_ic_map[date] = ic  # 保留 None 值，不过滤

# 按日期排序（包含所有日期，包括 None IC 值的日期）
all_dates = sorted(date_ic_map.keys())
all_ic_values = [date_ic_map[d] for d in all_dates]  # 包含 None

# 统计有效 IC 数（用于诊断信息）
valid_ic_count = sum(1 for ic in all_ic_values if ic is not None)
none_ic_count = len(all_ic_values) - valid_ic_count

print(f"  - 合并后总计: {len(all_dates)} 天（去重后）")
if none_ic_count > 0:
    print(f"  - 其中 {valid_ic_count} 天有效 IC，{none_ic_count} 天因股票数不足跳过（IC=None）")

# 后续 calculate_ic_statistics 会自动过滤 None 计算 valid_days
# total_days = len(all_dates)，valid_days = valid_ic_count
```

### 禁止行为

```python
# ❌ 禁止：合并时过滤 None
date_ic_map = {}
for date, ic in zip(existing_dates, existing_ic_values):
    if ic is not None:  # ✗ 过滤了 None，丢失跳过的日期
        date_ic_map[date] = ic

# ❌ 禁止：只统计有效 IC 的日期
all_dates = sorted(date_ic_map.keys())  # ✗ 不包含 None IC 的日期
all_ic_values = [date_ic_map[d] for d in all_dates]  # ✗ 不包含 None

# 问题：
# - total_days = len(all_dates) = valid_days
# - 无法区分"股票数不足跳过"的日期
# - 语义失真
```

### 为何必须保留 None 值

1. **语义正确性：** total_days 应表示所有日期数，valid_days 应表示有效 IC 数
2. **诊断信息完整：** 用户需要知道有多少天因股票数不足跳过
3. **统计指标准确：** calculate_ic_statistics 自动过滤 None，不影响 IC/ICIR 计算
4. **与全量路径一致：** 全量路径也保留 None 值

### calculate_ic_statistics 处理逻辑

```python
# common/ic_calculator.py 中的 calculate_ic_statistics
# 自动过滤 None 值，只计算有效 IC 的统计指标
def calculate_ic_statistics(ic_series: pd.Series) -> dict:
    # 过滤 None 值（pd.Series 中的 NaN）
    valid_ic = ic_series.dropna()
    
    # 统计指标基于有效 IC 计算
    ic_mean = valid_ic.mean()
    ic_std = valid_ic.std()
    icir = ic_mean / ic_std if ic_std > 0 else 0
    
    # 但 total_days = len(ic_series)，valid_days = len(valid_ic)
    return {
        'total_days': len(ic_series),  # 包含 None 的日期数
        'valid_days': len(valid_ic),   # 有效 IC 的日期数
        ...
    }
```

### 检查清单

```
□ 合并时不过滤 None（保留所有日期）
□ all_dates 包含所有日期（包括 None IC 的日期）
□ all_ic_values 包含 None（不过滤）
□ 提供诊断信息（valid_ic_count vs none_ic_count）
□ total_days 与 valid_days 差值语义正确
```

---

## 布林带因子必须加载 close 列规范

### 核心原则

**布林带因子依赖 close 价格计算，load_data_from_cache 必须强制加载和过滤 'close' 列，无论 factor_col 参数值为何。**

### 问题背景

```
设计缺陷问题：

旧代码（错误）：
```python
factor_cols = ['date', 'asset', factor_col]  # ✗ 如果 factor_col != 'close'，不包含 'close'
factor_df = factor_df[factor_cols].copy()

factor_df.dropna(subset=[factor_col])  # ✗ 只过滤 factor_col 的 NaN，不过滤 'close'
```

问题后果：
- 如果调用方传入 factor_col='volume'（或其他非 'close'）
- close 列不会被加载和过滤
- 原始缓存中 close 有 NaN 的行不会被过滤
- 后续布林带计算需要 close 列 → KeyError 或 NaN 值传播

示例场景：
- 原始缓存: {"date": "2024-01-02", "close": null, "volume": 500000}
- 调用 load_data_from_cache(factor_col='volume')
- factor_cols = ['date', 'asset', 'volume']（不包含 'close'）
- dropna(subset=['volume']) 不过滤 close=null 的行
- 后续布林带计算: close 列不存在 → KeyError
- 或如果 close 列存在但未被过滤: close=null → NaN 值传播
```

### 正确实现

```python
# ✓ 正确：强制加载 'close' 列（布林带依赖）
factor_cols = ['date', 'asset']
if factor_col not in factor_cols:
    factor_cols.append(factor_col)
if 'close' not in factor_cols:  # 强制加载 'close' 列
    factor_cols.append('close')

factor_df = factor_df[factor_cols].copy()

# ✓ 正确：强制过滤 'close' 列的 NaN
dropna_cols = ['close']  # 布林带因子必须过滤 close 列
if factor_col not in dropna_cols:
    dropna_cols.append(factor_col)

factor_df = factor_df.dropna(subset=dropna_cols).reset_index(drop=True)
```

### 禁止行为

```python
# ❌ 禁止：只加载 factor_col 列，不强制加载 'close'
factor_cols = ['date', 'asset', factor_col]  # ✗ 如果 factor_col != 'close'，不包含 'close'

# ❌ 禁止：只过滤 factor_col 的 NaN，不过滤 'close'
factor_df.dropna(subset=[factor_col])  # ✗ close 列的 NaN 未被过滤

# 问题：
# - 布林带计算需要 close 列
# - close 有 NaN 的行未被过滤
# - NaN 值传播到布林带计算
```

### 为何必须强制加载 close 列

1. **布林带公式依赖 close**：布林带%B = (close - lower) / (upper - lower)
2. **close 有 NaN 必须过滤**：NaN 值传播会导致布林带计算产生 NaN
3. **防御性设计**：即使调用方传入错误的 factor_col，也能确保 close 列被正确加载
4. **避免 KeyError**：后续布林带计算需要 close 列，必须提前加载

### 适用范围

此规范适用于所有依赖 close 价格的因子脚本：
1. **布林带 %B**：依赖 close 计算布林带上下轨
2. **RSI**：依赖 close 计算价格变动
3. **KDJ**：依赖 close 计算 J 值
4. **任何需要 close 价格的技术指标**

### 检查清单

```
□ 强制加载 'close' 列（无论 factor_col 参数）
□ 强制过滤 'close' 列的 NaN
□ 同时过滤 factor_col 的 NaN（调用方指定的因子列）
□ 提供诊断信息（显示过滤的列）
□ 确保布林带计算所需列存在
```

---

**典型场景：**

| 场景 | 旧实现 | 新实现 | 清理要求 |
|------|-------|-------|---------|
| 性能优化 | 循环处理单股票 | 向量化处理多股票 | 删除循环版本函数 |
| 算法重构 | 单数据点函数 | 向量化版本 | 删除单数据点函数 |
| 公共函数复用 | 本地实现 | common/ 公共函数 | 删除本地实现 |

**正确示例：**
```python
# ✓ 正确：向量化版本替代循环版本后，删除旧函数

# 旧版本（删除）：
# def calculate_single_stock(stock_df): ...  # 已删除

# 新版本（保留）：
def calculate_all_stocks_vectorized(factor_df):
    return factor_df.groupby('asset').transform(...)
```

**禁止行为：**
```python
# ❌ 禁止：保留旧函数但从不调用（死代码）
def calculate_single_stock(stock_df):  # 死代码！
    """单股票版本，从未被调用"""
    return stock_df.rolling(20).mean()

def calculate_all_stocks_vectorized(factor_df):  # 实际使用
    """向量化版本"""
    return factor_df.groupby('asset').transform(...)

# calculate_single_stock 定义后从未被调用，是死代码
```

**为何必须清理死代码：**
1. 死代码误导读者：以为有两条实现路径可选
2. 死代码增加维护成本：修改逻辑时需同步多处
3. 死代码可能不一致：与新实现产生偏差
4. 代码审计浪费时间：分析死代码的用途

---

## 函数签名变更同步规范

**核心原则：** 返回值变更时必须同步更新类型注解和 docstring。

**正确示例：**
```python
def load_data_from_cache(...) -> Tuple[pd.DataFrame, pd.DataFrame, dict]:
    """
    Returns:
        factor_df: 过滤后的因子数据
        return_df: 过滤后的收益数据
        raw_metadata: 原始数据范围信息（新增）
    """
```

**禁止行为：**
- ❌ 只改返回值不改类型注解
- ❌ 只改返回值不改 docstring

---

## 参数类型约定规范

**核心原则：** output_file 统一转为 Path 对象。

**正确实现：**
```python
def generate_rsi_ic_data(output_file=None):
    if output_file is None:
        output_file = get_ic_output_path('rsi_1d')  # 返回 Path
    else:
        output_file = Path(output_file)  # str → Path
```

**为何必须统一类型：**
- Path 对象可安全使用 .parent.mkdir()
- str 对象需要额外处理
- 统一类型避免后续代码类型判断

---

## 统计显著性判断规范

**五维度判断（独立输出，不合并）：**

| 维度 | 判断规则 | 输出字段 |
|------|---------|---------|
| 维度1: 统计显著性 | p < 0.05（与 |t| > 1.96 等价） | is_significant, nw_lag |
| 维度2: 因子方向 | ic_mean 符号判断 | factor_direction |
| 维度3: 经济显著性 | |ic_mean| >= 0.05 → strong; >= 0.03 → weak | economic_significance |
| 维度4: ICIR稳定性 | ICIR >= 2.0 → excellent; >= 1.0 → good | icir_stability |
| 维度5: IC分布一致性 | positive_ratio 与 ic_mean_sign 匹配 | is_consistent, consistency_type |

---

## IC分布一致性判断边界规范

**判断规则（含优先级）：**

| 优先级 | 条件 | 输出 |
|-------|------|------|
| 1（最高） | ic_mean_sign = 'zero' | balanced |
| 2 | 正向因子 positive_ratio >= 50% | consistent |
| 2 | 反向因子 positive_ratio <= 50% | consistent |
| 3 | positive_ratio ∈ [49%, 51%]（闭区间） | balanced |
| 4 | 其他情况 | contradictory |

**边界示例：**
- 正向因子 49% → balanced（优先级3）
- 正向因子 50% → consistent（优先级2）
- 反向因子 50% → consistent（优先级2）
- 反向因子 51% → balanced（优先级3）

---

## 增量模式 period 语义规范

**核心原则：** period.start/end 必须基于原始缓存数据（dropna 前）。

**正确实现：**
```python
# 在 dropna 之前，先计算原始数据范围
raw_period_start = factor_df['date'].min()
raw_period_end = factor_df['date'].max()
raw_total_days = factor_df['date'].nunique()

# 然后 dropna
factor_df = factor_df.dropna()

# 返回过滤后的数据 + raw_metadata
return factor_df, return_df, {'period_start': raw_period_start, ...}
```

**为何必须使用原始数据：**
- dropna 可能过滤掉某些日期的全部股票
- factor_df['date'].min()/max() 计算的是过滤后的范围
- 与语义定义冲突："原始缓存覆盖范围" ≠ "过滤后的数据范围"

---

## 引用说明

本文档定义 factor_ic/ 目录下所有 IC 计算脚本的开发规范。

**相关文档：**
- 项目级规范：PROJECT.md（目录结构、开发检查清单）
- 流程文档：factor_ic/docs/ic_<因子名>_<周期>_flow.md
- 公共函数：factor_ic/common/ 模块

---

*最后更新: 2026-05-19*