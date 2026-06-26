# Design: 多 Pipeline 架构

> 状态：待审核
> 创建：2026-06-26
> 作者：云瑶
> 方案选型：B（`<module>/result/<alias>/`）

---

## 1. 背景与目标

### 1.1 问题

当前系统只有一条 pipeline：全市场 → IC → 回测 → composite → 选股 → 报告。
所有产出物写入各模块的 `result/` 目录，无法并行运行第二条 pipeline（产出物会覆盖）。

### 1.2 目标

构建多 pipeline 执行能力：
- **Stage 0-1 共享**：数据拉取和 factor_generator 只跑一次
- **Stage 1.5 数据切割**：每个 pipeline 按任意维度切割 `factor_ic_data.parquet`，取一个别名
- **Stage 2-7 独立执行**：每个 pipeline 的 IC、回测、composite、选股、报告各自独立产出
- **产出隔离**：每个 pipeline 的所有产出物在各自别名子目录下

### 1.3 典型用例

```yaml
# pipelines/pipelines.yaml
default:                    # 全市场全时段（现有行为）
  filter: null
ob_pool:                    # 超买股子集
  filter: "rsi_6 > 70"
recent_30d:                 # 近30天
  filter: "date >= '{latest_date_minus_30}'"
```

---

## 2. 目录结构（方案 B）

### 2.1 设计决策

采用 **方案 B：`<module>/result/<alias>/`**，在现有模块目录树内新增 `<alias>` 子目录层级。

**选择理由**：
1. **AGENTS.md 规则 #2 兼容**：现有规则"输出位置：`<模块>/result/`"自然扩展为 `<模块>/result/<alias>/`，语义不变，只多一层
2. **模块归属不变**：模块仍拥有自己的 `result/` 和 `logs/` 目录树，不引入跨模块路径
3. **logger_config.py 自包含**：`Path(__file__).parent.parent / "logs" / alias`，无需 `from paths import` 跨模块依赖
4. **文档改动更小**：PROJECT.md 加一条规则覆盖全部模块，不需要改 AGENTS.md 跨模块数据路径表的路径前缀

### 2.2 新目录树

```
factor_ic_analyzer/
│
├── data_fetchers/              # ── 共享区（Stage 0-1，不随 pipeline 变化）──
│   └── result/
│       ├── factor_ic_data.parquet    # 主数据源（唯一的全量数据）
│       ├── default/                  # NEW: default pipeline 数据
│       │   └── factor_ic_data.parquet   # symlink → 主数据源
│       └── ob_pool/                  # NEW: ob_pool pipeline 数据
│           └── factor_ic_data.parquet   # 切割后子集 (~20MB)
│
├── factor_ic/                  # ── 代码 + 产出区（结构不变，result/logs 下多一层 alias）──
│   ├── common/
│   │   ├── data_loader.py      # 改：DEFAULT_DATA_CACHE 从 paths 导入
│   │   ├── ic_result_builder.py # 不变：已从 paths 导入
│   │   └── logger_config.py    # 改：log_dir 追加 alias 子目录
│   ├── ic_*.py                 # 不变：33 个 IC 脚本
│   ├── result/
│   │   ├── default/            # default pipeline 的 IC 结果
│   │   │   └── ic_amplitude_1d_analysis_result.json
│   │   └── ob_pool/            # ob_pool pipeline 的 IC 结果
│   │       └── ic_amplitude_1d_analysis_result.json
│   └── logs/
│       ├── default/
│       └── ob_pool/
│
├── backtest/                   # 同 factor_ic 结构
│   ├── common/
│   │   ├── data_loader.py      # 改：同 factor_ic
│   │   └── logger_config.py    # 改：同
│   ├── result/
│   │   ├── default/
│   │   └── ob_pool/
│   └── logs/
│       ├── default/
│       └── ob_pool/
│
├── comprehensive_factor/       # 同结构
│   ├── common/
│   │   ├── composite_runner.py # 不变：ic_result_dir 已参数化
│   │   └── logger_config.py    # 改：同
│   ├── result/
│   │   ├── default/
│   │   │   ├── composite_rolling_icir_weight_1d.json
│   │   │   ├── weight_selection_result.json
│   │   │   ├── stock_selection_history/    # Parquet 分区
│   │   │   └── lr_training_data/
│   │   └── ob_pool/
│   │       └── ...
│   └── logs/
│       ├── default/
│       └── ob_pool/
│
├── stock_selector/             # 同结构
│   ├── common/logger_config.py # 改：同
│   ├── result/                 # （如有产出）
│   │   ├── default/
│   │   └── ob_pool/
│   └── logs/
│       ├── default/
│       └── ob_pool/
│
├── summary/                    # 同结构
│   ├── common/logger_config.py # 改：同
│   ├── result/
│   │   ├── default/
│   │   │   └── factor_summary_report_YYYY-MM-DD.txt
│   │   └── ob_pool/
│   │       └── ...
│   └── logs/
│       ├── default/
│       └── ob_pool/
│
├── reverse_discovery/          # 同结构（如启用）
│   └── ...
│
├── pipelines/                  # ── Pipeline 配置区（NEW）──
│   └── pipelines.yaml          # Pipeline 配置文件
│
├── paths.py                    # 改：路径常量加 alias 层
├── pipeline_context.py         # NEW：pipeline 上下文管理
├── pipeline_data_slicer.py     # NEW：Stage 1.5 数据切割脚本
└── run_pipeline.py             # 改：多 pipeline 编排
```

