# web_ui 模块规范

> **版本**: v0.3（草案，伴随 PROJECT.md 业务模块豁免条款实施）
> **创建时间**: 2026-07-04
> **最后更新**: 2026-07-04
> **状态**: [experimental] — v1 仅实现 1 个页面，迭代中
> **关联 design**: `designs/feat_web_ui_module.md`

---

## 模块概述

`web_ui/` 是 Factor IC Analyzer 项目的**前端展示模块**，是 `summary/` 流水线的"前端分支"。

**核心铁律**（与 PROJECT.md §"前端模块豁免条款"对应）：
- web_ui **不**直接读取 Parquet/JSON —— **必须**经 `summary/report/data_loaders.py` 加载
- web_ui **不**产生 Python 业务产物（无 `result/`、`schemas/`、`common/`）
- 复用 `summary/report/formatters.py` 格式化数值
- 复用 `summary/report/sections.py` 的"展示逻辑"——只是渲染介质从 txt 变成 HTML

**v1 范围**：仅展示 `summary/report/load_stock_selection_result()` 返回的当天数据（Stage 1/2/3 Top 50）。其他展示（IC 排名、分层回测、综合因子）留 v2/v3。

## 目录结构

```
web_ui/
├── app.py                  # Flask 入口 + 路由（v0.3 实施）
├── templates/              # Jinja2 模板
│   └── selection.html      # 当天 stock_selection 展示页（v0.3 实施）
├── logs/                   # Flask access log + 应用日志
├── test_cases/             # pytest 测试（v0.3 实施）
└── MODULE.md               # 本文件
```

## 数据契约

| 路由 | URL | 数据源（复用 summary） | 响应 |
|------|-----|---------------------|------|
| 首页重定向 | `/` | `summary/report/data_loaders.get_date_str()` | 302 → `/selection/<today>` |
| 当日选择 | `/selection/<date>` | `summary/report/data_loaders.load_stock_selection_result()` | HTML |
| 最新选择 | `/selection/latest` | 同上 | 302 → `/selection/<max_date>` |

**禁止行为**：
- ❌ 禁止 `import pandas`、`import pyarrow`、`import json`（除非只是用 json 处理路径字符串）
- ❌ 禁止硬编码 `comprehensive_factor/result/default/` 路径
- ❌ 禁止 web_ui 内复刻 `summary/report/data_loaders.py` 任何函数

## 实施记录

| 日期 | 阶段 | 内容 |
|------|------|------|
| 2026-07-04 | v0.3 规范层 | 注册 web_ui/ 目录 + 重写本规范（删除 factor_ic 2432 行复制） |
| 待实施 | v0.3 后端层 | `app.py` Flask + 3 路由 + 复用 `load_stock_selection_result()` |
| 待实施 | v0.3 模板层 | `selection.html` Jinja2 表格 |
| 待实施 | v0.3 测试层 | `test_app.py` pytest 测 3 路由 |

## 引用

- PROJECT.md §"前端模块豁免条款"（业务模块统一约定下方）
- `summary/report/data_loaders.py`（数据契约唯一来源）
- `summary/report/formatters.py`（格式化工具）
- `summary/report/sections.py`（txt 渲染参考实现）
- `designs/feat_web_ui_module.md`（v0.3 design，10KB / 230 行）
