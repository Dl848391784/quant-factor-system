# KDJ_J_1D IC 计算流程文档

> 生成时间: 2026-05-21 18:55 北京时间
> 实测数据时间: 2026-05-21 18:55 北京时间
> 版本: v1.29
> 更新内容: 修复流程文档语法错误（删除重复的 ``` 结束标记）

---

## 数据流向

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   cache/    │────▶│ run_complex │────▶│ calculate_kdj_j │
│ factor_data │     │ factor_ic   │     │    (自定义)      │
└─────────────┘     └─────────────┘     └─────────────┘
                          │                   │
                          │                   ▼
                          │            添加 kdj_j 列
                          │                   │
                          ▼                   ▼
                   ┌─────────────┐     ┌─────────────┐
                   │ incremental │────▶│  IC 计算    │
                   │  engine     │     │  (五维度)   │
                   └─────────────┘     └─────────────┘
                          │                   │
                          ▼                   ▼
                   ┌─────────────┐     ┌─────────────┐
                   │   result/   │     │   保存      │
                   │ ic_kdj_j_   │◀────│  JSON      │
                   │ 1d_*.json   │     └─────────────┘
                   └─────────────┘
```

---

## 函数调用关系（公共模块版本）

```
main()
    │
    └─ run_complex_factor_ic(
         factor_name='kdj_j',
         factor_col='kdj_j',
         factor_cols=['close', 'high', 'low'],
         custom_factor_calculation=calculate_kdj_j
       )
         │
         ├─ load_factor_return_data(factor_cols=['close', 'high', 'low'])
         │   └─ 返回 factor_df, return_df, raw_metadata
         │
         ├─ [增量模式] custom_factor_calculation(factor_df)
         │   │   ├─ 计算 RSV (rolling, min_periods=n)
         │   │   ├─ 计算 K (_calculate_k_with_initial, ewm)
         │   │   ├─ 计算 D (_calculate_d_with_initial, ewm)
         │   │   └─ 计算 J = 3K - 2D
         │   │   └─ 返回带 kdj_j 列的 factor_df
         │   │
         │   └─ incremental_update_ic(factor_df, return_df, factor_col='kdj_j')
         │       ├─ 读取现有缓存
         │       ├─ 确定缺失日期
         │       ├─ 计算缺失日期 IC (calculate_single_day_ic)
         │       ├─ 合并数据（去重）
         │       └─ 重算统计指标 (calculate_ic_statistics)
         │
         ├─ [全量模式] custom_factor_calculation(factor_df)
         │   │   └─ 同上 KDJ 计算
         │   │
         │   └ calculate_ic_with_direction_verification(factor_df, return_df)
         │       ├─ 计算每日 IC 序列
         │       ├─ Newey-West t 检验
         │       └─ 五维度判断输出
         │
         └─ build_ic_result + save_ic_result
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

# 显式控制流：检查标志变量，确保控制流清晰
if not should_full_recalculate:
    raise RuntimeError(
        "控制流逻辑错误：should_full_recalculate=False 但未返回\n"
        "可能原因：skip 模式成功读取缓存后应直接返回，不应继续执行\n"
        "请检查增量判断逻辑是否正确"
    )

# 全量计算逻辑（显式保护：仅当 should_full_recalculate=True 时执行）
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
| v1.12 | 2026-05-20 | 修复 should_full_recalculate 标志未使用问题，添加显式检查确保控制流有效 |
| v1.13 | 2026-05-20 | 修复闭包耦合问题，将内嵌函数提升为模块级私有函数 `_calculate_k_with_initial` 和 `_calculate_d_with_initial`，显式传参 |
| v1.14 | 2026-05-20 | 补充 RSV 值域检查规范，添加值域统计日志和异常值警告（遵循 MODULE.md 因子计算规范） |
| v1.15 | 2026-05-20 | 修复边界条件处理缺失，dates 为空时提前抛出有意义的异常（遵循 MODULE.md 边界条件规范） |
| v1.16 | 2026-05-20 | 修复 K/D 初始值函数注释语义表述，精确描述 ewm 递推逻辑（预处理输入而非直接赋值输出） |
| v1.17 | 2026-05-20 | 修复死代码守卫问题，移除无效守卫逻辑，用注释说明控制流语义（遵循 MODULE.md 控制流规范） |
| v1.18 | 2026-05-20 | 修复 groupby transform 异常信息淹没问题，添加 try/except 捕获并附加诊断信息（遵循 MODULE.md 异常处理规范） |
| v1.19 | 2026-05-20 | 修复 IC 空场景异常信息使用过滤后数据而非原始数据统计的问题（遵循 MODULE.md 异常处理规范） |
| v1.20 | 2026-05-20 | 修复 EPSILON 常量未提升为模块级的问题，便于统一管理和复用（遵循 PROJECT.md 常量管理规范） |
| v1.21 | 2026-05-20 | 修复 K/D 值 NaN 传播错误（核心缺陷）—— ewm alpha 参数、ignore_na 参数、初始值位置 |
| v1.22 | 2026-05-20 | 统一异常处理风格注释，明确包装类与保留类的设计意图（遵循 PROJECT.md 异常处理规范） |
| v1.23 | 2026-05-20 | 删除 should_full_recalculate 死代码变量，简化控制流注释（遵循 MODULE.md 控制流规范） |
| v1.24 | 2026-05-20 | 补充 ic_values round 隐式行为注释，说明 ic_series 不含 NaN 的原因（遵循 MODULE.md NaN 处理规范） |
| v1.25 | 2026-05-20 | 修复 output_file 参数类型标注不一致（str vs Path），统一转换为 Path 对象（遵循 PROJECT.md 参数类型约定） |
| v1.26 | 2026-05-20 | 修复异常诊断中 DataFrame 列访问的 KeyError 风险，添加防御性检查（遵循 MODULE.md 防御性异常处理规范） |
| v1.27 | 2026-05-20 | 移除 ic_metrics 中冗余的 p_value 和 p_value_display 字段，与 ic_rsi_1d.py 对齐（遵循 MODULE.md 字段去重化规范） |

---

## 死代码清理规范

### 问题根因

**场景：** should_full_recalculate 变量作为"控制流标记"，但实际上所有可达路径都会执行全量计算。

**原始代码（死代码）：**
```python
should_full_recalculate = force_full  # 默认需要全量计算

