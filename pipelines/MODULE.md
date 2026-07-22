# pipelines 模块规范

> 版本: v1.0
> 最后更新: 2026-06-30（首次创建：子包化重构 + 静默丢配置 bug 修复）
>
> 本规范由 AI 智能体或人类开发者执行。每条规则采用统一框架:**What / Why / How / Don't / When / Verify**。
>
> **harness 中立**:不绑定特定智能体平台,描述均为通用语义。

---

## 目录

### 一、模块概况
- [快速参考](#快速参考)
- [模块概述](#模块概述)
- [目录结构](#目录结构)

### 二、规则索引 (P1-P8)
- [P1 配置位置](#p1-配置位置)
- [P2 包内导入规范](#p2-包内导入规范)
- [P3 data_slicer 退出码](#p3-data_slicer-退出码)
- [P4 filter 表达式语法](#p4-filter-表达式语法)
- [P5 filter 占位符白名单](#p5-filter-占位符白名单)
- [P6 主数据源路径独立于 paths.py](#p6-主数据源路径独立于-pathspy)
- [P7 不删 pipeline 配置](#p7-不删-pipeline-配置)
- [P8 子包不产 result/ 业务结果](#p8-子包不产-result-业务结果)
- [★ P9 移动文件后必审 Path(__file__).parent](#★-p9-移动文件后必审-path__file__parent)

### 三、附录
- [更新记录](#更新记录)
- [引用说明](#引用说明)

---

## 快速参考

### 模块定位

| 项目 | 内容 |
|------|------|
| 模块职责 | 解析 `pipelines.yaml` + 切割/链接每个 pipeline 的数据子集 (Stage 1.5) |
| 数据流向 | 主数据源 `data_fetchers/result/factor_ic_data.parquet` → 按 pipeline filter 切割 → `data_fetchers/result/<alias>/factor_ic_data.parquet` |
| 触发方式 | `run_pipeline.py --start-stage 1.5` (独立运行) 或 Stage 1.5 在全 pipeline 流程中 |
| 依赖关系 | **上游**: `data_fetchers/factor_generator.py` (主数据源)  **下游**: factor_ic / backtest / comprehensive_factor / summary (读 `paths.FACTOR_IC_DATA`) |

### 关键文件 (4 个)

| 文件 | 行数 | 职责 |
|------|------|------|
| `pipelines.yaml` | ~15 | pipeline 别名 → filter 配置 (单一来源) |
| `pipelines/__init__.py` | 0 | 子包标识 (空, 不重导出) |
| `pipelines/pipeline_context.py` | 62 | 配置加载 + 占位符解析 (Stage 0 基础设施) |
| `pipelines/pipeline_data_slicer.py` | 77 | Stage 1.5: 数据切割/symlink 执行器 |

### 4 条硬约束 (速查)

| # | 约束 | 对应规则 |
|---|------|---------|
| 1 | `pipelines.yaml` 是配置唯一来源, .py 文件不接配置参数 | P1 |
| 2 | filter 表达式必须可被 `pandas.DataFrame.query()` 解析 | P4 |
| 3 | `pipeline_context.py` 找不到 yaml 时**禁止静默兜底为 default** (设计遗留 bug, v2 移除兜底) | P1, P9 |
| 4 | 子包移动/重命名后**必须审计**所有 `Path(__file__).parent` 引用 | P9 |

### 跨模块通用原则 (来自 PROJECT.md)
- 输出结构必须统一 (本子包产出: `data_fetchers/result/<alias>/factor_ic_data.parquet`)
- 路径全部从 `paths.py` 导入 (本子包例外: P6)
- 字段值不可为 None (yaml 中 filter=null 表示不过滤, 不是 None 字段缺失)

---

## 模块概述

`pipelines/` 子包是**多 pipeline 并行隔离架构**的配置与执行层。它不参与任何业务计算 (IC/回测/选股), 只负责两件事:

1. **配置解析** (`pipeline_context.py`): 读 `pipelines.yaml`, 把 `default` / `ob_quality` 等别名解析成可用的 filter 表达式, 并支持 `{latest_date}` 等动态占位符
2. **数据切割** (`pipeline_data_slicer.py`): 根据解析出的 filter, 为每个 pipeline 准备独立的数据子集 (filter=None 时创建 symlink, filter=表达式时 query 后写新 parquet)

**架构定位**: Stage 0 (数据拉取) 和 Stage 1 (数据整合) 是**共享区**——所有 pipeline 共享同一份主数据源。Stage 1.5 是**隔离关口**——从这里开始, 每个 pipeline 看到的是**完全独立**的数据子集。Stage 2-7 全部按 `PIPELINE_ALIAS` 目录隔离。

---

## 目录结构

```
pipelines/
├── __init__.py                   # 子包标识 (空)
├── pipeline_context.py           # 配置解析 + 占位符替换
├── pipeline_data_slicer.py       # Stage 1.5 数据切割执行器
└── MODULE.md                     # 本文件

data_fetchers/result/             # 数据源 + 切割产物
├── factor_ic_data.parquet        # 主数据源 (Stage 1 产出, 共享)
├── default/                      # default pipeline 子集
│   └── factor_ic_data.parquet    # symlink → 主数据源
└── ob_quality/                   # ob_quality pipeline 子集
    └── factor_ic_data.parquet    # filter='rsi_6 > 70 and turnover_rate > 5' 后写入
```

---

## 规则索引

### P1: 配置位置

**What**: 所有 pipeline 的 filter 配置**只**放在 `pipelines/pipelines.yaml`, 不通过环境变量、命令行参数或代码常量注入。

**How**:
```yaml
# pipelines/pipelines.yaml
default:
  filter: null
  description: "全市场全时段"

ob_quality:
  filter: "rsi_6 > 70 and turnover_rate > 5"
  description: "超买股 × 高换手率"
```

**Don't**:
- ❌ 在 `pipeline_context.py` 里硬编码 `{"default": {"filter": None}}` 兜底字典（**当前代码存在此兜底, v2 计划移除**——它会导致 yaml 不存在时**静默丢失**所有非 default pipeline, 见 [bug 案例](#更新记录)）
- ❌ 通过 `--filter` CLI 参数覆盖 yaml (破坏了"配置单一来源"原则)
- ❌ 把 filter 逻辑分散到下游模块的代码里

**Why**: 单一来源 → 改一处全 pipeline 生效 → 避免"`ob_quality` 在 ic 模块是 X、在 backtest 是 Y"的不一致灾难。

**When**: 新增/修改/弃用 pipeline 时, 改 yaml 即可, 不需要碰任何 .py 文件 (除 P9 类的重构)。

**Verify**: `python -c "from pipelines.pipeline_context import load_pipeline_config; print(len(load_pipeline_config()))"` 输出必须 = `pipelines.yaml` 里的 pipeline 数。

---

### P2: 包内导入规范

**What**: `pipelines/` 子包内部的 .py 文件互相导入时, **必须**使用完整包路径 `from pipelines.xxx import yyy`, 不允许 `from xxx import yyy` (即使两者在同一目录下)。

**How**:
```python
# pipelines/pipeline_data_slicer.py
from pipelines.pipeline_context import load_pipeline_config, resolve_filter
```

**Don't**:
- ❌ `from pipeline_context import ...` (旧风格, 子包化前可用, **子包化后禁止**)
- ❌ `from .pipeline_context import ...` (相对导入, 在 `python pipelines/pipeline_data_slicer.py` 直接调用模式下**会失败**, 因为脚本不是作为包模块启动的)

**Why**: 显式包路径既能在 `python pipelines/xxx.py` 模式工作, 又能在 `python -m pipelines.xxx` 模式工作。相对导入要求包级启动, 与项目当前的 ScriptTask 启动方式不兼容。

**When**: 任何新增的 `pipelines/*.py` 文件之间的导入。

**Verify**: `grep -rn "^from pipeline_\|^from \." pipelines/ --include="*.py"` 必须无输出 (除了 `from .context` 类的相对导入, 也禁止)。

---

### P3: data_slicer 退出码

**What**: `pipeline_data_slicer.py` 退出码 0/1 (无 2), 与项目其他 Stage 1.x 脚本保持一致。

**How**:
```python
# 成功
sys.exit(0)  # 隐式, main() 正常 return

# 失败 (主数据源不存在)
print("[ERROR] 主数据源不存在:", source)
sys.exit(1)
```

**Don't**:
- ❌ 退出码 2 (那是 import-time 配置/注册失败专用, 见 PROJECT.md H12 退出码语义)
- ❌ `sys.exit(0)` 即便有 pipeline 处理失败也退出 0 (必须保证所有 pipeline 都成功才 exit 0)

**Why**: `run_pipeline.py` 的 ScriptTask 重试机制依赖退出码语义 (0=成功不重试, 非0=重试)。

**When**: 任何 `pipeline_data_slicer.py` 的 main() 异常分支。

**Verify**: `python pipelines/pipeline_data_slicer.py; echo $?` 必须输出 0。临时把主数据源改名为不存在, 再跑一次, `echo $?` 必须输出 1。

---

### P4: filter 表达式语法

**What**: `pipelines.yaml` 中 `filter` 字段的值必须是 **`pandas.DataFrame.query()` 可解析**的字符串, 或 `null` (不过滤)。

**How**:
```yaml
ob_quality:
  filter: "rsi_6 > 70 and turnover_rate > 5"  # pandas query 合法语法
```

合法引用:
- 列名直接引用: `rsi_6 > 70`
- 字符串字面量: `industry == '银行'`
- 逻辑运算: `and` / `or` / `not`
- 算术运算: `rsi_6 * 1.5 > 100`
- 占位符: `{latest_date_minus_30}` (见 P5)

**Don't**:
- ❌ Python 表达式但 query 不支持: `rsi_6 in [60, 70]` (改成 `(rsi_6 == 60) or (rsi_6 == 70)`)
- ❌ 函数调用: `np.abs(rsi_6) > 5` (query 不支持, 改成在 factor_generator 阶段算好新列)
- ❌ 引用环境变量: `os.environ.get('MIN_RSI')` (破坏 P1)

**Why**: filter 在 `data_slicer.py:50` 用 `df.query(resolved)` 直接执行, 非合法 pandas query 会抛 `pd.core.computation.ops.UndefinedVariableError` 等异常, 导致 Stage 1.5 失败。

**When**: 新增 pipeline 时, 先在 Jupyter 里验证 `df.query("你的 filter")` 能跑通, 再写入 yaml。

**Verify**:
```python
import pandas as pd
df = pd.read_parquet("data_fetchers/result/factor_ic_data.parquet", columns=["rsi_6", "turnover_rate"])
print(len(df.query("rsi_6 > 70 and turnover_rate > 5")))
```

---

### P5: filter 占位符白名单

**What**: filter 表达式支持 3 个动态占位符, 由 `resolve_filter()` 在执行前替换为实际日期字符串:

| 占位符 | 替换为 | 用途 |
|--------|--------|------|
| `{latest_date}` | 主数据源最大日期 (`%Y-%m-%d` 格式) | 当前截面 |
| `{latest_date_minus_30}` | 最大日期 - 30 天 | 1 个月窗口 |
| `{latest_date_minus_60}` | 最大日期 - 60 天 | 2 个月窗口 |

**How**:
```yaml
# 假设主数据源最大日期是 2026-06-30
temp_history:
  filter: "date >= '{latest_date_minus_30}'"
  # 运行时被替换为: "date >= '2026-05-31'"
```

**Don't**:
- ❌ 自行扩展占位符: `{latest_date_minus_90}` / `{start_of_year}` 等 (需要先在 `resolve_filter()` 里加替换规则)
- ❌ 在 filter 字符串里手动写日期: `"date >= '2026-01-01'"` (硬编码违反"数据驱动"原则, 且数据更新后失效)

**Why**: 避免每次数据更新后都要手改 yaml 里的日期, 减少人为失误。

**When**: filter 表达式需要引用"最近 N 天"语义时。

**Verify**: 跑 `python -c "from pipelines.pipeline_context import resolve_filter; print(resolve_filter(\"date >= '{latest_date_minus_30}'\"))"`, 输出日期字符串而非字面占位符。

---

### P6: 主数据源路径独立于 paths.py

**What**: `pipeline_data_slicer.py` 中的**主数据源路径**写死为 `PROJECT_ROOT / "data_fetchers" / "result" / "factor_ic_data.parquet"`, **不**走 `paths.FACTOR_IC_DATA_MASTER` 导入。

**How**:
```python
# pipelines/pipeline_data_slicer.py:59
source = PROJECT_ROOT / "data_fetchers" / "result" / "factor_ic_data.parquet"
```

**Don't**:
- ❌ `from paths import FACTOR_IC_DATA_MASTER` 然后用 `FACTOR_IC_DATA_MASTER` (循环依赖风险)
- ❌ `from paths import FACTOR_IC_DATA` (`FACTOR_IC_DATA` 含 `PIPELINE_ALIAS`, slicer 是 `PIPELINE_ALIAS` 的**上游**, 不能反向依赖)

**Why**: `paths.py` 里的 `FACTOR_IC_DATA = .../PIPELINE_ALIAS/factor_ic_data.parquet` 是**已隔离**的路径, 而 slicer 正是**产生** `PIPELINE_ALIAS` 子目录的执行器——`PIPELINE_ALIAS` 还没确定时, slicer 已经在跑。引用 `paths.FACTOR_IC_DATA` 会导致: 跑 `PIPELINE_ALIAS=ob_quality python slicer.py` 时, slicer 读 `ob_quality/factor_ic_data.parquet` (上次跑剩下的), 切完覆盖, 形成循环。

**When**: 永远。这是架构层硬约束, 不可破。

**Verify**: `grep -n "from paths" pipelines/pipeline_data_slicer.py pipelines/pipeline_context.py` 必须无输出。

---

### P7: 不删 pipeline 配置

**What**: `pipelines.yaml` 中**已存在**的 pipeline 配置不允许直接删除, 弃用时必须**注释保留** (历史可追溯)。

**How**:
```yaml
# ob_pool 已弃用 (2026-06-XX, 改用 ob_quality)
# ob_pool:
#   filter: "rsi_6 > 80"
#   description: "超买股 (旧版, 已弃用)"
```

**Don't**:
- ❌ `git rm` 删除 yaml 中的 pipeline 段 (丢失历史决策原因)
- ❌ 改 `filter` 字段为 `null` 当作"软删除" (这会让该 pipeline 退化成 default, 静默污染下游结果)

**Why**: 量化研究中"为什么当时不用这个 pipeline"和"为什么改用另一个"同等重要, 注释是唯一可追溯记录。

**When**: 弃用一个 pipeline (策略失效 / 被新 pipeline 替代) 时。

**Verify**: `git log -p pipelines/pipelines.yaml | head -50` 能看到所有 pipeline 的历史变更。

---

### P8: 子包不产 result/ 业务结果

**What**: `pipelines/` 子包**不**创建 `result/` 子目录, **不**写业务结果 JSON/Parquet 到自己目录下。所有产物写到 `data_fetchers/result/<alias>/`。

**How**:
- ✅ 产物: `data_fetchers/result/ob_quality/factor_ic_data.parquet`
- ✅ 日志: 复用项目根 `logs/` 目录, 或 `data_fetchers/logs/` (Stage 0 共享)

**Don't**:
- ❌ `pipelines/result/` 目录
- ❌ `pipelines/logs/` 目录
- ❌ 业务结果写到 `pipelines/` 任何子目录 (破坏"配置层不产数据"的角色定位)

**Why**: `pipelines/` 是配置/执行层, 业务数据归属 `data_fetchers/` (主数据源) 和各业务模块 `result/` (IC/回测/选股结果)。`pipelines/result/` 会让"配置 vs 数据"边界混乱, 增加新手理解成本。

**When**: 永远。这是子包角色定位硬约束。

**Verify**: `find pipelines/ -type d` 必须**只**有 `__pycache__` 和 `pipelines/` 自身 (无 result/ logs/ 等子目录)。

---

### ★ P9: 移动文件后必审 Path(__file__).parent

**What**: **任何**对 `pipelines/` 子包内 .py 文件的移动/重命名/目录调整后, **第一步**必须审计**所有** `Path(__file__).parent` 和 `Path(__file__).resolve().parent` 引用, 必要时改为 `Path(__file__).parent.parent` (或更深)。

**How** (审计步骤):
```bash
# 1. 列出包内所有 .py 文件
find pipelines/ -name "*.py" -not -path "*/__pycache__/*"

# 2. grep 所有 __file__ 引用
grep -n "__file__" pipelines/*.py

# 3. 对每个引用, 手动确认 Path 深度是否仍正确
#    - 文件在 pipelines/xxx.py → Path(__file__).parent = pipelines/, 如需项目根用 .parent.parent
#    - 文件在 pipelines/sub/xxx.py → Path(__file__).parent = pipelines/sub/, 如需 pipelines/ 用 .parent, 项目根用 .parent.parent
```

**Don't**:
- ❌ 移动文件后只跑 `python xxx.py` 验证"能跑通"就过 (能跑 ≠ 跑对, 见下方 bug 案例)
- ❌ 在 design 阶段只审计部分文件的 `PROJECT_ROOT` (2026-06-30 实战踩坑, 见下方)

**Why — 实战案例 (2026-06-30)**:
- `pipeline_context.py:11` 移动到 `pipelines/pipeline_context.py` 后, `PROJECT_ROOT = Path(__file__).parent` 指向 `pipelines/`
- 第 29 行 `config_path = PROJECT_ROOT / "pipelines" / "pipelines.yaml"` 变成 `pipelines/pipelines/pipelines.yaml`
- yaml 不存在 → `load_pipeline_config()` 静默兜底返回 `{"default": ...}`
- Stage 1.5 跑出来**只处理 1 个 pipeline**, 但 yaml 实际配置 2 个
- **`ob_quality` 静默丢失, 所有依赖该 pipeline 的下游分析结论错误**

**When**: 任何重构涉及文件路径变化时 (移动 / 子包化 / 目录嵌套加深)。

**Verify (加强版)**:
```bash
# 不仅要看"能跑", 要看"跑出来的内容数量对不对"
python -c "from pipelines.pipeline_context import load_pipeline_config; cfg = load_pipeline_config(); print('pipeline 数:', len(cfg), '| yaml 声明数:', sum(1 for line in open('pipelines/pipelines.yaml') if line and not line.startswith('#') and not line.startswith(' ') and ':' in line))"
```
两个数必须相等。

---

## 更新记录

### v1.0 (2026-06-30)
- 首次创建模块规范
- **触发事件**: 子包化重构 (`pipeline_context.py` + `pipeline_data_slicer.py` 从项目根移入 `pipelines/`)
- **同步 bug 修复**: `pipeline_context.py:11` `PROJECT_ROOT` 未跟随子包化更新, 导致 `ob_quality` pipeline 静默丢失 (详见 P9 实战案例 + `designs/refactor_pipelines_subpackage.md` §8.5)
- **新增规则**: P9 (Path(__file__).parent 审计铁律)
- **新增规则**: P1 兜底警告 (当前代码仍保留 yaml 不存在时的 default 兜底, v2 计划移除——因为它与 P9 配合时会**双重静默**丢配置)

### 未来计划 (v2)
- 移除 `load_pipeline_config()` 的 `{"default": ...}` 兜底, 改为 `FileNotFoundError` (符合 PROJECT.md H13 死代码禁止 + 符合第一性原理 "不要兜底")
- 增加 `pipelines/test_cases/` 单元测试 (等 P9 这类边界条件有 2+ 个真实案例后再加, 避免为假想需求写空测试)

---

## 引用说明

| 上游规范 | 引用内容 |
|---------|---------|
| `PROJECT.md` 跨模块数据路径 | Stage 1.5 输出契约: `data_fetchers/result/<alias>/factor_ic_data.parquet` |
| `PROJECT.md` 第一性原理 | "不要兜底" 原则 → P1 v2 计划 |
| `PROJECT.md` H12 退出码语义 | 退出码语义 (P3) |
| `PROJECT.md` H7 路径导入 | `from paths import` 规范 (P6 反例, 因循环依赖) |
| `PROJECT.md` H13 死代码禁止 | 死代码禁止 (P1 v2 计划) |
| `PROJECT.md` §规范补充结构模板 (What/How/Don't/Why/When/Examples/Verify 七段式) | 本文档采用的七段式 |
| `paths.py` 注释 | Stage 1.5 与 PIPELINE_ALIAS 关系 (本次同步更新) |
| `designs/refactor_pipelines_subpackage.md` | 本次重构完整 design 记录 + P9 实战案例详细复盘 |
