# stock_selector.py 开发计划

> 版本: v1.0
> 创建日期: 2026-06-03
> 状态: 待审核

---

## 一、任务概述

### 1.1 目标

开发 `stock_selector.py` 股票选股脚本，使用最优权重方法计算每只股票的综合因子值，排序后选出 Top N 股票。

### 1.2 背景

权重选择脚本 (`weight_selector.py`) 已完成，最优方法为 `rolling_icir_weight`（综合得分 0.8137）。现在需要：
1. 使用最优权重方法计算股票综合因子值
2. 按综合因子值排序选出 Top N 股票

### 1.3 模块定位

```
comprehensive_factor 模块流程：
Step 1-5: 单因子分析 → 因子筛选 → 标准化 → 加权计算 → 分层回测
Step 6: 权重方式选择 (weight_selector.py) ← 已完成
Step 7: 股票选股 (stock_selector.py) ← 本次开发 ★
```

---

## 二、设计规范

### 2.1 遵循 MODULE.md 规范

| 规范编号 | 内容 |
|---------|------|
| M2 | 公共模块强制复用（factor_loader, weight_engine） |
| M4 | 输出到 `comprehensive_factor/result/` |
| M21 | 数据来源：factor_ic_data.json.gz |
| M9 | 每日截面标准化 |
| M41-45 | CLI 与异常处理（退出码、logger 传递） |
| M46-48 | Config 类设计（继承 + 单一数据源） |

### 2.2 数据来源

| 数据类型 | 来源 | 公共函数 |
|---------|------|---------|
| 因子原始值 | `factor_ic_data.json.gz` | `load_factor_values()` |
| IC 统计结果 | `factor_ic/result/*.json` | `load_ic_results()` |
| IC 每日序列 | `factor_ic/result/*.json` | `load_ic_daily()` |
| 最优权重配置 | `weight_selection_result.json` | 直接读取 |

---

## 三、核心算法

### 3.1 综合因子计算流程

```
输入: factor_df (date, asset, 因子列)
处理:
  1. 加载最优权重方法 (rolling_icir_weight)
  2. 标准化因子值 (截面标准化)
  3. 加载 IC 每日序列 (用于滚动ICIR计算)
  4. 计算滚动 ICIR 权重 (动态权重)
  5. 加权求和得到综合因子值
输出: composite_factor Series
```

### 3.2 排序规则

| 因子方向 | 排序规则 | 说明 |
|---------|---------|------|
| negative（反向） | 升序（值越小越好） | 低综合因子值 → 高预期收益 |
| positive（正向） | 降序（值越大越好） | 高综合因子值 → 高预期收益 |

**当前综合因子方向**：MODULE.md 规定综合因子默认为反向因子（M79），因此使用**升序排序**。

### 3.3 Top N 选股

```
1. 按综合因子值排序
2. 取前 N 只股票
3. 输出股票代码、股票名称、综合因子值、排名
```

---

## 四、实现方案

### 4.1 文件结构

```
comprehensive_factor/
├── stock_selector.py           ← 新建脚本
├── test_cases/
│   └── test_stock_selector.py  ← 新建测试
├── result/
│   └── stock_selection_result.json  ← 输出结果
└── common/
    ├── factor_loader.py        ← 复用
    ├── weight_engine.py        ← 复用
    └── logger_config.py        ← 复用
```

### 4.2 Config 类设计

```python
@dataclass
class StockSelectorConfig:
    """股票选股配置
    
    遵循 MODULE.md M46-48 规范：
    - 继承公共配置模式
    - 单一数据源
    """
    
    # === 因子参数 ===
    factor_list: List[str] = field(
        default_factory=lambda: ['rsi', 'volume_ratio', 'kdj_j', 'bollinger_pb', 'turnover_surge', 'main_inflow_ratio']
    )
    factor_cols: List[str] = field(
        default_factory=lambda: ['rsi_6', 'volume_ratio_5', 'kdj_j_9', 'bollinger_pb_20', 'turnover_surge_5', 'main_inflow_ratio_1d']
    )
    
    # === 选股参数 ===
    top_n: int = 10  # 选出前 N 只股票
    factor_direction: str = 'negative'  # 综合因子方向（反向）
    rolling_window: int = 60  # 滚动ICIR窗口
    
    # === 数据路径 ===
    data_source: Path | str | None = None  # 统一数据源
    ic_result_dir: Path | str | None = None  # IC结果目录
    weight_result_path: Path | str | None = None  # 权重选择结果
    output_dir: Path | str | None = None  # 输出目录
    
    # === 时间参数 ===
    selection_date: str | None = None  # 选股日期（默认取最新日期）
```