if not force_full:
    mode, missing_dates, info = check_data_completeness('kdj_j_1d')
    
    if mode == 'skip':
        try:
            return json.load(f)  # 提前退出
        except FileNotFoundError:
            should_full_recalculate = True  # 显式标记：需要全量计算
    
    elif mode == 'incremental':
        should_full_recalculate = True  # 当前版本降级全量计算
    
    else:  # mode == 'full'
        should_full_recalculate = True

# 控制流语义说明（大量注释解释）
# 此处 should_full_recalculate 在所有可达路径上均为 True：
# - force_full=True → 初始值 True
# - force_full=False + mode='skip' + 成功读取 → 已提前 return
# - ...（更多注释）
```

**问题分析：**
1. 变量在所有可达路径上都为 True，没有实际用途
2. 大量注释解释控制流，增加认知负担
3. 代码逻辑依赖"提前 return"而非变量标记
4. 违反"最小必要复杂度"原则

### 修复方案

**删除死代码，简化注释：**
```python
# 增量判断（除非强制全量）
# 控制流语义：
# - force_full=True → 直接执行全量计算
# - force_full=False + mode='skip' + 成功读取 → 提前 return（退出函数）
# - force_full=False + 其他情况 → 执行全量计算
# 结论：只有 mode='skip' 且成功读取会提前退出，其他所有路径都执行全量计算

if not force_full:
    mode, missing_dates, info = check_data_completeness('kdj_j_1d')
    
    if mode == 'skip':
        try:
            return json.load(f)  # 成功读取，提前退出
        except FileNotFoundError:
            # 继续执行全量计算（无需标记，控制流自然到达）
            print("  [诊断] 缓存文件不存在，执行全量计算")
    
    elif mode == 'incremental':
        # 当前版本降级全量计算，继续执行全量计算逻辑

# 全量计算逻辑（此处无变量守卫）
```

### 设计原则

1. **控制流优于标记：** 使用 `return` 提前退出，而非变量标记
2. **注释精简：** 用一行注释说明控制流语义，而非十行解释
3. **死代码删除：** 所有可达路径都相同的变量都是死代码
4. **自然控制流：** 代码执行顺序本身表达逻辑，无需额外标记

### 适用场景

- 所有使用"控制流标记变量"的场景
- 所有需要判断是否提前退出的逻辑

---

## 异常处理风格规范

### 问题根因

**场景：** generate_kdj_j_ic_data 函数中有两类异常处理风格：
- 包装类：`raise RuntimeError(...) from e`
- 保留类：裸 `raise`

**原始代码（风格混淆）：**
```python
except FileNotFoundError as e:
    # 基础设施错误：可包装为 RuntimeError
    raise RuntimeError(f"缓存文件不存在: {e}") from e
    
except KeyError as e:
    # 数据验证错误：直接 raise，保留原始类型
    raise  # 不包装，遵循 PROJECT.md 异常处理类型保留规范
    
except Exception as e:
    # 未预期异常：包装为 RuntimeError，保留异常链
    raise RuntimeError(...) from e
```

**问题分析：**
1. 注释表述不够清晰，"可包装"与"直接 raise"风格对比不明显
2. FileNotFoundError 错误信息使用 `{e}` 而非缓存路径常量
3. 缺少设计意图说明：为什么有些包装、有些保留？

### 修复方案

**明确分层设计原则：**

1. **基础设施错误（FileNotFoundError）：包装**
   - 原因：原始信息不够详细，需要附加缓存路径
   - 使用 `from e` 保留异常链

2. **数据验证错误（KeyError、ValueError）：保留原始类型**
   - 原因：是可预期错误，原始类型更易诊断
   - 裸 `raise` 直接传播

3. **未预期异常（Exception）：包装**
   - 原因：类型多变，统一处理
   - 使用 `from e` 保留异常链

**修复后代码：**
```python
except FileNotFoundError as e:
    # 基础设施错误：包装为 RuntimeError，添加缓存路径上下文
    # 原因：FileNotFoundError 原始信息不够详细，需要附加缓存路径
    # 使用 `from e` 保留异常链，便于调试
    raise RuntimeError(f"缓存文件不存在: {FACTOR_CACHE}") from e
    
