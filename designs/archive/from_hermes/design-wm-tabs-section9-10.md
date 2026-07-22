# Design: Section 9/10 页签展示四种 weight_method

## 问题
- Section 9 (胜率) 和 Section 10 (候选明细) 依赖 txt_parser 解析 txt 报告
- txt 报告只含"最优" weight_method 的数据
- 当 weight_method 变化 (如 rolling_icir_weight -> equal_weight), 历史数据断层 -> Section 9 空

## 方案
用 `?wm=xxx` query param 切换 weight_method, 从 parquet 直接读数据 (不依赖 txt)
页签 = 链接, 点击刷新页面带新 wm 参数

## 影响范围
- □ 短名单 (30~50) ← 量化职责
- □ 最终持仓 (3~5) ← 用户职责
- ✅ Layer 1 候选池展示 ← 量化基础设施

## 文件变更 (4 文件)
1. **新建 `web_ui/common/weight_method_data.py`** (~150 行)
   - `get_best_weight_method()` - 读 weight_selection_result.json
   - `get_available_weight_methods()` - 4 种
   - `load_win_matrix(weight_method)` - 读 segment_win_rates.parquet, 返回与 txt_s9_matrix 同结构
   - `load_candidates(weight_method, stock_name_map)` - 读 segment_stock_details.parquet + win_rates

2. **修改 `web_ui/app.py`** (~30 行改动)
   - 接受 `?wm=xxx` query param, 默认 = best_weight_method
   - 调用新 parquet 函数替代 txt_parser (txt_parser 仍保留作为 fallback)
   - 传 `available_wms`, `current_wm` 给模板

3. **修改 `web_ui/templates/_section_segment_win.html`** (~30 行)
   - 顶部加 4 个 weight_method 页签链接
   - 数据源从 txt_s9_matrix 改为 parquet_win_matrix (同结构, 无需改 chart JS)

4. **修改 `web_ui/templates/_section_candidate_detail.html`** (~30 行)
   - 顶部加 4 个 weight_method 页签链接
   - 数据源从 txt_s10_segments 改为 parquet_candidates (同结构)

## 数据结构 (与 txt_parser 返回值对齐, 模板零改动)

### load_win_matrix 返回:
```json
{
  "dates": ["06-15", "06-16", ...],
  "segments": [{"label": "S1", "win_rates": [46.3, 75.0, ...], "merged": 46.3}, ...],
  "best_segment": {"label": "S7", "merged": 59.6}
}
```

### load_candidates 返回:
```json
{
  "selection_date": "2026-07-14",
  "pool_size": 27,
  "weight_method": "equal_weight",
  "segments": [{"label": "S1", "n_stocks": 1, "win_rate": 42.0, "stocks": [...]}],
  "best_segment": {"label": "S7", "win_rate": 61.4}
}
```

## 不改动
- Chart.js / ApexCharts JS 逻辑 (数据结构对齐, 无需改)
- merged_win_trend / pl_ratio_trend / asset_value_trend (已支持 weight_method 参数, app.py 传入选中的 wm)
- txt_parser.py (保留作为 fallback, 不删除)
