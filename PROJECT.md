# Project Context - Factor IC Analyzer

量化因子 IC 分析系统项目级规范。各模块规范详见各目录下的 MODULE.md。

---

## 目录结构

```
factor_ic_analyzer/
├── factor_ic/              # IC 计算模块
│   ├── MODULE.md           # IC 计算规范（命名、输出、增量模式等）
│   ├── common/             # 公共函数
│   ├── docs/               # 流程文档
│   ├── result/             # IC 计算结果输出
│   └── test_cases/         # 测试用例
│
├── backtest/               # 分层回测模块
│   ├── MODULE.md           # 分层回测规范
│   └── ...
│
├── data_fetchers/          # 数据获取模块
│   ├── MODULE.md           # 数据拉取规范
│   └── ...
│
├── common/                 # 项目级公共模块
├── cache/                  # 缓存目录
├── tests/                  # 项目级测试目录
│
└── PROJECT.md              # 本文件（项目级规范）
```

---

## 模块间依赖关系

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│ data_fetchers│────▶│    cache    │────▶│  factor_ic  │
│  (数据拉取)  │     │  (缓存数据)  │     │  (IC 计算)  │
└─────────────┘     └─────────────┘     └─────────────┘
                                              │
                                              ▼
                                        ┌─────────────┐
                                        │   backtest  │
                                        │ (分层回测)  │
                                        └─────────────┘