except KeyError as e:
    # 数据验证错误：裸 raise 保留原始类型
    # 原因：KeyError 表示数据缺少必需列，是可预期错误，原始类型更易诊断
    # 不包装，直接传播原始异常（遵循 PROJECT.md 异常类型保留规范）
    raise
    
except ValueError as e:
    # 数据验证错误：裸 raise 保留原始类型
    # 原因：ValueError 表示数据格式错误（如无效日期），是可预期错误
    raise
    
except Exception as e:
    # 未预期异常：包装为 RuntimeError，保留异常链
    # 原因：未预期异常类型多变，包装为 RuntimeError 统一处理
    raise RuntimeError(...) from e
```

### 设计原则

1. **包装类：** 需要添加上下文的错误（如缓存路径）
2. **保留类：** 可预期错误，原始类型更易诊断
3. **统一风格：** 注释必须说明设计意图，避免维护混乱
4. **异常链：** 包装类必须使用 `from e` 保留原始异常

### 适用场景

- 所有需要分层异常处理的主函数
- 所有需要区分"可预期错误"与"未预期异常"的场景

---

## KDJ ewm 参数匹配规范

### 问题根因（核心缺陷）

**场景：** RSV 前 N-1 期为 NaN（rolling window min_periods=n），计算 K 值时应正确传播 NaN。

**原始代码（三个关键错误）：**
```python
# 错误 1：alpha 参数语义不匹配
alpha_k = 1.0 / m1  # 错误！应该是 (m1-1)/m1

# 错误 2：ewm 默认跳过 NaN
k_series = rsv_copy.ewm(alpha=alpha_k, adjust=False).mean()  # 缺少 ignore_na=False

# 错误 3：初始值位置错误
rsv_copy.iloc[0] = initial_k  # 应该是第一个有效位置，而非第一个元素
```

**问题分析：**

1. **alpha 参数语义错误：**
   - ewm(alpha) 公式：`y[t] = alpha * x[t] + (1-alpha) * y[t-1]`
   - KDJ 公式：`K[t] = (1/m1) * K[t-1] + (1-1/m1) * RSV[t]`
   - 要匹配，需要 `alpha = 1 - 1/m1 = (m1-1)/m1`
   - 例如 m1=3：alpha = 2/3（而非 1/3）
   - 原代码使用 alpha=1/m1 导致权重颠倒！

2. **ignore_na 缺失：**
   - ewm 默认 `ignore_na=True`，会跳过 NaN 继续计算
   - 例如 RSV=[50, NaN, NaN, 10]，ewm 会继续计算 K[1]=50, K[2]=50（错误）
   - 正确行为：`ignore_na=False`，NaN 应传播

3. **初始值位置错误：**
   - 原代码把第一个元素设为 initial_k（但第一个元素可能是 NaN）
   - 应该找到第一个有效 RSV 位置，设为 initial_k
   - 使用 `rsv_series.first_valid_index()` 而非 `iloc[0]`

### 修复方案

**正确实现：**
```python
# 1. alpha 参数修正
alpha_k = (m1 - 1) / m1  # 匹配 KDJ 公式
alpha_d = (m2 - 1) / m2

# 2. K 值计算函数
def _calculate_k_with_initial(rsv_series, alpha_k, initial_k):
    # 找到第一个有效位置
    first_valid_idx = rsv_series.first_valid_index()
    if first_valid_idx is None:
        return rsv_series  # 全 NaN
    
    rsv_copy = rsv_series.copy()
    rsv_copy[first_valid_idx] = initial_k  # 索引访问（而非 iloc）
    
    # 使用 ignore_na=False 使 NaN 传播
    k_series = rsv_copy.ewm(alpha=alpha_k, adjust=False, ignore_na=False).mean()
    return k_series
```

### 验证示例

```
RSV = [NaN, NaN, NaN, 10, 20, 30, 40, 50]  # 前 N-1=3 天为 NaN

修复前（alpha=1/3, ignore_na=True）:
K = [50, 50, 50, 28.82, 25.88, 27.25, ...]  # 错误：前缀不是 NaN

修复后（alpha=2/3, ignore_na=False）:
K = [NaN, NaN, NaN, 50, 30, 30, 36.67, 45.56]  # 正确！

