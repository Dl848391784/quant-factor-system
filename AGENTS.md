# 项目：因子 IC 分析系统

> Python 量化因子分析项目。本文件是 agent 每次对话都会自动加载的"必备知识"，只放硬约束。
> 详细规范见 `PROJECT.md`（按需主动读取）。模块特定规范见 `<模块>/MODULE.md`。

---

## 1. 跨模块数据路径（不可违反）

| 模块 | 输出目录 | 输出文件 | 下游读取 |
|------|---------|---------|---------|
| data_fetchers/fetch_factor_cache | `data_fetchers/result/` | `factor_data.json.gz` | factor_generator |
| data_fetchers/fetch_turnover | `data_fetchers/result/` | `turnover_rate_data.json.gz` | factor_generator |
| data_fetchers/factor_generator | `data_fetchers/result/` | `factor_ic_data.json.gz` | factor_ic, backtest, comprehensive_factor, summary |
| factor_ic | `factor_ic/result/` | `ic_<因子>_<周期>_analysis_result.json` | comprehensive_factor, summary |
| backtest | `backtest/result/` | `<因子>_layered_backtest.json` | summary |
| comprehensive_factor | `comprehensive_factor/result/` | `composite_<加权>_1d.json` | summary |
| summary | `summary/result/` | `factor_summary_report_YYYY-MM-DD.txt` | — |

**统一数据源**：`factor_ic_data.json.gz` 包含行情 + 基础因子 + 扩展因子 + 收益数据（`forward_return_1d/3d/5d`）。所有下游模块**只能**从此文件读取，禁止从 `return_data.json.gz` 读收益数据（仅备份）。

---

## 2. 硬规则（违反即拒收）

1. **模块边界**：模块只能复用自己目录下的 `common/`，禁止跨模块 import 别的模块的 `common/`。如需复用，复制代码到本模块。
2. **输出位置**：所有结果必须输出到 `<模块>/result/`。禁止输出到临时目录、脚本同级目录、根目录。
3. **临时文件**：实验/调试/一次性脚本必须放 `temporary/`。禁止在模块目录或根目录散落临时文件。
4. **字段非空**：输出字段为 `None` 必须显式设置 + 记录原因（`logger.warning(...)`）。禁止隐式 `None`（计算错误导致字段未被赋值）。
5. **因子方向**：根据实际 IC 结果确定，不能根据因子类型预判。`factor_direction = 'negative' if ic_mean < 0 else 'positive'`。
6. **退出码**：脚本统一使用 `0=成功 / 1=失败`。详细错误走 `logger`，禁止用退出码编码错误类型。
7. **测试位置**：测试代码必须是 `<模块>/test_cases/test_<脚本名>.py`，pytest 可执行。**禁止在 `__main__` 块写测试代码**。
8. **配套文件**：新增脚本时同步新建 `docs/<脚本名>_flow.md` + `test_cases/test_<脚本名>.py`。

---

## 3. 已知陷阱（历史 bug，重点防御）

### 陷阱 1：路径迁移未同步（2026-05-26）
修改任何模块的输出路径前，**必须**：
- 先验证新文件实际包含哪些列（`gunzip -c xxx.json.gz | python -c "import json,sys; print(list(json.load(sys.stdin)['data'][0].keys()))"`）
- 同步更新所有依赖模块的 `data_loader.py`（或读取代码）
- 同步更新 `PROJECT.md` 跨模块路径表
- 同步更新依赖模块的 `MODULE.md`
- 改完跑一遍依赖模块的测试

### 陷阱 2：冗余的"向后兼容"假设（2026-05-26）
路径迁移时**禁止做"某些列还在旧目录"的假设**。错误案例：`factor_data_extended.json.gz` 已包含 `turnover_rate`，但保留了 `additional_factor_files` 的冗余读取逻辑——根因是没先验证数据结构就动手。

### 陷阱 3：跨规范层级写错位置
- 项目级规范（跨模块通用）→ `PROJECT.md`
- 模块级规范（单模块）→ `<模块>/MODULE.md`
- 流程级规范（单脚本）→ `<模块>/docs/<脚本名>_flow.md`

写错层级 = 重复定义 / 遗漏更新。

---

## 4. 任务前必做

- [ ] 读 `PROJECT.md`（首次接触项目时）
- [ ] 读对应 `<模块>/MODULE.md`
- [ ] 涉及 2 个以上文件的改动 → 先输出 design.md（要改哪些文件、改哪些接口、加哪些测试），等审核通过再动手
- [ ] 涉及路径变更 → 走"陷阱 1"的完整流程

---

## 5. 任务后必做

- [ ] 跑测试：`pytest <模块>/test_cases/ -v`
- [ ] 同步更新流程文档（如有流程变更）和时间标注（生成时间、版本号、更新内容）
- [ ] 同步更新规范文档（如有规范变更）：项目级改 `PROJECT.md`，模块级改 `MODULE.md`
- [ ] 提交模板：列出改了哪些文件 + 引用了规范的哪几条 + 跑了哪些测试（粘贴输出）

---

## 6. 代码风格 / 日志

由 `pyproject.toml` 中的 ruff + mypy 强制执行。**本文件不重复**这些机器能管的规则。
日志使用 Python 标准库 `logging`，配置见 `common/logging_setup.py`（统一格式、文件路径、级别）。

异常处理两条铁律：
- 异常链必须 `raise ... from e`，不能丢弃原始异常
- 捕获后必须 `logger.exception(...)`，不能只 `logger.error(str(e))`

---

## 7. 何时回头读 PROJECT.md

下列场景必须主动读 `PROJECT.md`：
- 新增模块 / 新增脚本类型
- 修改跨模块数据契约（路径、文件名、字段）
- 不确定规范应该写在哪一层
- 用户提到"为什么这样设计"——背景在 PROJECT.md