### 4.3 主函数流程

```python
def select_stocks(
    config: StockSelectorConfig,
    logger: logging.Logger | None = None
) -> dict:
    """股票选股主函数
    
    流程：
    1. 加载最优权重配置
    2. 加载因子数据
    3. 加载 IC 每日序列（滚动ICIR需要）
    4. 标准化因子
    5. 计算综合因子（使用最优权重方法）
    6. 排序选出 Top N
    7. 返回结果
    """
    
    # Step 1: 加载最优权重配置
    weight_config = load_weight_config(config.weight_result_path, logger)
    best_method = weight_config['best_selection']['method']
    
    # Step 2: 加载因子数据
    factor_df = load_factor_values(config.factor_cols, config.data_source, logger)
    
    # Step 3: 确定选股日期（默认取最新日期）
    if config.selection_date is None:
        config.selection_date = get_latest_date(factor_df, logger)
    
    # Step 4: 过滤数据（只保留选股日期）
    factor_df = factor_df[factor_df['date'] == config.selection_date]
    
    # Step 5: 标准化因子（截面标准化）
    factor_df = standardize_factors(factor_df, config.factor_cols, logger)
    
    # Step 6: 加载 IC 每日序列（滚动ICIR需要）
    if best_method == 'rolling_icir_weight':
        ic_daily_data = load_ic_daily(config.factor_list, config.ic_result_dir, '1d', logger)
    else:
        ic_daily_data = None
    
    # Step 7: 加载 IC 统计结果（静态权重需要）
    if best_method in ['icir_weight', 'ic_weight']:
        ic_results = load_ic_results(config.factor_list, config.ic_result_dir, '1d', logger)
    else:
        ic_results = None
    
    # Step 8: 计算综合因子（使用最优权重方法）
    weight_engine = WeightEngine(logger=logger)
    composite_factor = weight_engine.calculate(
        method=best_method,
        factor_df=factor_df,
        factor_cols=config.factor_cols,
        ic_results=ic_results,
        ic_daily_data=ic_daily_data,
        window=config.rolling_window
    )
    
    # Step 9: 排序选出 Top N
    sorted_stocks = sort_and_select(composite_factor, factor_df, config.top_n, config.factor_direction, logger)
    
    # Step 10: 返回结果
    return build_result(sorted_stocks, config, weight_config, logger)
```

### 4.4 输出结构

```json
{
  "meta": {
    "selection_date": "2026-06-03",
    "weight_method": "rolling_icir_weight",
    "composite_score": 0.8137,
    "factor_direction": "negative",
    "top_n": 10,
    "total_stocks": 2580,
    "created_at": "2026-06-03T18:00:00"
  },
  "top_stocks": [
    {
      "rank": 1,
      "code": "000001",
      "name": "平安银行",
      "composite_value": -2.35,
      "factor_values": {"rsi_6": 45.2, "volume_ratio_5": 0.85, ...}
    },
    ...
  ],
  "weight_config": {
    "method": "rolling_icir_weight",
    "window": 60,
    "factor_list": ["rsi", "volume_ratio", ...]
  }
}
```

---

## 五、依赖模块

### 5.1 公共模块复用

| 功能 | 公共模块 | 函数 |
|------|---------|------|
| 因子数据加载 | `factor_loader.py` | `load_factor_values()` |
| IC 结果加载 | `factor_loader.py` | `load_ic_results()` |
| IC 每日序列加载 | `factor_loader.py` | `load_ic_daily()` |
| 因子标准化 | `factor_loader.py` | `standardize_factors()` |
| 权重计算 | `weight_engine.py` | `WeightEngine.calculate()` |
| 日志配置 | `logger_config.py` | `get_logger()` |
| 类型转换 | `convert_types.py` | `convert_to_native_types()` |

### 5.2 WeightEngine 接口

```python
# weight_engine.py 已有接口
class WeightEngine:
    def calculate(
        self,
        method: str,
        factor_df: pd.DataFrame,
        factor_cols: list[str],
        ic_results: dict | None = None,
        ic_daily_data: dict | None = None,
        window: int = 60
    ) -> pd.Series:
        """计算综合因子
        
        Args:
            method: 加权方式 ('equal_weight', 'icir_weight', 'ic_weight', 'rolling_icir_weight')
            factor_df: 因子 DataFrame（包含标准化因子列）
            factor_cols: 因子列名
            ic_results: IC统计结果（静态权重需要）
            ic_daily_data: IC每日序列（滚动ICIR需要）
            window: 滚动窗口
            
        Returns:
            综合因子值 Series
        """
```

