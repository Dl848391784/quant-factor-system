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

## 版本历史

| 版本 | 日期 | 更新内容 |
|------|------|---------|
| v2.2 | 2026-05-20 | 新增"代码风格规范"章节（import、注释缩进、异常链、死代码清理等） |
| v2.1 | 2026-05-20 | 新增"脚本配套文件规范"：流程文档位置、测试用例位置、强制规则 |
| v2.0 | 2026-05-19 | 重构：factor_ic 规范移至 MODULE.md，精简项目级规范 |
| v1.x | 2026-05-07~19 | factor_ic 规范逐步完善（已移至 MODULE.md） |

---

*最后更新: 2026-05-20*
