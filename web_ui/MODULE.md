# web_ui 模块规范

> **版本**: v0.4.7（v0.3 升级，伴随 PROJECT.md H1.1 边界铁律实施）
> **创建时间**: 2026-07-04
> **最后更新**: 2026-07-04
> **状态**: [experimental] — 严格遵守模块边界，迭代中
> **关联 design**: `designs/feat_web_ui_module.md` (v0.3), `designs/feat_web_ui_full_report_v0.4.md` (v0.4), `designs/feat_web_ui_obq_parity_v0.4.8.md` (v0.4.8, 简化版待写)
> **关联规范**: `PROJECT.md` §硬规则 H1 / H1.1

---

## 模块概述

`web_ui/` 是 Factor IC Analyzer 项目的**前端展示模块**，是 `summary/` 流水线的"前端分支"。

**核心定位**:
- web_ui 是 ob_quality 管线报告的 HTML 渲染前端
- **只展示 1 个 pipeline**（v0.4.7 简化: ob_quality 固定，不做 default/ob_quality tab 切换）
- 单页 + 锚点导航 + 折叠展开

---

## ⚠️ 模块边界（强约束，v0.4.7 起）

**这是本规范最重要的条款。** 任何 web_ui 改动必须严格遵守。

### 边界规则

1. **只读其他模块的 Python 脚本**: 可以 `from summary.report.data_loaders import ...` 调用 data_loaders 已有接口（**只读**）
2. **禁止修改其他模块目录**: `summary/`、`factor_ic/`、`backtest/`、`comprehensive_factor/`、`data_fetchers/`、`factor_definitions/`、`paths.py` 等任何 web_ui 目录外的文件**禁止修改**
3. **禁止在 web_ui 内复刻其他模块的函数**（v0.3 沿用）
4. **如需其他模块未暴露的接口**:
   - **首选**: 在 web_ui/common/ 下自行实现（例: LR 训练状态从 `comprehensive_factor/result/ob_quality/lr_training_data/` 直读）
   - **次选**: 直接读 summary 已生成的 txt 报告（`summary/result/ob_quality/factor_summary_report_*.txt`）用正则解析
   - **禁止**: 修改其他模块的 data_loaders 等代码来"暴露"接口（除非走 Design-First + 各模块 owner 确认流程）

### 历史教训

- v0.4.5 / v0.4.6.2 R2a 曾**错误**地修改 `summary/report/data_loaders.py` 加 `pipeline_scope` / `load_lr_training_status` — 已严格回退 (commit `217f1ad`)
- v0.4.7 起 web_ui 全部自包含: pipeline 切换移除, LR 状态 web_ui 内部实现

### 检查工具

- **CI**: `scripts/check_web_ui_boundary.py` (待实施, 见 PROJECT.md H1.1)
- **人工 review**: PR review 时核对"改动文件清单"是否 100% 在 `web_ui/` 目录下

---

## 数据契约

| 路由 | URL | 数据源 | 响应 |
|------|-----|--------|------|
| 当日选择 | `/report/<date>` | `summary/report/data_loaders.load_stock_selection_result()` (ob_quality pipeline) | HTML |
| 最新选择 | `/report/latest` | 同上 (固定 ob_quality) | 302 → `/report/<max_date>` |
| 首页 | `/` | 302 → `/report/latest` | 重定向 |

**v0.4.7 简化**:
- 不再有 `/selection` 路由（v0.3 路由已废弃，218f1ad 之后 v0.4.1 是首个有效路由）
- 不再有 `?pipeline=` query param（固定 ob_quality）

**禁止行为**（v0.3 沿用）:
- ❌ 禁止 `import pandas`、`import pyarrow`、`import json`（除非只是用 json 处理路径字符串）
- ❌ 禁止硬编码 `comprehensive_factor/result/default/` 路径
- ❌ 禁止 web_ui 内复刻 `summary/report/data_loaders.py` 任何函数
- ❌ **禁止修改 web_ui 目录外的任何文件**（v0.4.7 新增, H1.1）

---

## 目录结构

```
web_ui/
├── app.py                          # Flask 入口 + 路由
├── common/                         # web_ui 私有 common/ (v0.4.7 新增)
│   ├── __init__.py
│   ├── lr_training_status.py       # 解析 lr_training_data HIVE 分区
│   ├── pl_ratio_db.py              # v0.4.8 R42: 30 段每日合并收益率 (B1 主路径, 读 ssd)
│   └── txt_parser.py               # 解析 ob_quality txt 报告 (v0.4.7 R3+) |
├── templates/                      # Jinja2 模板
│   ├── report.html                 # 主报告页 (ob_quality 8+9+10+10-fallback)
│   ├── _section_selection.html     # 八·股票选股结果
│   ├── _section_segment_win.html   # 九·30分段胜率汇总
│   ├── _section_candidate_detail.html  # 十·今日三十分段候选明细
│   └── _section_intraday.html      # 十·S7/S9 段日内操作建议
├── test_cases/                     # pytest 测试
│   ├── test_app.py
│   └── test_parity_obq.py          # v0.4.8: 字段级 diff 测试
├── logs/                           # Flask access log
└── MODULE.md                       # 本文件
```

---

## 实施记录

| 日期 | 阶段 | 内容 |
|------|------|------|
| 2026-07-04 | v0.3 规范层 | 注册 web_ui/ 目录 + 重写本规范（删除 factor_ic 2432 行复制） |
| 2026-07-04 | v0.3 后端/模板/测试 | app.py Flask + 3 路由 + selection.html + test_app.py |
| 2026-07-04 | v0.4.1 | /report/<date> 路由 + 8 section 框架 (本会话 commit 后已严格回退) |
| 2026-07-04 | v0.4.5-v0.4.6.2 R2b | pipeline 切换 + ob_quality 9/10 段 (本会话 commit 后已严格回退) |
| 2026-07-04 | v0.4.7 规范升级 | 加 H1.1 模块边界条款 + 简化需求 (只 ob_quality) + 严格回退到 217f1ad |
| 2026-07-07 | v0.4.8 R42 | 30 段每日合并收益率趋势概览 B1 主路径: web_ui 直接读 summary/result/segment_stock_details.parquet (alias 切片, 无 fallback), merge forward_return_1d · 段内资产 = 管线筛后 ~1-5 只/段, 与 R39a 全市场 composite 段位不一致 (用户知情决策, h3 加 alias 切片警告) |

---

## 引用

- **PROJECT.md** §硬规则 H1 / H1.1（**模块边界铁律**）
- `summary/report/data_loaders.py`（**只读**数据契约: `load_stock_selection_result`, `load_stock_name_map`, `load_decile_stats`, `load_intraday_strategy`）
- `summary/report/sections.py`（txt 渲染**参考实现**，不直接调用内部函数）
- `summary/result/ob_quality/factor_summary_report_*.txt`（**已生成的 txt 报告**，v0.4.8+ 字段补全用正则解析）
- `comprehensive_factor/result/ob_quality/lr_training_data/`（HIVE 分区，**直读**用于 LR 训练状态）
- `designs/feat_web_ui_module.md` (v0.3 design)
- `designs/feat_web_ui_full_report_v0.4.md` (v0.4 design, 已回退)
- `designs/feat_web_ui_obq_parity_v0.4.7.md` (v0.4.7 design, **作废**, v0.4.8 重写)
