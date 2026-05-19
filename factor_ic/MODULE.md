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
```python
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