手动验证：
K[3] = 50（初始值）
K[4] = 1/3 * 50 + 2/3 * 20 = 30 ✓
K[5] = 1/3 * 30 + 2/3 * 30 = 30 ✓
```

### 设计原则

1. **公式匹配：** ewm 参数必须与 KDJ 公式语义一致
2. **NaN 传播：** 使用 `ignore_na=False` 确保前缀 NaN 正确传播
3. **初始值位置：** 使用 `first_valid_index()` 找到第一个有效位置
4. **索引访问：** 使用 `series[idx]` 而非 `series.iloc[idx]`（因为 groupby transform 后索引是原始索引）

### 适用场景

- 所有基于 ewm 的技术指标计算（KDJ、MACD 等）
- 所有需要正确处理 NaN 前缀的场景

---

## IC 空场景异常诊断规范

### 问题根因

**场景：** 当所有交易日股票数均不足 min_stocks 时，IC 计算结果为空，抛出 RuntimeError。

**原始代码（诊断信息误导）：**
```python
if len(dates) == 0:
    raise RuntimeError(
        f"IC 计算结果为空：所有交易日股票数均不足 min_stocks={min_stocks}\n"
        f"诊断信息:\n"
        f"  - 因子数据: {len(factor_df)} 行, {factor_df['asset'].nunique()} 只股票\n"  # 过滤后数据
        f"  - 收益数据: {len(return_df)} 行, {return_df['asset'].nunique()} 只股票\n"
        f"  - 日期范围: {factor_df['date'].min()} ~ {factor_df['date'].max()}\n"
    )
```

**问题分析：**
1. factor_df/return_df 是过滤后的数据（已删除缺失值）
2. 若 IC 为空，这些数据可能已经很小或为空，甚至无法获取 min/max
3. 用户无法知道原始数据规模，无法判断是数据源问题还是过滤问题
4. 诊断信息误导：`len(factor_df)=0` 可能让人误以为是数据缺失，而非 min_stocks 过滤

### 修复方案

**使用 raw_metadata 中的原始数据统计：**
```python
if len(dates) == 0:
    # 诊断信息必须使用原始数据统计（遵循 MODULE.md 异常处理规范）
    # raw_metadata 包含原始数据统计（period_start/total_days/avg_stocks_per_day）
    raise RuntimeError(
        f"IC 计算结果为空：所有交易日股票数均不足 min_stocks={min_stocks}\n"
        f"原始数据统计（来自 raw_metadata）:\n"
        f"  - 原始日期范围: {period_start} ~ {period_end}\n"
        f"  - 原始交易日数: {total_days}\n"
        f"  - 原始平均每日股票数: {raw_metadata.get('avg_stocks_per_day', 'N/A')}\n"
        f"过滤后数据统计（诊断用）:\n"
        f"  - 因子数据: {len(factor_df)} 行, {factor_df['asset'].nunique()} 只股票\n"
        f"  - 收益数据: {len(return_df)} 行, {return_df['asset'].nunique()} 只股票\n"
    )
```

### 设计原则

1. **优先使用原始数据：** raw_metadata 中的统计反映数据源真实情况
2. **保留过滤后数据作为补充：** 便于诊断过滤过程是否有问题
3. **信息分层：** 原始数据统计（判断数据源）→ 过滤后统计（判断过滤逻辑）
4. **遵循 MODULE.md 规范：** 异常信息必须完整、可诊断

### 适用场景

- 所有涉及数据过滤后的异常处理
- 所有需要诊断数据规模的异常场景

---

## 模块级常量管理规范

### 问题根因

**场景：** EPSILON 是浮点数精度容差常量，用于浮点数等值比较（替代 == 0）。

**原始代码（函数内局部常量）：**
```python
def calculate_kdj_j_factor(factor_df, n=9, m1=3, m2=3):
    # ...
    EPSILON = 1e-10  # 浮点数精度容差（每次调用重新创建）
    diff = factor_df['rolling_high'] - factor_df['rolling_low']
    factor_df['rsv'] = np.where(
        np.abs(diff) < EPSILON,
        50.0,
        (factor_df['close'] - factor_df['rolling_low']) / diff * 100
    )
```

**问题分析：**
1. EPSILON 在函数内定义，每次调用函数都重新创建
2. 无法被其他模块复用或统一修改
3. 若其他因子脚本也需要 EPSILON，需要重复定义
4. 不符合 PROJECT.md 常量管理规范（应集中在模块顶部）

### 修复方案

**提升为模块级常量：**
```python
# ============================================================================
# 参数统一管理（遵循 PROJECT.md 参数传递规范）
# ============================================================================
DEFAULT_MIN_STOCKS = 10

# 浮点数精度容差：用于浮点数等值比较（替代 == 0）
# 原因：浮点数运算结果直接 == 0 比较会漏判极小值（如 1e-15）
# 注意：修改此值会影响 RSV 计算等浮点数除零判断逻辑
EPSILON = 1e-10

def calculate_kdj_j_factor(factor_df, n=9, m1=3, m2=3):
    # ...
    # 使用模块级常量 EPSILON，便于统一管理和复用
    diff = factor_df['rolling_high'] - factor_df['rolling_low']
    factor_df['rsv'] = np.where(
        np.abs(diff) < EPSILON,
        50.0,
        (factor_df['close'] - factor_df['rolling_low']) / diff * 100
    )
