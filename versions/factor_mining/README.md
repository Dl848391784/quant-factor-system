# 因子挖掘系统

因子挖掘三阶段流水线系统，用于发现高IC、低相关的有效因子。

## 目录结构

```
factor_mining/
├── main.py          # 统一CLI入口
├── config.py        # 全局配置
├── README.md        # 本文档
├── output/          # 输出目录
│   └── mined_factors.json  # 最终因子输出
├── stage_a/         # 阶段A - 因子组合与IC筛选
├── stage_b/         # 阶段B - 技术指标挖掘
└── stage_c/         # 阶段C - 遗传规划因子挖掘
```

## 三阶段说明

### 阶段A：因子组合与IC筛选

**目标**: 从基础因子通过数学组合生成新因子

**流程**:
1. 加载基础因子数据
2. 生成组合表达式（加减乘除、嵌套组合）
3. IC筛选（IC > 0.03）
4. 因子去重（相关性 < 0.8）
5. 输出筛选因子

**配置参数**:
| 参数 | 默认值 | 说明 |
|------|--------|------|
| ic_threshold | 0.03 | IC绝对值阈值 |
| correlation_threshold | 0.8 | 相关性阈值 |
| max_combination_depth | 2 | 最大组合深度 |

### 阶段B：技术指标挖掘

**目标**: 从OHLCV数据计算各类技术指标作为因子

**流程**:
1. 加载OHLCV价格数据
2. 计算趋势/波动/动量/成交量指标
3. 格式化为因子数据
4. IC筛选
5. 因子去重
6. 输出筛选指标

**指标类别**:
- **趋势**: SMA, EMA, MACD, ADX
- **波动**: ATR, Bollinger, Keltner
- **动量**: RSI, KDJ, CCI, Williams %R
- **成交量**: OBV, VWAP, Volume Ratio

### 阶段C：遗传规划因子挖掘

**目标**: 使用遗传算法自动进化发现复杂因子表达式

**流程**:
1. 准备特征数据
2. 遗传规划进化（种群迭代）
3. IC评估
4. 交叉验证防过拟合
5. 选择最优因子
6. 输出因子表达式

**配置参数**:
| 参数 | 默认值 | 说明 |
|------|--------|------|
| population_size | 1000 | 种群大小 |
| generations | 20 | 迭代代数 |
| cv_n_splits | 5 | CV折数 |
| cv_decay_threshold | 0.03 | IC衰减阈值 |

## 使用方式

### 单阶段执行

```bash
# 执行阶段A
python main.py --stage A

# 执行阶段B
python main.py --stage B

# 执行阶段C
python main.py --stage C
```

### 全流程执行

```bash
# 执行全部三个阶段
python main.py --stage all

# 快速模式验证（小数据量）
python main.py --stage all --quick
```

### 自定义输出目录

```bash
python main.py --stage all --output /path/to/output
```

### 使用配置文件

```bash
python main.py --stage all --config config.yaml
```

## 快速模式

快速模式使用小数据量快速验证流程正确性：

| 阶段 | 正常模式 | 快速模式 |
|------|----------|----------|
| A | 500组合 | 50组合 |
| B | 500天×100股 | 100天×20股 |
| C | 1000种群×20代 | 100种群×5代 |

使用方式：
```bash
python main.py --stage all --quick
```

## 输出文件

### mined_factors.json

最终因子输出文件格式：

```json
{
  "timestamp": "2025-01-01 12:00:00",
  "quick_mode": false,
  "total_factors": 45,
  "stage_summary": {
    "A": 15,
    "B": 20,
    "C": 10
  },
  "factors": [
    {
      "factor_id": "A_comb_001",
      "expression": "rsi * volume_ratio - kdj_j",
      "stage": "A",
      "ic": 0.052,
      "create_time": "2025-01-01 12:00:00"
    }
  ]
}
```

### 因子字段说明

| 字段 | 类型 | 说明 |
|------|------|------|
| factor_id | str | 因子唯一ID |
| expression | str | 因子表达式 |
| stage | str | 来源阶段 (A/B/C) |
| ic | float | IC值 |
| cv_decay | float | CV衰减（阶段C） |
| create_time | str | 创建时间 |

## 配置说明

### config.py 主要配置项

```python
# 阶段A配置
ic_threshold = 0.03        # IC阈值
correlation_threshold = 0.8  # 相关性阈值

# 阶段B配置  
n_days = 500              # 数据天数
n_stocks = 100            # 股票数量

# 阶段C配置
population_size = 1000    # 遗传种群大小
generations = 20          # 迭代代数
cv_n_splits = 5           # 交叉验证折数
```

