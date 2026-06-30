# Design: 30 分段胜率落库 + Section 9 读库解耦

**日期**: 2026-06-30
**状态**: pending review
**影响文件**: 3 (新增 1 + 修改 2)

## 问题

当前 `_render_cross_pipeline_summary`（L309）通过扫描 `comprehensive_factor/result/ob_quality_06XX/` 目录来收集 30 分段胜率数据。两个痛点：

1. **目录依赖**：胜率表不更新是因为没有新目录，而非没有新数据
2. **重复计算**：每次跑主管线报告都要重新读取所有子管线 parquet 再 qcut

## 方案

### 新增：`summary/report/segment_win_db.py`

Parquet 文件 `summary/result/segment_win_rates.parquet`，append 模式写入：

**Schema**（Parquet 列）：
```
pipeline        TEXT       -- 'ob_quality'
selection_date  TEXT       -- '2026-06-24'
trade_date      TEXT       -- '2026-06-25' (T+1)
weight_method   TEXT       -- 'rolling_icir_weight'
n_segments      INT        -- 30
n_total         INT        -- 当日股票总数
segment_label   TEXT       -- 'S1'..'S30'
wins            INT
total           INT
win_rate         DOUBLE
created_at      TEXT       -- ISO timestamp
```

**去重保证**：append 前按 `(pipeline, selection_date, weight_method)` 删除旧行，再写入新行。

提供两个函数：
- `save_segment_win_rates(pipeline, selection_date, trade_date, weight_method, n_segments, n_total, seg_stats)` → 去重后 append 到 parquet
- `load_segment_win_rates(pipeline, weight_method)` → 读 parquet，返回 `[(selection_date, trade_date, seg_label, wins, total, win_rate), ...]`

### 修改：`summary/generate_factor_summary_report.py`

`_render_cross_pipeline_summary`（L309-465）：
- **旧逻辑**：扫描 `comprehensive_factor/result/ob_quality_06XX/` 目录 → 读 parquet → qcut → 输出表
- **新逻辑**：直接读 `segment_win_rates` 表 → 输出表（已有数据直接渲染）
- **兼容**：如果表中无数据，回退到目录扫描逻辑（保持向前兼容）

### 修改：数据填充（executed separately）

落库不耦合到 `run_pipeline` 主流程中。提供独立脚本 `scripts/populate_segment_win_db.py`，从现有 `ob_quality_06XX` 目录迁移历史数据到 Parquet。后续新时间切片管线跑完后手动或 cron 调此脚本 append 新数据。

## 影响范围

| 影响 | 说明 |
|------|------|
| Section 9 数据源 | `ob_quality_06XX/` 目录 → SQLite 表 |
| 主管线执行 | 无影响（落库是独立脚本） |
| 报告内容 | 不变，只是数据来源变了 |
| 向后兼容 | 表中无数据时回退到目录扫描 |

## 规则检查

- [x] 模块边界：新文件在 `summary/report/` 下，属于 summary 模块
- [x] 输出位置：DB 文件在 `summary/result/` 下
- [x] 任务粒度：3 文件（1 新增 + 2 修改），符合 ≤3 文件约束
