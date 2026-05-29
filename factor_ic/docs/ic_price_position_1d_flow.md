# Price Position_1D IC 计算流程文档

> 生成时间: 2026-05-29 18:12 (北京时间)
> 作者: 云瑶
> 状态: 已验证

## 1. 因子定义

**公式**: `Price Position = (Close - Low) / (High - Low)`

**含义**: 收盘价在全天振幅中的相对位置
- 0 = 收盘价等于最低价（全天最低收盘）
- 1 = 收盘价等于最高价（全天最高收盘）
- 0.5 = 收盘价在振幅中位

**边界处理**: 
- High - Low = 0 时（振幅为零），设为 0.5（中位）
- 使用 `_DEFAULT_PRICE_POSITION_EPSILON = 1e-10` 防止除零

## 2. 数据流程

```
factor_ic_data.json.gz
    │
    ├── high, low, close (原始数据)
    │
    ▼
calculate_price_position()
    │
    ├── 计算: range_val = high - low
    ├── 检测: zero_range_mask = |range_val| < epsilon
    ├── 计算: price_position = (close - low) / range_val
    ├── 边界: 振幅为零时设为 0.5
    │
    ▼
run_complex_factor_ic()
    │
    ├── IC 计算（Spearman 相关性）
    ├── 五维度判断
    │
    ▼
ic_price_position_1d_analysis_result.json
```

## 3. 运行结果（2026-05-29）

| 指标 | 值 |
|------|-----|
| IC 均值 | -0.0131 |
| IC 标准差 | 0.1333 |
| ICIR | 0.10 |
| t 统计量 | -2.49 |
| 有效 IC 天数 | 514 天 |
| 振幅为零记录 | 3177 条 |

**五维度判断**:
- ICIR < 0.3（弱因子）
- |IC 均值| < 0.03（弱因子）
- t 统计量 |t| < 3（统计不显著）

## 4. 关键参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| min_stocks | 10 | 最小股票数阈值 |
| epsilon | 1e-10 | 防止除零阈值 |
| factor_cols | ['high', 'low', 'close'] | 需加载的列 |
| return_col | 'forward_return_1d' | 收益列名 |

## 5. 命令行使用

```bash
# 全量计算
python3 factor_ic/ic_price_position_1d.py --force-full

# 增量计算（默认）
python3 factor_ic/ic_price_position_1d.py

# 自定义参数
python3 factor_ic/ic_price_position_1d.py --min-stocks 20
```

## 6. 代码复用关系

遵循 PROJECT.md 公共模块强制复用规范：

- **主入口**: `run_complex_factor_ic()`（factor_ic_runner.py）
- **因子计算**: `calculate_price_position()`（factor_calculator.py）
- **脚本**: 仅 CLI 入口 + 参数传递，约 110 行

## 7. 数据质量说明

- **振幅为零**: 3177 条记录（high = low），约占 0.21%
- 这类记录表示当日价格无波动，price_position 设为 0.5（中性）

## 8. 版本历史

| 版本 | 日期 | 变更 |
|------|------|------|
| v1.0 | 2026-05-29 | 初始版本 |