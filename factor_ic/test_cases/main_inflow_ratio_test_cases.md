# 主力净流入占比因子IC测试用例

> 文档版本: v1.0  
> 生成时间: 2026-05-09  
> 对应脚本: `ic_main_inflow_ratio.py`

---

## 测试环境

### 数据库连接要求
- 无需数据库连接（使用缓存数据文件）
- 需要文件系统访问权限

### 测试数据准备

#### 目录结构
```
cache/
├── main_inflow/
│   └── main_inflow_history.json.gz  # 主力净流入历史数据（专用缓存）
└── factor_data/
    └── return_data.json.gz          # 收益数据缓存
```

#### 数据格式要求

**main_inflow_history.json.gz**:
```json
{
    "meta": {
        "dates": ["2026-01-01", "2026-01-02", ...]
    },
    "data": [
        {
            "date": "2026-01-01", 
            "asset": "000001.SZ", 
            "main_net_inflow": 50000000,
            "float_market_cap": 10000000000,
            "main_inflow_ratio": 0.005,
            "super_net_inflow": 30000000,
            "big_net_inflow": 20000000,
            "medium_net_inflow": 10000000,
            "small_net_inflow": -5000000
        },
        ...
    ]
}
```

**return_data.json.gz**:
```json
{
    "data": [
        {"date": "2026-01-01", "asset": "000001.SZ", "forward_return_1d": 0.023},
        {"date": "2026-01-01", "asset": "000002.SZ", "forward_return_1d": -0.015},
        ...
    ]
}
```

#### 必需字段
| 文件 | 必需字段 |
|------|---------|
| main_inflow_history.json.gz | date, asset, main_net_inflow, float_market_cap |
| return_data.json.gz | date, asset, forward_return_1d |

#### 最小测试数据量
- 交易日数: ≥ 20天
- 股票数量: ≥ 10只/天
- 推荐测试数据: 100个交易日 × 50只股票

---

## 功能测试

### TC001: 正常流程 - 完整IC计算
**前置条件**: 
- 缓存文件 `main_inflow_history.json.gz` 和 `return_data.json.gz` 存在
- 数据包含至少20个交易日
- 每个交易日至少10只股票

**测试步骤**:
1. 执行 `python ic_main_inflow_ratio.py`
2. 观察控制台输出
3. 检查输出文件 `cache/factor_ic/main_inflow_ratio_ic.json`

**预期结果**:
- 脚本正常完成，无异常退出
- 控制台显示:
  - 数据加载统计（因子数据、收益数据行数和内存占用）
  - 因子计算统计（总记录数、有效记录数、流通市值为0数量、主力净流入缺失数量）
  - 极端值裁剪信息（范围、裁剪记录数）
  - IC均值、ICIR、正比例、t统计量
  - 分层回测统计（多空收益、夏普比率、最大回撤）
- 输出JSON文件包含:
  - `factor_name`: "main_inflow_ratio"
  - `ic_metrics`: 包含所有统计指标
  - `ic_series`: 包含日期列表、IC值列表、滚动均值列表
  - `layered_result`: 分层回测结果
  - `generated_at`: 生成时间戳

---

### TC002: 数据加载功能验证 - 主力净流入数据
**前置条件**: 
- 主力净流入缓存文件存在且格式正确

**测试步骤**:
1. 调用 `load_main_inflow_history()` 函数
2. 验证返回的 DataFrame 结构

**预期结果**:
- 返回两个 DataFrame: `factor_df`, `return_df`
- `factor_df` 包含列: `['date', 'asset', 'main_net_inflow', 'float_market_cap', 'main_inflow_ratio', ...]`
- `return_df` 包含列: `['date', 'asset', 'forward_return', 'forward_return_1d']`
- 数据限制在最近500天（或实际数据量，如果少于500天）
- date 和 asset 列已转换为 category 类型（use_category=True）

---

### TC003: 因子计算功能验证
**前置条件**: 
- 已加载有效的 factor_df，包含 main_net_inflow 和 float_market_cap 列

