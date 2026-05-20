# 换手率突增因子IC测试用例

> 生成时间: 2026-05-20
> 对应脚本: ic_turnover_surge_1d.py (v1.5)
> 测试版本: v1.2
> 更新内容:
>   - [v1.1] 更新 ic_metrics 字段规范（ic_mean, ic_std, icir, p_value, p_value_display）
>   - [v1.2] 修复输出结构过时：dates/ic_values/rolling_ic_mean 提升为顶层字段（ic_series 子结构已移除）
>   - [v1.2] 修复字段名过时：significance 已移除，n_days 改为 valid_days
>   - [v1.2] 修复函数名过时：load_data_for_turnover_surge 改为 load_data_from_cache
>   - [v1.2] 修复测试用例 TC007：删除不存在的日期限制功能测试，改为缓存数据检查测试

---

## 测试环境

### 数据库连接要求
- 无需数据库连接，使用本地缓存文件
- 缓存目录: `cache/factor_data/`

### 测试数据准备

**必需文件**:
```
cache/factor_data/
├── turnover_rate_data.json.gz  ← 换手率数据（必需）
├── factor_data.json.gz         ← 收盘价数据（必需）
└── return_data.json.gz         ← 未来收益数据（必需）
```

**数据格式要求**:
- `turnover_rate_data.json.gz`: 包含 `date`, `asset`, `turnover_rate` 字段
- `factor_data.json.gz`: 包含 `date`, `asset`, `close` 字段
- `return_data.json.gz`: 包含 `date`, `asset`, `forward_return_1d` 或 `forward_return` 字段

**最小测试数据集**:
- 至少 10 只股票
- 至少 6 个交易日（5日均值计算 + 1日收益）
- 建议使用 100+ 交易日进行完整测试

---

## 功能测试

### TC001: 正常流程 - 全量IC计算

**前置条件**:
- 缓存目录存在三个必需数据文件
- 数据覆盖至少 10 只股票、100 个交易日

**测试步骤**:
1. 执行 `python ic_turnover_surge_1d.py`
2. 观察控制台输出
3. 检查输出文件 `cache/factor_ic/turnover_surge_1d_ic.json`

**预期结果**:
- 脚本正常执行完成，无异常退出
- 控制台输出包含以下信息:
  - 加载数据统计（交易日数、股票数量、日期范围）
  - 因子计算统计（换手率突增记录数、上涨记录数、有效因子记录数）
  - IC 统计（IC均值、ICIR、正比例、t统计量）
- 输出 JSON 文件包含以下字段:
  - `factor_name`: "turnover_surge_1d"
  - `update_mode`: "full" 或 "incremental" 或 "skip"
  - `ic_metrics`: ic_mean, ic_std, icir, p_value, p_value_display (5字段)
  - `dates`: list of dates (顶层字段)
  - `ic_values`: list of IC values (顶层字段)
  - `rolling_ic_mean`: list of rolling IC mean (顶层字段)
  - `filter_stats`: total_records, turnover_surge_count, price_up_count 等
  - `positive_ratio`: 正 IC 比例（顶层字段）
  - `t_stat`: t 统计量（顶层字段）

---

### TC002: 因子计算 - 换手率突增因子

**前置条件**:
- 准备测试数据，包含已知换手率序列

**测试数据示例**:
```
股票A:
  Day1: turnover_rate = 0.02
  Day2: turnover_rate = 0.03
  Day3: turnover_rate = 0.02
  Day4: turnover_rate = 0.02
  Day5: turnover_rate = 0.02
  Day6: turnover_rate = 0.10  ← 突增
  Day7: turnover_rate = 0.02
```

**测试步骤**:
1. 运行 `calculate_turnover_surge_ratio()` 函数
2. 检查 Day6 的 `turnover_surge` 值

**预期结果**:
- Day6 的 turnover_ma = (0.02+0.03+0.02+0.02+0.02) / 5 = 0.022
- Day6 的 turnover_surge = 0.10 / 0.022 ≈ 4.55

---

### TC003: 筛选条件 - 换手率突增且上涨

**前置条件**:
- 准备测试数据，包含换手率和收盘价

**测试数据示例**:
```
场景1: turnover_surge = 2.0, pct_change = 0.05 (上涨)
场景2: turnover_surge = 0.8, pct_change = 0.05 (上涨)
场景3: turnover_surge = 2.0, pct_change = -0.03 (下跌)
场景4: turnover_surge = 0.8, pct_change = -0.03 (下跌)
```

**测试步骤**:
1. 调用 `calculate_turnover_surge_factor(filter_conditions=True)`
2. 检查各场景的 `turnover_surge` 是否被保留