### 2.3 设计原则

| 原则 | 说明 |
|------|------|
| **代码不动，路径动** | 脚本代码（ic_*.py, backtest_*.py 等）不改动，只改路径解析 |
| **环境变量传递别名** | `PIPELINE_ALIAS` 环境变量在 subprocess 启动时注入 |
| **paths.py 集中解析** | 所有路径常量在 `paths.py` import 时根据别名一次性解析 |
| **模块归属不变** | `factor_ic/result/` 仍是 factor_ic 的目录，只是多了 `<alias>` 子目录 |
| **共享区与隔离区分明** | `data_fetchers/result/` 是共享区，各模块 `result/<alias>/` 是隔离区 |

### 2.4 不选方案 A 的原因

| 维度 | A: `pipelines/<alias>/` | B: `<module>/result/<alias>/`（选用） |
|------|------------------------|--------------------------------------|
| AGENTS.md 规则 #2 | ❌ 破坏"输出位置：`<模块>/result/`"，需重写规则 | ✅ 自然扩展，只多一层 |
| 跨模块数据路径表 | ❌ 6 行路径前缀全改 | ✅ 只加 `/<alias>/` 后缀 |
| 模块归属 | ❌ 模块不再拥有自己的 result 目录 | ✅ 模块仍拥有自己的目录树 |
| logger_config.py | ❌ 需 `from paths import` 跨模块依赖 | ✅ `Path(__file__).../"logs"/alias` 自包含 |
| 新增 pipeline | ✅ 建一个目录 | ❌ 需在 6 个模块下各建子目录（用 slicer 自动化） |
| 查看/删除 pipeline | ✅ 一处 | ❌ 散落 6 处（用 `find -name <alias>` 解决） |

A 的"集中"优势在操作层面，B 的"规范兼容"优势在架构层面。架构稳定性优先于操作便利性。

---

## 3. 配置文件：pipelines.yaml

```yaml
# pipelines/pipelines.yaml
# Pipeline 别名 → 数据切割配置
# filter 使用 pandas query 表达式，null 表示不切割（全量）

default:
  filter: null
  description: "全市场全时段"

ob_pool:
  filter: "rsi_6 > 70"
  description: "超买股子集 (RSI>70)，用于超买池内部选股研究"

# 未来扩展示例（当前不启用）：
# recent_30d:
#   filter: "date >= '2026-05-27'"
#   description: "近30天子集"
# ob_recent_30d:
#   filter: "rsi_6 > 70 and date >= '2026-05-27'"
#   description: "超买股 × 近30天"
```

