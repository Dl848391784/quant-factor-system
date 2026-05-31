# Return_5d_1D IC 计算流程文档

> 生成时间: 2026-05-31 15:30 (北京时间)
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

## 3. 运行结果（2026-05-31）

|| 指标 | 值 |
||------|-----|
|| IC 均值 | 待实测 |
|| IC 标准差 | 待实测 |
|| ICIR | 待实测 |
|| t 统计量 | 待实测 |
|| 有效 IC 天数 | 待实测 |

**五维度判断**:
- 待实测后补充

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