# 主力净流入占比因子分析需求文档

## 1. 功能概述

### 1.1 功能背景

量化系统已有 RSI(6)、量比(5)、3日涨幅、换手率突增等因子分析功能，现在需要新增"主力净流入占比"因子分析。该因子用于衡量主力资金流入相对于流通市值的强度，标准化后可以更公平地比较不同市值股票的主力活跃度。

### 1.2 功能定义

**主力净流入占比因子**：主力净流入金额与流通市值的比值，标准化后的主力资金流入强度指标。

**核心价值**：
- 标准化主力资金流入强度（元/元 = 无量纲比例）
- 可以比较不同市值股票的主力活跃度
- 消除市值规模的影响，更公平地衡量主力资金参与程度
- 捕捉主力资金高度关注的股票

### 1.3 页面路由

- **前端路由**: `/main-inflow-ratio-analysis`
- **API 路由前缀**: `/api/factor/main-inflow-ratio`

---

## 2. 因子计算公式

### 2.1 基础公式

```
主力净流入占比 = 主力净流入金额 / 流通市值
```

### 2.2 计算逻辑

```python
def calculate_main_inflow_ratio(main_net_inflow, float_market_cap):
    """计算主力净流入占比因子
    
    Args:
        main_net_inflow: 主力净流入金额（当日）
        float_market_cap: 流通市值（当日）
        
    Returns:
        主力净流入占比因子值（无量纲比例）
    """
    # 计算占比
    inflow_ratio = main_net_inflow / float_market_cap
    
    # 极端值处理（可选）
    inflow_ratio = inflow_ratio.clip(-0.1, 0.1)  # 裁剪至 [-10%, +10%]
    
    return inflow_ratio
```

### 2.3 数值特性

| 指标 | 说明 |
|------|------|
| 正值含义 | 主力资金净流入，占比越高流入越强 |
| 负值含义 | 主力资金净流出，占比越高流出越强 |
| 基准值 | 0（主力资金平衡） |
| 典型范围 | -5% ~ +5%（极端值裁剪至 ±10%） |
| 单位 | 无量纲比例（元/元） |

### 2.4 与其他资金因子对比

| 因子 | 计算方式 | 优点 | 缺点 |
|------|----------|------|------|
| 主力净流入金额 | 直接金额 | 直观 | 受市值影响大，大股票天然流入多 |
| **主力净流入占比** | 金额/市值 | 标准化，可比较 | 需要市值数据 |
| 主力净流入率 | 流入/总成交 | 反映流入比例 | 不考虑市值规模 |

---

## 3. 数据需求分析

### 3.1 数据字段需求

| 字段名 | 数据类型 | 来源 | 说明 |
|--------|----------|------|------|
| `main_net_inflow` | float | 新浪财经资金流向接口 | 主力净流入金额（万元） |
| `float_market_cap` | float | 新浪财经行情接口 | 流通市值（万元） |
| `close` | float | 缓存已有 | 收盘价 |
| `forward_return_1d` | float | 缓存已有 | 未来1日收益 |

### 3.2 缓存字段现状检查

**当前缓存字段列表**：
```
- asset     (股票代码)
- date      (日期)
- close     (收盘价)
- rsi_6     (6日RSI)
- volume_ratio_5 (5日量比)
```

**缺失字段**：
- ✗ `main_net_inflow`（主力净流入金额）- **需要新增**
- ✗ `float_market_cap`（流通市值）- **需要新增**

### 3.3 数据获取方案

#### 方案A：扩展新浪财经 API

**主力资金流向接口**：
```python
# 新浪财经资金流向 API
MONEYFLOW_API = 'https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/MoneyFlow.ssl_mfstock_history'

# 参数
params = {
    'symbol': 'sh600000',  # 股票代码
    'num': 60              # 最近60天数据
}

# 返回字段
{
    'date': '交易日期',
    'main_net_inflow': '主力净流入（万元）',
    'main_inflow': '主力流入（万元）',
    'main_outflow': '主力流出（万元）',
    'retail_net_inflow': '散户净流入（万元）',
    ...
}
```

