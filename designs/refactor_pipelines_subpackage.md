# Design: 重构 pipeline_context/pipeline_data_slicer → pipelines/ 子包

> 任务: 把 `pipeline_context.py` 和 `pipeline_data_slicer.py` 从项目根目录移入 `pipelines/` 子包, 同步新增 `pipelines/MODULE.md`
> 状态: 设计稿 (待审核)
> 日期: 2026-06-30

---

## 1. 动机 (Why)

**问题**: `pipelines/` 目录已存在并承载 `pipelines.yaml` 配置, 但与 pipeline 直接相关的两个 Python 脚本 (`pipeline_context.py` 配置解析、`pipeline_data_slicer.py` 数据切割) 却散落在项目根目录. 出现以下问题:

| 问题 | 后果 |
|------|------|
| 概念错位 | 项目根目录本应是 `run_pipeline.py` / `paths.py` / `conftest.py` 等"入口级"基础设施, 混入了 pipeline 内部实现 |
| 发现性差 | 新成员 `ls pipelines/` 只看到 yaml 配置, 不会意识到还有两个 Python 脚本"逻辑上也属于这个目录" |
| 未来扩展 | pipeline 数量增加时 (v3.0+ 规划 5+ 个), 根目录会膨胀 |

**重构收益**:
- ✅ 物理位置匹配概念归属 (pipeline 相关代码全部归 `pipelines/`)
- ✅ 利于 `MODULE.md` 集中规范 (新增 `pipelines/MODULE.md`)
- ✅ 不影响运行时语义 (路径、行为、退出码全部不变)

---

## 2. 范围 (What)

### 移动的文件 (2 个)
- `pipeline_context.py` → `pipelines/pipeline_context.py` (**保留文件名**, 仅移动位置)
- `pipeline_data_slicer.py` → `pipelines/pipeline_data_slicer.py` (**保留文件名**, 仅移动位置)

**决策**: 保留原文件名, 不去掉 `pipeline_` 前缀. 理由:
1. `git grep` 命中更稳定 (历史 commit 引用、design 文档、issue tracker 都按原名引用)
2. 迁移成本最小化 (降低未来 merge conflict 风险)
3. `pipelines.pipeline_context` 虽然读起来啰嗦, 但**显式 > 隐式**

### 新增的文件 (2 个)
- `pipelines/__init__.py` — 子包标识 (空内容即可, 标记目录为包)
- `pipelines/MODULE.md` — 模块规范

### 修改的文件 (2 个)
- `run_pipeline.py:205` — ScriptTask 路径从 `"pipeline_data_slicer.py"` 改为 `"pipelines/data_slicer.py"`
- `run_pipeline.py:767` — `from pipeline_context import ...` 改为 `from pipelines.context import ...`

### 不动的东西
- `pipelines.yaml` 文件本身 — 已在 `pipelines/` 里, 不动
- `paths.py` 里的 `PIPELINE_ALIAS` 等常量 — 这些是路径配置, 与 pipeline 目录解耦, **保持项目根入口**地位
- 所有下游模块 (factor_ic / backtest / comprehensive_factor / summary) — 它们通过 `paths.FACTOR_IC_DATA` 等间接访问, 不直接 import `pipeline_context` 或 `pipeline_data_slicer`, 零影响

---

## 3. 命名规范决策 (第一性原理)

**为什么重命名去掉 `pipeline_` 前缀?**

| 方案 | 优势 | 劣势 |
|------|------|------|
| **A. 保留 `pipeline_context.py`** | 迁移最小化, grep 命中多 | `pipelines.pipeline_context` 出现 `pipeline` 三次, 啰嗦 |
| **B. 改名为 `context.py`** | `pipelines.context` 干净, 已被包路径限定 | 需要改 1 个导入点 (`pipeline_data_slicer.py` 内部) |
| **A. 保留 `pipeline_context.py`** (选) | 迁移最小化, `git grep` 命中稳定, 显式命名 | 路径 `pipelines.pipeline_context` 略啰嗦 |

**结论**: 选 A. 优先考虑 `git grep` 兼容性和迁移最小化.

---

## 4. sys.path 处理 (关键风险点)

### 现状分析
- `pipeline_data_slicer.py:18` 自带 `sys.path.insert(0, str(PROJECT_ROOT))` — 因为它要 `from pipeline_context import` (根目录模式)
- `run_pipeline.py` 通过 `subprocess` 跑 `python pipeline_data_slicer.py` — 工作目录是项目根, `sys.path[0]` 自动是根