### 3.1 filter 表达式规范

| 类型 | 示例 | 说明 |
|------|------|------|
| 无过滤 | `null` | 全量数据（default pipeline） |
| 截面过滤 | `rsi_6 > 70` | 每日只保留 RSI>70 的股票 |
| 时间过滤 | `date >= '2026-05-27'` | 只保留指定日期后数据 |
| 组合过滤 | `rsi_6 > 70 and turnover_rate > 3` | 多条件 AND |
| 动态时间 | `date >= '{latest_date_minus_30}'` | 占位符，slicer 运行时替换 |

---

## 4. 核心组件

### 4.1 paths.py 改造

**核心改动**：路径常量从"硬编码模块路径"变为"根据 PIPELINE_ALIAS 环境变量动态解析，追加 alias 子目录"。

```python
# paths.py (改造后)

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent

# ============================================================================
# Pipeline 别名（环境变量注入，subprocess 级别隔离）
# ============================================================================
PIPELINE_ALIAS = os.environ.get("PIPELINE_ALIAS", "default")

# ============================================================================
# 共享区（Stage 0-1，不随 pipeline 变化）
# ============================================================================
DATA_FETCHERS_RESULT = PROJECT_ROOT / "data_fetchers" / "result"

# 主数据源（factor_generator 产出，所有 pipeline 的源头）
FACTOR_IC_DATA_MASTER = DATA_FETCHERS_RESULT / "factor_ic_data.parquet"

# 其他共享数据源（不变）
FINANCIAL_DATA = DATA_FETCHERS_RESULT / "financial_data.json.gz"
FUND_FLOW_DATA = DATA_FETCHERS_RESULT / "fund_flow_data.json.gz"
MARKET_CAP_DATA = DATA_FETCHERS_RESULT / "market_cap_data.json.gz"
STOCK_LIST_DATA = DATA_FETCHERS_RESULT / "stock_list.json"
RETURN_DATA_BACKUP = DATA_FETCHERS_RESULT / "return_data.json.gz"
FACTOR_DATA_BACKUP = DATA_FETCHERS_RESULT / "factor_data.json.gz"

# ============================================================================
# Pipeline 数据源（slicer 产出，放在 data_fetchers/result/<alias>/ 下）
# ============================================================================
FACTOR_IC_DATA = DATA_FETCHERS_RESULT / PIPELINE_ALIAS / "factor_ic_data.parquet"

# ============================================================================
# 模块产出目录（方案 B：在现有 result/logs 下追加 alias 子目录）
# ============================================================================
FACTOR_IC_RESULT = PROJECT_ROOT / "factor_ic" / "result" / PIPELINE_ALIAS
BACKTEST_RESULT = PROJECT_ROOT / "backtest" / "result" / PIPELINE_ALIAS
COMPREHENSIVE_FACTOR_RESULT = PROJECT_ROOT / "comprehensive_factor" / "result" / PIPELINE_ALIAS
SUMMARY_RESULT = PROJECT_ROOT / "summary" / "result" / PIPELINE_ALIAS
STOCK_SELECTOR_RESULT = PROJECT_ROOT / "stock_selector" / "result" / PIPELINE_ALIAS
REVERSE_DISCOVERY_RESULT = PROJECT_ROOT / "reverse_discovery" / "result" / PIPELINE_ALIAS

# LR 训练数据（自动隔离）
LR_TRAINING_DATA_DIR = COMPREHENSIVE_FACTOR_RESULT / "lr_training_data"

# 模块日志目录（同理追加 alias）
FACTOR_IC_LOGS = PROJECT_ROOT / "factor_ic" / "logs" / PIPELINE_ALIAS
BACKTEST_LOGS = PROJECT_ROOT / "backtest" / "logs" / PIPELINE_ALIAS
COMPREHENSIVE_FACTOR_LOGS = PROJECT_ROOT / "comprehensive_factor" / "logs" / PIPELINE_ALIAS
SUMMARY_LOGS = PROJECT_ROOT / "summary" / "logs" / PIPELINE_ALIAS
STOCK_SELECTOR_LOGS = PROJECT_ROOT / "stock_selector" / "logs" / PIPELINE_ALIAS
REVERSE_DISCOVERY_LOGS = PROJECT_ROOT / "reverse_discovery" / "logs" / PIPELINE_ALIAS

# 临时文件目录（pipeline 隔离）
TEMPORARY_DIR = PROJECT_ROOT / "temporary" / PIPELINE_ALIAS

# design.md 目录（共享，不隔离）
DESIGNS_DIR = PROJECT_ROOT / "designs"
```

