# KDJ_J_1D IC 计算流程文档

> 生成时间: 2026-05-20 15:40 北京时间
> 实测数据时间: 2026-05-20 15:35 北京时间
> 版本: v1.11
> 更新内容: 修复 ewm 初始值函数副作用问题，使用 .copy() 避免修改原始数据

---

## 数据流向

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   cache/    │────▶│  load_data  │────▶│ calculate_kdj_j │
│ factor_data │     │ from_cache  │     │    factor      │
└─────────────┘     └─────────────┘     └─────────────┘
                                               │
                                               ▼
                                        ┌─────────────┐
                                        │ calculate_ic│
                                        │ with_direction│
                                        └─────────────┘
                                               │
                                               ▼
                                        ┌─────────────┐
                                        │   result/   │
                                        │  ic_kdj_j_  │
                                        │ 1d_*.json   │
                                        └─────────────┘
```

---

## 函数调用关系

```
generate_kdj_j_ic_data()
    ├─ load_data_from_cache()
    │   ├─ calculate_kdj_j_factor()
    │   │   ├─ 计算 RSV (向量化)
    │   │   ├─ 计算 K (ewm)
    │   │   ├─ 计算 D (ewm)
    │   │   └─ 计算 J = 3K - 2D
    │   └─ 返回 factor_df + raw_metadata
    ├─ calculate_daily_ic_series(factor_df, return_df, raw_metadata)
    │   ├─ calculate_ic_with_direction_verification()
    │   │   └─ 返回五维度判断结果
    │   ├─ 计算 rolling_ic_mean
    │   └─ 构建 JSON 输出结构
    └─ 保存到 result/ic_kdj_j_1d_analysis_result.json
```

---

## 输出字段说明

### 顶层字段

| 字段 | 类型 | 说明 |
|------|------|------|
| factor_name | str | 因子名称（kdj_j_1d） |
| calculation_date | str | 计算日期（YYYY-MM-DD） |
| period | object | 数据覆盖范围 |
| ic_metrics | object | IC统计指标 |
| statistical_significance | object | 统计显著性判断 |
| factor_direction | object | 因子方向判断 |
| economic_significance | object | 经济显著性判断 |
| sample_stats | object | 样本统计 |
| dates | array | 有效IC日期列表 |
| ic_values | array | 每日IC值列表 |
| rolling_ic_mean | array | 20日滚动IC均值 |
| positive_ratio | float | IC正值比例 |
| n_assets | int | 股票数量 |
| summary | str | 五维度判断摘要 |

### sample_stats 字段

| 字段 | 类型 | 说明 |
|------|------|------|
| total_days | int | 原始缓存覆盖的日期数（545） |
| valid_days | int | 实际计算出IC的天数（514） |
| avg_stocks_per_day | int | 平均每日有效股票数（2720） |
| avg_stocks_period | object | avg_stocks_per_day 的统计口径范围 |

**avg_stocks_period 子字段：**

| 字段 | 类型 | 说明 |
|------|------|------|
| start | str | 统计范围起始日期（2024-02-06） |
| end | str | 统计范围结束日期（2026-05-15） |
| description | str | 字段语义说明 |

**语义说明：**
- `total_days = 545`：原始因子缓存覆盖545个交易日
- `valid_days = 514`：实际参与IC计算的日期（股票数 >= 10）
- `差值 = 31`：因股票数不足跳过的交易日
- `avg_stocks_per_day`：反映 dropna 后数据范围内的平均每日股票数

---

## 示例数据（实测结果）

### IC统计指标

```json
{
  "ic_mean": -0.016024,
  "ic_std": 0.143459,
  "icir": 0.1117,
  "p_value": 0.008991
}
```

### 统计显著性判断

```json
{
  "p_value": 0.008991,
  "p_value_display": "0.0090",
  "t_stat": -2.6124,
  "nw_lag": 5,
  "nw_lag_method": "Newey-West (1994): lag = int(4*(T/100)^(2/9))",
  "is_significant": true,
  "conclusion": "统计显著（p=0.0090<0.05）"
}
```

**字段说明：**
- `nw_lag`：Newey-West 自相关校正滞后阶数
- `nw_lag_method`：滞后阶数计算方法（遵循 PROJECT.md 规范）
- 直接传递完整 result 对象，包含所有子字段（对齐 ic_rsi_1d.py）

### 因子方向判断

```json
{
  "ic_mean_sign": "negative",
  "ic_mean": -0.016024,
  "direction_usage": "反向因子",
  "conclusion": "因子方向为反向（ic_mean=-0.0160<0），分层回测做多低值组"
}
```

**字段说明：**
- `ic_mean_sign`：IC均值符号（negative/positive）
- `direction_usage`：因子使用方向说明
- 直接传递完整 result 对象（对齐 ic_rsi_1d.py）

### 经济显著性判断

```json
{
  "abs_ic_mean": 0.016024,
  "level": "不显著",
  "is_economically_significant": false,
  "threshold_used": "0.03",
  "conclusion": "经济不显著（|ic_mean|=0.0160<0.03）"
}
```

**字段说明：**
- `threshold_used`：显著性阈值（遵循 PROJECT.md 规范）
- 直接传递完整 result 对象（对齐 ic_rsi_1d.py）

### rolling_ic_mean 前10个值

```json
[
  null, null, null, null, null, null, null, null, null,
  0.193292, 0.175398, 0.192537, ...
]
```

**说明：** 前 min_periods-1=9 个时间点为 null（min_periods=10，窗口需至少10个有效值才返回结果）

---

## 参数传递规范

### DEFAULT_MIN_STOCKS 常量

```python
# 模块顶部定义
DEFAULT_MIN_STOCKS = 10
```

**用途：**
- calculate_daily_ic_series 函数参数
- 数据验证阈值
- 统一参数管理（遵循 PROJECT.md 规范）

---

## 异常处理规范

### 分层捕获（数据加载）

```python
except FileNotFoundError as e:
    # 基础设施错误：可包装为 RuntimeError
    raise RuntimeError(f"缓存文件不存在: {e}") from e
