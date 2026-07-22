---
name: factor-development
description: 规范化的因子开发全流程（新增因子、IC、分层回测、composite 权重、选股）。
version: 1.0
---

# factor-development

> 覆盖因子开发全流程的触发识别 + 方法论要点。本 skill 自包含（正文即要点），不依赖外部 reference 文件。
> 完整规范以 PROJECT.md「因子开发规范」+ 各模块 MODULE.md 为准。

## 1. 触发识别表

| 用户场景关键词 | 主题 | 要点 |
|---|---|---|
| 新增因子 / factor_generator | §1 因子设计 | 按"新增因子必改位置"6 处全改；重跑 factor_generator 更新 parquet |
| IC 脚本 / IC 显著性 / ICIR / 中性化 | §2 IC 分析 | 无效判定 5 阈值见 MODULE.md M12；中性化用市值/行业 OLS |
| 分层回测 / layered_backtest / look-ahead | §3 回测+分段胜率 | 薄声明架构(factor_name=ClassVar)；look-ahead 只用 T-1 数据算 T 推荐 |
| composite / 综合因子 | §4 综合因子 | composite_runner 公共入口；方向由 ic_mean 定(H5) |
| 权重选择 / weight_engine / weight-cap | §5 权重+阈值 | 单因子权重上限 25%(M30a)；除零回退等权(M30) |
| stock_selector / 选股 / 涨跌停 / untradeable | §6 选股+不可交易 | 涨停=买不进排除，跌停=可买不排除；untradeable 全链过滤 |
| pipeline / run_pipeline / summary | §7 Pipeline+Summary | 加载 `/factor-summary-reporting` skill |
| 方向翻转 / 反转 | §8 方向验证 | 方向由实测 IC 定，禁硬编码(H5)；反向因子取反对齐正向(M56) |
| 命名 / factor_name / 列名映射 | §9 命名 | FACTOR_NAME_TO_COL_MAP 双处同步(factor_selector + weight_engine) |
| OOM / memory / 大文件 | §12 OOM | 流式加载(load_factor_values)；禁 json.load 全量(OOM exit 137) |
| 第一性原理 / 叙事标签 | §13 原理 | 禁贴叙事标签；方案从基本原理推导(CLAUDE.md §1.5 / PROJECT.md §第一性原理) |

## 2. 新增因子必改位置（按顺序）
1. `data_fetchers/factor_generator.py::_EXTENDED_FACTOR_COLS`
2. `data_fetchers/factor_generator.py` 因子计算函数（结果存 `factor_ic_data.parquet`）
3. `comprehensive_factor/common/factor_selector.py::FACTOR_NAME_TO_COL_MAP`（筛选层）
4. `comprehensive_factor/common/weight_engine.py::FACTOR_NAME_TO_COL_MAP`（权重层）
5. `factor_definitions.py::FACTOR_DEFINITIONS`
6. `PROJECT.md` 因子列表章节

**关键依赖**：改完必须重跑 `factor_generator.py` 更新 `factor_ic_data.parquet`，否则下游读不到新因子。

## 3. 工作流（Plan -> Execute -> Review -> Debug）
- **Plan**：读 PROJECT.md + 对应 MODULE.md；查触发表路由
- **Execute**：改因子脚本先看 `factor_ic/ic_*.py` 标准结构；每步 ruff + pytest
- **Review**：`ruff check --fix . && ruff format . && ruff check . && pytest`；commit 引用规范行号
- **Debug**：找根因(reproduce -> hypothesis -> test -> fix)，**禁调参数式修复**(CLAUDE.md §1.5)

## 4. 验证清单
- [ ] ruff check --fix . / ruff format . / ruff check . 通过
- [ ] pytest 通过
- [ ] JSON Schema 校验输出（如适用）
- [ ] commit message 引用 PROJECT.md 规范行号

## 5. 不要做的事
- ❌ 硬编码因子方向（H5）
- ❌ 改 PROJECT.md / MODULE.md（除非任务本就是改规范）
- ❌ 改完不重跑 factor_generator
