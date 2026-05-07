# 换手率突增因子分析需求文档

## 1. 功能概述

### 1.1 功能背景

量化系统已有 RSI(6)、量比(5)、3日涨幅等因子分析功能，现在需要新增"换手率突增"因子分析。该因子用于捕捉换手率突然放大的股票，这类股票往往伴随着市场关注度的急剧上升，可能存在交易机会。

### 1.2 功能定义

**换手率突增因子**：衡量当日换手率相对于过去5日换手率均值的放大倍数，并仅在"放量且上涨"的股票上计算。

**核心价值**：
- 捕捉市场关注度突然上升的股票
- 结合"放量上涨"形态，筛选强势股
- 通过 IC 分析和分层回测验证因子预测能力

### 1.3 页面路由

- **前端路由**: `/turnover-surge-analysis`
- **API 路由前缀**: `/api/factor/turnover-surge`

---

## 2. 因子计算公式

### 2.1 基础公式

```
换手率突增 = 当日换手率 / 过去5日换手率均值
```

### 2.2 计算逻辑

```python
def calculate_turnover_surge(turnover_rate_series, period=5):
    """计算换手率突增因子
    
    Args:
        turnover_rate_series: 换手率序列（当日换手率）
        period: 均值计算周期，默认5日
        
    Returns:
        换手率突增值（原始值，未经筛选）
    """
    # 计算过去5日换手率均值（不含当日）
    avg_turnover = turnover_rate_series.rolling(window=period).mean().shift(1)
    
    # 计算换手率突增
    surge = turnover_rate_series / avg_turnover
    
    return surge
```

### 2.3 数值特性

| 指标 | 说明 |
|------|------|
| 基准值 | 1.0（换手率与均值持平） |
| 放大信号 | > 1.5（换手率放大50%以上） |
| 剧烈放大 | > 2.0（换手率翻倍） |
| 极端值处理 | 裁剪至 [0.5, 10] 区间 |

---

## 3. 筛选条件说明（重要）

### 3.1 筛选逻辑

**核心原则**：只对"放量且上涨"的股票计算换手率突增因子值，其他股票的因子值设为 `None`（即剔除）。

### 3.2 筛选条件

| 条件 | 公式 | 说明 |
|------|------|------|
| 放量条件 | 当日成交量 > 过去5日成交量均值 | 排除缩量股票 |
| 上涨条件 | 当日涨跌幅 > 0% | 排除下跌股票 |
| **组合条件** | 放量 AND 上涨 | 同时满足才计算因子 |

### 3.3 实现逻辑

```python
def calculate_turnover_surge_with_filter(
    turnover_rate, 
    volume, 
    pct_change,
    period=5
):
    """计算换手率突增因子（带筛选条件）
    
    Args:
        turnover_rate: 当日换手率
        volume: 当日成交量
        pct_change: 当日涨跌幅（%）
        period: 均值计算周期
        
    Returns:
        换手率突增因子值（不满足条件的为 None）
    """
    # 计算均值
    avg_turnover = turnover_rate.rolling(window=period).mean().shift(1)
    avg_volume = volume.rolling(window=period).mean().shift(1)
    
    # 筛选条件
    volume_surge = volume > avg_volume  # 放量
    price_up = pct_change > 0  # 上涨
    
    # 计算因子
    turnover_surge = turnover_rate / avg_turnover
    
    # 应用筛选条件：不满足条件的设为 None
    mask = volume_surge & price_up
    turnover_surge_filtered = turnover_surge.where(mask, None)
    
    return turnover_surge_filtered
```

### 3.4 筛选条件的作用

| 场景 | 换手率突增 | 放量 | 上涨 | 因子值 |
|------|-----------|------|------|--------|
| 放量上涨 | 高 | ✓ | ✓ | 保留 |
| 放量下跌 | 高 | ✓ | ✗ | None |
| 缩量上涨 | 高 | ✗ | ✓ | None |
| 缩量下跌 | 高 | ✗ | ✗ | None |
| 正常波动 | ~1 | - | - | None |

**设计理由**：
- 放量下跌：可能是恐慌抛售，换手率高不一定是机会
- 缩量上涨：换手率突增可能只是均值低，关注度未提升
- 放量上涨：市场关注度和资金流入同时确认，更有分析价值

---

## 4. 分析方法

### 4.1 Rank IC 分析