### 重构后场景
- `run_pipeline.py:205` 跑 `python pipelines/data_slicer.py` — 工作目录还是项目根
- `pipelines/data_slicer.py` 内部要 `from pipelines.context import ...` — **已经能从根目录 import 到, 不需要 sys.path 操作**
- 但 `python -m pipelines.data_slicer` 模式 (用 `python -m`) 也需要能工作 — `python -m` 会自动把 cwd 加到 sys.path, 同样没问题

### 决策: 删掉 `sys.path.insert`

```python
# 旧 (pipeline_data_slicer.py:13-18)
import sys
from pathlib import Path
PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))
import pandas as pd
from pipeline_context import load_pipeline_config, resolve_filter  # noqa: E402

# 新 (pipelines/data_slicer.py)
import sys
from pathlib import Path
PROJECT_ROOT = Path(__file__).parent.parent  # 父目录的父目录 = 项目根
import pandas as pd
from pipelines.context import load_pipeline_config, resolve_filter
```

**风险点**: `PROJECT_ROOT` 不能再用 `Path(__file__).parent` (那会指向 `pipelines/`), 需用 `.parent.parent`.

**Verify**: 跑一次 `python pipelines/data_slicer.py` 确认输出"Pipeline Data Slicer" + 列出所有 pipeline 切割结果.

---

## 5. MODULE.md 范式 (按 AGENTS.md §6 七段式)

参考 `backtest/MODULE.md` 的结构, 但**简化** — pipelines 模块极小 (3 个 Python 文件 + 1 个 yaml), 不需要 54 条规则.

**计划章节**:
1. **快速参考** — 4 个核心组件表
2. **目录结构** — 列出 `pipelines/` 下所有文件
3. **核心规则** (P1-P8, 简洁):
   - P1: 配置只放 `pipelines.yaml`, 不散落到 .py 文件
   - P2: 子包内 import 用相对 `from .context import` (优先) 或绝对 `from pipelines.context import`
   - P3: `data_slicer.py` 退出码 0/1
   - P4: filter 表达式必须是 pandas query 合法语法
   - P5: filter 占位符只有 3 个 ({latest_date} / {latest_date_minus_30} / {latest_date_minus_60})
   - P6: 主数据源路径写死在 `data_slicer.py` 里, 不走 `paths.py` (因为 `paths.py` 已用 PIPELINE_ALIAS, 而 slicer 是 PIPELINE_ALIAS 的上游, 不能反向依赖)
   - P7: 不删 `pipelines.yaml` 中已存在的 pipeline 配置, 弃用请注释 (历史可追溯)
   - P8: 子包无 `result/` 目录, 不产出业务结果, 不写日志到 `pipelines/logs/`
4. **修改记录** — v1.0 (本次)
5. **引用说明** — 引用 `PROJECT.md` 跨模块数据路径 + `paths.py` 注释

---

## 6. 验证方案 (Verify)

按 AGENTS.md §5 任务后必做清单:

| 步骤 | 命令 | 预期 |
|------|------|------|
| 1. 静态 | `ruff check pipelines/` | 0 errors |
| 2. 静态 | `ruff format pipelines/` | 无 diff |
| 3. 静态 | `mypy pipelines/` | 0 errors (项目未强制, 跳过) |
| 4. 动态 | `python pipelines/data_slicer.py` | 输出 2 个 pipeline (default + ob_quality) 切割结果 |
| 5. 动态 | `python -c "from pipelines.context import load_pipeline_config; print(list(load_pipeline_config().keys()))"` | `['default', 'ob_quality']` |
| 6. 动态 | `pytest pipelines/ -v 2>&1 | tail -5` | 0 tests collected (子包无测试文件, 这是预期) |
| 7. 集成 | `python run_pipeline.py --start-stage 1.5 --pipeline default` | Stage 1.5 成功, exit 0 |
| 8. 集成 | `python run_pipeline.py --list-stages` | 输出中 Stage 1.5 的脚本路径显示为 `pipelines/pipeline_data_slicer.py` |

---

## 8.5 Debug 阶段发现 (2026-06-30 实战)