**预期结果**:
| 场景 | turnover_surge | pct_change | 结果 |
|------|----------------|------------|------|
| 1 | 2.0 (>1) | 0.05 (>0) | 保留 |
| 2 | 0.8 (≤1) | 0.05 (>0) | 设为 None |
| 3 | 2.0 (>1) | -0.03 (≤0) | 设为 None |
| 4 | 0.8 (≤1) | -0.03 (≤0) | 设为 None |

---

### TC004: 筛选条件 - 禁用筛选

**前置条件**:
- 准备测试数据，包含各类换手率突增情况

**测试步骤**:
1. 调用 `calculate_turnover_surge_factor(filter_conditions=False)`
2. 检查所有记录的因子值是否保留

**预期结果**:
- 所有记录的 turnover_surge 均保留（不为 None）
- filter_stats.filter_ratio = 1.0

---

### TC005: 极端值处理 - 因子裁剪

**前置条件**:
- 准备包含极端值的测试数据

**测试数据示例**:
```
股票A: turnover_surge = 15.0 (超出上限)
股票B: turnover_surge = 0.3 (低于下限)
股票C: turnover_surge = 3.0 (正常范围)
```

**测试步骤**:
1. 运行因子计算流程
2. 检查极端值是否被裁剪

**预期结果**:
- 股票A: turnover_surge 裁剪为 10.0
- 股票B: turnover_surge 裁剪为 0.5
- 股票C: turnover_surge 保持 3.0

---

### TC006: IC计算 - 正向排名

**前置条件**:
- 准备因子值和收益数据

**测试步骤**:
1. 调用 `calculate_turnover_surge_ic()` 函数
2. 验证排名方向

**预期结果**:
- factor_rank 使用 `ascending=True`（正向排名）
- 高因子值对应高排名
- IC 计算使用 Spearman 相关系数

---

### TC007: 数据加载 - 缓存数据检查

**前置条件**:
- 缓存数据存在且可加载

**测试步骤**:
1. 调用 `load_data_from_cache()`
2. 检查加载的数据结构

**预期结果**:
- factor_df 和 return_df 成功加载
- metadata 包含 total_days 和 date_range 信息
- 数据类型正确（date 为 datetime，asset 为 str）

---

### TC008: 增量判断 - 数据完备

**前置条件**:
- IC 计算结果已存在且数据完备

**测试步骤**:
1. 确保 `check_data_completeness()` 返回 `mode='skip'`
2. 运行主函数

**预期结果**:
- 输出 "数据完备，无需重新计算"
- 脚本提前退出，不执行计算

---

