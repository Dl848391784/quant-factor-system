# factor_generator.py 流程文档

> 版本: v1.0
> 创建时间: 2026-05-25 10:25 北京时间
> 脚本路径: `data_fetchers/factor_generator.py`

---

## 整体架构

```
┌─────────────────────────────────────────────────────────────────────────┐
│                       factor_generator.py 统一因子生成                    │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│   输入数据                                                               │
│   ┌──────────────────┐    ┌──────────────────┐                         │
│   │factor_data.json.gz│    │turnover_rate_data│                         │
│   │  (基础因子数据)    │    │   .json.gz       │                         │
│   │  - rsi_6         │    │  (换手率数据)     │                         │
│   │  - volume_ratio_5│    │                  │                         │
│   └──────────────────┘    └──────────────────┘                         │
│           │                        │                                    │
│           ▼                        ▼                                    │
│   ┌─────────────────────────────────────────────────────────────┐      │
│   │                    Step 1-2: 数据加载                         │      │
│   │  - 加载基础因子数据（gzip JSON）                              │      │
│   │  - 加载换手率数据并合并                                       │      │
│   └─────────────────────────────────────────────────────────────┘      │
│                              │                                          │
│                              ▼                                          │
│   ┌─────────────────────────────────────────────────────────────┐      │
│   │                 Step 3-5: 扩展因子计算                        │      │
│   │  - calculate_bollinger_pb (布林带 %B)                        │      │
│   │  - calculate_kdj_j (KDJ 指标 J 值)                           │      │
│   │  - calculate_turnover_surge (换手率突增)                     │      │
│   └─────────────────────────────────────────────────────────────┘      │
│                              │                                          │
│                              ▼                                          │
│   ┌─────────────────────────────────────────────────────────────┐      │
│   │                    Step 6-7: 输出格式化                        │      │
│   │  - 格式化日期（YYYY-MM-DD）                                   │      │
│   │  - 构建 dates + data 结构                                     │      │
│   │  - 原子写入 gzip JSON                                         │      │
│   └─────────────────────────────────────────────────────────────┘      │
│                              │                                          │
│                              ▼                                          │
│   ┌─────────────────────────────────────────────────────────────┐      │
│   │                 factor_data_extended.json.gz                  │      │
│   │  - dates: [日期列表]                                          │      │
│   │  - data: [所有因子数据]                                       │      │
│   │  (包含 5 个因子: rsi_6, volume_ratio_5, bollinger_pb,        │      │
│   │   kdj_j, turnover_surge)                                     │      │
│   └─────────────────────────────────────────────────────────────┘      │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 详细流程步骤

### Step 1: 加载基础因子数据

**输入**: `cache/factor_data/factor_data.json.gz`

**操作**:
```python
with gzip.open(factor_data_path, 'rt') as f:
    base_data = json.load(f)
factor_df = pd.DataFrame(base_data['data'])
factor_df['date'] = pd.to_datetime(factor_df['date'])
```

**验证**:
- 检查 `data` 字段存在
- 检查 `date` 列存在

---

### Step 2: 加载换手率数据并合并

**输入**: `cache/factor_data/turnover_rate_data.json.gz`

**操作**:
```python
turnover_df = pd.DataFrame(turnover_data['data'])
turnover_df['date'] = pd.to_datetime(turnover_df['date'], format='mixed')
factor_df = factor_df.merge(
    turnover_df[['date', 'asset', 'turnover_rate']],
    on=['date', 'asset'], how='left'
)
```

**验证**:
- 检查 `data` 字段存在
- 记录换手率缺失数量

---

### Step 3: 计算 Bollinger_PB 因子

**调用**: `calculate_bollinger_pb(factor_df)`

**参数**:
- n=20（移动平均周期）
- k=2.0（标准差倍数）

**依赖**:
- close（收盘价）

**输出列**: `bollinger_pb`

---

### Step 4: 计算 KDJ_J 因子

**调用**: `calculate_kdj_j(factor_df)`

**参数**:
- n=9（RSV 计算周期）
- m1=3（K 值平滑周期）
- m2=3（D 值平滑周期）

**依赖**:
- close（收盘价）
- high（最高价）
- low（最低价）

**输出列**: `kdj_j`

---

### Step 5: 计算 Turnover_Surge 因子

**调用**: `calculate_turnover_surge(factor_df)`

**参数**:
- window=5（换手率均值窗口）

**依赖**:
- turnover_rate（换手率）
- close（收盘价）

**输出列**: `turnover_surge`

---

### Step 6: 格式化输出

**操作**:
```python
factor_df['date'] = factor_df['date'].dt.strftime('%Y-%m-%d')