**关键点**：
- 常量名不变（`FACTOR_IC_RESULT`、`FACTOR_IC_DATA` 等），下游代码不需要改
- import 时一次性解析，subprocess 间天然隔离
- `default` pipeline 的 `FACTOR_IC_DATA` 是 symlink → 主数据源，不占额外存储
- 与方案 A 的唯一差异：路径前缀是 `PROJECT_ROOT / "<module>" / "result" / PIPELINE_ALIAS`，而非 `PIPELINE_DIR / "<module>" / "result"`

### 4.2 pipeline_context.py（NEW）

```python
# pipeline_context.py
"""Pipeline 上下文管理：读取配置、解析别名、提供查询接口"""

import os
from datetime import timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent


def get_pipeline_alias() -> str:
    """获取当前 pipeline 别名（环境变量）"""
    return os.environ.get("PIPELINE_ALIAS", "default")


def load_pipeline_config() -> dict:
    """加载 pipelines.yaml"""
    import yaml

    config_path = PROJECT_ROOT / "pipelines" / "pipelines.yaml"
    if not config_path.exists():
        return {"default": {"filter": None, "description": "全量数据（无配置文件）"}}
    with open(config_path) as f:
        return yaml.safe_load(f)


def resolve_filter(filter_expr: str | None) -> str | None:
    """解析 filter 表达式中的动态占位符"""
    if filter_expr is None:
        return None
    import pandas as pd

    master = PROJECT_ROOT / "data_fetchers" / "result" / "factor_ic_data.parquet"
    dates = pd.read_parquet(master, columns=["date"])["date"]
    latest_date = pd.to_datetime(dates).max()

    replacements = {
        "{latest_date}": latest_date.strftime("%Y-%m-%d"),
        "{latest_date_minus_30}": (latest_date - timedelta(days=30)).strftime("%Y-%m-%d"),
        "{latest_date_minus_60}": (latest_date - timedelta(days=60)).strftime("%Y-%m-%d"),
    }
    result = filter_expr
    for placeholder, value in replacements.items():
        result = result.replace(placeholder, value)
    return result
```

### 4.3 pipeline_data_slicer.py（NEW）