### TC009: p_value 字段验证

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
  p_value = 2 * (1 - stats.t.cdf(abs(t_stat), df=valid_days - 1))
  ```
- p_value_display 格式正确（科学计数法或百分比）
- p_value 可序列化为 JSON（非 numpy 类型）

**实际结果**: (测试时填写)

---

## 边界测试

### TC101: 最小数据集 - 刚好满足条件

**前置条件**:
- 准备 10 只股票、6 个交易日的最小数据集

**测试步骤**:
1. 运行 IC 计算脚本
2. 检查是否正常完成

**预期结果**:
- 脚本正常执行
- IC 计算结果有效
- 输出 JSON 包含 1 个交易日的 IC 值

---

### TC102: 单日数据 - 无法计算IC

**前置条件**:
- 准备只有 1 个交易日的数据

**测试步骤**:
1. 运行 IC 计算脚本

**预期结果**:
- 无法计算滚动均值（需要 5 日）
- IC 时间序列为空
- 返回 `valid_days: 0`, `ic_mean: 0`

---

### TC103: 股票数量不足 - 少于10只

**前置条件**:
- 准备只有 5 只股票的数据

**测试步骤**:
1. 运行主函数

**预期结果**:
- 抛出 ValueError: "股票数量不足以计算有效的 IC"
- 错误信息包含当前股票数量

---

### TC104: 全部不满足筛选条件

**前置条件**:
- 准备全部下跌或不满足换手率突增条件的数据

**测试步骤**:
1. 运行因子计算
2. 检查筛选统计

**预期结果**:
- `filtered_count = 0`
- `filter_ratio = 0`
- IC 计算返回 `valid_days: 0`

---

### TC105: 所有股票同日相同因子值

**前置条件**:
- 某日所有股票的 turnover_surge 值相同

**测试步骤**:
1. 运行 IC 计算

**预期结果**:
- 该日不参与 IC 计算（跳过）
- 不影响其他日期的 IC 计算

---

### TC106: 所有股票同日相同收益

**前置条件**:
- 某日所有股票的 forward_return 值相同

**测试步骤**:
1. 运行 IC 计算

**预期结果**:
- 该日不参与 IC 计算（跳过）
- 其他日期正常计算

---

## 异常测试

### TC201: 缓存文件不存在 - 换手率数据

**前置条件**:
- 删除 `turnover_rate_data.json.gz`

**测试步骤**:
1. 运行主函数

**预期结果**:
- 抛出 FileNotFoundError
- 错误信息包含文件路径

---

### TC202: 缓存文件不存在 - 收盘价数据

**前置条件**:
- 删除 `factor_data.json.gz`

**测试步骤**:
1. 运行主函数

**预期结果**:
- 抛出 FileNotFoundError
- 错误信息包含 "因子缓存不存在"

---

### TC203: 缓存文件不存在 - 收益数据

**前置条件**:
- 删除 `return_data.json.gz`

**测试步骤**:
1. 运行主函数

**预期结果**:
- 抛出 FileNotFoundError
- 错误信息包含 "收益缓存不存在"

---

### TC204: 数据格式错误 - 缺少必需字段

**前置条件**:
- 准备缺少 `turnover_rate` 字段的数据文件

**测试步骤**:
1. 运行主函数

**预期结果**:
- 抛出 KeyError 或 ValueError
- 数据加载失败

---

### TC205: 数据格式错误 - 非法JSON

**前置条件**:
- 创建格式错误的 JSON 文件

**测试步骤**:
1. 运行主函数

**预期结果**:
- 抛出 json.JSONDecodeError
- 错误信息包含解析错误位置

---

### TC206: 数据类型错误 - 非数值换手率

**前置条件**:
- 数据中包含非数值类型的 turnover_rate

**测试步骤**:
1. 运行数据加载函数

**预期结果**:
- 非数值记录被转换为 NaN
- NaN 记录被过滤掉
- 不影响其他正常记录

---

### TC207: 内存不足 - 大数据集

**前置条件**:
- 准备超大数据集（如 5000+ 股票、1000+ 交易日）

**测试步骤**:
1. 监控内存使用
2. 运行脚本

**预期结果**:
- 脚本能够正常完成
- 内存使用合理（通过 gc.collect() 释放）
- 无 MemoryError

---

### TC208: 数据全为空值

**前置条件**:
- 所有 turnover_rate 值为 null

**测试步骤**:
1. 运行数据加载函数

**预期结果**:
- 返回空 DataFrame
- 或抛出 ValueError: "换手率数据加载失败"

---

### TC209: numpy 类型序列化测试

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
  # valid_days: numpy.int64 → int  
  # ic_values: numpy.ndarray → list[float]
  # positive_ratio: numpy.float64 → float
  ```
- `convert_to_native_types()` 函数正确处理嵌套字典结构
- 输出文件可直接被 JSON 解析器读取

**实际结果**: (测试时填写)

---

## 性能测试

### TC301: 大规模数据加载性能

**前置条件**:
- 准备 5000 只股票、500 个交易日的完整数据集

**测试步骤**:
1. 记录开始时间
2. 运行 `load_data_from_cache()`
3. 记录结束时间

**预期结果**:
- 加载时间 < 60 秒
- 内存增长 < 2GB

---

### TC302: 因子计算性能

**前置条件**:
- 准备 5000 只股票、500 个交易日的完整数据集

**测试步骤**:
1. 记录开始时间
2. 运行 `calculate_turnover_surge_factor()`
3. 记录结束时间

**预期结果**:
- 计算时间 < 30 秒
- 内存无显著增长

---

### TC303: IC计算性能

**前置条件**:
- 准备完整的因子和收益数据

**测试步骤**:
1. 记录开始时间
2. 运行 `calculate_turnover_surge_ic()`
3. 记录结束时间

**预期结果**:
- 计算时间 < 60 秒
- 内存无显著增长

---

### TC304: 全流程性能

**前置条件**:
- 准备 5000 只股票、500 个交易日的完整数据集

**测试步骤**:
1. 记录开始时间
2. 运行完整流程 `main()`
3. 记录结束时间

**预期结果**:
- 总执行时间 < 180 秒（3分钟）
- 峰值内存 < 4GB
- 无内存泄漏

---

### TC305: GC效率测试

**前置条件**:
- 运行完整流程

**测试步骤**:
1. 观察控制台输出的内存提示
2. 检查各阶段的内存释放

**预期结果**:
- 每个大对象加载后都有 `del` 和 `gc.collect()`
- 内存及时释放

---

## 数据质量测试

### TC401: 换手率数据完整性

**前置条件**:
- 数据包含部分缺失值

**测试步骤**:
1. 检查 turnover_df 的缺失值处理
2. 验证 dropna 操作

**预期结果**:
- 缺失值被正确过滤
- 数据加载日志显示过滤后的记录数