**测试步骤**:
1. 调用 `calculate_main_inflow_ratio_factor(factor_df)`
2. 验证返回的 factor_df 和统计信息

**预期结果**:
- factor_df 新增或更新 `main_inflow_ratio` 列
- 返回 stats 字典包含:
  - `total_records`: 总记录数
  - `valid_records`: 有效记录数（流通市值>0且主力净流入非空）
  - `zero_cap_count`: 流通市值为0的记录数
  - `missing_inflow_count`: 主力净流入缺失的记录数
  - `winsorized_count`: 被极端值裁剪的记录数
- 极端值被裁剪到 [-0.5, 0.5] 范围

---

### TC004: 正向排名IC计算验证
**前置条件**: 
- 准备已知数据的测试用例

**测试步骤**:
1. 构造测试数据（某日3只股票）:
   - 股票A: main_inflow_ratio=+0.05（主力流入）, forward_return=0.06
   - 股票B: main_inflow_ratio=0.00（无流入流出）, forward_return=0.02
   - 股票C: main_inflow_ratio=-0.03（主力流出）, forward_return=-0.02
2. 调用 `calculate_main_inflow_ratio_ic()`
3. 验证IC值

**预期结果**:
- IC值应为正相关（接近 +1）
- 因为流入占比高→收益高，流入占比低→收益低
- 验证使用的是 Spearman 相关系数
- 验证排名使用 `ascending=True`（正向排名）

---

### TC005: 极端值裁剪功能
**前置条件**: 
- 准备包含极端值的数据

**测试步骤**:
1. 构造测试数据:
   - 股票A: main_net_inflow=100亿, float_market_cap=50亿 → ratio=2.0（超出上限）
   - 股票B: main_net_inflow=-80亿, float_market_cap=50亿 → ratio=-1.6（超出下限）
   - 股票C: main_net_inflow=1亿, float_market_cap=10亿 → ratio=0.1（正常范围）
2. 调用 `calculate_main_inflow_ratio_factor(factor_df, winsorize=True)`

**预期结果**:
- 股票A的 ratio 被裁剪为 0.5
- 股票B的 ratio 被裁剪为 -0.5
- 股票C的 ratio 保持 0.1
- `winsorized_count` = 2

---

### TC006: 极端值裁剪关闭
**前置条件**: 
- 准备包含极端值的数据

**测试步骤**:
1. 构造包含极端值的测试数据
2. 调用 `calculate_main_inflow_ratio_factor(factor_df, winsorize=False)`

**预期结果**:
- 极端值保持原值，不被裁剪
- `winsorized_count` = 0

---

### TC007: 流通市值为0的处理
**前置条件**: 
- 数据中存在流通市值为0的记录

**测试步骤**:
1. 构造测试数据:
   - 股票A: float_market_cap=100亿, main_net_inflow=1亿
   - 股票B: float_market_cap=0, main_net_inflow=5000万
   - 股票C: float_market_cap=-1, main_net_inflow=3000万（异常负值）
2. 执行因子计算

**预期结果**:
- 股票A正常计算 ratio
- 股票B和股票C的 ratio 设为 NaN
- `zero_cap_count` = 2
- 这些记录不参与IC计算

---

### TC008: 主力净流入缺失的处理
**前置条件**: 
- 数据中存在主力净流入缺失的记录

**测试步骤**:
1. 构造测试数据，部分记录 main_net_inflow 为 NaN
2. 执行因子计算

**预期结果**:
- 缺失记录的 ratio 设为 NaN
- `missing_inflow_count` 正确统计
- 这些记录不参与IC计算

---

### TC009: 显著性判断逻辑
**前置条件**: 
- 已计算出 t_stat 值

**测试步骤**:
创建测试用例验证各显著性级别:

| t_stat 范围 | 预期显著性 |
|------------|-----------|
| \|t_stat\| > 3.29 | "***" |
| 2.58 < \|t_stat\| ≤ 3.29 | "**" |
| 1.96 < \|t_stat\| ≤ 2.58 | "*" |
| \|t_stat\| ≤ 1.96 | "" |