```

**数据流向：**
1. data_fetchers 拉取数据 → cache 存储
2. factor_ic 读取 cache → 计算 IC → 输出 result
3. backtest 读取 IC 结果 → 分层回测

---

## 模块规范文件

| 模块 | 规范文件 | 说明 |
|------|---------|------|
| factor_ic | factor_ic/MODULE.md | IC 计算脚本命名、输出格式、增量模式、参数传递 |
| backtest | backtest/MODULE.md | 分层回测规则、统计指标 |
| data_fetchers | data_fetchers/MODULE.md | 数据源定义、缓存格式 |

---

## 开发前检查清单

执行开发任务前**必须阅读**：

```
□ 项目级：阅读 PROJECT.md（目录结构、模块依赖）
□ 模块级：阅读对应目录下的 MODULE.md
□ 流程级：阅读 docs/ 目录下的流程文档
□ 公共函数：检查 common/ 是否有可复用函数
```

---

## 开发后动作（必做）

完成开发后**必须执行**：

```
□ 代码修改 → 同步更新 MODULE.md（如有规范变更）
□ 代码修改 → 同步更新流程文档 docs/<脚本名>_flow.md
□ 流程文档时间标注 → 生成时间、实测数据时间、版本号递增
□ 运行脚本验证 → 输出数据结构符合规范
□ 运行测试用例 → test_cases/ 目录下测试通过
```

---

## 脚本配套文件规范（2026-05-20新增）

### 核心原则

**创建或更新脚本时，必须同步创建或更新相应的流程文档、测试用例。**

### 配套文件位置

| 文件类型 | 位置 | 命名规则 | 示例 |
|---------|------|---------|------|
| 流程文档 | `<模块目录>/docs/` | `<脚本名>_flow.md` | `factor_ic/docs/ic_rsi_1d_flow.md` |
| 测试用例 | `<模块目录>/test_cases/` | `<脚本名>_test_cases.md` | `factor_ic/test_cases/ic_rsi_1d_test_cases.md` |

**命名说明：**
- `<脚本名>` = 脚本文件名去掉 `.py` 后缀
- 例如：`ic_rsi_1d.py` → 流程文档 `ic_rsi_1d_flow.md`，测试用例 `ic_rsi_1d_test_cases.md`

### 强制规则

**新建脚本时：**
```
□ 创建脚本文件（如 ic_xxx.py）
□ 同步创建流程文档（docs/ic_xxx_flow.md）
□ 同步创建测试用例（test_cases/ic_xxx_test_cases.md）
□ 流程文档包含：整体架构、详细流程步骤、输出结构、关键指标
□ 测试用例包含：输入验证、输出验证、边界条件、异常处理
```

**更新脚本时：**
```
□ 修改脚本代码
□ 同步更新流程文档（如有流程变更）
□ 同步更新测试用例（如有功能变更）
□ 流程文档时间标注同步更新
□ 重新运行测试用例验证
```

### 禁止行为

```
❌ 只写代码不写流程文档
❌ 只写代码不写测试用例
❌ 流程文档滞后于代码修改
❌ 测试用例滞后于代码修改
❌ 流程文档只更新内容不更新时间标注
```

### 各模块目录结构

**factor_ic/ 目录结构（已有）：**
```
factor_ic/
├── MODULE.md           # IC 计算规范
├── common/             # 公共函数
├── docs/               # 流程文档 ← ic_xxx_flow.md 存放位置
├── result/             # IC 计算结果输出
└── test_cases/         # 测试用例 ← ic_xxx_test_cases.md 存放位置
```

**backtest/ 目录结构（已有）：**
```
backtest/
├── MODULE.md           # 分层回测规范
├── docs/               # 流程文档 ← xxx_backtest_flow.md 存放位置
└── test_cases/         # 测试用例 ← xxx_backtest_test_cases.md 存放位置
```

**data_fetchers/ 目录结构（已有）：**
```
data_fetchers/
├── MODULE.md           # 数据拉取规范
├── docs/               # 流程文档 ← fetch_xxx_flow.md 存放位置
└── test_cases/         # 测试用例 ← fetch_xxx_test_cases.md 存放位置
```

### 检查清单

```
□ 新建脚本 → 同步创建流程文档 + 测试用例
□ 更新脚本 → 同步更新流程文档（如有流程变更）
□ 更新脚本 → 同步更新测试用例（如有功能变更）
□ 流程文档时间标注 → 四个位置同步更新（生成时间、实测时间、版本号、更新内容）
□ 测试用例覆盖 → 输入验证、输出验证、边界条件、异常处理
□ 运行验证 → 流程文档与实际执行一致
□ 运行验证 → 测试用例全部通过
```

---

## 文档一致性规范

### 跨文档同步原则

**修改代码时，必须同步更新以下文档：**

| 修改内容 | 需同步更新的文档 |
|---------|----------------|
| factor_ic/ic_xxx.py | docs/ic_xxx_flow.md + MODULE.md（如有规范变更） |
| factor_ic/common/*.py | 所有引用该模块的流程文档 |
| MODULE.md 规范变更 | 所有相关流程文档示例 |
| PROJECT.md 规范变更 | 所有相关 MODULE.md |

### 流程文档时间标注规范

流程文档更新时**必须同步更新**：

```
□ 生成时间：文档头部的时间标注
□ 实测数据时间：示例数据的运行时间
□ 版本号：递增（如 v1.0 → v1.1）
□ 更新内容：说明本次修改的内容
```

**禁止行为：** 只更新文档内容不更新时间标注。

---

## 代码风格规范（2026-05-20新增）

以下规范适用于全项目所有模块，不仅限于特定模块。

### Python 代码风格

**核心原则：** 遵循 PEP8 规范，保持代码可读性和一致性。

### import 规范

**所有 import 语句必须在文件顶部，禁止在函数内部 import。**

```python
# ✓ 正确：所有 import 在文件顶部
from factor_ic.common.ic_calculator import (
    calculate_ic_with_direction_verification,
    calculate_single_day_ic,
    calculate_ic_statistics
)

def _incremental_update(...):
    result = calculate_ic_statistics(ic_series)  # 已在顶部导入

# ❌ 禁止：函数内部 import
def _incremental_update(...):
    from factor_ic.common.ic_calculator import calculate_ic_statistics  # 错误！
```

### 注释缩进规范

**注释必须与代码保持一致的缩进层级。**

```python
# ✓ 正确：注释与代码缩进一致
def calculate_ic_series(...):
    # 计算每日IC值（4空格缩进，与函数体一致）
    for date, daily_data in merged.groupby('date'):
        ic_value = calculate_single_day_ic(daily_data)  # 正确

# ❌ 禁止：注释缩进不一致
def calculate_ic_series(...):
# 计算每日IC值（顶格，与函数体不一致）  # 错误！
    for date, daily_data in merged.groupby('date'):
        ic_value = calculate_single_day_ic(daily_data)
```

### 字典结构缩进规范

**JSON 字典结构必须保持一致的缩进层级。**

```python
# ✓ 正确：多层级字典缩进一致
result = {
    'factor_name': 'rsi_1d',          # 第1层：4空格
    'ic_metrics': {                   # 第1层：4空格
        'ic_mean': 0.05,              # 第2层：8空格
        'ic_std': 0.15                # 第2层：8空格
    },                                # 第1层闭合：4空格
    'sample_stats': {                 # 第1层：4空格
        'total_days': 545             # 第2层：8空格
    }                                 # 第1层闭合：4空格
}

