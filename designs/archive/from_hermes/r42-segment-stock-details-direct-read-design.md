# R42: web_ui 直接读 summary/result/segment_stock_details.parquet (候选 A)

> **版本**: v2 (2026-07-07, 用户最终拍板候选 A, 无 fallback)
> **作者**: Hermes (用户拍板)
> **关联 commit**: R42 (待写)
> **关联规范**: `web_ui/MODULE.md` §边界规则 (v0.4.7 起), `PROJECT.md` H1.1

---

## 0. 背景与动机

**R39a 当前实现**(commit `2958323`):

- `web_ui/common/pl_ratio_db.py` 现场读 `composite_rolling_icir_weight_1d_daily.parquet` (60615 × 3) + `factor_ic_data.parquet` (75643 × 85)
- 现场 groupby + qcut 30 段 + mean(forward_return_1d) × 100

**用户决策 2026-07-07**: 直接读 summary 已写好的 `segment_stock_details.parquet`,merge forward_return_1d 算 seg_return,不再现场 qcut。

**已知语义差异**(R42 algorithm empirical validation 420 行 CSV, `web_ui/temporary/r42_b1_algorithm_empirical_validation.csv`):

- 段号算法一致(S7 资产 set 100% overlap, 2026-07-07 venv 实测)
- **段内资产不同**: ssd = summary alias 切片(ob_quality 管线筛后 ~1-5 只/段); composite_daily = 全市场 ~89 只/段
- **段位级别数值跳变不可避免**(最大 15.28pp)
- **用户知情决策**,h3 标题加 alias 切片语义警告(见 §5.3)

---

## 1. 影响范围

| 量化产出环节 | 影响 |
|---|---|
| Layer 1 候选池 (549) | 不影响 |
| 短名单 (30~50) | 不影响 (R39a R39 R40 R40b 不动) |
| 最终持仓 (3~5) | 不影响 |

---

## 2. 改动文件清单 (H1.1 自检)

按 `web_ui/MODULE.md` §边界规则 + `PROJECT.md` H1.1:

- ✅ **可改**: `web_ui/common/pl_ratio_db.py` (主逻辑重写)
- ✅ **可改**: `web_ui/templates/_section_segment_win.html` (h3 + 注释)
- ✅ **可改**: `web_ui/test_cases/test_app.py` (测试同步)
- ✅ **可改**: `web_ui/MODULE.md` (数据契约更新)
- ❌ **禁改**: `summary/`、`comprehensive_factor/`、`data_fetchers/`、其他任何 web_ui 目录外文件

---

## 3. 数据契约

### 3.1 新增依赖 parquet

| parquet | 路径 | 行 × 列 | 角色 |
|---|---|---|---|
| **主数据源** | `summary/result/segment_stock_details.parquet` | 1565 × 8 | 30 段选股明细 (含 segment_label S1~S30) |
| merge 数据源 | `data_fetchers/result/ob_quality/factor_ic_data.parquet` | 75643 × 85 | 取 forward_return_1d |

### 3.2 字段使用

| ssd 列 | 用途 |
|---|---|
| `selection_date` | 按日期分组,mm-dd 渲染 |
| `segment_label` | S1~S30 **直接用**,不再 qcut |
| `asset` | merge forward_return_1d 键 |
| `weight_method` | 过滤 `rolling_icir_weight` |

### 3.3 trade_date 算法

复用 summary 算法 (`generate_factor_summary_report.py:629-633`):

```python
master_dates = sorted(md["date"].dropna().unique())
idx = master_dates.index(selection_date)
trade_date = master_dates[idx + 1]
```

---

## 4. 设计决策(用户 2026-07-07 拍板)

| # | 决策 | 状态 |
|---|---|---|
| 1 | trade_date 复用 summary 算法 | ✅ 拍板 |
| 2 | **无 fallback**(用户原话"以 ssd 为主") | ✅ **拍板** (v1 → v2 删除 R39a legacy fallback) |
| 3 | 不跳 selection_date 最后一天 | ✅ 拍板 |
| 4 | 信任 summary 资产数过滤 | ✅ 拍板 |
| 5 | h3 加 alias 切片语义警告 | ✅ 加 |

---

## 5. 改动代码草图

### 5.1 `web_ui/common/pl_ratio_db.py` 重写

**新增路径**:
```python
_SEGMENT_STOCK_DETAILS_PATH: Path = (
    PROJECT_ROOT / "summary" / "result" / "segment_stock_details.parquet"
)
```