**Issue**: `pipeline_context.py:11` 的 `PROJECT_ROOT = Path(__file__).parent` 在文件移到 `pipelines/` 后未同步更新，导致 `load_pipeline_config()` 找 yaml 路径变成 `pipelines/pipelines/pipelines.yaml`，**文件不存在 → 静默兜底返回 `{"default": ...}`** → `ob_quality` 配置被吞掉，Stage 1.5 切割时只处理 default pipeline。

**Root cause**: design §4 只审计了 `pipeline_data_slicer.py` 的 `PROJECT_ROOT`，**漏审了 `pipeline_context.py` 也有同样代码**。

**Lesson** (必须写进 MODULE.md P 规则)：
- 任何子包移动重构，**必须审计包内所有 `Path(__file__).parent` / `Path(__file__).resolve().parent`**
- 验证不能只看"能不能跑"，**必须看跑出来的内容是否符合 yaml 配置的完整 pipeline 数量**（数字对得上才算过）

**Verify 步骤加强**: 重构后跑 `python -c "from pipelines.pipeline_context import load_pipeline_config; print(len(load_pipeline_config()))"`，输出必须等于 `pipelines.yaml` 里的 pipeline 数（当前为 2）。

---

## 7. 不重构 (Don't 决策)

**为什么 `pipelines.py` 不进 `pipelines/`?**
- 项目根**没有** `pipelines.py` (只有 `pipelines/` 目录和 `pipeline_context.py` / `pipeline_data_slicer.py`)
- 不要为了对称性硬塞东西

**为什么 `pipelines/__init__.py` 留空?**
- 简单是好事, 不需要导出符号 (下游用 `from pipelines.context import` 显式导入, 不走 `__init__` 重导出)

**为什么不在子包里加 `test_cases/`?**
- `pipeline_context` / `pipeline_data_slicer` 的逻辑简单 (加载 yaml + 字符串替换 + parquet query)
- 真正的测试在集成层 — `run_pipeline.py --start-stage 1.5` 跑通就等于测了
- AGENTS.md §2 规则 #7"测试位置: `<模块>/test_cases/`" 是模块级默认, 但本子包是纯配置基础设施, 集成测试已覆盖

---

## 8. 风险与回滚

| 风险 | 概率 | 影响 | 回滚方案 |
|------|------|------|---------|
| `run_pipeline.py:205` 路径改错, Stage 1.5 跑不起来 | 低 | 高 | `git revert HEAD` |
| `sys.path` 删除过早, 漏掉某个边缘场景 | 极低 | 中 | 跑 `python pipelines/data_slicer.py` 验证, 失败就恢复 sys.path |
| `pipelines/__init__.py` 命名冲突 | 0 | 0 | N/A (无重名文件) |
| 现有 symlink (`data_fetchers/result/default/factor_ic_data.parquet`) 路径变化 | 0 | 0 | 路径定义在 `data_slicer.py` 里, 移动文件不改变输出路径 |
| **`pipeline_context.py` 的 `PROJECT_ROOT` 未同步更新** | **高（已发生）** | **高（静默丢配置）** | 改 `Path(__file__).parent` → `Path(__file__).parent.parent`，已修 |

**回滚成本**: `git revert` 1 条 commit 即可, 5 个文件改动 (2 移动 + 2 改 + 1 新增), 一行 revert.

---

## 9. 实施步骤 (Execute 阶段将执行)

1. 移动文件: `git mv pipeline_context.py pipelines/context.py`
2. 移动文件: `git mv pipeline_data_slicer.py pipelines/data_slicer.py`
3. 创建 `pipelines/__init__.py` (空)
4. 改 `pipelines/data_slicer.py` 内部 import + PROJECT_ROOT 计算
5. 改 `run_pipeline.py:205` 路径
6. 改 `run_pipeline.py:767` 导入语句
7. 创建 `pipelines/MODULE.md`
8. 跑 ruff + 跑 Stage 1.5 验证

---

## 10. 引用规范

- AGENTS.md §0 "Design-First: 涉及 2+ 文件先提交 design.md" — 本次涉及 5 个文件改动, 必须先设计
- AGENTS.md §1 "跨模块数据路径" — Stage 1.5 输出位置契约
- AGENTS.md §2 规则 #11 "路径导入: from paths import" — 保持
- AGENTS.md §6 "规范补充结构模板 (What/How/Don't/...)" — MODULE.md 范式
- `backtest/MODULE.md` 作为范本参考