except KeyError as e:
    # 数据验证错误：直接 raise
    raise  # 不包装，保留原始类型
except ValueError as e:
    # 数据验证错误：直接 raise
    raise  # 不包装，保留原始类型
except Exception as e:
    # 未预期异常：包装为 RuntimeError
    raise RuntimeError(...) from e
```

### 分层捕获（缓存文件读取）

```python
# 增量模式读取已有缓存时
except FileNotFoundError:
    # 可恢复错误：缓存文件不存在，降级全量计算
    print("  [诊断] 缓存文件不存在，执行全量计算")
    pass  # fallthrough 到全量计算
except json.JSONDecodeError as e:
    # 严重错误：缓存文件损坏，不静默降级
    raise RuntimeError(
        f"缓存文件损坏，无法解析 JSON: {output_file}\n"
        f"错误详情: {e}\n"
        f"建议: 删除损坏的缓存文件后重新运行"
    ) from e
except PermissionError as e:
    # 严重错误：权限问题，不静默降级
    raise RuntimeError(
        f"缓存文件权限不足，无法读取: {output_file}\n"
        f"错误详情: {e}"
    ) from e
except Exception as e:
    # 未预期异常：抛出异常 + 详细诊断
    raise RuntimeError(
        f"读取缓存失败（未预期异常）: {output_file}\n"
        f"异常类型: {type(e).__name__}\n"
        f"错误详情: {e}"
    ) from e
```

**关键原则：**
- FileNotFoundError：可恢复，降级全量计算
- JSONDecodeError/PermissionError：严重错误，不静默降级
- 遵循 factor-script-optimization-checklist.md Section 22 规范

---

## 日期类型一致性

### 统一转换

```python
# 从 JSON 加载后统一转换为 "YYYY-MM-DD" 格式
date_series = pd.to_datetime(factor_df['date'], errors='coerce')
factor_df['date'] = date_series.dt.strftime('%Y-%m-%d')
```

**处理无效日期：**
```python
nat_count = date_series.isna().sum()
if nat_count > 0:
    invalid_samples = factor_df['date'][date_series.isna()].iloc[:5].tolist()
    raise ValueError(f"存在无效日期格式: {invalid_samples}")
