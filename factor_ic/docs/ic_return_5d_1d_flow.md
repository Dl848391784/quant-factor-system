# ic_return_5d_1d IC 计算流程文档

> 生成时间: 2026-05-31 19:08 (北京时间，实测完成)
> 作者: 云瑶
> 状态: 已验证

## 1. 因子定义

**公式**: `Return_5d = Close[t] / Close[t-5] - 1`

**含义**: 过去5日累计涨跌幅
- 正值 → 上涨
- 负值 → 下跌
- 0 → 无变化
- 范围: 理论 [-∞, +∞)，A股日涨跌幅±10%，5日累计约±50%

**边界处理**: 
- 前5日数据设为 NaN（历史数据不足）
- Close[t-5] = 0 时设为 NaN（无效数据）
- 使用 `_EPSILON = 1e-10` 防止除零

## 2. 数据流程

```
factor_ic_data.json.gz
    │
    ├── close, asset, date (原始数据)
    │
    ▼
calculate_return_5d()
    │
    ├── 按 asset 分组排序
    ├── shift(5) 获取历史收盘价
    ├── 计算: return_5d = close[t] / close[t-5] - 1
    ├── 边界: close[t-5]=0 或 NaN 时设为 NaN
    │
    ▼
run_complex_factor_ic()
    │
    ├── IC 计算（Spearman 相关性）
    ├── 五维度判断
    │
    ▼
ic_return_5d_1d_analysis_result.json
```

## 3. 运行结果（2026-05-31 19:07 实测）

|| 指标 | 值 |
|------|-----|
| IC 均值 | -0.0337 |
| IC 标准差 | 0.1566 |
| ICIR | 0.21 |
| t 统计量 | -5.51 |
| p_value | 3.61e-08 |
| 有效 IC 天数 | 509 天 |
| 总天数 | 545 天 |
| 平均每日股票数 | 2727.3 |

**五维度判断**:

1. **统计显著性**: 统计显著（p=3.61e-08<0.05）
   - t_stat: -5.51
   - nw_lag: 5

2. **因子方向**: 反向因子（ic_mean=-0.0337<0）
   - direction_usage: 分层回测时做多低值组、做空高值组

3. **经济显著性**: 经济显著弱（|ic_mean|=0.0337>=0.03）
   - threshold_used: weak=0.03, strong=0.05

4. **ICIR稳定性**: IC稳定性不足（ICIR=0.21<0.5）
   - threshold_used: usable=0.5, good=1.0, excellent=2.0

5. **IC分布一致性**: 一致（正比例42.04%<50%对应负方向）
   - distribution_hint: IC分布偏向负值（58.0%天数IC<0）

**综合结论**: 5日累计涨幅因子具有统计显著性，但IC稳定性不足，建议谨慎使用。

## 4. 关键参数

|| 参数 | 默认值 | 说明 |
||------|--------|------|
|| min_stocks | 10 | 最小股票数阈值 |
|| window | 5 | 计算窗口 |
|| factor_cols | ['close', 'asset', 'date'] | 需加载的列 |
|| return_col | 'forward_return_1d' | 收益列名 |

## 5. 命令行使用

```bash
# 全量计算
python3 factor_ic/ic_return_5d_1d.py --force-full

# 增量计算（默认）
python3 factor_ic/ic_return_5d_1d.py

# 自定义参数
python3 factor_ic/ic_return_5d_1d.py --min-stocks 20
```

## 6. 代码复用关系

遵循 PROJECT.md 公共模块强制复用规范：

- **主入口**: `run_complex_factor_ic()`（factor_ic_runner.py）
- **因子计算**: `calculate_return_5d()`（factor_calculator.py）
- **脚本**: 仅 CLI 入口 + 参数传递，约 140 行

## 7. 数据质量说明

- **前5日NaN**: 正常情况，历史数据不足
- **close[t-5]=0**: 极罕见情况，return_5d 设为 NaN（无效数据）

## 8. 版本历史

|| 版本 | 日期 | 变更 |
||------|------|------|
|| v1.0 | 2026-05-29 | 初始版本，复用 factor_calculator.calculate_return_5d |
|| v1.1 | 2026-05-31 | 优化日志字段名 + 防御性 None 处理 + 删除未使用导入 + 异常处理改进 |
|| v1.2 | 2026-05-31 | 深度优化 - 创建流程文档 + 创建测试用例 + MODULE.md 版本同步 |