**预期结果**:
- 显著性标记正确对应 t_stat 值范围

---

### TC010: 分层回测功能验证
**前置条件**: 
- 准备充足的数据用于分层回测
- 数据量至少覆盖100个交易日

**测试步骤**:
1. 执行完整分析 `run_main_inflow_ratio_analysis(n_days=100, num_layers=10)`
2. 验证 `layered_result` 输出

**预期结果**:
- `layered_result` 包含:
  - `layer_returns`: 每日各层收益
  - `cumulative_returns`: 累计收益
  - `statistics`: 各层统计信息
  - `long_short`: 多空组合数据
  - `summary`: 包含多空年化收益、夏普比率、最大回撤、单调性检验
- 主力净流入占比是正向因子：
  - Layer 1（流入占比最低）预期收益低
  - Layer 10（流入占比最高）预期收益高
  - 单调性检验应通过（收益递增）

---

### TC011: 增量判断 - 数据完备跳过
**前置条件**: 
- IC缓存文件 `main_inflow_ratio_ic.json` 已存在
- 缓存数据完备，无需更新

**测试步骤**:
1. 确保 IC 缓存文件存在
2. 运行 `check_data_completeness('main_inflow_ratio')`
3. 验证返回 mode

**预期结果**:
- 返回 mode = 'skip'
- 脚本输出 "数据完备，无需重新计算"
- 脚本以 exit(0) 正常退出

---

### TC012: 增量判断 - 需要补充数据
**前置条件**: 
- IC缓存文件存在但数据不完整
- 部分日期需要更新

**测试步骤**:
1. 删除部分日期的数据
2. 运行 `check_data_completeness('main_inflow_ratio')`

**预期结果**:
- 返回 mode = 'incremental'
- 返回 missing_dates 列表
- 脚本继续执行增量计算

---

### TC013: 增量判断 - 全量重算
**前置条件**: 
- IC缓存文件不存在
- 或主力净流入数据有重大更新

**测试步骤**:
1. 删除 IC 缓存文件
2. 运行 `check_data_completeness('main_inflow_ratio')`

**预期结果**:
- 返回 mode = 'full'
- 脚本执行全量计算

---

### TC014: 输出文件格式验证
**前置条件**: 
- 脚本正常执行完成

**测试步骤**:
1. 读取输出文件 `cache/factor_ic/main_inflow_ratio_ic.json`
2. 验证JSON结构

**预期结果**:
JSON结构包含:
```json
{
    "factor_name": "main_inflow_ratio",
    "ic_metrics": {
        "ic_mean": <float>,
        "ic_std": <float>,
        "icir": <float>,
        "positive_ratio": <float>,
        "t_stat": <float>,
        "p_value": <float>,
        "significance": "<string>",
        "n_days": <int>,
        "n_assets": <int>,
        "summary": "<string>"
    },
    "ic_series": {
        "dates": [<string>, ...],
        "ic_values": [<float>, ...],
        "rolling_ic_mean": [<float>, ...]
    },
    "calculated_at": "<ISO datetime>"
}
```

---

### TC015: p_value 字段验证
**前置条件**: 
- IC 计算完成，输出文件已生成
- t_stat 值已计算

**测试步骤**:
1. 读取输出文件中的 `ic_metrics.p_value` 字段
2. 验证 p_value 计算逻辑
3. 验证 p_value 与 t_stat 的对应关系

**预期结果**:
- `p_value` 为 float 类型，范围在 [0, 1]
- p_value 计算公式正确：
  ```python
  from scipy import stats
  p_value = 2 * (1 - stats.t.cdf(abs(t_stat), df=n_days - 1))
  ```
- p_value 与 significance 对应正确：
  - p < 0.001 → significance = "***"
  - p < 0.01 → significance = "**"
  - p < 0.05 → significance = "*"
  - p >= 0.05 → significance = ""
