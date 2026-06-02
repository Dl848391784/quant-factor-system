# 尾盘量能加速度因子 IC 计算流程文档

> 版本: v1.2
> 创建时间: 2026-06-02
> 更新时间: 2026-06-02 18:56 北京时间

---

## 1. 因子概述

### 1.1 因子定义

尾盘量能加速度因子衡量尾盘后半段相对于前半段的交易活跃度变化：

```
前半段成交量总和 = sum(volumes[0:6])  # 14:00-14:25
后半段成交量总和 = sum(volumes[7:13])  # 14:35-15:00
量能加速度 = 后半段成交量总和 / 前半段成交量总和
```

**K线索引说明**：

| 索引 | 时间点 | 所属段 |
|-----|-------|--------|
| 0 | 14:00 | 前半段 |
| 1 | 14:05 | 前半段 |
| 2 | 14:10 | 前半段 |
| 3 | 14:15 | 前半段 |
| 4 | 14:20 | 前半段 |
| 5 | 14:25 | 前半段 |
| 6 | 14:30 | **不属于任何段** |
| 7 | 14:35 | 后半段 |
| 8 | 14:40 | 后半段 |
| 9 | 14:45 | 后半段 |
| 10 | 14:50 | 后半段 |
| 11 | 14:55 | 后半段 |
| 12 | 15:00 | 后半段 |

### 1.2 因子特性

| 特性 | 描述 |
|------|------|
| 理论范围 | (0, +∞)，无上界 |
| 含义 | 尾盘交易活跃度变化 |
| >1 含义 | 后半段交易更活跃（加速） |
| =1 含义 | 前后段交易活跃度相等 |
| <1 含义 | 前半段交易更活跃（减速） |

### 1.3 IC 分析结果

来源：`factor_ic/result/ic_tail_volume_acceleration_1d_analysis_result.json`
实测时间：2026-06-02 18:53 北京时间

| 指标 | 值 | 说明 |
|------|------|------|
| IC 均值 | -0.0148 | 反向因子（ic_mean < 0） |
| IC 标准差 | 0.0458 | IC 波动性 |
| ICIR | 0.3229 | IC 均值 / IC 标准差 |
| 正比例 | 36.36% | IC > 0 的比例 |
| 有效数据 | 2.4% | 35968 / 1487081 条匹配 |
| 日期范围 | 2026-05-15 ~ 2026-05-29 | 尾盘数据覆盖范围 |

**因子方向判定**：反向因子（ic_mean = -0.0148 < 0）

---

## 2. 边界处理

| 场景 | 处理 | 原因 |
|------|------|------|
| volumes 长度不足 13 | 返回 NaN | 数据不完整 |
| volumes 包含 NaN/None | 返回 NaN | 数据污染 |
| 前半段成交量总和 = 0 | 返回 NaN | 除零防护 |
| 后半段成交量总和 = 0 | 返回 0 | 无交易（合理值） |

---

## 3. 数据依赖

| 数据文件 | 路径 | 字段 | 说明 |
|---------|------|------|------|
| 尾盘K线数据 | tail_trading_data.json.gz | volumes | 13根5分钟K线成交量 |
| 主数据源 | factor_ic_data.json.gz | date, asset | 日期和资产匹配 |

---

## 4. 运行方式

### 4.1 CLI 命令

```bash
# 增量计算（默认）
python factor_ic/ic_tail_volume_acceleration_1d.py

# 强制全量计算
python factor_ic/ic_tail_volume_acceleration_1d.py --force-full

# 指定最小股票数
python factor_ic/ic_tail_volume_acceleration_1d.py --min-stocks 50
```

### 4.2 输出位置

- **结果文件**: `factor_ic/result/ic_tail_volume_acceleration_1d_analysis_result.json`
- **缓存文件**: `factor_ic/cache/ic_tail_volume_acceleration_1d_cache.json.gz`

---

## 5. 输出结构

```json
{
  "meta": {
    "factor_name": "tail_volume_acceleration",
    "generated_at": "2026-06-02T...",
    "calculation_mode": "full/incremental",
    "version": "1.0"
  },
  "ic_metrics": {
    "ic_mean": <float>,
    "ic_std": <float>,
    "icir": <float>
  },
  "sample_stats": {
    "avg_stocks_per_day": <float>,
    "total_days": <int>
  },
  "period": {
    "start": <str>,
    "end": <str>
  },
  "ic_distribution_consistency": {
    "positive_ratio": <float>
  }
}
```

---

## 6. 测试覆盖

- **测试文件**: `factor_ic/test_cases/test_ic_tail_volume_acceleration_1d.py`
- **覆盖场景**:
  - 因子计算逻辑（前后段划分）
  - 边界处理（长度不足、除零、NaN）
  - 数据合并逻辑
  - 配置参数验证

---

## 7. 版本历史

| 版本 | 时间 | 修改内容 |
|------|------|----------|
| v1.0 | 2026-06-02 | 初始版本，创建尾盘量能加速度因子 IC 脚本与配套文档 |
| v1.1 | 2026-06-02 18:56 | Round 1 优化 - 导入分组注释、版本历史完善、main()返回值 |
| v1.2 | 2026-06-02 18:56 | Round 2 优化 - 内部函数类型注解完善（list | np.ndarray） |