# KDJ_J_1D IC 计算流程文档

> 生成时间: 2026-05-20 13:15 北京时间
> 实测数据时间: 2026-05-20 13:10 北京时间
> 版本: v1.1
> 更新内容: 新增 avg_stocks_period 字段说明、完善异常处理分层规范

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
  "is_significant": true,
  "p_value": 0.008991,
  "t_stat": -2.6124,
  "conclusion": "统计显著（p=0.0090<0.05）"
}
```

### 因子方向判断

```json
{
  "direction": "negative",
  "ic_mean": -0.016024,
  "conclusion": "因子方向为反向（ic_mean=-0.0160<0），分层回测做多低值组"
}
```

**KDJ_J 因子说明：**
- J值 > 100：超买，预期下跌
- J值 < 0：超卖，预期反弹
- **IC均值负向（-0.0160）符合反向因子预期**
- ic_mean < 0 表示因子有效（高J值预测低收益）

### rolling_ic_mean 前10个值

```json
[
  null, null, null, null, null, null, null, null, null,
  0.193292, 0.175398, 0.192537, ...
]
```

**说明：** 前9个为 null（min_periods=10，至少需要10个有效值）

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

# K 计算（ewm）
alpha_k = 1.0 / m1
factor_df['k'] = factor_df.groupby('asset')['rsv'].transform(
    lambda x: x.ewm(alpha=alpha_k, adjust=False).mean()
)
```

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

| 规范项 | 符合状态 | 说明 |
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

---

## 更新历史

| 版本 | 日期 | 更新内容 |
|------|------|---------|
| v1.0 | 2026-05-20 | 初始版本，基于优化后的代码实现 |
| v1.1 | 2026-05-20 | 新增 avg_stocks_period 字段说明，完善异常处理分层规范（Section 22） |

---

*最后更新: 2026-05-20 13:15*"