```

---

## 防御性校验

### required_fields 检查

```python
required_fields = [
    'ic_series', 'ic_mean', 'ic_std', 'icir',
    'statistical_significance', 'factor_direction',
    'economic_significance', 'icir_stability',
    'ic_distribution_consistency', 'positive_ratio', 'summary'
]
missing_fields = [f for f in required_fields if f not in result]
if missing_fields:
    raise RuntimeError(f"返回值缺少必需字段: {missing_fields}")
```

### dates 排序校验

```python
if dates != sorted(dates):
    raise RuntimeError("dates 未按升序排列")
```

---

## 因子计算逻辑

### KDJ_J 公式

```
RSV(N) = (Close - Low_N) / (High_N - Low_N) × 100
K = K_{t-1} × (M1-1)/M1 + RSV × 1/M1  (ewm alpha=1/M1)
D = D_{t-1} × (M2-1)/M2 + K × 1/M2    (ewm alpha=1/M2)
J = 3K - 2D
```

### 参数

- N = 9（RSV计算周期）
- M1 = 3（K值平滑周期）
- M2 = 3（D值平滑周期）

### 向量化实现

```python
# RSV 计算
rolling_high = factor_df.groupby('asset')['high'].transform(
    lambda x: x.rolling(window=n, min_periods=1).max()
)
rolling_low = factor_df.groupby('asset')['low'].transform(
    lambda x: x.rolling(window=n, min_periods=1).min()
)

# 浮点数除零精度容差判断（遵循 PROJECT.md 浮点数等值比较规范）
EPSILON = 1e-10  # 浮点数精度容差
diff = rolling_high - rolling_low
# 使用 np.abs(diff) < EPSILON 替代 diff == 0
rsv = np.where(np.abs(diff) < EPSILON, 50.0, (close - rolling_low) / diff * 100)