---

### TC402: 收益数据兼容性 - forward_return_1d 映射

**前置条件**:
- 数据文件使用 `forward_return_1d` 字段名

**测试步骤**:
1. 运行数据加载
2. 检查 return_df 列名

**预期结果**:
- 自动映射到 `forward_return` 列
- IC 计算使用正确的列名

---

### TC403: 数据日期对齐

**前置条件**:
- 换手率数据和收益数据日期范围不完全匹配

**测试步骤**:
1. 运行数据加载
2. 检查合并后的日期范围

**预期结果**:
- 只保留三个数据源共有的日期
- 使用 inner join 合并

---

## 输出验证测试

### TC501: JSON输出格式验证

**前置条件**:
- 完成一次成功计算

**测试步骤**:
1. 读取输出 JSON 文件
2. 验证必需字段

**预期结果**:
必需字段:
```
- factor_name
- ic_metrics.ic_mean
- ic_metrics.ic_std
- ic_metrics.icir
- ic_metrics.p_value
- ic_metrics.p_value_display
- sample_stats.total_days
- sample_stats.valid_days
- dates (顶层字段)
- ic_values (顶层字段)
- rolling_ic_mean (顶层字段)
- filter_stats
- calculation_date
```

---

### TC502: IC统计值合理性

**前置条件**:
- 完成一次成功计算

**测试步骤**:
1. 读取 IC 统计值
2. 验证数值范围

**预期结果**:
| 指标 | 合理范围 |
|------|----------|
| ic_mean | [-1, 1] |
| ic_std | [0, 1] |
| icir | 实数（通常 -5 到 5） |
| p_value | [0, 1] |
| positive_ratio | [0, 1] |
| t_stat | 实数 |

---

### TC503: 筛选统计一致性

**前置条件**:
- 完成一次成功计算

**测试步骤**:
1. 读取 filter_stats
2. 验证统计一致性

**预期结果**:
```
total_records >= turnover_surge_count
total_records >= price_up_count
both_conditions_count <= min(turnover_surge_count, price_up_count)
filtered_count == both_conditions_count
filter_ratio = filtered_count / total_records
```

---

### TC504: IC时间序列格式

**前置条件**:
- 完成一次成功计算

**测试步骤**:
1. 读取 dates, ic_values, rolling_ic_mean 顶层字段
2. 验证格式

**预期结果**:
- dates, ic_values, rolling_ic_mean 数组长度相等
- 所有 IC 值在 [-1, 1] 范围内
- 滚动均值使用 20 日窗口

---

## 回归测试

### TC601: 历史结果对比

**前置条件**:
- 保存一份历史基准结果

**测试步骤**:
1. 使用相同数据运行计算
2. 对比结果文件

**预期结果**:
- IC 统计值与历史结果一致（考虑浮点精度）
- 筛选统计数据一致

---

### TC602: 增量计算验证

**前置条件**:
- 历史数据已计算
- 新增一天的增量数据

**测试步骤**:
1. 触发增量计算模式
2. 验证结果包含新增日期

**预期结果**:
- 当前版本执行全量计算（日志提示）
- 结果包含所有历史数据 + 新增数据

---

## 测试执行顺序

```
阶段1: 功能测试
  TC001 → TC002 → TC003 → TC004 → TC005 → TC006 → TC007 → TC008

阶段2: 边界测试
  TC101 → TC102 → TC103 → TC104 → TC105 → TC106

阶段3: 异常测试
  TC201 → TC202 → TC203 → TC204 → TC205 → TC206 → TC207 → TC208

阶段4: 性能测试
  TC301 → TC302 → TC303 → TC304 → TC305

阶段5: 数据质量测试
  TC401 → TC402 → TC403

阶段6: 输出验证测试
  TC501 → TC502 → TC503 → TC504

阶段7: 回归测试
  TC601 → TC602
```

---

## 测试工具脚本

### 自动化测试脚本示例

```bash
#!/bin/bash
# run_tests.sh

echo "=== 换手率突增因子IC测试 ==="

# 运行功能测试
python -c "
from ic_turnover_surge_1d import *
# TC001 测试代码
"

# 运行边界测试
# ...

# 运行异常测试
# ...

echo "=== 测试完成 ==="
```

---

## 测试通过标准

| 类别 | 通过标准 |
|------|----------|
| 功能测试 | 100% 通过 |
| 边界测试 | 100% 通过 |
| 异常测试 | 100% 通过 |
| 性能测试 | 满足时间限制 |
| 数据质量测试 | 100% 通过 |
| 输出验证测试 | 100% 通过 |
| 回归测试 | 结果一致 |

---

*文档结束*