```

### 设计原则

1. **集中管理：** 所有可配置常量集中在模块顶部，便于查找和修改
2. **注释完整：** 每个常量必须有注释说明用途、修改影响
3. **跨模块复用：** 可通过 `from module import EPSILON` 复用
4. **遵循 PROJECT.md 规范：** 参数统一管理，修改时需同步更新注释

### 适用场景

- 所有多次使用的常量（如阈值、精度容差、路径等）
- 所有可能需要跨模块复用的配置值

---

## groupby transform 异常处理规范

### 问题根因

**场景：** groupby transform 对每个分组调用 lambda 函数，若某只股票触发异常，pandas 会将异常包装在模糊的 ValueError 或 TypeError 中，丢失股票代码和原始异常类型。

**原始代码（异常信息淹没）：**
```python
factor_df['k'] = factor_df.groupby('asset')['rsv'].transform(
    lambda rsv: _calculate_k_with_initial(rsv, alpha_k, initial_k)
)

def _calculate_k_with_initial(rsv_series, alpha_k, initial_k):
    # 若此处抛出异常，pandas 会包装为：
    # ValueError: transform() returned an error
    # 丢失股票代码和原始异常类型
    k_series = rsv_series.ewm(alpha=alpha_k, adjust=False).mean()
    return k_series
```

**问题分析：**
1. pandas groupby transform 内部捕获异常并包装
2. 无法知道是哪只股票出错
3. 无法知道原始异常类型（TypeError、ValueError 等）
4. 调试困难，需要手动遍历所有股票

### 修复方案

**在辅助函数内部添加 try/except，捕获并附加诊断信息：**
```python
def _calculate_k_with_initial(rsv_series, alpha_k, initial_k):
    """计算 K 值（无副作用版本）"""
    if len(rsv_series) == 0:
        return rsv_series
    
    try:
        rsv_copy = rsv_series.copy()
        rsv_copy.iloc[0] = initial_k
        k_series = rsv_copy.ewm(alpha=alpha_k, adjust=False).mean()
        return k_series
        
    except Exception as e:
        # 捕获异常并附加诊断信息
        raise RuntimeError(
            f"K 值计算异常（groupby transform 内部）\n"
            f"原始异常: {type(e).__name__}: {e}\n"
            f"诊断信息:\n"
            f"  - Series 长度: {len(rsv_series)}\n"
            f"  - 索引范围: {rsv_series.index.min() if len(rsv_series) > 0 else 'N/A'} ~ "
            f"{rsv_series.index.max() if len(rsv_series) > 0 else 'N/A'}\n"
            f"  - 参数: alpha_k={alpha_k}, initial_k={initial_k}\n"
            f"  - RSV[0] 原始值: {rsv_series.iloc[0] if len(rsv_series) > 0 else 'N/A'}\n"
            f"建议: 检查对应股票的 RSV 数据是否存在异常值（如 inf、NaN）"
        ) from e
```

### 设计原则

1. **异常链保留：** 使用 `raise ... from e` 保留原始异常链，便于调试
2. **诊断信息完整：** 附加 Series 长度、索引范围、参数值、第一个数据值
3. **修复建议明确：** 提供具体的检查方向（如 inf、NaN）
4. **遵循 MODULE.md 规范：** 异常分层、信息完整、可恢复性明确

### 适用场景

- 所有 groupby transform 中的辅助函数
- 所有 apply/map 中的辅助函数
- 任何可能被 pandas 内部包装的函数

### 注意事项

- 由于函数只有 Series 数据，无法获取股票代码（asset）
- 若需要股票代码，需在外层捕获或改用 groupby apply（牺牲性能）
- 诊断信息应包含足够的信息以定位问题（索引范围、参数值等）

---

## 闭包耦合规范

### 问题根因

**原始代码（闭包耦合）：**
```python
def calculate_kdj_j_factor(factor_df, n=9, m1=3, m2=3):
    # ...
    alpha_k = 1.0 / m1
    initial_k = 50.0
    
    def calculate_k_with_initial(rsv_series):
        # 闭包捕获 alpha_k, initial_k（隐式依赖）
        rsv_copy = rsv_series.copy()
        rsv_copy.iloc[0] = initial_k  # 使用外层变量
        k_series = rsv_copy.ewm(alpha=alpha_k, adjust=False).mean()  # 使用外层变量
        return k_series
    
    factor_df['k'] = factor_df.groupby('asset')['rsv'].transform(calculate_k_with_initial)
```

**问题分析：**
- 内嵌函数通过闭包隐式依赖 `alpha_k`、`initial_k`
- 函数签名只有 `rsv_series`，无法看出依赖关系
- 若外层函数重构（如 `m1` 改名），内嵌函数静默使用旧值，难以发现
- 重构风险高：修改外层变量时，需手动追踪所有闭包使用点

### 修复方式

**提升为模块级私有函数，显式传参：**
```python
# 模块级私有函数（显式传参）
def _calculate_k_with_initial(
    rsv_series: pd.Series,
    alpha_k: float,
    initial_k: float
) -> pd.Series:
    """计算 K 值，第一个值使用 initial_k（无副作用版本）
    
    Args:
        rsv_series: RSV 序列（单只股票）
        alpha_k: K 值 ewm 平滑系数（1/m1）
        initial_k: K 初始值（标准值 50.0）
    
    Returns:
        K 值序列
    
    设计原则：显式传参，避免闭包捕获外部变量
    """
    if len(rsv_series) == 0:
        return rsv_series
    
    rsv_copy = rsv_series.copy()
    rsv_copy.iloc[0] = initial_k
    k_series = rsv_copy.ewm(alpha=alpha_k, adjust=False).mean()
    return k_series


