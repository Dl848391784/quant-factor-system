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

## 流程文档规范

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

## 引用说明

本文档定义 factor_ic/ 目录下所有 IC 计算脚本的开发规范。

**相关文档：**
- 项目级规范：PROJECT.md（目录结构、开发检查清单）
- 流程文档：factor_ic/docs/ic_<因子名>_<周期>_flow.md
- 公共函数：factor_ic/common/ 模块

---

*最后更新: 2026-05-19*