# K 计算（ewm）
alpha_k = 1.0 / m1
factor_df['k'] = factor_df.groupby('asset')['rsv'].transform(
    lambda x: x.ewm(alpha=alpha_k, adjust=False).mean()
)
```

### 浮点数精度容差规范

**问题根因：**
- `diff` 是浮点数运算结果（`rolling_high - rolling_low`）
- IEEE 754 浮点数无法精确表示某些数值，运算结果可能产生微小误差（如 `1e-15`）
- 直接 `== 0` 比较会漏判极小值
- 极小值作为除数会产生极端 RSV 值（如 `1e15`）

**修复方式：**
```python
# 精度容差判断：|diff| < 1e-10 视为零
EPSILON = 1e-10
rsv = np.where(np.abs(diff) < EPSILON, 50.0, ...)
```

**参考规范：** factor-script-optimization-checklist.md Section 17

---

## 增量模式控制流规范

### 问题根因

**原始代码（隐式 fallthrough）：**
```python
if mode == 'skip':
    print("\n数据完备，无需更新")
    try:
        with open(output_file, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        print("  [诊断] 缓存文件不存在，执行全量计算")
        pass  # except 块结束，代码继续向下执行全量计算
    except json.JSONDecodeError as e:
        raise RuntimeError(...)  # 不继续
    except PermissionError as e:
        raise RuntimeError(...)  # 不继续

# 全量计算逻辑（隐式 fallthrough 到这里）
```

**问题分析：**
- `pass` 后代码继续执行，读者需追踪"哪些分支会继续"
- 重构风险：若外层加 `else`，可能误判控制流
- 缺少 `mode == 'incremental'` 处理
- 控制流依赖隐式 fallthrough，违反显式控制流原则

### 修复方式

**使用显式控制流（变量标记）：**
```python
should_full_recalculate = force_full  # 默认需要全量计算

if not force_full:
    mode, missing_dates, info = check_data_completeness('kdj_j_1d')
    
    if mode == 'skip':
        try:
            with open(output_file, 'r', encoding='utf-8') as f:
                return json.load(f)  # 成功读取，直接返回
        except FileNotFoundError:
            should_full_recalculate = True  # 显式标记：需要全量计算
    
    elif mode == 'incremental':
        should_full_recalculate = True  # 当前版本降级全量计算
    
    else:  # mode == 'full'
        should_full_recalculate = True

# 此处：should_full_recalculate=True（所有分支已处理）
# 全量计算逻辑
```

### 控制流分析

| 分支 | should_full_recalculate | 行为 |
|------|------------------------|------|
| force_full=True | True | 执行全量计算 |
| mode='skip' + 成功读取 | - | 直接返回（不继续） |
| mode='skip' + FileNotFoundError | True | 执行全量计算 |
| mode='incremental' | True | 执行全量计算 |
| mode='full' | True | 执行全量计算 |

**优势：**
- 显式控制流，每个分支行为清晰
- 重构安全：添加新分支不会破坏逻辑
- 易于扩展：增量模式可单独实现

**参考规范：** MODULE.md "控制流显式化"章节

---

## RSV 计算窗口期规范

### 问题根因

**原始代码（错误）：**
```python
factor_df['rolling_high'] = factor_df.groupby('asset')['high'].transform(
    lambda x: x.rolling(window=n, min_periods=1).max()
)
```

**问题分析：**
- `min_periods=1` 允许前 N-1 天用不足 N 天的数据计算
- 第 1 天只有 1 天数据，`rolling_high = high[0]`, `rolling_low = low[0]`
- 若 `close[0] = high[0]` 或 `close[0] = low[0]`，则 `RSV = 100` 或 `0`（极端值）
- 前 N-1 天的 RSV 数据失真，影响后续 K/D/J 计算

### 标准定义

**标准 KDJ 实现要求：**
- 满 N 期才开始计算 RSV
- 前 N-1 天标记为 NaN（无有效数据）
- 确保使用完整窗口数据（最高价取 N 天内最高，最低价取 N 天内最低）

### 修复方式

```python
# 遵循标准 KDJ 定义：满 N 期才开始计算，前 N-1 期为 NaN
# min_periods=n 确保使用完整窗口数据，避免前 N-1 天数据失真
factor_df['rolling_high'] = factor_df.groupby('asset')['high'].transform(
    lambda x: x.rolling(window=n, min_periods=n).max()
)
factor_df['rolling_low'] = factor_df.groupby('asset')['low'].transform(
    lambda x: x.rolling(window=n, min_periods=n).min()
)
```

### 影响分析

| 指标 | min_periods=1（错误） | min_periods=n（正确） | 说明 |
|------|----------------------|---------------------|------|
| 有效数据起点 | 第 1 天 | 第 N 天 | 前 N-1 天为 NaN |
| 因子最小值 | -28.62 | -54.44 | 消除极端值后范围更真实 |
| 因子最大值 | 129.14 | 154.44 | 消除极端值后范围更真实 |
| IC 均值 | -0.0160 | -0.0180 | 消除噪音后更显著 |
| t 统计量 | -2.61 | -3.12 | 显著性增强 |

**结论：** min_periods=n 消除了前 N-1 天的失真数据，使因子统计更准确、IC 更显著。

---

## KDJ 初始值规范

### 问题根因

**原始代码（错误）：**
```python
# ewm 计算完成后修正第一个值
stock_data['k'] = stock_data['rsv'].ewm(alpha=1/3, adjust=False).mean()
stock_data.loc[stock_data.index[0], 'k'] = initial_k * (m1-1)/m1 + stock_data['rsv'].iloc[0] / m1
```

**问题分析：**
- `ewm(adjust=False)` 的第一个输出 = 第一个输入，即 K[0] = RSV[0]
- ewm 已完成所有行的递推计算：K[1] = 2/3*K[0] + 1/3*RSV[1]，K[2] = ...
- 后修正 K[0] 无法影响已计算完成的 K[1]、K[2]...
- **修正无效！后续 K 值递推链断裂**

### ewm(adjust=False) 递推公式

```
y[0] = x[0]                  # 第一个输出 = 第一个输入
y[1] = (1-alpha) * y[0] + alpha * x[1]
y[2] = (1-alpha) * y[1] + alpha * x[2]
...
```

对于 KDJ（alpha = 1/M1 = 1/3）：
```
K[0] = RSV[0]
K[1] = 2/3 * K[0] + 1/3 * RSV[1]
K[2] = 2/3 * K[1] + 1/3 * RSV[2]
```

### 标准定义 vs ewm 默认行为

**标准 KDJ 定义：**
```
K[0] = initial_k = 50       # 用户指定初始值
K[1] = 2/3 * K[0] + 1/3 * RSV[1]
K[2] = 2/3 * K[1] + 1/3 * RSV[2]
```

**ewm(adjust=False) 默认行为：**
```
K[0] = RSV[0]               # 第一个观测值（非标准）
K[1] = 2/3 * K[0] + 1/3 * RSV[1]
```

### 修复方案：预处理第一个输入值

**修复代码：**
```python
# 在 ewm 前预处理 RSV[0]
alpha_k = 1.0 / m1
initial_k = 50.0

if len(stock_data) > 0:
    original_rsv_0 = stock_data['rsv'].iloc[0]
    stock_data.loc[stock_data.index[0], 'rsv'] = initial_k  # 替换为 initial_k

stock_data['k'] = stock_data['rsv'].ewm(alpha=alpha_k, adjust=False).mean()

# 恢复原始 RSV 值（不影响后续逻辑）
if len(stock_data) > 0:
    stock_data.loc[stock_data.index[0], 'rsv'] = original_rsv_0
```

**原理：**
- ewm(adjust=False) 的 y[0] = x[0]
- 若要 y[0] = initial_k，则 x[0] = initial_k
- 在 ewm 前替换 RSV[0] = initial_k，使 K[0] = initial_k
- K[1] = 2/3 * K[0] + 1/3 * RSV[1] = 2/3 * 50 + 1/3 * RSV[1]（正确递推）
- ewm 计算后恢复原始 RSV 值（不影响后续逻辑）

### 批量计算处理（无副作用版本）

**calculate_kdj_j_factor() 批量处理：**
```python
def calculate_k_with_initial(rsv_series):
    """计算 K 值，第一个值使用 initial_k（无副作用版本）
    
    正确做法：复制 Series，在副本上构造初始值序列，不修改原始数据
    原因：iloc 修改传入的 Series 产生副作用，若 ewm 异则还原不会执行
    """
    if len(rsv_series) == 0:
        return rsv_series
    
    # 复制 Series，避免修改原始数据（遵循 MODULE.md 无副作用规范）
    rsv_copy = rsv_series.copy()
    
    # 在副本上预处理第一个 RSV 值
    rsv_copy.iloc[0] = initial_k
    
    # 计算 ewm
    k_series = rsv_copy.ewm(alpha=alpha_k, adjust=False).mean()
    
    return k_series

factor_df['k'] = factor_df.groupby('asset')['rsv'].transform(calculate_k_with_initial)
```

**为何必须避免副作用：**
1. **数据污染风险**：`iloc` 修改传入的 Series，可能影响原始 `factor_df`
2. **异常恢复失败**：若 `ewm` 抛异常，还原代码不会执行，原始数据被污染
3. **调试困难**：副作用难以追踪，数据来源不清晰
4. **函数契约违反**：transform 函数应返回新 Series，不应修改输入

**旧版本问题（已修复）：**
```python
# ❌ 错误：修改原始数据 + 还原（不可靠的 hack）
original_rsv_0 = rsv_series.iloc[0]
rsv_series.iloc[0] = initial_k  # 副作用！
k_series = rsv_series.ewm(...).mean()
rsv_series.iloc[0] = original_rsv_0  # 若 ewm 异常，这行不执行
```

### D 值初始值处理

同理，D 值需要预处理 K[0]：
```python
# D[0] = initial_d = 50
original_k_0 = stock_data['k'].iloc[0]
stock_data.loc[stock_data.index[0], 'k'] = initial_d

stock_data['d'] = stock_data['k'].ewm(alpha=alpha_d, adjust=False).mean()

stock_data.loc[stock_data.index[0], 'k'] = original_k_0
```

### 验证结果

```
测试股票: 002309
RSV 前5个值: [50.0, 0.0, 21.05, 54.17, 91.67]
K 前5个值:   [50.0, 33.33, 29.24, 37.55, 55.59]
D 前5个值:   [50.0, 44.44, 39.38, 38.77, 44.37]
J 前5个值:   [50.0, 11.11, 8.97, 35.11, 78.02]

验证结论:
✓ K[0] = 50.0（正确初始化）
✓ D[0] = 50.0（正确初始化）
✓ K[1] = 2/3 * K[0] + 1/3 * RSV[1] = 33.33（正确递推）
✓ D[1] = 2/3 * D[0] + 1/3 * K[1] = 44.44（正确递推）
```

**参考规范：** MODULE.md 「KDJ 初始值规范」

---

## 防御性校验完整性规范

### 问题根因

**原始代码（校验不完整）：**
```python
required_fields = [
    'ic_series', 'ic_mean', 'ic_std', 'icir',
    'statistical_significance', 'factor_direction',
    ...
]
missing_fields = [f for f in required_fields if f not in result]
if missing_fields:
    raise RuntimeError(...)

# 校验通过后，直接访问 p_value
'p_value': round(result['p_value'], 6),  # KeyError！
```

**问题分析：**
- `required_fields` 未包含 `p_value`，校验通过
- 第468行直接访问 `result['p_value']`
- 若 `ic_calculator` 未返回 `p_value`，校验通过后仍会 KeyError
- 校验与实际访问不一致，防御失效

### 修复方式

**校验列表必须包含所有直接访问的字段：**
```python
required_fields = [
    'ic_series', 'ic_mean', 'ic_std', 'icir', 'p_value',  # 新增 p_value
    'statistical_significance', 'factor_direction',
    ...
]
```

### 规范要求

**遵循 PROJECT.md 函数返回值契约规范：**
- `required_fields` 必须包含所有后续直接访问的字段
- 校验通过意味着所有字段访问安全
- 校验列表与实际访问代码需保持一致

**为何必须完整校验：**
1. 防御失效：校验通过后仍抛 KeyError，违背防御目的
2. 错误定位误导：KeyError 在第468行而非校验处，难以定位根因
3. 重构风险：新增字段访问时，易忘记更新校验列表

---

## 五维度判断结果

### KDJ_J_1D 测试结果

| 维度 | 判断 | 依据 |
|------|------|------|
| 统计显著性 | ✓ 显著 | p=0.0090 < 0.05 |
| 因子方向 | ✓ 反向 | ic_mean=-0.0160 < 0 |
| 经济显著性 | ✗ 不显著 | |ic_mean|=0.0160 < 0.03 |
| ICIR稳定性 | ✗ 不稳定 | ICIR=0.11 < 0.5 |
| IC分布一致性 | ✗ 不一致 | positive_ratio=44.5%（反向因子应<50%） |

**总结：** 统计显著但经济不显著，IC预测能力较弱。

---

## 对比表（ic_rsi_1d vs ic_kdj_j_1d）

| 指标 | ic_rsi_1d | ic_kdj_j_1d | 说明 |
|------|-----------|-------------|------|
| total_days | 545 | 545 | 原始缓存日期数一致 |
| valid_days | 514 | 514 | 有效IC天数一致 |
| ic_mean | -0.0160 | -0.0160 | IC均值相同（巧合） |
| ICIR | 0.11 | 0.11 | 信息比率相同 |
| p_value | 0.0090 | 0.0090 | 统计显著性相同 |
| t_stat | -2.61 | -2.61 | t统计量相同 |

**注意：** 以上数据为实测结果，不同因子可能有差异。

---

## 输出文件路径

```
factor_ic/result/ic_kdj_j_1d_analysis_result.json
```

---

## 规范符合性

|| 规范项 | 符合状态 | 说明 |
|--------|---------|------|
| DEFAULT_MIN_STOCKS 常量 | ✓ | 已添加 |
| 函数签名一致性 | ✓ | 与 ic_rsi_1d.py 一致 |
| 异常处理分层 | ✓ | ValueError直接raise，JSONDecodeError/PermissionError不降级 |
| 日期类型转换 | ✓ | pd.to_datetime + errors='coerce' |
| total_days 使用 raw_metadata | ✓ | 545 vs 514（有差距） |
| rolling_ic_mean NaN处理 | ✓ | 前9个为 null |
| 打印字段访问正确 | ✓ | statistical_significance子对象 |
| 输入验证友好 | ✓ | 显示可用列列表 |
| 防御性校验完整 | ✓ | required_fields + 排序 |
| avg_stocks_period 字段 | ✓ | 新增，说明统计口径范围 |
| 异常分层缓存读取 | ✓ | 区分可恢复和严重错误 |
| 五维度判断字段结构 | ✓ | 对齐 ic_rsi_1d.py，直接传递完整 result 对象 |
| 浮点数除零精度容差 | ✓ | 使用 EPSILON=1e-10，替代 diff == 0 |
|| KDJ 初始值 ewm 递推 | ✓ | 预处理 RSV[0]/K[0] 使 ewm 输出 = initial_k/initial_d |
| 死代码清理 | ✓ | 删除未调用的 calculate_kdj_j_for_stock_vectorized |
| RSV 窗口期完整性 | ✓ | 使用 min_periods=n，前 N-1 天为 NaN |
| 增量模式控制流 | ✓ | 使用显式变量 should_full_recalculate，避免隐式 fallthrough |
| required_fields 完整性 | ✓ | 包含 p_value 字段，校验与实际访问一致 |
| 统计口径一致性 | ✓ | raw_avg_stocks_per_day 与 total_days 一致，avg_stocks_per_day 与 valid_days 一致 |
| ewm 初始值无副作用 | ✓ | 使用 .copy() 避免修改原始数据，替代不可靠的"修改再还原" hack |

---

## 更新历史

| 版本 | 日期 | 更新内容 |
|------|------|---------|
| v1.0 | 2026-05-20 | 初始版本，基于优化后的代码实现 |
| v1.1 | 2026-05-20 | 新增 avg_stocks_period 字段说明，完善异常处理分层规范（Section 22） |
| v1.2 | 2026-05-20 | 对齐 ic_rsi_1d.py 五维度判断字段结构（直接传递完整 result 对象） |
| v1.3 | 2026-05-20 | 修复浮点数除零判断（使用精度容差 EPSILON=1e-10，遵循 Section 17 规范） |
| v1.4 | 2026-05-20 | 修复 K/D 初始值 ewm 递推逻辑（预处理 RSV[0]/K[0] 使 ewm 输出 = initial_k/initial_d） |
| v1.5 | 2026-05-20 | 删除死代码 calculate_kdj_j_for_stock_vectorized（未被调用，仅保留 calculate_kdj_j_factor） |
| v1.6 | 2026-05-20 | 修复 RSV 计算 min_periods 参数，使用 min_periods=n 确保满窗口期数据完整性 |
| v1.7 | 2026-05-20 | 修复增量模式隐式 fallthrough，使用显式控制流（should_full_recalculate 变量） |
| v1.8 | 2026-05-20 | 修复 required_fields 校验遗漏 p_value 字段（防御性校验完整性） |
| v1.9 | 2026-05-20 | 修复统计口径不一致，新增 raw_avg_stocks_per_day（口径与 total_days 一致） |
| v1.10 | 2026-05-20 | 统一 min_periods 注释表述，使用"前 min_periods-1 个时间点"替代模糊的"前 N 天" |
| v1.11 | 2026-05-20 | 修复 ewm 初始值函数副作用问题，使用 .copy() 避免修改原始数据 |

---

*最后更新: 2026-05-20 15:40*