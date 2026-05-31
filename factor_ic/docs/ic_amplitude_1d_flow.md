# Amplitude_1D IC 计算流程文档

> 生成时间: 2026-05-31 12:00 (北京时间)
> 作者: 云瑶
> 状态: 已验证

## 1. 因子定义

**公式**: `Amplitude = (High - Low) / Close`

**含义**: 当日振幅相对于收盘价的比率，反映价格波动强度
- 值越大 → 波动越剧烈
- 值越小 → 波动平稳
- 范围: 理论 [0, +∞)，实际通常 [0, 0.15]（A股振幅上限15%）

**边界处理**: 
- Close = 0 时，设为 NaN（无效数据）
- High = Low 时，振幅为 0（一字涨停/跌停）
- 使用 `_DEFAULT_AMPLITUDE_EPSILON = 1e-10` 防止除零

## 2. 数据流程

```
factor_ic_data.json.gz
    │
    ├── high, low, close (原始数据)
    │
    ▼
calculate_amplitude()
    │
    ├── 计算: range_val = high - low
    ├── 检测: zero_close_mask = |close| < epsilon
    ├── 计算: amplitude = range_val / close
    ├── 边界: close=0 时设为 NaN
    │
    ▼
run_complex_factor_ic()
    │
    ├── IC 计算（Spearman 相关性）
    ├── 五维度判断
    │
    ▼
ic_amplitude_1d_analysis_result.json
```

## 3. 运行结果（2026-05-31）

| 指标 | 值 |
|------|-----|
| IC 均值 | 待实测 |
| IC 标准差 | 待实测 |
| ICIR | 待实测 |
| t 统计量 | 待实测 |
| 有效 IC 天数 | 待实测 |

**五维度判断**:
- 待实测后补充

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
python3 factor_ic/ic_amplitude_1d.py --force-full

# 增量计算（默认）
python3 factor_ic/ic_amplitude_1d.py

# 自定义参数
python3 factor_ic/ic_amplitude_1d.py --min-stocks 20
```

## 6. 代码复用关系

遵循 PROJECT.md 公共模块强制复用规范：

- **主入口**: `run_complex_factor_ic()`（factor_ic_runner.py）
- **因子计算**: `calculate_amplitude()`（factor_calculator.py）
- **脚本**: 仅 CLI 入口 + 参数传递，约 100 行

## 7. 数据质量说明

- **close=0**: 极罕见情况，amplitude 设为 NaN（无效数据）
- **一字涨跌停**: high=low 时，振幅为 0，有效因子值

## 8. 版本历史

| 版本 | 日期 | 变更 |
|------|------|------|
| v1.0 | 2026-05-31 | 初始版本，修复日志字段名错误 |