**流通市值获取方式**：
```python
# 从日K线数据获取流通市值
# 或者使用实时行情接口
MARKET_CAP_API = 'https://quotes.sina.cn/cn/api/json_v2.php/CN_MarketDataService.getKLineData'

# 返回字段包含
{
    'date': '交易日期',
    'close': '收盘价',
    'volume': '成交量',
    'turnover': '成交额',
    ...
}

# 流通市值可以计算或从其他接口获取
```

#### 方案B：使用第三方数据源

| 数据源 | 获取方式 | 字段可用性 |
|--------|----------|------------|
| 东方财富 | API/爬虫 | 主力资金 + 流通市值 |
| 同花顺 | API | 主力资金流向 |
| Wind/通达信 | 付费接口 | 完整资金数据 |

**建议方案**：优先使用新浪财经 API（免费），后续可扩展其他数据源。

### 3.4 数据预计算脚本

需要新增数据预计算脚本：

```bash
# 预计算主力净流入占比数据
python precompute_main_inflow_ratio.py
```

**脚本功能**：
1. 从新浪财经获取主力资金流向数据
2. 从新浪财经获取流通市值数据
3. 计算主力净流入占比
4. 存入缓存文件 `factor_data.json.gz`

---

## 4. 分析方法

### 4.1 Rank IC 分析

#### 4.1.1 IC 计算公式

```
IC(date) = SpearmanCorr(rank(主力净流入占比), rank(未来1日收益))
```

**排名方式**：正向排名（主力净流入占比越高，排名越高）

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

每日按主力净流入占比值升序分层：

| 分层 | 排名范围 | 含义 |
|------|----------|------|
| Layer 1 | 0-20% | 主力净流入占比最低（流出最强） |
| Layer 2 | 20-40% | 主力净流入占比较低 |
| Layer 3 | 40-60% | 主力净流入占比中等 |
| Layer 4 | 60-80% | 主力净流入占比较高 |
| Layer 5 | 80-100% | 主力净流入占比最高（流入最强） |

#### 4.2.3 每层收益曲线