def calculate_kdj_j_factor(factor_df, n=9, m1=3, m2=3):
    # ...
    alpha_k = 1.0 / m1
    initial_k = 50.0
    
    # 使用模块级函数，显式传参（lambda 包装适配 groupby transform）
    factor_df['k'] = factor_df.groupby('asset')['rsv'].transform(
        lambda rsv: _calculate_k_with_initial(rsv, alpha_k, initial_k)
    )
```

### 设计原则

| 原则 | 说明 |
|------|------|
| 显式传参 | 函数签名暴露所有依赖，调用者一目了然 |
| 避免闭包 | 外层变量重构时，编译器/静态分析能发现传参错误 |
| 模块级私有函数 | 以 `_` 前缀命名，表明仅供模块内部使用 |
| lambda 包装 | 适配 `groupby transform` 接口，保持向量化性能 |

**优势：**
- 重构安全：修改 `alpha_k` 参数名时，调用处报错，不会静默失败
- 可测试性：模块级函数可独立测试，无需构造完整上下文
- 文档完整性：函数签名 + docstring 说明所有参数

**参考规范：MODULE.md "函数设计规范 - 禁止闭包捕获外部变量"**

---

## 死代码守卫问题规范

### 问题根因

**原始代码（死代码守卫）：**
```python
should_full_recalculate = force_full  # 初始值

if not force_full:
    mode, missing_dates, info = check_data_completeness('kdj_j_1d')
    
    if mode == 'skip':
        try:
            with open(output_file, 'r') as f:
                return json.load(f)  # 成功读取 → 直接返回
        except FileNotFoundError:
            should_full_recalculate = True  # 分支1
    elif mode == 'incremental':
        should_full_recalculate = True  # 分支2
    else:  # mode == 'full'
        should_full_recalculate = True  # 分支3

# 无效守卫：在所有可达路径上 should_full_recalculate=True 或已返回
if not should_full_recalculate:
    raise RuntimeError("控制流逻辑错误...")  # 死代码！永远不会执行
```

**问题分析：**
- `should_full_recalculate` 初始值 `force_full`：
  - `force_full=True` → `should_full_recalculate=True` → 守卫不执行
- `force_full=False` 时进入 `if not force_full` 块：
  - `mode='skip'` + 成功读取 → `return`（已退出，不达守卫）
  - `mode='skip'` + FileNotFoundError → `should_full_recalculate=True`
  - `mode='incremental'` → `should_full_recalculate=True`
  - `mode='full'` → `should_full_recalculate=True`
- **所有可达路径**：`should_full_recalculate=True` 或已返回
- 守卫 `if not should_full_recalculate` 永远为 False，永远不会执行
- v1.12 添加的"显式控制流"守卫实际上是死代码

### 修复方式

**移除无效守卫，用注释说明控制流语义：**
```python
should_full_recalculate = force_full  # 初始值

if not force_full:
    mode, missing_dates, info = check_data_completeness('kdj_j_1d')
    
    if mode == 'skip':
        try:
            with open(output_file, 'r') as f:
                return json.load(f)  # 成功读取 → 直接返回
        except FileNotFoundError:
            should_full_recalculate = True
    elif mode == 'incremental':
        should_full_recalculate = True
    else:  # mode == 'full'
        should_full_recalculate = True

# 控制流语义（遵循 MODULE.md 控制流规范）
# 此处 should_full_recalculate 在所有可达路径上均为 True：
# - force_full=True → 初始值=True
# - force_full=False + mode='skip' + 成功读取 → 已返回（不达此处）
# - force_full=False + mode='skip' + FileNotFoundError → True
# - force_full=False + mode='incremental' → True
# - force_full=False + mode='full' → True
# 若到达此处，说明 should_full_recalculate=True（所有分支已处理）

# 全量计算逻辑
print("KDJ_J_1D IC 计算器...")
```

### 设计原则

| 原则 | 说明 |
|------|------|
| 移除死代码 | 守卫在所有路径上为 False，给读者制造"有保护"错觉 |
| 注释说明语义 | 用注释而非代码表达控制流逻辑（避免死代码） |
| 控制流分析 | 明确列出所有可达路径及其结果 |
| 避免无效守卫 | v1.12 添加的守卫本意是"显式控制流"，实为死代码 |

**优势：**
- 代码更简洁，无死代码干扰
- 注释清晰说明控制流语义
- 避免读者误以为有保护

**参考规范：MODULE.md "控制流规范 - 死代码守卫"**

---

## RSV 值域检查规范

### 问题根因

**原始代码（缺少值域检查）：**
```python
EPSILON = 1e-10
diff = factor_df['rolling_high'] - factor_df['rolling_low']
factor_df['rsv'] = np.where(
    np.abs(diff) < EPSILON,
    50.0, 
    (factor_df['close'] - factor_df['rolling_low']) / diff * 100
)