- p_value 可序列化为 JSON（非 numpy 类型）

**实际结果**: (测试时填写)

---

## 边界测试

### TC101: 最小数据量 - 刚好满足阈值
**前置条件**: 
- 数据包含10只股票
- 数据包含20个交易日

**测试步骤**:
1. 准备最小数据集（10只股票 × 20天）
2. 执行IC计算

**预期结果**:
- 脚本正常执行
- 输出结果包含所有字段
- IC计算有效
- 每个交易日刚好满足阈值

---

### TC102: 单日数据
**前置条件**: 
- 数据仅包含1个交易日
- 包含20只股票

**测试步骤**:
1. 准备单日数据
2. 执行IC计算

**预期结果**:
- 可以计算该日IC值
- t_stat 计算不稳定（n=1）
- p_value = 1（无法计算显著性）
- 滚动均值与IC值相同

---

### TC103: 股票数量刚好为10
**前置条件**: 
- 某个交易日刚好有10只股票有数据

**测试步骤**:
1. 准备包含某天刚好10只股票的数据
2. 执行IC计算

**预期结果**:
- 该天被包含在IC计算中（>= 10只股票阈值）
- 计算成功完成

---

### TC104: 股票数量为9
**前置条件**: 
- 某个交易日仅有9只股票有数据

**测试步骤**:
1. 准备包含某天仅9只股票的数据
2. 执行IC计算

**预期结果**:
- 该天被跳过（< 10只股票阈值）
- 其他天数正常计算
- 控制台无错误提示

---

### TC105: IC值全部为正
**前置条件**: 
- 构造因子与收益完全正相关的数据

**测试步骤**:
1. 构造测试数据使得所有天数IC > 0
2. 执行IC计算

**预期结果**:
- `positive_ratio` = 1.0
- `ic_mean` > 0
- `significance` 应为 "***"（如果样本量足够）
- 符合正向因子预期（流入→收益）

---

### TC106: IC值全部为负
**前置条件**: 
- 构造因子与收益完全负相关的数据

**测试步骤**:
1. 构造测试数据使得所有天数IC < 0
2. 执行IC计算

**预期结果**:
- `positive_ratio` = 0.0
- `ic_mean` < 0
- t_stat 为负值
- 与正向因子预期相反，可能需要检查数据

---

### TC107: 因子值全部相同
**前置条件**: 
- 某日所有股票的 main_inflow_ratio 相同

**测试步骤**:
1. 构造某日所有股票因子值相同的数据
2. 执行IC计算

**预期结果**:
- 该日被跳过（因子值无差异）
- `factor_rank.nunique() == 1` 触发跳过
- 其他天数正常计算

---

### TC108: 收益值全部相同
**前置条件**: 
- 某日所有股票的 forward_return 相同

**测试步骤**:
1. 构造某日所有股票收益相同的数据
2. 执行IC计算

**预期结果**:
- 该日被跳过（收益值无差异）
- `return_rank.nunique() == 1` 触发跳过
- 其他天数正常计算

---

### TC109: n_days参数限制
**前置条件**: 
- 缓存数据包含1000个交易日

**测试步骤**:
1. 使用默认 n_days=500 参数
2. 验证输出数据天数

**预期结果**:
- 只处理最近500天数据
- 早期数据被排除
- 控制台显示 "只加载最近 500 天"

---

### TC110: 数据量少于n_days
**前置条件**: 
- 缓存数据仅包含200个交易日

**测试步骤**:
1. 使用默认 n_days=500 参数
2. 执行IC计算

**预期结果**:
- 使用全部200天数据
- 不报错，正常完成
- 输出 n_days = 200

---

### TC111: 极端正值因子占比
**前置条件**: 
- 某股票主力净流入占流通市值的80%

**测试步骤**:
1. 构造 main_net_inflow=80亿, float_market_cap=100亿 的数据
2. 执行因子计算（开启裁剪）