#### 4.1.1 IC 计算公式

```
IC(date) = SpearmanCorr(rank(换手率突增), rank(未来1日收益))
```

**排名方式**：正向排名（换手率突增越高，排名越高）

#### 4.1.2 IC 指标

| 指标 | 计算方式 | 有效阈值 | 说明 |
|------|----------|----------|------|
| IC 均值 | 所有日期 IC 的平均值 | > 0.03 | 因子整体预测能力 |
| ICIR | IC均值 / IC标准差 | > 0.5 | 因子稳定性 |
| t 统计量 | IC均值 / (IC标准差/√n) | | 显著性检验 |
| p 值 | 双边检验 | < 0.05 | 统计显著性 |
| 正 IC 占比 | IC > 0 的天数占比 | > 50% | 正向预测比例 |
| IC 标准差 | 所有日期 IC 的标准差 | < 0.1 | IC 波动性 |

#### 4.1.3 IC 时间序列

- **主图**: 每日 IC 值折线图（采样显示，每5个点取1个）
- **副图**: 20日滚动 IC 均值曲线
- **配色**: 主线蓝色 (#00d9ff)，滚动线绿色 (#00ff88)

---

### 4.2 分层回测

#### 4.2.1 分层数量

- 默认: **5层**（每层20%股票）
- 可选: **10层**（每层10%股票）

#### 4.2.2 分层逻辑

每日按换手率突增值升序分层（注意：只对有因子值的股票分层）：

| 分层 | 排名范围 | 含义 |
|------|----------|------|
| Layer 1 | 0-20% | 换手率突增最低（关注弱） |
| Layer 2 | 20-40% | 换手率突增较低 |
| Layer 3 | 40-60% | 换手率突增中等 |
| Layer 4 | 60-80% | 换手率突增较高 |
| Layer 5 | 80-100% | 换手率突增最高（关注强） |

#### 4.2.3 每层收益曲线

- **类型**: 折线图叠加
- **数据**: 各层累计净值（初始值=1.0）
- **配色**: 
  - Layer 1: 深红 (#dc3545)
  - Layer 2: 浅红 (#fd7e14)
  - Layer 3: 黄色 (#ffc107)
  - Layer 4: 浅绿 (#5cb85c)
  - Layer 5: 深绿 (#28a745)

#### 4.2.4 统计表格

| 列名 | 计算方式 | 说明 |
|------|----------|------|
| 分层名称 | Layer 1/N | 带含义标注 |
| 年化收益 | 日均收益 × 252 | 各层等权组合年化收益 |
| t 统计量 | 显著性检验 | 是否显著不为零 |
| p 值 | 显著性概率 | < 0.05 表示显著 |
| 夏普比率 | 年化收益 / 年化波动 | 风险调整收益 |

---

### 4.3 多空分析

#### 4.3.1 多空策略

**策略定义**:
- **做多**: Layer 5（换手率突增最高，关注最强）
- **做空**: Layer 1（换手率突增最低，关注最弱）

**逻辑解释**:
- 换手率突增最高：市场关注度急剧上升，可能有持续性
- 换手率突增较低：关注度提升不明显，动能较弱

| 因子 | 多头 | 空头 | 预期逻辑 |
|------|------|------|----------|
| RSI(6) | Layer 5（超卖） | Layer 1（超买） | 反转逻辑 |
| 量比(5) | Layer 5（放量） | Layer 1（缩量） | 资金关注逻辑 |
| **换手率突增** | Layer 5（高突增） | Layer 1（低突增） | 关注度提升逻辑 |

#### 4.3.2 净值曲线

- **类型**: 折线图
- **数据**: 多空组合累计净值
- **配色**: 紫色 (#6f42c1)
- **初始值**: 1.0

#### 4.3.3 关键指标

| 指标 | 有效阈值 | 说明 |
|------|----------|------|
| 年化收益 | > 0 | 多空策略盈利能力 |
| 夏普比率 | > 1 | 风险调整收益 |
| 最大回撤 | < 20% | 最大亏损幅度 |

---

### 4.4 单调性检验

**检验方法**: 检查各层年化收益是否单调递增（Layer 1 → Layer 5 收益递增）

| 结果 | 含义 |
|------|------|
| ✓ 通过 | 换手率突增越高，收益越高，符合预期 |
| ✗ 未通过 | 存在非线性关系，需进一步分析 |

---

## 5. 页面设计

### 5.1 布局结构

参考 volume-ratio-analysis 页面风格：

```
┌─────────────────────────────────────────────────┐
│                    页面标题                      │
│          换手率突增因子分析总览                    │
├─────────────────────────────────────────────────┤
│                    导航栏                        │
│  [因子分析总览] [RSI分析] [量比分析] [换手率突增] │
├─────────────────────────────────────────────────┤
│                   控制面板                       │
│    数据范围(固定)  分层数量  [运行分析按钮]        │
├─────────────────────────────────────────────────┤
│                  筛选条件说明                    │
│     仅对"放量且上涨"的股票计算换手率突增因子      │
├─────────────────────────────────────────────────┤
│                  核心指标卡片                    │
│  IC均值  ICIR  t统计量  多空收益  夏普  单调性    │
├─────────────────────────────────────────────────┤
│                    图表区域                      │
│  ┌─────────────┐ ┌─────────────┐               │
│  │ IC时间序列  │ │ 分层收益柱状 │               │
│  └─────────────┘ └─────────────┘               │
│  ┌─────────────┐ ┌─────────────┐               │
│  │ 多空净值曲线│ │ 各层净值叠加 │               │
│  └─────────────┘ └─────────────┘               │
├─────────────────────────────────────────────────┤
│                    数据表格                      │
│  ┌─────────────┐ ┌─────────────┐               │
│  │ IC统计指标表│ │ 分层统计指标 │               │
│  └─────────────┘ └─────────────┘               │
├─────────────────────────────────────────────────┤
│                    指标说明                      │
│       解释换手率突增因子的含义和解读逻辑          │
└─────────────────────────────────────────────────┘
```

### 5.2 筛选条件说明区

在控制面板下方，增加一个醒目的筛选条件说明区：

```
┌─────────────────────────────────────────────────┐
│  📊 筛选条件说明                                 │
│                                                 │
│  换手率突增因子仅在满足以下条件的股票上计算：      │
│                                                 │
│  ✓ 放量：当日成交量 > 过去5日成交量均值           │
│  ✓ 上涨：当日涨跌幅 > 0%                         │
│                                                 │
│  不满足条件的股票，因子值设为 None（剔除）        │
└─────────────────────────────────────────────────┘
```

### 5.3 图表类型

| 图表名称 | 类型 | 数据 | 说明 |
|----------|------|------|------|
| IC 时间序列图 | 折线图 | IC值 + 滚动均值 | 展示 IC 随时间变化 |
| 分层收益柱状图 | 柱状图 | 各层年化收益 | 展示分层收益分布 |
| 多空净值曲线 | 折线图 | 多空累计净值 | 展示多空策略表现 |
| 各层净值叠加图 | 折线图 | 各层累计净值 | 展示分层收益走势 |

### 5.4 核心指标卡片

| 指标 | 格式 | 颜色规则 |
|------|------|----------|
| IC 均值 | 0.035 | > 0.03 绿色，< 0 红色 |
| ICIR | 0.52 | > 0.5 绿色，< 0.3 红色 |
| t 统计量 | 2.85 | > 2 绿色，< -2 红色 |
| 多空年化收益 | 7.2% | > 5% 绿色，< 0 红色 |
| 夏普比率 | 0.85 | > 1 绿色，< 0 红色 |
| 单调性 | ✓通过 | 通过绿色，未通过红色 |

---

## 6. API 设计

### 6.1 /api/factor/turnover-surge

#### 请求参数

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| num_layers | int | 5 | 分层数量（5或10） |

**固定参数**:
- n_days = 500（约2年数据）
- max_stocks = 0（全部主板股票）

#### 返回数据结构

```json
{
  "ic_metrics": {
    "ic_mean": 0.042,
    "ic_std": 0.082,
    "icir": 0.51,
    "t_stat": 3.12,
    "p_value": 0.0021,
    "positive_ratio": 0.55,
    "n_days": 475,
    "n_assets": 2850,
    "significance": "**",
    "summary": "IC均值为正，因子有一定预测能力"
  },
  "ic_series": {
    "dates": ["2024-01-02", "2024-01-03", ...],
    "ic_values": [0.048, -0.012, ...],
    "rolling_ic_mean": [0.042, 0.038, ...]
  },
  "layered_result": {
    "layer_returns": [
      {"date": "2024-01-02", "layer_1": 0.001, "layer_2": 0.002, ...}
    ],
    "cumulative_returns": [
      {"date": "2024-01-02", "layer_1": 1.001, "layer_2": 1.002, ...}
    ],
    "statistics": [
      {"layer": "layer_1", "annual_return": 0.04, "t_stat": 0.95, "p_value": 0.34, "sharpe": 0.28},
      {"layer": "layer_5", "annual_return": 0.15, "t_stat": 3.2, "p_value": 0.001, "sharpe": 0.95},
      {"layer": "long_short", "annual_return": 0.11, "t_stat": 2.1, "p_value": 0.035, "sharpe": 0.68}
    ],
    "long_short": [
      {"date": "2024-01-02", "daily_return": 0.002, "cumulative_nav": 1.002}
    ],
    "num_layers": 5,
    "n_days": 475,
    "n_stocks_filtered": 2850,
    "filter_ratio": 0.35,
    "summary": {
      "long_short_annual_return": 0.11,
      "long_short_sharpe": 0.68,
      "long_short_max_drawdown": -0.12,
      "monotonicity_passed": true
    }
  },
  "filter_stats": {
    "total_stocks": 8150,
    "filtered_stocks": 2850,
    "filter_ratio": 0.35,
    "volume_surge_count": 3500,
    "price_up_count": 4800,
    "both_conditions_count": 2850
  },
  "params": {
    "n_days": 500,
    "max_stocks": 0,
    "num_layers": 5,
    "factor_col": "turnover_surge",
    "filter_conditions": ["volume_surge", "price_up"]
  },
  "generated_at": "2024-04-05T18:00:00"
}
```

### 6.2 /api/factor/turnover-surge/progress

#### 进度状态返回

```json
{
  "status": "running",
  "message": "正在筛选放量上涨股票...",
  "progress": 35,
  "stage": "filtering",
  "start_time": 1712323200,
  "last_update": "2024-04-05T18:05:00",
  "estimated_remaining_seconds": 25
}
```

**阶段说明**:
- `loading_data`: 加载缓存数据
- `filtering`: 应用筛选条件
- `calculating_factor`: 计算换手率突增因子
- `calculating_ic`: 计算 IC 指标
- `layered_backtest`: 分层回测
- `completed`: 完成

---

## 7. 技术实现要点

### 7.1 数据来源

使用缓存中的换手率数据：

```python
# 缓存文件路径
cache_dir = Path('cache/factor_data')
factor_path = cache_dir / 'factor_data.json.gz'
return_path = cache_dir / 'return_data.json.gz'

# 数据字段
factor_data:
  - date
  - asset
  - turnover_rate       # 当日换手率
  - volume              # 当日成交量
  - pct_change          # 当日涨跌幅（%）

return_data:
  - date
  - asset
  - forward_return      # 未来1日收益
```

### 7.2 核心计算逻辑

```python
def calculate_turnover_surge_factor(df, period=5):
    """计算换手率突增因子（带筛选条件）
    
    Args:
        df: 包含 turnover_rate, volume, pct_change 的 DataFrame
        period: 均值计算周期
        
    Returns:
        DataFrame，包含 turnover_surge 列（不满足条件的为 None）
    """
    # 计算过去5日均值
    df['avg_turnover_5d'] = df.groupby('asset')['turnover_rate'].transform(
        lambda x: x.rolling(window=period, min_periods=period).mean().shift(1)
    )
    df['avg_volume_5d'] = df.groupby('asset')['volume'].transform(
        lambda x: x.rolling(window=period, min_periods=period).mean().shift(1)
    )
    
    # 筛选条件
    df['volume_surge'] = df['volume'] > df['avg_volume_5d']
    df['price_up'] = df['pct_change'] > 0
    
    # 计算换手率突增
    df['turnover_surge_raw'] = df['turnover_rate'] / df['avg_turnover_5d']
    
    # 应用筛选条件
    df['turnover_surge'] = df['turnover_surge_raw'].where(
        df['volume_surge'] & df['price_up'],
        None
    )
    
    # 极端值处理
    df['turnover_surge'] = df['turnover_surge'].clip(0.5, 10)
    
    return df
```

### 7.3 IC 计算

```python
from scipy.stats import spearmanr

def calculate_ic(df, factor_col='turnover_surge', return_col='forward_return'):
    """计算 Rank IC
    
    Args:
        df: 包含因子值和收益的 DataFrame
        factor_col: 因子列名
        return_col: 收益列名
        
    Returns:
        IC 值（每日）
    """
    # 移除 None 值（筛选条件剔除的股票）
    df_valid = df.dropna(subset=[factor_col, return_col])
    
    # 按日期计算 Spearman 秩相关系数
    ic_series = df_valid.groupby('date').apply(
        lambda x: spearmanr(x[factor_col], x[return_col])[0]
    )
    
    return ic_series
```

### 7.4 分层回测

```python
def layered_backtest(df, factor_col='turnover_surge', return_col='forward_return', num_layers=5):
    """分层回测
    
    Args:
        df: 包含因子值和收益的 DataFrame
        factor_col: 因子列名
        return_col: 收益列名
        num_layers: 分层数量
        
    Returns:
        分层回测结果
    """
    results = []
    
    for date, group in df.groupby('date'):
        # 移除 None 值
        valid = group.dropna(subset=[factor_col, return_col])
        
        if len(valid) < num_layers * 10:
            continue
        
        # 按因子值分层
        valid['layer'] = pd.qcut(
            valid[factor_col], 
            q=num_layers, 
            labels=[f'layer_{i+1}' for i in range(num_layers)]
        )
        
        # 计算各层收益
        layer_returns = valid.groupby('layer')[return_col].mean()
        
        results.append({
            'date': date,
            **layer_returns.to_dict()
        })
    
    return pd.DataFrame(results)
```

### 7.5 API 实现

在 `web_app.py` 中新增：

```python
# 换手率突增因子分析状态
turnover_surge_analysis_state = {
    'status': 'idle',
    'message': '',
    'progress': 0,
    'stage': '',
    'start_time': None,
    'result': None
}
turnover_surge_analysis_lock = threading.Lock()

@app.route('/turnover-surge-analysis')
def turnover_surge_analysis_page():
    """换手率突增因子分析页面"""
    return render_template('turnover_surge_analysis.html')

@app.route('/api/factor/turnover-surge', methods=['GET'])
def api_turnover_surge():
    """API: 换手率突增因子分析"""
    num_layers = request.args.get('num_layers', default=5, type=int)
    
    # 启动后台分析任务
    # ... 类似 volume_ratio_analysis
    
@app.route('/api/factor/turnover-surge/progress')
def api_turnover_surge_progress():
    """API: 换手率突增因子分析进度"""
    with turnover_surge_analysis_lock:
        return jsonify(turnover_surge_analysis_state)
```

---

## 8. 测试用例（给云汐）

### 8.1 功能测试

| 场景 | 操作 | 预期结果 |
|------|------|----------|
| 正常访问 | 打开 `/turnover-surge-analysis` | 显示页面标题和筛选条件说明 |
| 运行分析 | 点击"运行分析"按钮 | 显示进度条，阶段显示正确 |
| 筛选统计 | 分析完成后查看筛选统计 | 显示总股票数、筛选后股票数、筛选比例 |
| IC 指标 | 查看 IC 指标卡片 | IC均值、ICIR、t统计量等数值合理 |
| IC 时间序列 | 查看 IC 时间序列图 | 图表正常显示，有滚动均值曲线 |
| 分层收益 | 查看分层收益柱状图 | 5层收益柱状图显示正确 |
| 多空净值 | 查看多空净值曲线 | 曲线平滑，显示累计净值 |
| 各层净值 | 查看各层净值叠加图 | 5条曲线颜色区分清晰 |
| 数据表格 | 查看 IC 统计和分层统计表格 | 数值与图表对应一致 |
| 单调性检验 | 查看单调性检验结果 | 显示通过/未通过，颜色正确 |

### 8.2 边界测试

| 场景 | 操作 | 预期结果 |
|------|------|----------|
| 无缓存数据 | 删除缓存后运行分析 | 显示错误提示，引导获取数据 |
| 筛选后股票为0 | 所有股票都不满足条件 | 显示警告，提示筛选条件过严 |
| 单日数据 | 只有1天数据 | IC 无法计算，显示提示 |
| 极端值处理 | 换手率突增值 > 10 | 裁剪至 10，不影响分析 |

### 8.3 性能测试

| 场景 | 预期结果 |
|------|----------|
| 首次运行时间 | < 60秒（使用缓存） |
| 进度更新频率 | 每秒更新一次 |
| 页面加载时间 | < 2秒 |
| 图表渲染时间 | < 3秒 |

### 8.4 UI 测试

| 场景 | 预期结果 |
|------|----------|
| 页面标题 | "换手率突增因子分析总览" |
| 筛选条件说明 | 醒目显示，内容正确 |
| 导航栏 | 包含"换手率突增"链接 |
| 指标卡片样式 | 与其他因子页面一致 |
| 图表交互 | 鼠标悬停显示 tooltip |
| 表格排序 | 点击列头可排序 |

### 8.5 数据验证

| 验收项 | 预期结果 |
|--------|----------|
| IC均值范围 | 通常在 -0.05 ~ 0.08 |
| ICIR范围 | 通常在 0 ~ 1.5 |
| 筛选比例 | 通常在 20% ~ 50%（放量上涨的股票比例） |
| 分层收益 | 各层有差异，非完全相同 |
| 多空收益 | 正或负（取决于因子有效性） |

---

## 9. 验收标准

### 9.1 功能验收

| 验收项 | 验收方法 | 预期结果 |
|--------|----------|----------|
| 页面可访问 | 浏览器访问 `/turnover-surge-analysis` | 显示页面 |
| 筛选条件生效 | 查看筛选统计 | 显示筛选比例 |
| IC 计算正确 | 对比手工计算 | 数值一致 |
| 分层回测正确 | 检查分层收益数据 | 数据结构完整 |
| 多空净值计算 | 检查净值曲线 | 曲线起点=1.0 |
| 单调性检验 | 检查检验结果 | 显示通过/未通过 |

### 9.2 数据验收

| 验收项 | 预期结果 |
|--------|----------|
| 筛选统计准确 | 总股票数 × 筛选比例 ≈ 筛选后股票数 |
| 因子值范围 | 在 [0.5, 10] 区间内 |
| 无因子值的股票 | 不参与分层 |
| 各层股票数相近 | 每层约占筛选后股票的 20% |

---

## 10. 开发优先级

| 优先级 | 功能 | 原因 |
|--------|------|------|
| P0 | 筛选逻辑实现 | 核心功能 |
| P0 | 因子计算实现 | 核心功能 |
| P0 | API 接口实现 | 前端依赖 |
| P0 | 页面模板创建 | 用户入口 |
| P1 | IC 计算逻辑 | 分析核心 |
| P1 | 分层回测 | 分析核心 |
| P1 | 筛选统计显示 | 数据透明 |
| P2 | 图表渲染 | 可复用代码 |
| P2 | 指标卡片 | 可复用代码 |
| P3 | 导航链接 | 整合到系统 |

---

## 11. 附录

### 11.1 换手率突增因子的理论背景

**换手率**：当日成交量 / 流通股本，反映股票的活跃程度。

**换手率突增**：当日换手率相对历史均值的大幅提升，可能意味着：
- 市场关注度突然上升
- 有重大消息或事件
- 资金开始流入或流出

**筛选"放量且上涨"的理由**：
- 放量上涨：市场关注 + 价格确认 = 可能的趋势启动
- 放量下跌：可能是恐慌抛售，不一定是机会
- 缩量上涨：关注度未提升，持续性存疑

### 11.2 与其他因子的对比

| 因子 | 计算方式 | 筛选条件 | 预测逻辑 |
|------|----------|----------|----------|
| RSI(6) | 相对强弱指数 | 无 | 超卖反弹 |
| 量比(5) | 当日成交量/5日均量 | 无 | 放量关注 |
| 3日涨幅 | 3日累计涨幅 | 无 | 动量延续 |
| **换手率突增** | 当日换手率/5日均值 | 放量且上涨 | 关注度提升 + 价格确认 |

### 11.3 预期结果

基于理论分析，预期：
- **IC 均值**：正数，0.03 ~ 0.06
- **多空收益**：正数，年化 5% ~ 15%
- **单调性**：通过，换手率突增越高，收益越高

**注意**：因子有效性需通过实际数据验证，可能出现与预期不符的情况。

---

**文档生成时间**: 2026-04-05
**文档作者**: 云柏 📝
**目标读者**: 云舟（开发）、云汐（测试）