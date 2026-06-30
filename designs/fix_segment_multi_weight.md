# Design: 修复三十分段多权重并存问题

**日期**: 2026-06-30
**状态**: pending review
**影响文件**: 3 (修改 3)

## 问题

ob_quality 管线三十分段体系存在 5 个 bug，核心是 weight_method 硬编码导致多权重无法并存：

| # | 严重度 | 问题 | 位置 |
|---|--------|------|------|
| 1 | P0 | `_compute_pending_win_rates` 硬编码 `weight_method="rolling_icir_weight"` | gen_report L469 |
| 2 | P1 | `SEGMENT_STOCK_COLUMNS` 缺少 `weight_method` 列，同日不同权重互相覆盖 | segment_win_db L41-44 |
| 3 | P2 | 死代码：`os.environ.get("PIPELINE_ALIAS", "")` 独立表达式未赋值 | gen_report L390 |
| 4 | P2 | 误导性标签："共 N 条时间递减管线" 实为 N 个日期 | gen_report L510 |
| 5 | P3 | `_render_today_best_segment_candidates` 重复读 composite_daily + qcut，未复用 stock_details | gen_report L581-593 |

## 方案

### 修改 1: `summary/report/segment_win_db.py`

**What**: 为 stock_details 增加 `weight_method` 列，去重逻辑包含 weight_method。

**How**:
- `SEGMENT_STOCK_COLUMNS`: 在 `pipeline` 后插入 `"weight_method"`
- `save_segment_stock_details`: 新增 `weight_method: str` 参数，写入行 + 去重 mask 包含 `weight_method`
- `load_segment_stock_details`: 新增可选 `weight_method: str | None` 参数，非 None 时过滤
- **数据迁移**: `_read_parquet` 读出后，若缺少 `weight_method` 列，补 `default='rolling_icir_weight'`（现有 1087 行均为 rolling_icir_weight 产生）

**Don't**: 不删除现有数据，用默认值补列保持兼容。

**Why**: stock_details 和 win_rates 都需要按 (pipeline, selection_date, weight_method) 唯一标识。win_rates 已有 weight_method 列，stock_details 缺失导致同日不同权重覆盖。

### 修改 2: `summary/generate_factor_summary_report.py`

**`_save_today_segment_details` (L323-377)**:
- 传 `weight_method` 给 `save_segment_stock_details`

**`_compute_pending_win_rates` (L380-479)**:
- 删除死代码 L390
- 按 `weight_method` 分组处理：读 stock_details → 获取唯一 weight_method 列表 → 逐 weight_method 查 done_dates → 算 pending → 写入实际 weight_method
- master_path 改用 `FACTOR_IC_DATA`（pipeline-aware），替代硬编码 fallback

**`_render_cross_pipeline_summary` (L510)**:
- "共 N 条时间递减管线" → "共 N 个选股日期"

**`_render_today_best_segment_candidates` (L562-629)**:
- 改为从 `load_segment_stock_details` 读取最新日期的明细（已含 weight_method 过滤）
- 不再重复读 composite_daily + qcut

### 修改 3: `summary/test_cases/test_segment_win_db.py`

新增测试：
- `test_stock_details_weight_method`: 写入 + 读取带 weight_method 的 stock_details
- `test_stock_details_multi_weight_coexist`: 同日不同 weight_method 不覆盖
- `test_stock_details_migration`: 旧数据（无 weight_method 列）读取时自动补列

## 影响范围

| 影响 | 说明 |
|------|------|
| 短名单 (30~50) | 无直接影响 |
| 最终持仓 (3~5) | 无直接影响 |
| Layer 1 候选池 (549) | 无直接影响 |
| 三十分段胜率 | 修复后支持多权重并存，ic_weight 等非 rolling_icir_weight 权重可正常渲染 Section 9 |

## 规则检查

- [x] 模块边界：修改均在 summary 模块内
- [x] 输出位置：Parquet 文件仍在 `summary/result/`
- [x] 任务粒度：3 文件，约 130 行改动
- [x] 路径导入：master_path 改用 `from paths import FACTOR_IC_DATA`
- [x] 异常链：保留现有 `raise ... from e` / `logger.exception` 模式
- [x] 日志格式：惰性格式化（% 风格）