**主路径(`load_pl_ratio_trend` 重写,签名不变)**:
```python
def load_pl_ratio_trend(n_recent_dates=12, weight_method="rolling_icir_weight", logger=None):
    """B1 主路径: 读 summary/result/segment_stock_details.parquet (R42 候选 A, 无 fallback)."""
    if not _SEGMENT_STOCK_DETAILS_PATH.exists():
        if logger:
            logger.warning("ssd parquet 不存在: %s", _SEGMENT_STOCK_DETAILS_PATH)
        return None

    try:
        ssd = pd.read_parquet(
            _SEGMENT_STOCK_DETAILS_PATH,
            columns=["selection_date", "segment_label", "asset", "weight_method"],
        )
        ssd = ssd[ssd["weight_method"] == weight_method]
        if ssd.empty:
            return None
        recent_dates = sorted(ssd["selection_date"].unique())[-n_recent_dates:]

        master = pd.read_parquet(
            _MASTER_PARQUET_PATH,
            columns=["date", "asset", "forward_return_1d"],
        )
        master_dates = sorted(master["date"].dropna().unique())
    except Exception as e:
        if logger:
            logger.warning("读 parquet 失败: %s", e)
        return None

    seg_returns = {f"S{i+1}": [] for i in range(30)}
    avg_line = []
    valid_dates_mmdd = []

    for selection_date in recent_dates:
        try:
            idx = master_dates.index(selection_date)
            trade_date = master_dates[idx + 1]
        except (ValueError, IndexError):
            continue
        ret_df = master[(master["date"] == trade_date) & master["forward_return_1d"].notna()]
        if ret_df.empty:
            continue

        day_stocks = ssd[ssd["selection_date"] == selection_date][["asset", "segment_label"]]
        merged = pd.merge(day_stocks, ret_df[["asset", "forward_return_1d"]],
                          on="asset", how="inner")
        if merged.empty:
            continue

        for seg_label in [f"S{i+1}" for i in range(30)]:
            subset = merged[merged["segment_label"] == seg_label]["forward_return_1d"]
            seg_returns[seg_label].append(
                round(float(subset.mean() * 100), 2) if len(subset) > 0 else 0.0
            )
        day_avg = round(float(merged["forward_return_1d"].mean() * 100), 2)
        avg_line.append(day_avg)
        valid_dates_mmdd.append(selection_date[5:])

    if not valid_dates_mmdd:
        return None

    segments = []
    for seg_label in [f"S{i+1}" for i in range(30)]:
        vals = seg_returns[seg_label]
        segments.append({
            "label": seg_label,
            "pl_ratios": [float(v) for v in vals],
            "avg_pl_ratio": float(round(sum(vals) / len(vals), 2)) if vals else 0.0,
        })

    if logger:
        logger.info(
            "pl_ratio_trend 加载 (R42 B1 读 ssd): %d 段 × %d 选股日 (源=%s)",
            len(segments), len(valid_dates_mmdd), _SEGMENT_STOCK_DETAILS_PATH.name,
        )

    return {
        "dates": valid_dates_mmdd,
        "segments": segments,
        "avg_line": avg_line,
        "source": "summary_segment_stock_details",
    }
```

**删除**:
- `_compute_segment_pl_ratio()` 函数 (pl_ratio_db.py:53-94)
- `_COMPOSITE_DAILY_PATH` 常量 (pl_ratio_db.py:46-48)
- `_N_SEGMENTS = 30` 改为局部常量(只读 ssd 用)

### 5.2 `web_ui/app.py`

不变 (只调用 `load_pl_ratio_trend()` 签名)。

### 5.3 `web_ui/templates/_section_segment_win.html` (h3 + 注释更新)

**h3 标题** (行 210,加 alias 切片警告):
```html
<h3>30 段每日合并收益率趋势概览 (seg_return = mean(forward_return_1d))</h3>
<p class="muted">
  数据源: summary/result/segment_stock_details.parquet (alias 切片, ob_quality 管线筛后 ~1-5 只/段) 
  + data_fetchers/result/ob_quality/factor_ic_data.parquet (forward_return_1d) 
  · 算法 mean(forward_return_1d) * 100 
  · 语义变化: R42 起段内资产 = 管线 alias 切片, 与 R39a 全市场 composite 段位不一致 
  · 用户原话 2026-07-06: "等权 1:1:1, 3 只 +5%/+1%/-8% → (5+1-8)/3 = -0.67%"
</p>
```

### 5.4 `web_ui/test_cases/test_app.py`

- `test_segment_win_renders_seg_return_chart`: mock `_SEGMENT_STOCK_DETAILS_PATH.exists = True` + mock ssd dataframe
- 去掉 fallback 测试 (R42 v2 无 fallback)
- 加测试: ssd 不存在 → None

### 5.5 `web_ui/MODULE.md`

数据契约章节加 ssd 依赖说明。

---

## 6. 风险与回退

### 风险 1: summary 早上没跑 → 0 个 selection_date → trend 图空

**已知**:用户 2026-07-07 接受"早上 summary 没跑,trend 图空"。

### 风险 2: 段内资产 = alias 切片 ≠ 全市场

**已知**:R42 algorithm empirical validation 420 行 CSV, 用户知情。

### 回退方案

```bash
git revert R42  # 一键回到 R39a 全市场 qcut 实现
```

---

## 7. 测试策略

### 7.1 单元测试

1. mock ssd parquet 完整 → 12 个 selection_date × 30 段
2. mock ssd parquet 不存在 → 返回 None
3. mock trade_date 找不到 → 跳过该日

### 7.2 实测验证 (R42 commit 后)

- 启动 web_ui
- 截图 seg_return trend 图
- 与 summary 第九节 txt 对比同一天 30 段数值
- 偏差 ≤ 0.01pp (round 误差)

---

## 8. 提交计划

```
R42 (1 commit, 主路径):
  - web_ui/common/pl_ratio_db.py (重写主路径, 删 R39a legacy)
  - web_ui/templates/_section_segment_win.html (h3 + 注释)
  - web_ui/test_cases/test_app.py (测试同步)
  - web_ui/MODULE.md (数据契约更新)

回退 (条件触发): git revert R42
```

---

## 9. 引用规范行号

- `web_ui/MODULE.md:30-35` H1.1 边界规则 — R42 改 web_ui/ 内文件,合规
- `web_ui/MODULE.md:33-34` 首选 web_ui/common 自实现 / 次选直接读 summary txt — R42 读 summary parquet,符合"次选"
- `PROJECT.md:400` H1.1 — web_ui 不修改 summary,只读 summary 产物,R16 先例已合规
- `web_ui/templates/_section_candidate_detail.html:134` — R16 先例
- `web_ui/templates/_section_segment_win.html:172` — R16 先例