```python
# pipeline_data_slicer.py
"""Stage 1.5: 为每个 pipeline 切割数据子集

读取主数据源 → 按 pipelines.yaml 的 filter 切割 → 写入 data_fetchers/result/<alias>/
- filter=null: 创建 symlink（不复制）
- filter=表达式: pandas query 后写新 parquet
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd

from pipeline_context import load_pipeline_config, resolve_filter


def slice_pipeline(alias: str, filter_expr: str | None, source: Path, output: Path):
    """为单个 pipeline 切割数据"""
    output.parent.mkdir(parents=True, exist_ok=True)

    if filter_expr is None:
        # 无过滤：symlink 到主数据源
        if output.is_symlink() or output.exists():
            output.unlink()
        output.symlink_to(source)
        print(f"  [{alias}] symlink -> {source}")
    else:
        # 有过滤：query 后写新文件
        resolved = resolve_filter(filter_expr)
        df = pd.read_parquet(source)
        before = len(df)
        df = df.query(resolved)
        after = len(df)
        df.to_parquet(output, index=False)
        print(f"  [{alias}] filter='{resolved}' | {before} -> {after} rows -> {output}")


def main():
    config = load_pipeline_config()
    source = PROJECT_ROOT / "data_fetchers" / "result" / "factor_ic_data.parquet"

    if not source.exists():
        print(f"[ERROR] 主数据源不存在: {source}")
        sys.exit(1)

    print("=== Pipeline Data Slicer ===")
    print(f"主数据源: {source}")

    for alias, pipeline_cfg in config.items():
        filter_expr = pipeline_cfg.get("filter")
        output = source.parent / alias / "factor_ic_data.parquet"
        slice_pipeline(alias, filter_expr, source, output)

    print(f"\n完成: {len(config)} 个 pipeline 数据已就绪")


if __name__ == "__main__":
    main()
```

### 4.4 logger_config.py 改造（每个模块）

**方案 B 优势**：不引入跨模块依赖，只需追加 alias 子目录。

```python
# factor_ic/common/logger_config.py（改造前）
def get_logger(name: str, log_dir: Path | None = None) -> logging.Logger:
    ...
    if log_dir is None:
        log_dir = Path(__file__).parent.parent / "logs"    # ← 硬编码模块路径
    ...

# 改造后（方案 B：自包含，不依赖 paths.py）
import os

def get_logger(name: str, log_dir: Path | None = None) -> logging.Logger:
    ...
    if log_dir is None:
        alias = os.environ.get("PIPELINE_ALIAS", "default")
        log_dir = Path(__file__).parent.parent / "logs" / alias    # ← 追加 alias 子目录
    ...
```

6 个模块各改 1-2 行（factor_ic / backtest / comprehensive_factor / stock_selector / summary / reverse_discovery）。

### 4.5 data_loader.py 改造

**factor_ic/common/data_loader.py**：

```python
# 改造前
DEFAULT_DATA_DIR = Path(__file__).parent.parent.parent / "data_fetchers" / "result"
DEFAULT_DATA_CACHE = DEFAULT_DATA_DIR / "factor_ic_data.parquet"

# 改造后
from paths import FACTOR_IC_DATA
DEFAULT_DATA_CACHE = FACTOR_IC_DATA
```

**backtest/common/data_loader.py**：

```python
# 改造前
DEFAULT_DATA_SOURCE = Path(__file__).parent.parent.parent / "data_fetchers" / "result" / "factor_ic_data.parquet"

# 改造后
from paths import FACTOR_IC_DATA
DEFAULT_DATA_SOURCE = FACTOR_IC_DATA
```

### 4.6 ic_result_builder.py

```python
# factor_ic/common/ic_result_builder.py
# 当前代码已从 paths 导入，无需改动：
def get_ic_output_path(factor_name, return_period):
    from paths import FACTOR_IC_RESULT
    return FACTOR_IC_RESULT / f"ic_{factor_name}_{return_period}_analysis_result.json"
```

**实际检查**：IC 结果输出路径已经从 `paths.py` 导入，不需要改。composite_runner 和 backtest 同理。

---

## 5. run_pipeline.py 改造

### 5.1 新增 Stage 1.5

```python
# 在 PIPELINE_SCRIPTS 列表中，Stage 1 之后插入：
ScriptTask("pipeline_data_slicer", "pipeline_data_slicer.py", 1.5, []),
```

### 5.2 多 Pipeline 编排