**预期结果**:
- 计算出的原始 ratio = 0.8
- 裁剪后 ratio = 0.5
- 记录被计入 winsorized_count

---

### TC112: 极端负值因子占比
**前置条件**: 
- 某股票主力净流出占流通市值的-60%

**测试步骤**:
1. 构造 main_net_inflow=-60亿, float_market_cap=100亿 的数据
2. 执行因子计算（开启裁剪）

**预期结果**:
- 计算出的原始 ratio = -0.6
- 裁剪后 ratio = -0.5
- 记录被计入 winsorized_count

---

## 异常测试

### TC201: 缓存文件不存在 - 主力净流入数据
**前置条件**: 
- `cache/main_inflow/main_inflow_history.json.gz` 不存在

**测试步骤**:
1. 删除或重命名主力净流入缓存文件
2. 执行脚本

**预期结果**:
- 控制台输出 "历史缓存文件不存在"
- 提示 "请先运行: python precompute_main_inflow.py"
- 返回 (None, None)

---

### TC202: 缓存文件不存在 - 收益数据
**前置条件**: 
- `cache/factor_data/return_data.json.gz` 不存在
- 主力净流入缓存文件存在

**测试步骤**:
1. 删除或重命名收益缓存文件
2. 执行脚本

**预期结果**:
- 控制台输出 "收益数据文件不存在"
- 返回 (None, None)

---

### TC203: 缓存文件损坏 - 非gzip格式
**前置条件**: 
- 缓存文件存在但不是有效的gzip格式

**测试步骤**:
1. 创建非gzip格式的缓存文件
2. 执行脚本

**预期结果**:
- 抛出 gzip 解压异常
- 异常信息包含加载失败提示
- 返回 (None, None)

---

### TC204: 缓存文件损坏 - 非JSON格式
**前置条件**: 
- 缓存文件是gzip格式但内容不是有效JSON

**测试步骤**:
1. 创建包含非JSON内容的gzip文件
2. 执行脚本

**预期结果**:
- 抛出 JSON 解析异常
- 控制台输出 "加载失败"

---

### TC205: 缓存JSON结构错误 - 缺少data字段
**前置条件**: 
- 缓存文件是有效JSON但缺少 `data` 字段

**测试步骤**:
1. 创建格式为 `{"other": "data"}` 的缓存文件
2. 执行脚本

**预期结果**:
- 数据解析后为空列表
- 控制台输出 "数据为空"
- 返回 (None, None)

---

### TC206: 缺少必要的因子列 - main_net_inflow
**前置条件**: 
- 主力净流入数据不包含 `main_net_inflow` 列

**测试步骤**:
1. 创建缺少 `main_net_inflow` 列的缓存
2. 执行脚本

**预期结果**:
- 控制台输出 "缺少必要列: ['main_net_inflow']"
- 因子计算返回空结果

---

### TC207: 缺少必要的因子列 - float_market_cap
**前置条件**: 
- 主力净流入数据不包含 `float_market_cap` 列

**测试步骤**:
1. 创建缺少 `float_market_cap` 列的缓存
2. 执行脚本

**预期结果**:
- 控制台输出 "缺少必要列: ['float_market_cap']"
- 因子计算返回空结果

---

### TC208: 缺少必要的收益列
**前置条件**: 
- 收益数据不包含 `forward_return_1d` 列

**测试步骤**:
1. 创建缺少 `forward_return_1d` 列的收益缓存
2. 执行脚本

**预期结果**:
- 抛出 KeyError 异常
- 或收益列为 NaN

---

### TC209: 全部数据为NaN
**前置条件**: 
- 所有 main_net_inflow 或 float_market_cap 值都是 NaN

**测试步骤**:
1. 创建全部值为 NaN 的缓存数据
2. 执行脚本

**预期结果**:
- 有效记录数为 0
- IC计算返回空结果
- summary 显示 "数据不足，无法计算IC"

---

### TC210: 股票数量不足
**前置条件**: 
- 数据包含的股票数量 < 10