# ❌ 禁止：缩进不一致（IndentationError）
result = {
    'factor_name': 'rsi_1d',
    'ic_metrics': {
        'ic_mean': 0.05
    },
'sample_stats': {  # 错误！缺少缩进
    'total_days': 545
}
```

**缩进规则：**
- 第1层字段：4空格（函数体内字典）
- 第2层字段：8空格（嵌套字典内）
- 闭合括号：与同级字段对齐

### 异常处理规范

**异常链必须使用 `from e` 保留原始异常信息。**

```python
# ✓ 正确：保留异常链
try:
    result = calculate_ic_with_direction_verification(...)
except KeyError as e:
    raise RuntimeError(
        f"返回值缺少必需字段\n"
        f"缺失字段: {missing_fields}"
    ) from e  # 保留原始 KeyError

# ❌ 禁止：丢弃异常链
try:
    result = calculate_ic_with_direction_verification(...)
except KeyError as e:
    raise RuntimeError(f"返回值缺少必需字段")  # 错误！丢弃了 KeyError
```

**为何必须保留异常链：**
1. traceback 可追溯原始异常位置
2. 问题定位更快速
3. 符合 Python 最佳实践

### 错误信息格式规范

**枚举类错误必须包含合法值列表。**

```python
# ✓ 正确：包含合法值列表
raise RuntimeError(
    f"未知模式: {mode}\n"
    f"合法值: ['skip', 'incremental', 'full']"
)

# ❌ 禁止：错误信息不完整
raise RuntimeError(f"未知模式: {mode}")  # 错误！缺少合法值列表
```

### 设计演进清理规范

**新实现替代旧实现后，必须删除旧代码，禁止保留死代码。**

```python
# ✓ 正确：向量化版本替代循环版本后，删除旧函数

# 旧版本（已删除）：
# def calculate_single_stock(stock_df): ...

# 新版本（保留）：
def calculate_all_stocks_vectorized(factor_df):
    return factor_df.groupby('asset').transform(...)

# ❌ 禁止：保留旧函数但从不调用（死代码）
def calculate_single_stock(stock_df):  # 死代码！
    """单股票版本，从未被调用"""
    return stock_df.rolling(20).mean()

def calculate_all_stocks_vectorized(factor_df):  # 实际使用
    return factor_df.groupby('asset').transform(...)
```

**为何必须清理死代码：**
1. 死代码误导读者
2. 增加维护成本
3. 可能与新实现不一致

### 函数签名变更同步规范

**返回值变更时必须同步更新类型注解和 docstring。**

```python
# ✓ 正确：类型注解和 docstring 同步更新
def load_data_from_cache(...) -> Tuple[pd.DataFrame, pd.DataFrame, dict]:
    """
    Returns:
        factor_df: 过滤后的因子数据
        return_df: 过滤后的收益数据
        raw_metadata: 原始数据范围信息（新增）
    """

# ❌ 禁止：只改返回值不改类型注解
def load_data_from_cache(...):  # 错误！缺少返回类型注解
    return factor_df, return_df, raw_metadata
```

---

## 日志规范（2026-05-20新增）

### 日志框架选择

**使用 Python 标准库 `logging` 模块。**

| 特性 | 说明 |
|------|------|
| 安装 | 无需安装，Python 标准库自带 |
| 功能 | 多级别、格式化、文件/控制台双输出、异常堆栈记录 |
| 标准 | 业界标准，所有 Python 项目通用 |
| 维护 | 无版本依赖问题，长期稳定 |

### 日志框架介绍

**logging 模块核心概念：**

```
┌─────────────────────────────────────────────────────────────────┐
│                     logging 模块架构                              │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  Logger（记录器）─────▶ Handler（处理器）─────▶ Formatter（格式器）│
│       │                    │                    │              │
│       │                    │                    │              │
│       ▼                    ▼                    ▼              │
│   logger.info()      FileHandler          "%(asctime)s..."     │
│   logger.error()     StreamHandler        格式化输出            │
│                                                                 │
│  Level（级别）：DEBUG < INFO < WARNING < ERROR < CRITICAL       │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

**四个核心组件：**

| 组件 | 作用 | 说明 |
|------|------|------|
| Logger | 记录器 | 代码调用入口，如 `logger.info()` |
| Handler | 处理器 | 决定输出位置（文件/控制台） |
| Formatter | 格式器 | 决定输出格式（时间、级别、消息） |
| Level | 级别 | 决定哪些消息被记录 |

### 日志级别规范

**五个日志级别及其使用场景：**

| 级别 | 数值 | 使用场景 | 示例 |
|------|------|---------|------|
| DEBUG | 10 | 调试信息，开发阶段 | `logger.debug("数据行数: %d", len(df))` |
| INFO | 20 | 正常运行信息 | `logger.info("IC 计算完成，有效天数: 514")` |
| WARNING | 30 | 警告但不影响运行 | `logger.warning("缓存过期，将重新计算")` |
| ERROR | 40 | 错误但程序可继续 | `logger.error("单日 IC 计算失败: 股票数不足")` |
| CRITICAL | 50 | 严重错误，程序可能终止 | `logger.critical("缓存文件损坏，无法恢复")` |

**级别设置原则：**
- 开发阶段：`DEBUG`（查看所有细节）
- 生产环境：`INFO` 或 `WARNING`（减少日志量）
- 调试问题：临时设置为 `DEBUG`

### 日志文件路径规范

**路径规则：脚本当前目录下的 `logs/` 子目录。**

```
factor_ic_analyzer/
├── factor_ic/
│   ├── ic_rsi_1d.py           # 脚本
│   ├── logs/                  # 日志目录 ← 自动创建
│   │   ├── ic_rsi_1d_2026-05-20.log
│   │   ├── ic_rsi_1d_2026-05-21.log
│   │   └── ...
│   └── result/                # 结果目录
│
├── backtest/
│   ├── layered_backtest.py
│   ├── logs/                  # 日志目录 ← 自动创建
│   │   └── layered_backtest_2026-05-20.log
│   └── ...
```

**路径计算：**
```python
# 获取脚本所在目录
script_dir = Path(__file__).parent

# 日志目录
logs_dir = script_dir / 'logs'

# 日志文件
log_file = logs_dir / f"{script_name}_{date}.log"
```

### 日志文件命名规范

**命名规则：`<脚本名>_YYYY-MM-DD.log`**

| 组成部分 | 说明 | 示例 |
|---------|------|------|
| `<脚本名>` | 脚本文件名去掉 `.py` 后缀 | `ic_rsi_1d` |
| `_` | 分隔符 | 固定 |
| `YYYY-MM-DD` | 当天日期 | `2026-05-20` |
| `.log` | 文件扩展名 | 固定 |

**示例：**
- `ic_rsi_1d.py` → `logs/ic_rsi_1d_2026-05-20.log`
- `layered_backtest.py` → `logs/layered_backtest_2026-05-20.log`
- `ic_kdj_j_1d.py` → `logs/ic_kdj_j_1d_2026-05-20.log`

**每天一个日志文件：**
- 便于按日期追溯问题
- 防止单个文件过大
- 自动清理历史日志（可选）

### 日志格式规范

**标准格式：`%(asctime)s | %(levelname)-8s | %(name)s | %(message)s`**

| 字段 | 说明 | 输出示例 |
|------|------|---------|
| `%(asctime)s` | 时间戳 | `2026-05-20 16:30:45,123` |
| `%(levelname)-8s` | 级别（左对齐8字符） | `ERROR    ` |
| `%(name)s` | Logger 名称 | `ic_rsi_1d` |
| `%(message)s` | 日志消息 | `缓存文件不存在` |

**完整输出示例：**
```
2026-05-20 16:30:45,123 | INFO     | ic_rsi_1d | IC 计算完成，有效天数: 514
2026-05-20 16:30:46,456 | WARNING  | ic_rsi_1d | 缓存过期，将重新计算
2026-05-20 16:30:47,789 | ERROR    | ic_rsi_1d | 单日 IC 计算失败: 股票数 < 10
```

**格式化参数说明：**
- `%(levelname)-8s`：`-8` 表示左对齐，宽度8字符
- `%d`、`%s`：在 `logger.info()` 中使用，如 `logger.info("行数: %d", len(df))`

### 异常记录规范

**所有异常必须用 `logger.error()` 或 `logger.exception()` 记录。**

**核心规则：**
1. 使用 `logger.exception()` 自动记录完整堆栈
2. 异常信息必须明确详细，便于定位问题
3. 记录异常类型、异常消息、关键变量值

**使用姿势：**

```python
# ✓ 正确：使用 logger.exception() 记录完整堆栈
try:
    result = calculate_ic_with_direction_verification(...)
except ValueError as e:
    logger.exception("IC 计算失败: %s", str(e))
    # 输出包含完整堆栈，便于定位问题
    raise

# ✓ 正确：异常信息明确详细
try:
    with open(cache_file, 'r') as f:
        data = json.load(f)
except FileNotFoundError as e:
    logger.error(
        "缓存文件不存在\n"
        "文件路径: %s\n"
        "请检查缓存路径或执行全量计算",
        cache_file
    )
    raise RuntimeError(f"缓存文件不存在: {cache_file}") from e

# ✓ 正确：记录关键变量值
try:
    ic_value = calculate_single_day_ic(daily_data, min_stocks=10)
except Exception as e:
    logger.exception(
        "单日 IC 计算异常\n"
        "日期: %s\n"
        "股票数: %d\n"
        "因子列: %s",
        date, len(daily_data), factor_col
    )
    raise

# ❌ 禁止：只记录简单信息，无法定位问题
try:
    result = calculate_ic(...)
except Exception as e:
    logger.error("计算失败")  # 错误！信息不明确
    raise

# ❌ 禁止：不记录异常堆栈
try:
    result = calculate_ic(...)
except Exception as e:
    logger.error(str(e))  # 错误！缺少堆栈
    raise
```

**logger.error() vs logger.exception()：**

| 方法 | 堆栈记录 | 使用场景 |
|------|---------|---------|
| `logger.exception()` | 自动记录完整堆栈 | 捕获异常时首选 |
| `logger.error()` | 不记录堆栈 | 普通错误信息 |

**推荐：捕获异常时优先使用 `logger.exception()`。**

### 使用姿势示例

**完整配置示例：**

```python
import logging
from pathlib import Path
from datetime import datetime

# ============================================================================
# 日志配置（遵循 PROJECT.md 日志规范）
# ============================================================================

def setup_logger(script_name: str) -> logging.Logger:
    """
    配置日志记录器
    
    参数:
        script_name: 脚本名称（不含 .py 后缀）
    
    返回:
        配置好的 Logger 对象
    
    规范:
        - 日志目录: 脚本当前目录/logs/
        - 日志文件: <脚本名>_YYYY-MM-DD.log
        - 日志格式: %(asctime)s | %(levelname)-8s | %(name)s | %(message)s
        - 日志级别: INFO（生产）/ DEBUG（开发）
    """
    # 获取脚本所在目录
    script_dir = Path(__file__).parent
    
    # 日志目录
    logs_dir = script_dir / 'logs'
    logs_dir.mkdir(parents=True, exist_ok=True)  # 自动创建
    
    # 日志文件名
    today = datetime.now().strftime('%Y-%m-%d')
    log_file = logs_dir / f"{script_name}_{today}.log"
    
    # 创建 Logger
    logger = logging.getLogger(script_name)
    logger.setLevel(logging.INFO)  # 生产环境用 INFO，开发阶段用 DEBUG
    
    # 防止重复添加 Handler（多次调用时）
    if logger.handlers:
        return logger
    
    # 文件 Handler
    file_handler = logging.FileHandler(
        log_file,
        mode='a',  # 追加模式，同一天的日志合并到同一文件
        encoding='utf-8'
    )
    file_handler.setLevel(logging.INFO)
    
    # 控制台 Handler（可选，便于开发调试）
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    
    # Formatter
    formatter = logging.Formatter(
        '%(asctime)s | %(levelname)-8s | %(name)s | %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    file_handler.setFormatter(formatter)
    console_handler.setFormatter(formatter)
    
    # 添加 Handler
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    
    return logger


# ============================================================================
# 脚本中使用
# ============================================================================

# 在脚本顶部配置日志
logger = setup_logger('ic_rsi_1d')

def load_data_from_cache():
    """从缓存加载数据"""
    logger.info("开始从缓存加载因子数据...")
    
    try:
        with gzip.open(FACTOR_CACHE, 'rt', encoding='utf-8') as f:
            factor_data = json.load(f)
        
        logger.info(
            "因子数据加载成功\n"
            "行数: %d\n"
            "股票数: %d\n"
            "日期范围: %s ~ %s",
            len(factor_data['data']),
            factor_data['metadata']['n_assets'],
            factor_data['metadata']['period_start'],
            factor_data['metadata']['period_end']
        )
        
        return factor_data
        
    except FileNotFoundError as e:
        logger.exception(
            "缓存文件不存在\n"
            "文件路径: %s\n"
            "请检查缓存路径或执行全量计算",
            FACTOR_CACHE
        )
        raise RuntimeError(f"缓存文件不存在: {FACTOR_CACHE}") from e
    
    except json.JSONDecodeError as e:
        logger.exception(
            "缓存文件 JSON 格式错误\n"
            "文件路径: %s\n"
            "错误位置: 行 %d\n"
            "请检查缓存文件或重新生成",
            FACTOR_CACHE, e.lineno
        )
        raise RuntimeError(f"缓存文件 JSON 格式错误: {FACTOR_CACHE}") from e


def calculate_daily_ic_series(...):
    """计算每日 IC 序列"""
    logger.info("开始计算每日 IC...")
    
    valid_days = 0
    for date, daily_data in merged.groupby('date'):
        try:
            ic_value = calculate_single_day_ic(daily_data, min_stocks=10)
            if ic_value is not None:
                valid_days += 1
        except Exception as e:
            logger.exception(
                "单日 IC 计算异常\n"
                "日期: %s\n"
                "股票数: %d\n"
                "因子列: rsi_6",
                date, len(daily_data)
            )
            # 继续计算其他日期，不中断整个流程
            continue
    
    logger.info("IC 计算完成，有效天数: %d", valid_days)
```

### 强制规则

**必须遵守：**

```
□ 所有异常必须用 logger.exception() 或 logger.error() 记录
□ 异常信息必须明确详细（异常类型、消息、关键变量值）
□ 日志文件路径: 脚本当前目录/logs/
□ 日志文件命名: <脚本名>_YYYY-MM-DD.log
□ 日志格式: %(asctime)s | %(levelname)-8s | %(name)s | %(message)s
□ 关键操作必须记录 INFO 日志（数据加载、计算完成、保存成功）
□ 错误场景必须记录 ERROR/WARNING 日志
□ 生产环境日志级别: INFO
□ 开发阶段日志级别: DEBUG（可选）
```

**禁止行为：**

```
❌ 异常只打印简单信息（"计算失败"），无法定位问题
❌ 使用 print() 替代 logger（无法持久化、无级别区分）
❌ 不记录异常堆栈（无法追溯问题位置）
❌ 日志文件放在任意位置（不在 logs/ 目录）
❌ 日志文件命名不规范（不含日期或脚本名）
```

### 日志清理规范（可选）

**历史日志清理策略：**

```python
# 清理 30 天前的日志文件
def cleanup_old_logs(logs_dir: Path, keep_days: int = 30):
    """清理过期日志文件"""
    cutoff_date = datetime.now() - timedelta(days=keep_days)
    
    for log_file in logs_dir.glob('*.log'):
        # 从文件名提取日期: ic_rsi_1d_2026-05-20.log
        date_str = log_file.stem.split('_')[-1]
        file_date = datetime.strptime(date_str, '%Y-%m-%d')
        
        if file_date < cutoff_date:
            logger.info("清理过期日志: %s", log_file.name)
            log_file.unlink()
```

**建议保留天数：**
- 开发环境：30 天
- 生产环境：90 天（可根据审计需求调整）

---

## 版本历史

| 版本 | 日期 | 更新内容 |
|------|------|---------|
| v2.3 | 2026-05-20 | 新增"日志规范"章节：框架选择（logging）、级别规范、路径规范、命名规范、格式规范、异常记录规范、使用姿势示例 |
| v2.2 | 2026-05-20 | 新增"代码风格规范"章节（import、注释缩进、异常链、死代码清理等） |
| v2.1 | 2026-05-20 | 新增"脚本配套文件规范"：流程文档位置、测试用例位置、强制规则 |
| v2.0 | 2026-05-19 | 重构：factor_ic 规范移至 MODULE.md，精简项目级规范 |
| v1.x | 2026-05-07~19 | factor_ic 规范逐步完善（已移至 MODULE.md） |

---

*最后更新: 2026-05-20*