```python
# run_pipeline.py 新增逻辑

def run_pipeline_for_alias(alias: str, stages: list[int], parallel: int = 1):
    """运行单个 pipeline 的 Stage 2-7"""
    env = os.environ.copy()
    env["PIPELINE_ALIAS"] = alias

    # 筛选该 pipeline 需要执行的脚本（Stage 2-7）
    pipeline_scripts = [s for s in PIPELINE_SCRIPTS if s.stage >= 2 and s.stage in stages]

    for task in pipeline_scripts:
        success = run_script(task, env=env, parallel=parallel)
        if not success:
            return False
    return True


def main():
    # ... 参数解析 ...

    # Stage 0-1: 共享（只跑一次）
    shared_scripts = [s for s in PIPELINE_SCRIPTS if s.stage < 2]
    for task in shared_scripts:
        run_script(task)

    # Stage 1.5: 数据切割（只跑一次）
    run_script(ScriptTask("pipeline_data_slicer", "pipeline_data_slicer.py", 1.5, []))

    # Stage 2-7: 每个 pipeline 独立运行
    config = load_pipeline_config()
    for alias in config:
        print(f"\n{'='*60}")
        print(f"Pipeline: {alias}")
        print(f"{'='*60}")
        run_pipeline_for_alias(alias, stages=range(2, 8), parallel=parallel)
```

### 5.3 CLI 参数

```bash
# 运行所有 pipeline
python run_pipeline.py

# 只运行指定 pipeline（跳过 Stage 0-1）
python run_pipeline.py --pipeline ob_pool --start-stage 2

# 运行多个指定 pipeline
python run_pipeline.py --pipelines default,ob_pool

# 只跑到 IC 阶段（调试用）
python run_pipeline.py --pipeline ob_pool --end-stage 2
```

---

## 6. 数据流

```
                    ┌─────────────────────────────────┐
                    │       Stage 0-1 (共享)            │
                    │  fetch_data → factor_generator   │
                    │  → factor_ic_data.parquet        │
                    └──────────────┬──────────────────┘
                                   │
                    ┌──────────────▼──────────────────┐
                    │     Stage 1.5: Data Slicer       │
                    │  按 pipelines.yaml 切割数据       │
                    └───┬────────────────┬────────────┘
                        │                │
            ┌───────────▼──┐    ┌───────▼──────────┐
            │  data_fetchers/  │    │  data_fetchers/   │
            │  result/default/ │    │  result/ob_pool/  │
            │  (symlink)       │    │  (filtered parquet)│
            └──────┬───────┘    └──────┬────────────┘
                   │                   │
     ┌─────────────┼───────────┐      │
     │  Stage 2-7 (各 pipeline 独立)  │
     │             │           │      │
     ▼             ▼           ▼      ▼
  factor_ic/   backtest/   comp_    factor_ic/  backtest/  ...
  result/      result/     factor/  result/     result/
  default/     default/    default/ ob_pool/    ob_pool/
  logs/        logs/       logs/    logs/       logs/
  default/     default/    default/ ob_pool/    ob_pool/
```

---

## 7. 影响范围

### 7.1 新增文件（3 个）

| 文件 | 行数（估） | 说明 |
|------|-----------|------|
| `pipeline_context.py` | ~50 | 别名管理、配置加载、filter 解析 |
| `pipeline_data_slicer.py` | ~60 | Stage 1.5 数据切割脚本 |
| `pipelines/pipelines.yaml` | ~20 | Pipeline 配置 |

### 7.2 改动文件（~10 个）

| 文件 | 改动量 | 说明 |
|------|--------|------|
| `paths.py` | 重写 ~30 行 | 路径常量加 alias 层 |
| `run_pipeline.py` | 新增 ~40 行 | 多 pipeline 编排 + CLI 参数 |
| `factor_ic/common/data_loader.py` | 2 行 | DEFAULT_DATA_CACHE 从 paths 导入 |
| `factor_ic/common/logger_config.py` | 1 行 | log_dir 追加 alias 子目录 |
| `backtest/common/data_loader.py` | 2 行 | 同 factor_ic |
| `backtest/common/logger_config.py` | 1 行 | 同 |
| `comprehensive_factor/common/logger_config.py` | 1 行 | 同 |
| `stock_selector/common/logger_config.py` | 1 行 | 同 |
| `summary/.../logger_config.py` | 1 行 | 同 |
| `reverse_discovery/common/logger_config.py` | 1 行 | 同 |

