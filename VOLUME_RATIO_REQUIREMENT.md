# 量比因子分析需求文档

## 一、需求概述

在现有 RSI(6) 因子分析的基础上，新增**量比因子**的 RankIC、分层回测和多空分析功能。

---

## 二、量比因子定义

### 2.1 计算公式

```
量比 = 当日成交量 / 过去N日平均成交量

常用参数：N = 5（5日量比）
```

### 2.2 指标含义

| 量比值 | 含义 | 信号 |
|--------|------|------|
| 量比 > 2.5 | 剧烈放量 | 可能是突破或见顶 |
| 1.5 < 量比 < 2.5 | 明显放量 | 资金关注度高 |
| 0.7 < 量比 < 1.5 | 成交正常 | 无明显信号 |
| 量比 < 0.7 | 成交萎缩 | 可能是底部或无人关注 |

### 2.3 与收益的关系（传统理论）

- **放量上涨**：量比高 + 股价上涨 → 买入信号
- **放量下跌**：量比高 + 股价下跌 → 卖出信号
- **缩量**：量比低 → 观望

---

## 三、技术实现需求

### 3.1 修改因子数据获取逻辑

**文件**: `real_data_loader.py`

**修改位置**: Step 7 因子计算部分

**新增内容**:

```python
# 计算量比(5)
print(f"  计算量比(5)...")

# 方法1：简单移动平均
def calculate_volume_ratio_sma(volume, period=5):
    """计算量比（简单移动平均法）"""
    avg_volume = volume.rolling(window=period).mean()
    vr = volume / avg_volume
    return vr

# 方法2：使用 groupby + transform 向量化计算
combined['volume_ratio_5'] = combined.groupby('asset')['volume'].transform(
    lambda x: x / x.rolling(window=5).mean()
)

# 处理缺失值和极值
combined['volume_ratio_5'] = combined['volume_ratio_5'].fillna(1.0)  # 缺失值填充为1（正常）
combined['volume_ratio_5'] = combined['volume_ratio_5'].clip(0.1, 10)  # 裁剪到合理范围
```

### 3.2 修改缓存数据结构

**新增字段**:

```python
# 因子数据结构
factor_record = {
    'date': '2024-03-11',
    'asset': '000001',
    'rsi_6': 57.81,
    'volume_ratio_5': 1.25  # 新增
}
```

**收益数据结构**: 保持不变

### 3.3 复用现有分析逻辑

**可复用的代码**:

| 功能 | 方法 | 说明 |
|------|------|------|
| 动态过滤 | `filter_abnormal_stocks_dynamic()` | 完全复用 |
| 去极值 | `winsorize_factor()` | 完全复用 |
| RankIC | `calculate_rank_ic()` | 修改 `factor_col` 参数 |
| 分层回测 | `run_layered_backtest()` | 修改 `factor_col` 参数 |

**调用示例**:

```python
# 量比因子的 RankIC
ic_df = loader.calculate_rank_ic(
    factor_df, 
    return_df,
    factor_col='volume_ratio_5',  # 指定量比列
    enable_filter=True,
    enable_winsorize=True
)

# 量比因子的分层回测
result = run_layered_backtest(
    factor_df, 
    return_df,
    factor_col='volume_ratio_5',  # 指定量比列
    num_layers=5,
    enable_filter=True,
    enable_winsorize=True
)
```

---

## 四、数据来源

### 4.1 已有数据

从 K 线数据中已有：
- `volume`: 成交量

### 4.2 需要新增

- `volume_ratio_5`: 5日量比

---

## 五、实现步骤

### Step 1: 修改因子计算逻辑

1. 在 `real_data_loader.py` 的 Step 7 中添加量比计算
2. 修改因子数据保存逻辑，新增 `volume_ratio_5` 字段

### Step 2: 更新缓存数据

1. 删除旧缓存或触发全量重新拉取
2. 生成包含 RSI(6) 和量比的新缓存

### Step 3: 测试验证

1. 验证量比计算正确性（抽查几只股票）
2. 运行量比因子的 RankIC、分层回测分析
3. 对比量比与 RSI(6) 的因子表现

---

## 六、验收标准

| 验收项 | 预期结果 |
|--------|----------|
| 缓存数据包含量比 | factor_data.json.gz 中有 `volume_ratio_5` 字段 |
| 量比范围合理 | 大部分在 0.5-3 之间 |
| RankIC 可计算 | 输出 IC 均值、ICIR、IC>0 比例 |
| 分层回测可执行 | 输出各层收益、多空收益、夏普比率 |

---

## 七、注意事项

1. **量比的计算时机**: 在获取 K 线数据后、过滤异常股票前计算
2. **缺失值处理**: 上市不足 5 天的股票，量比填充为 1.0
3. **极值处理**: 量比可能非常大（如新股首日），需要在计算时裁剪
4. **缓存兼容**: 修改缓存版本号，确保旧代码不会读取新缓存出错

---

## 八、预期输出

### 8.1 控制台输出示例

```
[因子计算] 计算 RSI(6)...
[因子计算] 计算量比(5)...
  量比范围: [0.10, 10.00]
  量比均值: 1.25

[缓存保存] 保存数据到缓存文件...
  因子字段: rsi_6, volume_ratio_5
  因子数据: 1,513,497 条
```

### 8.2 Web 界面

在因子选择下拉框中新增选项：
- RSI(6)
- 量比(5)

---

**文档生成时间**: 2026-04-03
**文档作者**: 云柏