### 修改阈值参数

```python
from config import DEFAULT_CONFIG

# 修改IC阈值
DEFAULT_CONFIG.stage_a.ic_threshold = 0.05

# 修改相关性阈值  
DEFAULT_CONFIG.stage_a.correlation_threshold = 0.7
```

## API使用

### Python代码调用

```python
from main import FactorMiningPipeline
from config import DEFAULT_CONFIG

# 创建Pipeline
pipeline = FactorMiningPipeline(
    config=DEFAULT_CONFIG,
    output_dir='./output'
)

# 执行全流程
result = pipeline.run_all()

# 单阶段执行
pipeline.run_stage_a()
pipeline.run_stage_b()
pipeline.run_stage_c()

# 获取因子
factors = pipeline.all_factors
```

### 单阶段Pipeline调用

```python
# 阶段A
from stage_a.pipeline import StageAPipeline
pipeline_a = StageAPipeline(config={'ic_threshold': 0.05})
result_a = pipeline_a.run(factor_data, returns)

# 阶段B
from stage_b.pipeline import StageBPipeline
pipeline_b = StageBPipeline()
result_b = pipeline_b.run()

# 阶段C  
from stage_c.pipeline import StageCPipeline
pipeline_c = StageCPipeline()
result_c = pipeline_c.run(X, y, feature_names)
```

## 依赖说明

### Python版本

- Python >= 3.8

### 主要依赖

```
numpy
pandas
scikit-learn
gplearn  # 遗传规划库（阶段C可选）
```

### 安装依赖

```bash
pip install numpy pandas scikit-learn
pip install gplearn  # 阶段C需要
```

## 执行示例

### 正常模式执行日志

```
============================================================
因子挖掘系统 - 全流程执行
============================================================
执行时间: 2025-01-01 12:00:00
快速模式: False
输出目录: ./output

============================================================
执行阶段A: 因子组合与IC筛选
============================================================
生成组合表达式: 350 个
通过IC筛选: 45 / 350
去重完成: 45 -> 15

阶段A完成，发现 15 个因子

============================================================
执行阶段B: 技术指标挖掘
============================================================
[数据加载] 生成模拟OHLCV数据: 100只股票, 500天
[指标生成] 生成 32 个技术指标
通过IC筛选: 25
去重完成: 25 -> 20

阶段B完成，发现 20 个因子

============================================================
执行阶段C: 遗传规划因子挖掘
============================================================
进化完成，发现 50 个因子表达式
交叉验证完成，筛选后因子: 10

阶段C完成，发现 10 个因子

============================================================
执行总结
============================================================
最终因子总数: 45
  - 阶段A: 15
  - 阶段B: 20
  - 阶段C: 10

Top 10 因子:
  1. [A] rsi * volume_ratio - kdj_j IC=0.0520
  2. [B] macd_histogram IC=0.0480
  3. [C] log(factor_0) + factor_1 * factor_2 IC=0.0420

最终因子已保存: ./output/mined_factors.json
✅ 执行成功
```

## 常见问题

### Q: 如何使用真实数据？

修改配置或直接传入数据：

```python
# 方式1：修改配置
config.data_source = 'api'

# 方式2：直接传入数据
pipeline.run_stage_a(factor_data=real_factors, returns=real_returns)
```

### Q: 阶段C导入失败？

安装gplearn依赖：
```bash
pip install gplearn
```

### Q: 如何调整因子筛选阈值？

修改config.py中的阈值参数：
```python
DEFAULT_CONFIG.stage_a.ic_threshold = 0.05  # 更严格的IC阈值
```

### Q: 快速模式用于什么场景？

快速模式用于：
- 开发调试时快速验证
- 代码修改后验证流程正确性
- CI/CD自动化测试

## 开发扩展

### 添加新指标

在 `stage_b/` 目录添加新指标模块：

```python
# stage_b/my_indicators.py
def generate_my_indicators(high, low, close):
    """自定义指标生成"""
    my_indicator = close / high
    return {'my_indicator': my_indicator}
```

### 添加新遗传算子

在 `stage_c/primitive_set.py` 添加：

```python
def my_function(x1, x2):
    """自定义遗传算子"""
    return np.log(x1 + 1) * x2

# 注册到primitive set
pset.addPrimitive(my_function, 2, name='my_func')
```

---

**版本**: 1.0.0
**最后更新**: 2025-05-03