### 7.3 不需要改动的文件

| 文件 | 原因 |
|------|------|
| `factor_ic/ic_*.py`（33 个 IC 脚本） | 通过 `run_factor_ic()` 调用公共模块，路径自动从 paths 解析 |
| `backtest/layered_backtest_*.py`（33 个） | 同上 |
| `comprehensive_factor/composite_*.py`（4 个） | composite_runner 已从 paths 导入路径 |
| `stock_selector/stock_selector.py` | 已从 paths 导入路径 |
| `summary/generate_factor_summary_report.py` | 已从 paths 导入路径 |
| `data_fetchers/` 全部 | 共享区，不随 pipeline 变化 |

### 7.4 IC/backtest 脚本为什么不需要改？

IC 脚本的调用链：
```
ic_amplitude_1d.py
  → run_factor_ic(spec=SPEC)           # factor_ic_runner.py
    → run_factor_ic_analysis(...)       # factor_ic_runner.py
      → load_factor_return_data(data_cache_path=None)  # data_loader.py
        → DEFAULT_DATA_CACHE            # 改后 = paths.FACTOR_IC_DATA (pipeline 感知)
      → get_ic_output_path(...)         # ic_result_builder.py
        → paths.FACTOR_IC_RESULT        # pipeline 感知
```

路径在公共模块层解析，脚本只传 `None` 用默认值。改了 `paths.py` 和 `data_loader.py`，全链路自动 pipeline 感知。

---

## 8. 实施计划

### Phase 1: 基础设施（3 文件，~130 行）

| 任务 | 文件 | 验证 |
|------|------|------|
| 创建 `pipelines/pipelines.yaml` | 配置文件 | `cat pipelines/pipelines.yaml` |
| 创建 `pipeline_context.py` | 上下文管理 | `python -c "from pipeline_context import get_pipeline_alias; print(get_pipeline_alias())"` |
| 创建 `pipeline_data_slicer.py` | 数据切割 | `python pipeline_data_slicer.py` → 检查 `data_fetchers/result/default/` 和 `data_fetchers/result/ob_pool/` |

### Phase 2: paths.py 改造（1 文件，~30 行）

| 任务 | 验证 |
|------|------|
| 重写 `paths.py` 路径常量 | `PIPELINE_ALIAS=default python -c "from paths import FACTOR_IC_RESULT; print(FACTOR_IC_RESULT)"` |
| | `PIPELINE_ALIAS=ob_pool python -c "from paths import FACTOR_IC_RESULT; print(FACTOR_IC_RESULT)"` |

### Phase 3: 公共模块适配（~8 文件，各 1-2 行）

| 任务 | 验证 |
|------|------|
| `factor_ic/common/data_loader.py` 改默认路径 | `PIPELINE_ALIAS=ob_pool python -c "from factor_ic.common.data_loader import DEFAULT_DATA_CACHE; print(DEFAULT_DATA_CACHE)"` |
| 6 个 `logger_config.py` 改 log_dir | `PIPELINE_ALIAS=ob_pool python -c "from factor_ic.common.logger_config import get_logger; l=get_logger('test')"` → 检查日志写入 `factor_ic/logs/ob_pool/` |
| `backtest/common/data_loader.py` 改默认路径 | 同上 |

### Phase 4: run_pipeline.py 改造（1 文件，~40 行）

| 任务 | 验证 |
|------|------|
| 新增 Stage 1.5 | `python run_pipeline.py --start-stage 1.5 --end-stage 1.5` |
| 多 pipeline 编排 | `python run_pipeline.py --pipeline ob_pool --start-stage 2 --end-stage 2` |
| CLI 参数 | `python run_pipeline.py --help` |

### Phase 5: 数据迁移 + 全量验证