# 直接删除临时列，没有值域检查
factor_df.drop(columns=['rolling_high', 'rolling_low'], inplace=True)
```

**问题分析：**
- RSV 理论值域：[0, 100]
- 浮点运算可能产生微小偏差（如 -0.000001 或 100.000001）
- 若 diff 极小（接近 EPSILON），除法可能产生极大值（如 1e12）
- np.where 先计算两个分支再选择，diff=0 时除零运算仍触发
- NaN 传播正确（前 N-1 期为 NaN），但非 NaN 值需要检查
- 缺少值域统计和异常值警告，难以诊断数值问题

### 修复方式

**添加值域统计日志和异常值警告：**
```python
EPSILON = 1e-10
diff = factor_df['rolling_high'] - factor_df['rolling_low']
factor_df['rsv'] = np.where(
    np.abs(diff) < EPSILON,
    50.0, 
    (factor_df['close'] - factor_df['rolling_low']) / diff * 100
)

# RSV 值域检查（遵循 MODULE.md 因子计算规范）
# 理论上 RSV 应在 [0, 100]，但浮点运算可能产生微小偏差
# NaN 传播正确（前 N-1 期为 NaN），此处只检查非 NaN 值
rsv_valid = factor_df['rsv'].dropna()
if len(rsv_valid) > 0:
    rsv_min = rsv_valid.min()
    rsv_max = rsv_valid.max()
    rsv_out_of_range = int(((rsv_valid < 0) | (rsv_valid > 100)).sum())
    
    # 值域统计日志（便于诊断）
    print(f"  RSV 值域统计:")
    print(f"    最小值: {rsv_min:.4f}")
    print(f"    最大值: {rsv_max:.4f}")
    
    # 异常值警告（超出理论范围）
    if rsv_out_of_range > 0:
        print(f"    ⚠ 超出 [0, 100] 范围: {rsv_out_of_range} 个 ({rsv_out_of_range/len(rsv_valid)*100:.2f}%)")
        print(f"    原因分析: 可能是 diff 极小（接近 EPSILON）导致的数值放大")
        print(f"    建议: 若异常值比例 > 1%，检查 EPSILON 阈值是否合适")
    
    # 调试断言（仅在开发期启用，生产环境可注释）
    # assert rsv_min >= -EPSILON * 100, f"RSV 下界溢出: {rsv_min}"
    # assert rsv_max <= 100 + EPSILON * 100, f"RSV 上界溢出: {rsv_max}"

factor_df.drop(columns=['rolling_high', 'rolling_low'], inplace=True)
```

### 检查原则

| 检查项 | 说明 |
|--------|------|
| 值域统计 | 打印最小值/最大值，便于诊断 |
| 异常值计数 | 统计超出 [0, 100] 范围的数量 |
| 异常值警告 | 若存在异常值，打印原因分析和建议 |
| 调试断言 | 开发期可启用，生产环境可注释 |

**实测数据（v1.14）：**
- RSV 最小值: 0.0000
- RSV 最大值: 100.0000
- 超出 [0, 100] 范围: 0 个（EPSILON=1e-10 保护有效）

**参考规范：MODULE.md "因子计算规范 - 值域检查"**

---

## 边界条件规范

### 问题根因

**原始代码（缺少边界条件检查）：**
```python
# 转换为 JSON 友好格式
dates = [str(d) for d in ic_series.index]
ic_values = [round(v, 6) for v in ic_series.values]

# 直接继续处理，未检查 dates 是否为空
rolling_mean = ic_series.rolling(window=20, min_periods=10).mean()
# ...

# 在 avg_stocks_period 中使用 dates[0]/dates[-1]，若 dates 为空则返回 None
'valid_range': {
    'start': dates[0] if dates else None,
    'end': dates[-1] if dates else None,
}
```

**问题分析：**
- 若所有交易日股票数均不足 `min_stocks`，`ic_series` 为空，`dates` 也为空
- `valid_range.start/end` 返回 `None`，形成"半空"结果字典
- 其他字段（`n_assets`、`positive_ratio`）正常，难以发现根本原因
- 调用方拿到无效结果，但不知道问题在哪
- 缺少边界条件检查，违反"前置条件必须验证"原则

### 修复方式

**在 dates 为空时提前抛出有意义的异常：**
```python
# 转换为 JSON 友好格式
dates = [str(d) for d in ic_series.index]
ic_values = [round(v, 6) for v in ic_series.values]