**测试步骤**:
1. 创建仅有5只股票的数据
2. 执行脚本

**预期结果**:
- 所有交易日被跳过（< 10只股票）
- IC序列为空
- summary 显示 "无法计算IC"

---

### TC211: 合并后数据为空
**前置条件**: 
- 因子数据和收益数据的日期/股票完全不匹配

**测试步骤**:
1. 因子数据使用日期2026-01-01
2. 收益数据使用日期2026-01-02（无重叠）
3. 执行脚本

**预期结果**:
- 合并后记录数为 0
- 控制台输出 "合并后数据为空"
- 返回默认IC结果（ic_mean=0, n_days=0）

---

### TC212: 分层回测失败处理
**前置条件**: 
- 数据量不足以进行分层回测
- 或分层回测模块异常

**测试步骤**:
1. 使用极少数据
2. 执行完整分析

**预期结果**:
- 分层回测返回 None 或空结果
- 脚本不崩溃
- layered_result 包含空数据结构

---

### TC213: numpy 类型序列化测试
**前置条件**: 
- 已实现 `convert_to_native_types()` 函数
- IC 计算产生 numpy 类型的数值

**测试步骤**:
1. 检查 IC 计算结果中各字段的原始类型
2. 验证输出 JSON 文件中的字段类型
3. 测试各种 numpy 类型转换：
   - `numpy.int64` → `int`
   - `numpy.float64` → `float`
   - `numpy.ndarray` → `list`
   - `numpy.bool_` → `bool`

**预期结果**:
- 所有数值字段在输出 JSON 中为 Python native 类型
- `json.dumps()` 不抛出 TypeError
- 典型转换场景：
  ```python
  # ic_mean: numpy.float64 → float
  # n_days: numpy.int64 → int  
  # ic_values: numpy.ndarray → list[float]
  # positive_ratio: numpy.float64 → float
  ```
- `convert_to_native_types()` 函数正确处理嵌套字典结构
- 输出文件可直接被 JSON 解析器读取

**实际结果**: (测试时填写)

---

## 性能测试

### TC301: 大数据量性能测试
**前置条件**: 
- 数据包含500个交易日
- 每个交易日约5000只股票

**测试步骤**:
1. 准备大规模数据（约250万条记录）
2. 执行完整分析
3. 记录内存使用和执行时间

**预期结果**:
- 脚本在合理时间内完成（< 5分钟）
- 内存增量 < 2GB
- 成功输出所有结果

---

### TC302: 内存优化验证 - category类型
**前置条件**: 
- 启用 use_category=True（默认）

**测试步骤**:
1. 执行数据加载
2. 检查 date 和 asset 列的数据类型

**预期结果**:
- date 列为 category 类型
- asset 列为 category 类型
- 内存占用低于不使用 category 的情况

---

### TC303: 内存优化验证 - 分批处理
**前置条件**: 
- 大数据量场景

**测试步骤**:
1. 观察内存使用曲线
2. 检查 gc.collect() 是否被调用

**预期结果**:
- 内存使用呈锯齿状（加载后释放）
- 无内存泄漏
- 峰值内存受控

---

### TC304: 重复执行稳定性
**前置条件**: 
- 正常数据环境

**测试步骤**:
1. 连续执行脚本5次
2. 比较输出结果

**预期结果**:
- 每次执行结果一致（相同输入）
- 无内存泄漏累积
- 无资源未释放问题

---

### TC305: 分层回测性能
**前置条件**: 
- 数据包含100个交易日
- 每个交易日约3000只股票

**测试步骤**:
1. 执行分层回测（10层）
2. 记录执行时间

**预期结果**:
- 分层回测在30秒内完成
- 返回完整的分层结果
- 内存增量合理

---

## 集成测试

### TC401: 与 precompute_main_inflow.py 集成
**前置条件**: 
- 已运行 `python precompute_main_inflow.py` 生成主力净流入缓存

