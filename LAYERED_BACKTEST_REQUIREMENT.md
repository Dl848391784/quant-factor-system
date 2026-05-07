# 需求文档: RSI(6) 分层回测功能

## 背景

用户需要对 RSI(6) 因子进行分层回测分析，以验证因子的有效性。分层回测是量化研究中常用的因子检验方法，通过观察不同分层组合的收益差异，判断因子是否具有预测能力。

## 功能描述

实现 RSI(6) 因子的分层回测功能，支持：
- 每日按 RSI(6) 值将股票分为5层
- 计算各层组合的收益表现
- 生成多空组合策略净值曲线
- 计算关键统计指标
- 可视化展示分层效果

---

## 技术需求（给云舟）

### 1. 数据结构定义

#### 1.1 输入数据

```python
# 因子数据
factor_data: pd.DataFrame
# 列: ['trade_date', 'stock_code', 'rsi_6']
# trade_date: 交易日期 (YYYYMMDD 或 datetime)
# stock_code: 股票代码
# rsi_6: RSI(6) 因子值

# 收益数据
return_data: pd.DataFrame
# 列: ['trade_date', 'stock_code', 'return']
# return: 当日收益率 (小数形式，如 0.02 表示 2%)
```

#### 1.2 分层结果数据结构

```python
layered_result: Dict[str, pd.DataFrame] = {
    'layer_returns': pd.DataFrame,     # 各层每日收益
    'cumulative_returns': pd.DataFrame, # 各层累计收益
    'statistics': pd.DataFrame,         # 统计指标
    'long_short': pd.DataFrame          # 多空组合
}

# layer_returns 结构
# 索引: trade_date
# 列: layer_1, layer_2, layer_3, layer_4, layer_5
# 值: 该层当日等权平均收益率

# cumulative_returns 结构
# 索引: trade_date
# 列: layer_1, layer_2, layer_3, layer_4, layer_5
# 值: 累计净值 (初始为1.0)

# statistics 结构
# 索引: layer_1 ~ layer_5, long_short
# 列: annual_return, t_stat, p_value, std, sharpe
# annual_return: 年化收益率
# t_stat: t统计量
# p_value: p值
# std: 收益标准差
# sharpe: 夏普比率

# long_short 结构
# 索引: trade_date
# 列: daily_return, cumulative_nav
# daily_return: 第1层 - 第5层 的收益差
# cumulative_nav: 累计净值
```

### 2. 分层计算逻辑

#### 2.1 分层方法

```python
def get_layer_labels(factor_series: pd.Series) -> pd.Series:
    """
    根据 RSI(6) 值进行分层
    
    参数:
        factor_series: 单日的 RSI(6) 值序列
    
    返回:
        layer_labels: 分层标签 (1-5)
    
    分层规则:
        - 第1层: RSI 值最低的 20% 股票 (最超卖)
        - 第2层: RSI 值次低的 20% 股票
        - 第3层: RSI 值中等的 20% 股票
        - 第4层: RSI 值次高的 20% 股票
        - 第5层: RSI 值最高的 20% 股票 (最超买)
    
    实现方式:
        使用 pd.qcut(factor_series, q=5, labels=[1,2,3,4,5])
    """
    pass
```

#### 2.2 日收益计算

```python
def calculate_layer_returns(
    factor_data: pd.DataFrame,
    return_data: pd.DataFrame,
    num_layers: int = 5
) -> pd.DataFrame:
    """
    计算各层每日等权平均收益
    
    步骤:
    1. 按日期分组
    2. 对每个交易日:
       a. 获取当日所有股票的 RSI(6) 值
       b. 使用 qcut 分为5层
       c. 将分层结果与次日收益关联
       d. 计算各层等权平均收益
    
    注意:
       - 分层使用当日因子值
       - 收益使用次日收益率 (避免未来函数)
       - 处理缺失值和停牌股票
    
    返回:
        DataFrame, 索引为 trade_date, 列为 layer_1 ~ layer_5
    """
    pass
```

#### 2.3 累计收益计算

```python
def calculate_cumulative_returns(layer_returns: pd.DataFrame) -> pd.DataFrame:
    """
    计算各层累计净值
    
    公式:
        cumulative_nav[t] = cumulative_nav[t-1] * (1 + return[t])
        初始净值 = 1.0
    
    返回:
        DataFrame, 索引为 trade_date, 列为 layer_1 ~ layer_5
    """
    pass
```

### 3. 统计指标计算

#### 3.1 年化收益