---

## 六、测试用例设计

### 6.1 pytest 测试文件

```python
# test_cases/test_stock_selector.py

class TestStockSelector:
    """股票选股测试"""
    
    def test_config_validation(self):
        """测试配置校验"""
        
    def test_load_weight_config(self):
        """测试权重配置加载"""
        
    def test_select_stocks_with_rolling_icir(self):
        """测试滚动ICIR权重选股"""
        
    def test_sort_stocks_negative_direction(self):
        """测试反向因子排序（升序）"""
        
    def test_sort_stocks_positive_direction(self):
        """测试正向因子排序（降序）"""
        
    def test_top_n_selection(self):
        """测试Top N选股数量"""
        
    def test_output_structure(self):
        """测试输出结构完整性"""
        
    def test_empty_factor_df(self):
        """测试空数据异常处理"""
        
    def test_missing_weight_config(self):
        """测试权重配置缺失异常"""
```

---

## 七、CLI 入口

### 7.1 命令行参数

```bash
python stock_selector.py \
    --top_n 10 \
    --selection_date 2026-06-03 \
    --data_source /path/to/factor_ic_data.json.gz \
    --weight_result /path/to/weight_selection_result.json \
    --output_dir /path/to/output
```

### 7.2 CLI 函数设计

```python
def create_cli_entrypoint(config_class: type) -> Callable:
    """创建 CLI 入口（遵循 MODULE.md M41-45）
    
    遵循规范：
    - 退出码：成功 0，失败 1
    - 异常处理：保留堆栈信息
    - logger 传递：公共函数接收 logger 参数
    """
```

---

## 八、执行计划

### 8.1 任务拆分（Bite-sized Tasks）

| 任务 | 预估时间 | 说明 |
|------|---------|------|
| Task 1: Config 类设计 | 2分钟 | 数据类定义 + 校验 |
| Task 2: 权重配置加载函数 | 2分钟 | load_weight_config() |
| Task 3: 排序选股函数 | 3分钟 | sort_and_select() |
| Task 4: 主函数流程 | 5分钟 | select_stocks() |
| Task 5: 结果构建函数 | 2分钟 | build_result() |
| Task 6: CLI 入口 | 3分钟 | create_cli_entrypoint() |
| Task 7: pytest 测试文件 | 5分钟 | 9个测试用例 |
| Task 8: 运行验证 | 2分钟 | 实际运行 + 输出检查 |
| Task 9: MODULE.md 更新 | 2分钟 | Step 7 流程说明 |

### 8.2 执行顺序

```
Task 1 → Task 2 → Task 3 → Task 4 → Task 5 → Task 6 → Task 7 → Task 8 → Task 9
```

---

## 九、风险与边界

### 9.1 需要确认的问题

1. **股票名称来源**：factor_ic_data.json.gz 是否包含股票名称？
   - 如果不包含，需要额外加载股票基本信息文件

2. **滚动 ICIR 单日计算**：滚动 ICIR 需要历史数据，单日数据如何处理？
   - 方案：使用当日滚动 ICIR（需要当日之前的 IC 历史）

3. **因子值缺失**：某只股票部分因子缺失时如何处理？
   - 方案：使用动态权重归一化（weight_engine 已实现）

### 9.2 边界情况

| 边界情况 | 处理方式 |
|---------|---------|
| 数据为空 | 抛 ValueError，提示检查数据源 |
| 权重配置缺失 | 抛 FileNotFoundError |
| Top N > 总股票数 | 返回所有股票 |
| 因子全部缺失 | 抛 ValueError，提示检查 factor_cols |

---

## 十、预期成果

### 10.1 文件清单

| 文件 | 行数 | 说明 |
|------|------|------|
| `stock_selector.py` | ~300 | 主脚本 |
| `test_stock_selector.py` | ~150 | pytest 测试 |
| `stock_selection_result.json` | ~50 | 输出结果 |

### 10.2 MODULE.md 更新

新增 **Step 7: 股票选股** 章节：
- 流程图节点
- 脚本说明
- 输出结构模板

---

## 十一、参考文件

| 文件 | 内容 |
|------|------|
| `MODULE.md` | 综合因子模块规范 |
| `weight_selector.py` | 权重选择脚本（参考模板） |
| `composite_runner.py` | 综合因子入口（参考模板） |
| `factor_loader.py` | 因子数据加载 |
| `weight_engine.py` | 权重计算引擎 |

---

*计划文档完成，等待用户审核*