**测试步骤**:
1. 确认主力净流入缓存文件存在
2. 执行 `python ic_main_inflow_ratio.py`
3. 验证IC计算结果

**预期结果**:
- 数据加载成功
- 因子计算正确
- IC计算完成
- 与预期结果一致

---

### TC402: 与其他因子IC模块一致性
**前置条件**: 
- 相同的收益数据缓存
- 多个因子IC模块使用相同的数据格式

**测试步骤**:
1. 比较不同因子IC模块的日期范围
2. 验证收益数据格式一致性

**预期结果**:
- 各模块使用的收益数据格式一致
- 日期对齐正确
- 可比较不同因子的IC值

---

### TC403: 完整流程回归测试
**前置条件**: 
- 标准测试数据集

**测试步骤**:
1. 执行完整分析流程
2. 验证所有输出文件
3. 验证所有统计指标

**预期结果**:
- 所有步骤正常完成
- 输出文件格式正确
- 统计指标在合理范围内:
  - IC均值: 通常在 -0.1 ~ 0.1 之间
  - ICIR: 绝对值通常 < 5
  - 正比例: 0.3 ~ 0.7 之间

---

## 测试执行清单

| 测试类别 | 用例数量 | 执行状态 |
|---------|---------|---------|
| 功能测试 | 14 | ☐ 待执行 |
| 边界测试 | 12 | ☐ 待执行 |
| 异常测试 | 12 | ☐ 待执行 |
| 性能测试 | 5 | ☐ 待执行 |
| 集成测试 | 3 | ☐ 待执行 |
| **总计** | **46** | |

---

## 测试数据生成脚本示例

```python
# 创建最小测试数据集
import json
import gzip
from pathlib import Path

def create_test_data():
    # 创建主力净流入测试数据
    inflow_data = {
        "meta": {"dates": ["2026-01-01", "2026-01-02"]},
        "data": []
    }
    
    for date in ["2026-01-01", "2026-01-02"]:
        for i in range(15):  # 15只股票
            asset = f"{600000+i:06d}.SH"
            inflow_data["data"].append({
                "date": date,
                "asset": asset,
                "main_net_inflow": (i - 7) * 10000000,  # 正负值
                "float_market_cap": 10000000000,  # 100亿
                "super_net_inflow": (i - 7) * 5000000,
                "big_net_inflow": (i - 7) * 5000000,
                "medium_net_inflow": 0,
                "small_net_inflow": 0
            })
    
    # 创建收益测试数据
    return_data = {"data": []}
    
    for date in ["2026-01-01", "2026-01-02"]:
        for i in range(15):
            asset = f"{600000+i:06d}.SH"
            return_data["data"].append({
                "date": date,
                "asset": asset,
                "forward_return_1d": (i - 7) * 0.01  # 与因子正相关
            })
    
    # 写入文件
    Path("cache/main_inflow").mkdir(parents=True, exist_ok=True)
    Path("cache/factor_data").mkdir(parents=True, exist_ok=True)
    
    with gzip.open("cache/main_inflow/main_inflow_history.json.gz", 'wt', encoding='utf-8') as f:
        json.dump(inflow_data, f)
    
    with gzip.open("cache/factor_data/return_data.json.gz", 'wt', encoding='utf-8') as f:
        json.dump(return_data, f)
    
    print("测试数据已创建")

if __name__ == "__main__":
    create_test_data()
```

---

## 附录：因子特性总结

| 特性 | 值/说明 |
|-----|--------|
| 因子类型 | 正向因子 |
| 排名方向 | ascending=True |
| 数据来源 | 专用缓存（main_inflow_history.json.gz） |
| 因子公式 | main_inflow_ratio = main_net_inflow / float_market_cap |
| 极端值裁剪 | [-0.5, 0.5] |
| 含义 | 正值=主力流入看涨，负值=主力流出看跌 |
| 因子预测能力判断 | IC均值>0.03=有效，<-0.03=反向有效 |
| 最小股票数阈值 | 10只/天 |

---

*文档结束*