```python
def calculate_annual_return(daily_returns: pd.Series, trading_days: int = 250) -> float:
    """
    计算年化收益率
    
    公式:
        annual_return = (1 + total_return) ^ (trading_days / n_days) - 1
        或使用复利公式: prod(1 + r) ^ (250 / n) - 1
    
    参数:
        daily_returns: 日收益率序列
        trading_days: 年交易日数 (默认250)
    """
    pass
```

#### 3.2 t统计量

```python
def calculate_t_stat(daily_returns: pd.Series) -> Tuple[float, float]:
    """
    计算t统计量和p值
    
    假设检验:
        H0: 平均收益 = 0
        H1: 平均收益 ≠ 0
    
    公式:
        t = mean(r) / (std(r) / sqrt(n))
    
    返回:
        (t_stat, p_value)
    """
    pass
```

#### 3.3 综合统计函数

```python
def calculate_statistics(layer_returns: pd.DataFrame) -> pd.DataFrame:
    """
    计算各层及多空组合的统计指标
    
    指标:
        - annual_return: 年化收益率
        - t_stat: t统计量
        - p_value: p值
        - std: 日收益标准差
        - sharpe: 夏普比率 (年化收益 / 年化标准差)
    
    多空组合:
        long_short_return = layer_1_return - layer_5_return
    """
    pass
```

### 4. API 接口设计

#### 4.1 后端 API

```python
# POST /api/layered-backtest
{
    "factor_name": "rsi_6",
    "start_date": "20200101",
    "end_date": "20241231",
    "num_layers": 5,
    "universe": "all"  # 可选: all, hs300, zz500, zz1000
}

# Response
{
    "code": 200,
    "data": {
        "layer_returns": [...],      # 各层收益时间序列
        "cumulative_returns": [...],  # 累计净值
        "statistics": [...],          # 统计指标
        "long_short": [...],          # 多空组合
        "ic_series": [...]            # IC时间序列 (可选)
    }
}
```

#### 4.2 核心类设计

```python
class LayeredBacktest:
    """分层回测核心类"""
    
    def __init__(self, num_layers: int = 5):
        self.num_layers = num_layers
    
    def run(
        self,
        factor_data: pd.DataFrame,
        return_data: pd.DataFrame
    ) -> LayeredResult:
        """执行分层回测"""
        pass
    
    def get_layer_assignment(self, daily_factors: pd.Series) -> pd.Series:
        """获取分层结果"""
        pass
    
    def calculate_layer_returns(self, ...) -> pd.DataFrame:
        """计算层收益"""
        pass
    
    def calculate_statistics(self, ...) -> pd.DataFrame:
        """计算统计指标"""
        pass
    
    def get_long_short(self, ...) -> pd.DataFrame:
        """计算多空组合"""
        pass


@dataclass
class LayeredResult:
    """分层回测结果"""
    layer_returns: pd.DataFrame
    cumulative_returns: pd.DataFrame
    statistics: pd.DataFrame
    long_short: pd.DataFrame
    ic_series: Optional[pd.Series] = None
```

---

## 前端展示要求

### 1. 图表设计

#### 1.1 各层累计收益柱状图

```
图表类型: 柱状图
X轴: 分层 (Layer 1 ~ Layer 5, Long-Short)
Y轴: 累计收益率 (%)
颜色方案: 
    - Layer 1 (最超卖): 深绿
    - Layer 2: 浅绿
    - Layer 3: 灰色
    - Layer 4: 浅红
    - Layer 5 (最超买): 深红
    - Long-Short: 紫色

交互:
    - 鼠标悬停显示具体数值
    - 点击柱子高亮对应曲线
```

#### 1.2 多空净值曲线

```
图表类型: 折线图
X轴: 日期
Y轴: 净值 (初始 = 1.0)
线条:
    - 多空净值曲线 (紫色实线)
    - 基准线 (灰色虚线, y=1.0)

辅助信息:
    - 显示最大回撤位置和数值
    - 显示最终净值
    - 显示夏普比率
```

#### 1.3 分层收益时间序列叠加图

```
图表类型: 多折线图
X轴: 日期
Y轴: 累计净值
线条:
    - Layer 1 ~ Layer 5 各一条线
    - 使用渐变色: 绿 -> 黄 -> 红
    - 图例显示各层最终收益

可选叠加:
    - IC 时间序列 (次坐标轴)
```

### 2. 数据表格

