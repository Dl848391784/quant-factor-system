# 脚本架构重构需求文档

## 背景

现有量化系统脚本架构存在职责混乱问题：
- 数据拉取脚本混合了缓存逻辑
- IC计算使用通用类而非独立脚本
- 输入输出格式不一致
- 脚本职责不清晰

## 目标

重构脚本架构，实现：
1. 数据拉取脚本只负责拉取数据
2. 因子IC计算脚本每个因子一个，独立运行
3. 输入输出格式统一规范
4. 每个脚本只干一件事情
5. 通过目录区分职责

## 现有脚本分析

### 数据拉取脚本
- `fetch_factor_data.py` - 拉取因子数据并缓存
- `fetch_turnover_rate*.py` - 换手率数据拉取（多个版本）
- `fetch_main_inflow.py` - 主力资金流入数据
- `fetch_float_mv.py` - 流通市值数据

### IC计算脚本
- `ic_calculator.py` - 通用IC计算类（可分析多个因子）
- `rsi_ic_generator.py` - RSI因子IC计算（但依赖RealDataLoader）

### 因子计算脚本
- `kdj_j_factor.py` - KDJ_J因子计算
- `bollinger_pb_factor.py` - BOLL_PB因子计算
- `turnover_surge_factor.py` - 换手率突增因子
- `main_inflow_ratio_factor.py` - 主力资金比例因子
- `volume_ratio` 相关脚本

## 目标架构设计

### 目录结构

```
factor_ic_analyzer/
├── data_fetchers/           # 数据拉取脚本（独立目录）
│   ├── __init__.py
│   ├── fetch_ohlcv.py       # 拉取OHLCV行情数据
│   ├── fetch_turnover.py    # 拉取换手率数据
│   ├── fetch_main_inflow.py # 拉取主力资金数据
│   └── fetch_float_mv.py    # 拉取流通市值数据
│   └── fetch_industry.py    # 拉取行业分类数据
│
├── factor_ic/               # 因子IC计算脚本（独立目录）
│   ├── __init__.py
│   ├── rsi_ic.py            # RSI因子IC计算
│   ├── kdj_j_ic.py          # KDJ_J因子IC计算
│   ├── bollinger_pb_ic.py   # BOLL_PB因子IC计算
│   ├── turnover_surge_ic.py # 换手率突增因子IC
│   ├── main_inflow_ratio_ic.py # 主力资金比例因子IC
│   ├── volume_ratio_ic.py   # 量比因子IC计算
│   └── ...                  # 其他因子IC脚本
│
├── common/                  # 公共模块（已存在）
│   ├── ic_engine.py         # IC计算引擎（通用函数）
│   ├── data_loader.py       # 数据加载器
│   └── ...
│
├── versions/                # 版本目录（已存在）
│   ├── v2/
│   ├── v3/
│   └── ...
│
└── scripts/                 # 其他脚本（已存在）
```

### 输入输出统一规范

#### 数据拉取脚本输入输出

**输入**（命令行参数）：
```bash
python data_fetchers/fetch_ohlcv.py --n_days 500 --max_stocks 0 --output cache/ohlcv.pkl
```

**输出**：
- 缓存文件：`cache/{data_type}.pkl` 或 `.json.gz`
- 日志文件：`logs/fetch_{data_type}.log`
- 状态文件：`cache/{data_type}_status.json`
  ```json
  {
    "success": true,
    "timestamp": "2026-05-07T17:00:00",
    "records_count": 123456,
    "stocks_count": 500,
    "days_count": 500,
    "cache_path": "cache/ohlcv.pkl"
  }
  ```

#### 因子IC计算脚本输入输出

**输入**（命令行参数）：
```bash
python factor_ic/rsi_ic.py --cache cache/ohlcv.pkl --output output/rsi_ic.json
```

**输入规范**（从缓存读取）：
- 因子数据缓存路径：`--factor_cache`
- 收益数据缓存路径：`--return_cache`
- 或合并缓存路径：`--cache`

**输出规范**（JSON格式）：
```json
{
  "factor_name": "rsi_6",
  "ic_mean": 0.0234,
  "ic_std": 0.1567,
  "icir": 0.15,
  "t_stat": 2.34,
  "positive_ratio": 0.56,
  "sample_days": 250,
  "sample_stocks": 500,
  "ic_series": [0.01, 0.02, ...],
  "dates": ["2026-01-01", ...],
  "status": "success",
  "timestamp": "2026-05-07T17:00:00"
}
```

### 脚本职责定义

#### 数据拉取脚本职责
1. 从数据源（akshare/baostock）拉取原始数据
2. 数据清洗和格式化
3. 缓存到本地文件
4. 输出状态信息
5. **不计算因子、不计算IC**

#### 因子IC计算脚本职责
1. 从缓存加载因子数据和收益数据
2. 计算该因子的每日IC序列
3. 计算IC统计指标（IC均值、ICIR、t统计量等）
4. 输出JSON结果文件
5. **不拉取数据、不计算其他因子**

### 公共模块职责

#### `common/ic_engine.py`
- 提供 `calculate_ic_series()` 函数
- 提供 `calculate_ic_statistics()` 函数
- 所有因子IC脚本调用此模块

#### `common/data_loader.py`
- 提供 `load_factor_cache()` 函数
- 提供 `load_return_cache()` 函数
- 所有脚本调用此模块加载缓存数据

## 实施计划

### 阶段1：创建公共模块
1. 创建 `common/ic_engine.py` - IC计算通用函数
2. 更新 `common/data_loader.py` - 缓存加载函数

### 阶段2：迁移数据拉取脚本
1. 创建 `data_fetchers/` 目录
2. 重构各 `fetch_*.py` 脚本到新目录
3. 统一输入输出格式

### 阘段3：拆分因子IC脚本
1. 创建 `factor_ic/` 目录
2. 从现有脚本拆分出独立因子IC脚本
3. 每个因子一个脚本

### 阶段4：验证测试
1. 测试数据拉取脚本独立运行
2. 测试因子IC脚本独立运行
3. 验证输入输出格式一致性

## 约束条件

1. **内存预算**：单个脚本内存不超过1GB
2. **兼容性**：不破坏现有 `versions/v2/v3` 的依赖
3. **可测试性**：每个脚本可独立测试
4. **日志规范**：统一使用 `logs/` 目录输出日志

## 验收标准

1. 所有数据拉取脚本在 `data_fetchers/` 目录
2. 所有因子IC脚本在 `factor_ic/` 目录
3. 输入输出格式符合规范
4. 每个脚本独立运行成功
5. 单元测试覆盖核心功能

## 下一步

- 云柏输出技术方案详细设计
- 云舟+云汐审核方案
- 云柏完善方案
- 云汐生成测试用例
- 云舟实施代码
- 云汐执行测试