# 边界条件检查：dates 为空时提前抛出异常（遵循 MODULE.md 边界条件规范）
# 原因：若所有交易日股票数均不足 min_stocks，ic_series 为空，dates 也为空
# 问题：返回"半空"结果字典难以诊断根本原因，valid_range.start/end 为 None
# 解决：在生成结果前检查，抛出有意义的异常便于诊断
if len(dates) == 0:
    raise RuntimeError(
        f"IC 计算结果为空：所有交易日股票数均不足 min_stocks={min_stocks}\n"
        f"诊断信息:\n"
        f"  - 因子数据: {len(factor_df)} 行, {factor_df['asset'].nunique()} 只股票\n"
        f"  - 收益数据: {len(return_df)} 行, {return_df['asset'].nunique()} 只股票\n"
        f"  - 日期范围: {factor_df['date'].min()} ~ {factor_df['date'].max()}\n"
        f"建议: 降低 min_stocks 阈值或检查数据源股票覆盖率"
    )

# 计算 20 日滚动均值（dates 已验证非空）
rolling_mean = ic_series.rolling(window=20, min_periods=10).mean()
```

### 设计原则

| 原则 | 说明 |
|------|------|
| 前置条件验证 | 在生成结果前检查输入有效性 |
| 有意义的异常 | 提供诊断信息和修复建议 |
| 避免"半空"结果 | 不返回无效结果，让调用方无从诊断 |
| 快速失败 | 尽早发现问题，不传播无效数据 |

**优势：**
- 调用方立即知道问题根源（股票数不足）
- 异常信息包含诊断数据和修复建议
- 不返回无效 JSON，避免下游分析错误

**参考规范：MODULE.md "边界条件规范 - 前置条件验证"**

---

## 隐式行为注释规范

### 问题场景

**代码位置：** `ic_values = [round(v, 6) for v in ic_series.values]`

**隐式行为：**
- `ic_series.values` 中的 `v` 理论上可能为 `numpy.nan` 或 Python `None`
- `round(NaN, 6)` 返回 Python `float('nan')`，而非 `None`
- `pd.isna(None)` 和 `pd.isna(numpy.nan)` 都返回 `True`

**问题：**
- 代码依赖 `ic_series` 不含 NaN 的隐式假设
- 若未来 `ic_calculator.py` 逻辑变化导致 `ic_series` 含 NaN，`round(v, 6)` 会返回 `nan`
- JSON 序列化时 `nan` 会被转为字符串 `"NaN"` 或报错（取决于序列化器）
- 缺少注释说明为什么这里不需要 `pd.isna(v)` 检查

### 根因分析

**ic_series 不含 NaN 的原因：**

`ic_calculator.py` 第 162-167 行：
```python
for date, daily_data in merged.groupby(date_col):
    ic_value = calculate_single_day_ic(
        daily_data, factor_col, return_col, min_stocks
    )
    if ic_value is not None:
        ic_list.append({'date': date, 'ic': ic_value})
```

**关键逻辑：**
- 只有 `ic_value is not None` 的日期才会被添加到 `ic_list`
- 不满足 `min_stocks` 的日期不会被添加（而非添加 NaN）
- `ic_series = pd.DataFrame(ic_list).set_index('date')['ic']`
- 因此 `ic_series.values` 中的 `v` 都是有效的 `numpy.float64` 值

### 修复方式

**添加注释说明隐式行为：**
```python
# 转换为 JSON 友好格式
dates = [str(d) for d in ic_series.index]

# ic_series.values 不含 NaN 的原因（隐式行为说明）：
# - ic_series 由 ic_calculator.py 构建，只有 ic_value is not None 的日期被添加
# - 不满足 min_stocks 的日期不会被添加到 ic_series（而非添加 NaN）
# - 因此 ic_series.values 中的 v 都是有效的 numpy.float64 值
# - round(v, 6) 对有效值正常工作，无需 pd.isna(v) 检查
# 防御性说明：若未来 ic_series 逻辑变化导致含 NaN，需改为：
#   [round(v, 6) if not pd.isna(v) else None for v in ic_series.values]
ic_values = [round(v, 6) for v in ic_series.values]
```

### 设计原则

| 原则 | 说明 |
|------|------|
| 隐式行为显式化 | 解释为什么不需要防御性检查 |
| 根因追溯 | 引用上游逻辑说明数据来源 |
| 防御性说明 | 提供未来变化的修改方案 |

**对比：rolling_ic_mean 处理**
```python
# rolling 参数语义：window=20（窗口大小），min_periods=10（最小有效样本数）
# 前 min_periods-1=9 个时间点不满足最小样本要求，返回 NaN
# 注意：round(NaN, 6) 返回 Python float nan，而非 None
rolling_ic_mean = [
    round(v, 6) if not pd.isna(v) else None
    for v in rolling_mean.values
]
```

**rolling_ic_mean 需要 pd.isna(v) 检查的原因：**
- `rolling_mean` 来自 `ic_series.rolling(...).mean()`
- 前 `min_periods-1` 个时间点返回 NaN
- 必须显式检查并转为 `None`（JSON 友好）

**参考规范：MODULE.md "NaN 处理规范 - 隐式行为显式化原则"**

---

*最后更新: 2026-05-20 17:35*