| 任务 | 说明 |
|------|------|
| 迁移现有产出物 | 将 `factor_ic/result/*` → `factor_ic/result/default/`，其他模块同理 |
| 运行 default pipeline 全量 | `python run_pipeline.py --pipeline default --start-stage 2` → 确认产出与现有结果一致 |
| 运行 ob_pool pipeline | `python run_pipeline.py --pipeline ob_pool --start-stage 2` → 确认产出在 `factor_ic/result/ob_pool/` 下 |
| ruff + pytest | 确保代码质量和测试通过 |

---

## 9. 风险与注意事项

### 9.1 向后兼容

| 风险 | 应对 |
|------|------|
| 现有 cron 定时任务未设 `PIPELINE_ALIAS` | 默认 `default`，行为与当前一致 |
| 现有测试用例硬编码路径 | 需排查并改为通过 `paths.py` 导入 |
| `data_fetchers/common/paths.py` 独立 | 不改动，数据拉取层不感知 pipeline |

### 9.2 存储与性能

| 项目 | 估计 |
|------|------|
| default pipeline 数据 | symlink，0 额外存储 |
| ob_pool pipeline 数据 | RSI>70 约占 13% 行，~20MB parquet |
| 磁盘增长 | 每个 pipeline ~50-100MB（数据 + IC/backtest JSON + 日志） |
| 切割耗时 | pandas query 全量 ~150 万行，<10 秒 |

### 9.3 内存

| 场景 | 内存占用 |
|------|---------|
| pipeline_data_slicer | ~2GB（读全量 parquet + query + write） |
| 单 pipeline IC 脚本 | 与当前一致（读子集，反而更省） |
| 多 pipeline 并行 | 当前不支持（串行执行），未来可扩展 |

### 9.4 data_loader.py 的硬编码路径问题

当前 `factor_ic/common/data_loader.py` 和 `backtest/common/data_loader.py` 各自硬编码了数据源路径，绕过了 `paths.py`。这违反了项目规范（规则 #11：路径必须从 paths.py 导入）。本次改造一并修复。

### 9.5 现有产出物迁移

现有 `factor_ic/result/`、`backtest/result/` 等目录下的文件需要迁移到 `factor_ic/result/default/` 下。可以通过：

```bash
# 迁移脚本（Phase 5 执行）
mkdir -p factor_ic/result/default
mv factor_ic/result/*.json factor_ic/result/default/   # IC JSON 文件
mkdir -p factor_ic/logs/default
mv factor_ic/logs/*.log factor_ic/logs/default/
# ... 其他模块同理
```

迁移后旧路径下只有 `<alias>/` 子目录，结构干净。

### 9.6 logger_config.py 改造方式（方案 B 特有）

方案 B 下 logger_config.py 不需要 `from paths import`，只需读取环境变量追加 alias 子目录：

```python
import os
alias = os.environ.get("PIPELINE_ALIAS", "default")
log_dir = Path(__file__).parent.parent / "logs" / alias
```

这是方案 B 相比方案 A 的一个优势：模块的 logger_config.py 保持自包含，不引入对根级 paths.py 的依赖。与 AGENTS.md 规则 #1（模块边界：只能复用自己目录的 common/）一致。

---

## 10. 不做的事情

| 不做 | 原因 |
|------|------|
| 修改 IC/backtest/composite 脚本的业务逻辑 | 管线方法论不变，只变输入数据集 |
| 新增因子定义 | 超买池用的因子与全市场相同 |
| 修改 factor_generator | 数据整合层共享 |
| 修改 stock_selector 的选股逻辑 | 选股逻辑不变，只是输入的 composite 数据来自不同 pipeline |
| 修改 summary 报告逻辑 | 报告逻辑不变，只是读取的路径不同 |
| 多 pipeline 并行执行 | 当前串行，未来可扩展（加进程池） |
| 跨 pipeline 对比报告 | 当前各 pipeline 独立产出报告，对比功能未来再加 |