```
分层统计表:
| 分层 | 年化收益 | t统计量 | p值 | 标准差 | 夏普比率 |
|------|----------|---------|-----|--------|----------|
| Layer 1 | xx% | x.xx | 0.xxx | x.x% | x.xx |
| Layer 2 | xx% | x.xx | 0.xxx | x.x% | x.xx |
| ...     | ... | ... | ... | ... | ... |
| Long-Short | xx% | x.xx | 0.xxx | x.x% | x.xx |

高亮规则:
    - 年化收益 > 0: 绿色
    - 年化收益 < 0: 红色
    - p值 < 0.05: 加粗 (显著)
```

### 3. 页面布局

```
+--------------------------------------------------+
|              RSI(6) 分层回测分析                    |
+--------------------------------------------------+
|  参数设置: [日期范围] [股票池] [分层数量] [运行]    |
+--------------------------------------------------+
|                                                  |
|  +------------------+  +----------------------+   |
|  | 各层累计收益柱状图 |  | 多空净值曲线          |   |
|  +------------------+  +----------------------+   |
|                                                  |
|  +--------------------------------------------+  |
|  |          分层收益时间序列叠加图               |  |
|  +--------------------------------------------+  |
|                                                  |
|  +--------------------------------------------+  |
|  |          分层统计表                          |  |
|  +--------------------------------------------+  |
|                                                  |
+--------------------------------------------------+
```

---

## 测试用例（给云汐）

### 正常场景

| 场景 | 操作 | 预期结果 |
|------|------|---------|
| 基础分层回测 | 选择日期范围2020-2024，运行分层回测 | 返回5层分层结果、统计指标、图表 |
| 多空组合验证 | 查看多空组合收益 | Layer1 - Layer5 收益差异符合预期 |
| IC分析 | 查看IC时间序列 | IC值在合理范围内，均值显著不为0 |

### 边界场景

| 场景 | 操作 | 预期结果 |
|------|------|---------|
| 短时间范围 | 选择1个月数据 | 正常返回结果，给出样本量警告 |
| 股票池筛选 | 选择沪深300成分股 | 仅对筛选后的股票分层 |
| 缺失数据处理 | 因子数据有缺失值 | 自动剔除缺失股票，记录剔除数量 |

### 异常场景

| 场景 | 操作 | 预期结果 |
|------|------|---------|
| 无数据 | 日期范围无数据 | 提示"该日期范围内无数据" |
| 参数错误 | 分层数量设为0 | 提示"分层数量必须大于1" |
| 数据不匹配 | 因子数据与收益数据日期不匹配 | 提示具体不匹配信息 |

---

## 验收标准

### 功能验收

- [ ] 正确执行 RSI(6) 因子分层
- [ ] 分层结果符合预期（每层约20%股票）
- [ ] 日收益计算正确（T日因子，T+1日收益）
- [ ] 累计收益计算正确
- [ ] 多空组合计算正确（Layer 1 - Layer 5）

### 统计指标验收

- [ ] 年化收益率计算正确
- [ ] t统计量计算正确
- [ ] p值计算正确
- [ ] 夏普比率计算正确

### 前端验收

- [ ] 柱状图正确展示各层收益
- [ ] 净值曲线平滑准确
- [ ] 数据表格与计算结果一致
- [ ] 交互功能正常

### 性能验收

- [ ] 4年数据（约1000交易日）计算时间 < 5秒
- [ ] 图表渲染流畅，无明显卡顿

---

## 附录

### A. 数学公式

```
分层方法:
    使用百分位数分割，每层包含约20%的股票

等权组合收益:
    R_layer = (1/N) * Σ R_i, for i in layer

累计净值:
    NAV_t = NAV_{t-1} * (1 + R_layer,t)

年化收益:
    R_annual = (1 + R_total)^(250/T) - 1

t统计量:
    t = μ / (σ / √n)
    其中 μ 为平均收益，σ 为标准差，n 为样本数

夏普比率:
    Sharpe = R_annual / σ_annual
    其中 σ_annual = σ_daily * √250
```

### B. 数据验证规则

```python
# RSI 值范围检查
assert factor_data['rsi_6'].between(0, 100).all()

# 收益率合理性检查
assert return_data['return'].between(-0.2, 0.2).all()  # 单日涨跌停限制

# 日期连续性检查
# 确保交易日期连续（排除非交易日）
```

### C. 参考资料

- 《量化投资：以Python为工具》- 蔡立耑
- 《主动投资组合管理》- Grinold & Kahn
- 因子检验标准流程 - Barra 风险模型

---

## 更新日志

| 日期 | 版本 | 说明 |
|------|------|------|
| 2026-04-02 | v1.0 | 初始版本 |

---

*本文档由云柏生成，供云舟开发、云汐测试使用*