- **类型**: 折线图叠加
- **数据**: 各层累计净值（初始值=1.0）
- **配色**: 
  - Layer 1: 深红 (#dc3545) - 流出最强
  - Layer 2: 浅红 (#fd7e14)
  - Layer 3: 黄色 (#ffc107)
  - Layer 4: 浅绿 (#5cb85c)
  - Layer 5: 深绿 (#28a745) - 流入最强

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
- **做多**: Layer 5（主力净流入占比最高，流入最强）
- **做空**: Layer 1（主力净流入占比最低，流出最强）

**逻辑解释**:
- 主力净流入占比最高：主力资金强烈看好，预期上涨
- 主力净流入占比最低（负值最大）：主力资金强烈看空，预期下跌

| 因子 | 多头 | 空头 | 预期逻辑 |
|------|------|------|----------|
| RSI(6) | Layer 5（超卖） | Layer 1（超买） | 反转逻辑 |
| 量比(5) | Layer 5（放量） | Layer 1（缩量） | 资金关注逻辑 |
| **主力净流入占比** | Layer 5（流入强） | Layer 1（流出强） | 主力资金逻辑 |

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
| ✓ 通过 | 主力净流入占比越高，收益越高，符合预期 |
| ✗ 未通过 | 存在非线性关系，需进一步分析 |

---

## 5. 页面设计

### 5.1 布局结构

参考 turnover_surge_analysis 页面风格：

```
┌─────────────────────────────────────────────────┐
│                    页面标题                      │
│          主力净流入占比因子分析总览                │
├─────────────────────────────────────────────────┤
│                    导航栏                        │
│  [因子分析总览] [RSI分析] [量比分析] [换手率突增] │
│  [主力净流入占比]                                │
├─────────────────────────────────────────────────┤
│                   控制面板                       │
│    数据范围(固定)  分层数量  [运行分析按钮]        │
├─────────────────────────────────────────────────┤
│                  因子说明区                      │
│     主力净流入占比 = 主力净流入金额 / 流通市值     │
│     标准化后的主力资金流入强度指标                 │
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
│       解释主力净流入占比因子的含义和解读逻辑       │
└─────────────────────────────────────────────────┘
```

### 5.2 因子说明区

在控制面板下方，增加因子说明区：

```
┌─────────────────────────────────────────────────┐
│  📊 因子定义                                     │
│                                                 │
│  主力净流入占比 = 主力净流入金额 / 流通市值        │
│                                                 │
│  ✦ 标准化后的主力资金流入强度指标                  │
│  ✦ 单位统一（元/元 = 无量纲比例）                 │
│  ✦ 可以比较不同市值股票的主力活跃度               │
│  ✦ 消除市值规模的影响，更公平地衡量主力资金参与程度 │
│                                                 │
│  正值：主力资金净流入，占比越高流入越强            │
│  负值：主力资金净流出，占比越高流出越强            │
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

### 6.1 /api/factor/main-inflow-ratio

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
    "n_stocks": 2850,
    "summary": {
      "long_short_annual_return": 0.11,
      "long_short_sharpe": 0.68,
      "long_short_max_drawdown": -0.12,
      "monotonicity_passed": true
    }
  },
  "data_availability": {
    "has_main_net_inflow": true,
    "has_float_market_cap": true,
    "coverage_ratio": 0.95,
    "missing_days": 25
  },
  "params": {
    "n_days": 500,
    "max_stocks": 0,
    "num_layers": 5,
    "factor_col": "main_inflow_ratio"
  },
  "generated_at": "2024-04-05T18:00:00"
}
```

### 6.2 /api/factor/main-inflow-ratio/progress

#### 进度状态返回

```json
{
  "status": "running",
  "message": "正在获取主力资金数据...",
  "progress": 35,
  "stage": "fetching_moneyflow",
  "start_time": 1712323200,
  "last_update": "2024-04-05T18:05:00",
  "estimated_remaining_seconds": 25
}
```

**阶段说明**:
- `loading_data`: 加载缓存数据
- `fetching_moneyflow`: 获取主力资金数据（如需补充）
- `calculating_factor`: 计算主力净流入占比因子
- `calculating_ic`: 计算 IC 指标
- `layered_backtest`: 分层回测
- `completed`: 完成

---

## 7. 技术实现要点

### 7.1 数据获取模块

**新增文件**: `precompute_main_inflow_ratio.py`

```python
#!/usr/bin/env python3
"""
主力净流入占比因子数据预计算脚本

功能：
1. 从新浪财经获取主力资金流向数据
2. 从新浪财经获取流通市值数据
3. 计算主力净流入占比因子
4. 存入缓存文件

作者: 云舟
日期: 2026-04-05
"""

import requests
import pandas as pd
import gzip
import json
from pathlib import Path
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor

# 新浪财经 API 端点
MONEYFLOW_API = 'https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/MoneyFlow.ssl_mfstock_history'

# 缓存路径
CACHE_DIR = Path('/home/admin/.openclaw/workspace/yunzhou/factor_ic_analyzer/cache/factor_data')
FACTOR_CACHE = CACHE_DIR / 'factor_data.json.gz'


def fetch_main_moneyflow(symbol: str, num_days: int = 60):
    """获取单只股票的主力资金流向数据
    
    Args:
        symbol: 股票代码（如 'sh600000'）
        num_days: 获取天数
        
    Returns:
        DataFrame: 主力资金数据
    """
    params = {
        'symbol': symbol,
        'num': num_days
    }
    
    headers = {
        'User-Agent': 'Mozilla/5.0',
        'Referer': 'http://finance.sina.com.cn/'
    }
    
    try:
        response = requests.get(MONEYFLOW_API, params=params, headers=headers, timeout=10)
        data = response.json()
        
        if isinstance(data, list) and len(data) > 0:
            df = pd.DataFrame(data)
            df['symbol'] = symbol
            return df
        return None
    except Exception as e:
        print(f"获取 {symbol} 主力资金失败: {e}")
        return None


def fetch_float_market_cap(symbol: str):
    """获取流通市值
    
    Args:
        symbol: 股票代码
        
    Returns:
        float: 流通市值（万元）
    """
    # TODO: 实现流通市值获取逻辑
    # 可以从实时行情接口获取
    pass


def calculate_main_inflow_ratio(main_net_inflow, float_market_cap):
    """计算主力净流入占比
    
    Args:
        main_net_inflow: 主力净流入金额（万元）
        float_market_cap: 流通市值（万元）
        
    Returns:
        float: 主力净流入占比（无量纲比例）
    """
    if float_market_cap is None or float_market_cap == 0:
        return None
    
    ratio = main_net_inflow / float_market_cap
    
    # 极端值裁剪
    ratio = max(-0.1, min(0.1, ratio))
    
    return ratio


def run_precompute():
    """执行主力净流入占比数据预计算"""
    # 1. 加载股票列表
    # 2. 并发获取主力资金数据
    # 3. 获取流通市值
    # 4. 计算主力净流入占比
    # 5. 存入缓存
    pass


if __name__ == '__main__':
    run_precompute()
```

### 7.2 因子计算模块

**新增文件**: `main_inflow_ratio_factor.py`

```python
#!/usr/bin/env python3
"""
主力净流入占比因子计算模块

因子定义：
- 主力净流入占比 = 主力净流入金额 / 流通市值
- 标准化后的主力资金流入强度指标

数据需求：
- main_net_inflow: 主力净流入金额（万元）
- float_market_cap: 流通市值（万元）

作者: 云舟
日期: 2026-04-05
"""

import pandas as pd
import numpy as np
from pathlib import Path
import gzip
import json
import gc
from typing import Tuple, Optional, Dict
import warnings
warnings.filterwarnings('ignore')


def load_data_for_main_inflow_ratio(max_days: int = 500) -> Tuple[Optional[pd.DataFrame], Optional[pd.DataFrame]]:
    """加载主力净流入占比因子所需数据
    
    需要的数据：
    - main_net_inflow: 主力净流入金额
    - float_market_cap: 流通市值
    - forward_return_1d: 未来收益
    
    Args:
        max_days: 最大加载天数
        
    Returns:
        (factor_df, return_df)
    """
    # TODO: 实现数据加载逻辑
    pass


def calculate_main_inflow_ratio_factor(factor_df: pd.DataFrame) -> Tuple[pd.DataFrame, Dict]:
    """计算主力净流入占比因子
    
    Args:
        factor_df: 包含 main_net_inflow, float_market_cap 的 DataFrame
        
    Returns:
        (处理后的 factor_df, 统计信息)
    """
    # 计算主力净流入占比
    factor_df['main_inflow_ratio'] = factor_df['main_net_inflow'] / factor_df['float_market_cap']
    
    # 处理极端值
    factor_df['main_inflow_ratio'] = factor_df['main_inflow_ratio'].clip(-0.1, 0.1)
    
    # 统计信息
    stats = {
        'valid_count': factor_df['main_inflow_ratio'].notna().sum(),
        'mean': factor_df['main_inflow_ratio'].mean(),
        'std': factor_df['main_inflow_ratio'].std(),
        'min': factor_df['main_inflow_ratio'].min(),
        'max': factor_df['main_inflow_ratio'].max()
    }
    
    return factor_df, stats


def run_main_inflow_ratio_analysis(n_days: int = 500, num_layers: int = 5) -> Dict:
    """执行完整的主力净流入占比因子分析
    
    Args:
        n_days: 交易日数量
        num_layers: 分层数量
        
    Returns:
        完整分析结果
    """
    # TODO: 实现完整分析流程
    pass


if __name__ == '__main__':
    result = run_main_inflow_ratio_analysis(n_days=500, num_layers=5)
```

### 7.3 API 实现

在 `web_app.py` 中新增：

```python
# 主力净流入占比因子分析状态
main_inflow_ratio_analysis_state = {
    'status': 'idle',
    'message': '',
    'progress': 0,
    'stage': '',
    'start_time': None,
    'result': None
}
main_inflow_ratio_analysis_lock = threading.Lock()


@app.route('/main-inflow-ratio-analysis')
def main_inflow_ratio_analysis_page():
    """主力净流入占比因子分析页面"""
    return render_template('main_inflow_ratio_analysis.html')


@app.route('/api/factor/main-inflow-ratio', methods=['GET'])
def api_main_inflow_ratio():
    """API: 主力净流入占比因子分析"""
    num_layers = request.args.get('num_layers', default=5, type=int)
    
    # 检查数据可用性
    has_data = check_main_inflow_ratio_data_availability()
    
    if not has_data:
        return jsonify({
            'success': False,
            'error': '数据不足：缺少主力净流入或流通市值数据',
            'message': '请先运行数据预计算脚本: python precompute_main_inflow_ratio.py'
        })
    
    # 启动后台分析任务
    # ... 类似 turnover_surge_analysis


@app.route('/api/factor/main-inflow-ratio/progress')
def api_main_inflow_ratio_progress():
    """API: 主力净流入占比因子分析进度"""
    with main_inflow_ratio_analysis_lock:
        return jsonify(main_inflow_ratio_analysis_state)


def check_main_inflow_ratio_data_availability():
    """检查主力净流入占比数据是否可用
    
    Returns:
        bool: 数据是否可用
    """
    factor_path = CACHE_DIR / 'factor_data.json.gz'
    
    if not factor_path.exists():
        return False
    
    with gzip.open(factor_path, 'rt', encoding='utf-8') as f:
        data = json.load(f)
    
    if 'data' in data and len(data['data']) > 0:
        sample = data['data'][0]
        return 'main_net_inflow' in sample and 'float_market_cap' in sample
    
    return False
```

### 7.4 页面模板

**新增文件**: `templates/main_inflow_ratio_analysis.html`

参考 `turnover_surge_analysis.html` 结构，调整：
- 页面标题改为"主力净流入占比因子分析总览"
- 因子说明区改为"主力净流入占比 = 主力净流入金额 / 流通市值"
- 导航栏增加"主力净流入占比"链接

---

## 8. 测试用例（给云汐）

### 8.1 功能测试

| 场景 | 操作 | 预期结果 |
|------|------|----------|
| 正常访问 | 打开 `/main-inflow-ratio-analysis` | 显示页面标题和因子说明 |
| 数据检查 | 点击"运行分析"按钮 | 检查数据可用性，显示提示 |
| 运行分析 | 数据可用时运行分析 | 显示进度条，阶段显示正确 |
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
| 数据缺失 | 缺少主力净流入/流通市值字段 | 显示错误提示，引导获取数据 |
| 无缓存数据 | 删除缓存后运行分析 | 显示错误提示，引导获取数据 |
| 单日数据 | 只有1天数据 | IC 无法计算，显示提示 |
| 极端值处理 | 主力净流入占比 > 10% | 裁剪至 10%，不影响分析 |
| 市值为0 | 流通市值=0的股票 | 因子值设为 None，剔除 |

### 8.3 性能测试

| 场景 | 预期结果 |
|------|----------|
| 首次运行时间 | < 90秒（包含数据获取） |
| 进度更新频率 | 每秒更新一次 |
| 页面加载时间 | < 2秒 |
| 图表渲染时间 | < 3秒 |

### 8.4 UI 测试

| 场景 | 预期结果 |
|------|----------|
| 页面标题 | "主力净流入占比因子分析总览" |
| 因子说明 | 醒目显示，内容正确 |
| 导航栏 | 包含"主力净流入占比"链接 |
| 指标卡片样式 | 与其他因子页面一致 |
| 图表交互 | 鼠标悬停显示 tooltip |
| 表格排序 | 点击列头可排序 |

### 8.5 数据验证

| 验收项 | 预期结果 |
|--------|----------|
| IC均值范围 | 通常在 -0.05 ~ 0.08 |
| ICIR范围 | 通常在 0 ~ 1.5 |
| 因子值范围 | 在 [-10%, +10%] 区间内 |
| 分层收益 | 各层有差异，非完全相同 |
| 多空收益 | 正或负（取决于因子有效性） |

---

## 9. 验收标准

### 9.1 功能验收

| 验收项 | 验收方法 | 预期结果 |
|--------|----------|----------|
| 页面可访问 | 浏览器访问 `/main-inflow-ratio-analysis` | 显示页面 |
| 数据可用性检查 | 检查缓存字段 | 显示数据状态 |
| IC 计算正确 | 对比手工计算 | 数值一致 |
| 分层回测正确 | 检查分层收益数据 | 数据结构完整 |
| 多空净值计算 | 检查净值曲线 | 曲线起点=1.0 |
| 单调性检验 | 检查检验结果 | 显示通过/未通过 |

### 9.2 数据验收

| 验收项 | 预期结果 |
|--------|----------|
| 主力净流入字段存在 | 缓存包含 main_net_inflow 字段 |
| 流通市值字段存在 | 缓存包含 float_market_cap 字段 |
| 因子值范围 | 在 [-10%, +10%] 区间内 |
| 数据覆盖率 | > 90%（大部分股票有数据） |

---

## 10. 开发优先级

| 优先级 | 功能 | 原因 |
|--------|------|------|
| **P0** | 数据获取模块 | 核心依赖，缺数据无法分析 |
| P0 | 因子计算模块 | 核心功能 |
| P0 | API 接口实现 | 前端依赖 |
| P0 | 页面模板创建 | 用户入口 |
| P1 | IC 计算逻辑 | 分析核心 |
| P1 | 分层回测 | 分析核心 |
| P1 | 数据可用性检查 | 数据透明 |
| P2 | 图表渲染 | 可复用代码 |
| P2 | 指标卡片 | 可复用代码 |
| P3 | 导航链接 | 整合到系统 |

---

## 11. 数据获取详细方案

### 11.1 新浪财经主力资金流向 API

**接口地址**：
```
https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/MoneyFlow.ssl_mfstock_history
```

**请求参数**：
| 参数 | 类型 | 说明 |
|------|------|------|
| symbol | string | 股票代码（如 sh600000） |
| num | int | 获取天数（如 60） |

**返回字段**：
| 字段 | 类型 | 说明 |
|------|------|------|
| date | string | 交易日期 |
| main_net_inflow | float | 主力净流入（万元） |
| main_inflow | float | 主力流入（万元） |
| main_outflow | float | 主力流出（万元） |
| retail_net_inflow | float | 散户净流入（万元） |

### 11.2 流通市值获取方案

**方案A：从实时行情接口获取**
```
https://quotes.sina.cn/cn/api/json_v2.php/CN_MarketDataService.getKLineData
```

返回字段可能包含流通市值，或可从收盘价 * 流通股本计算。

**方案B：从股票详情接口获取**
```
https://vip.stock.finance.sina.com.cn/corp/go.php/vIR_FinanceSummary/stockid/600000.phtml
```

包含流通股本信息，结合收盘价计算流通市值。

**方案C：使用缓存中的成交量数据**
- 从历史数据计算流通股本
- 结合收盘价估算流通市值

### 11.3 数据获取注意事项

| 注意项 | 说明 |
|--------|------|
| API 限流 | 新浪 API 有请求频率限制，需要分批获取 |
| 数据延迟 | 主力资金数据可能有延迟 |
| 数据缺失 | 部分股票可能无主力资金数据 |
| 并发控制 | 使用固定并发策略（每批次2线程） |
| 失败重试 | 添加重试机制，最多3次 |

---

## 12. 附录

### 12.1 主力净流入占比因子的理论背景

**主力资金**：通常指大单交易（> 50万元），反映机构或大户的资金流向。

**主力净流入**：主力流入金额 - 主力流出金额
- 正值：主力资金净买入，看好后市
- 负值：主力资金净卖出，看空后市

**为什么要标准化**：
- 大市值股票天然主力资金流入金额大（绝对金额）
- 小市值股票主力资金流入金额小
- 直接比较不公平，需要标准化

**主力净流入占比的优势**：
- 标准化后可以跨市值比较
- 无量纲比例，便于因子组合
- 反映主力资金的相对参与程度

### 12.2 与其他因子的对比

| 因子 | 计算方式 | 预测逻辑 | 适用场景 |
|------|----------|----------|----------|
| RSI(6) | 相对强弱指数 | 超卖反弹 | 反转策略 |
| 量比(5) | 当日成交量/5日均量 | 放量关注 | 资金流入 |
| 3日涨幅 | 3日累计涨幅 | 动量延续 | 趋势策略 |
| 换手率突增 | 换手率/5日均值 | 关注度提升 | 强势股筛选 |
| **主力净流入占比** | 主力净流入/流通市值 | 主力资金看好 | 主力资金策略 |

### 12.3 预期结果

基于理论分析，预期：
- **IC 均值**：正数，0.03 ~ 0.06（主力流入预示上涨）
- **多空收益**：正数，年化 5% ~ 15%
- **单调性**：通过，主力净流入占比越高，收益越高

**注意**：因子有效性需通过实际数据验证，可能出现与预期不符的情况。

---

**文档生成时间**: 2026-04-05
**文档作者**: 云柏 📝
**目标读者**: 云舟（开发）、云汐（测试）