output_cols = [
    'date', 'asset', 'open', 'close', 'high', 'low',
    'rsi_6', 'volume_ratio_5',
    'bollinger_pb', 'kdj_j', 'turnover_surge'
]

output_df = factor_df[output_cols].copy()
```

**列说明**:
| 索引范围 | 内容 | 说明 |
|---------|------|------|
| 0:6 | date, asset, open, close, high, low | 基础 OHLCV 数据 |
| 6:8 | rsi_6, volume_ratio_5 | 基础因子（来自输入） |
| 8:11 | bollinger_pb, kdj_j, turnover_surge | 扩展因子（本次计算） |

---

### Step 7: 保存输出

**输出路径**: `cache/factor_data/factor_data_extended.json.gz`

**操作**:
```python
output_data = {
    'dates': sorted(factor_df['date'].unique().tolist()),
    'data': output_df.to_dict('records')
}

# 原子写入：临时文件 + os.replace
temp_path = output_path.with_suffix('.tmp')
with gzip.open(temp_path, 'wt') as f:
    json.dump(output_data, f)
os.replace(temp_path, output_path)
```

---

### Step 8: 返回元数据

**返回结构**:
```python
metadata = {
    'generated_at': 'YYYY-MM-DD HH:MM:SS',
    'elapsed_seconds': 120.5,
    'total_records': 1480000,
    'valid_records': {
        'bollinger_pb': 1460000,
        'kdj_j': 1460000,
        'turnover_surge': 1460000,
    },
    'valid_records_percent': {
        'bollinger_pb': 98.65,
        'kdj_j': 98.65,
        'turnover_surge': 98.65,
    },
    'factor_columns': ['bollinger_pb', 'kdj_j', 'turnover_surge'],
    'input_sources': {...},
    'output_path': '...'
}
```

---

## 输出结构

### factor_data_extended.json.gz

```json
{
  "dates": ["2024-04-19", "2024-04-20", ...],
  "data": [
    {
      "date": "2024-04-19",
      "asset": "000001",
      "open": 10.71,
      "close": 10.69,
      "high": 10.82,
      "low": 10.66,
      "rsi_6": 64.42,
      "volume_ratio_5": 0.74,
      "bollinger_pb": null,
      "kdj_j": null,
      "turnover_surge": null
    },
    ...
  ]
}
```

**字段说明**:

| 字段 | 类型 | 说明 |
|------|------|------|
| dates | list[str] | 日期列表（YYYY-MM-DD 格式） |
| data | list[dict] | 因子数据列表 |
| date | str | 日期 |
| asset | str | 股票代码 |
| open/close/high/low | float | OHLCV 价格数据 |
| rsi_6 | float | RSI(6) 指标 |
| volume_ratio_5 | float | 量比(5) 指标 |
| bollinger_pb | float/null | 布林带 %B |
| kdj_j | float/null | KDJ 指标 J 值 |
| turnover_surge | float/null | 换手率突增 |

---

## 关键指标定义

### valid_records

**定义**: 因子值非空的记录数

**计算方式**:
```python
bollinger_valid = factor_df['bollinger_pb'].notna().sum()
kdj_valid = factor_df['kdj_j'].notna().sum()
surge_valid = factor_df['turnover_surge'].notna().sum()
```

### valid_records_percent

**定义**: 有效记录占总记录的百分比

**计算方式**:
```python
percent = round(valid_count / total_records * 100, 2)
```

### elapsed_seconds

**定义**: 因子生成总耗时（秒）

---

## CLI 使用方式

### 默认运行

```bash
python data_fetchers/factor_generator.py
```

### 自定义路径

```bash
python data_fetchers/factor_generator.py \
    --factor_data path/to/factor_data.json.gz \
    --turnover_data path/to/turnover_rate_data.json.gz \
    --output path/to/output.json.gz
```

### 静默模式

```bash
python data_fetchers/factor_generator.py --quiet
```

---

## Python API 使用方式

```python
from data_fetchers.factor_generator import generate_all_factors

# 使用默认 logger
metadata = generate_all_factors()

# 使用自定义 logger
import logging
logger = logging.getLogger('my_app')
metadata = generate_all_factors(logger=logger)

# 自定义路径
metadata = generate_all_factors(
    factor_data_path='path/to/factor_data.json.gz',
    turnover_data_path='path/to/turnover_rate_data.json.gz',
    output_path='path/to/output.json.gz',
    logger=logger
)
```

---

## 版本历史

| 版本 | 日期 | 更新内容 |
|------|------|---------|
| v1.0 | 2026-05-25 | 创建流程文档 |

---

*创建时间: 2026-05-25 10:25 北京时间*