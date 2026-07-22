# 30 段合并胜率趋势概览 (v0.4.8 R38 Stage 6)

**目标**: web_ui 第九节新增"30 段合并胜率趋势概览"折线图 —— X=选股日 / Y=胜率(0-100) / 30 条折线 (每段一条), 值 = 截至当日的累计合并胜率 (cumsum_wins / cumsum_total)

**用户原话**: "web_ui 中展示 30 段胜率趋势概览的折线图, 下面新增一个组件, 展示 30 段合并胜率趋势概览的折线图"

---

## 1. 数据契约 (H1.1 严守, §18.1g 已验证)

### 1.1 数据源
- `summary/result/segment_win_rates.parquet` (T+1 日读到 forward_return_1d 后算胜率写入)
- schema: pipeline, selection_date, trade_date, weight_method, n_segments, n_total, segment_label, **wins (int)**, **total (int)**, win_rate (float), created_at
- 当前 12 天 × 30 段 = 360 行 (ob_quality/rolling_icir_weight), 100% 对得上 txt 报告第九节

### 1.2 数据契约 (与 txt_s9_matrix 对齐)
```python
{
    "dates": ["06-15", "06-16", ...],  # 12 选股日 (mm-dd 格式, 与 txt 第九节一致)
    "segments": [
        {
            "label": "S1",
            "merged_running": [46.30, 47.73, ...],  # 截至每日的累计合并胜率 (cumsum_wins/cumsum_total*100)
            "merged_final": 46.30,                   # 末日累计合并胜率 (与 txt 第九节"合并"列对得上)
        },
        ...
    ],
    "source": "parquet",  # 区别于 txt_s9_matrix.source = "txt"
}
```

### 1.3 验证 (已跑, §18.1g)
- 末日 merged_running == strict sum(wins)/sum(total) == txt merged: **0/30 段偏差 > 0.5%, max diff 0.05%**
- 算法: `df.sort_values(['segment_label', 'selection_date'])` + `groupby('segment_label')[['wins','total']].cumsum()` + `cum_wins/cum_total*100`

### 1.4 §18 fork pattern (H1.1 严守)
- web_ui 不能直接 import summary 模块 (txt_parser 已示范此模式)
- 新增 `web_ui/common/segment_win_db.py` 读 `summary/result/segment_win_rates.parquet` —— **只读不写**, 不修改 summary 模块
- 走 `paths.SUMMARY_DIR / "result" / "segment_win_rates.parquet"` 路径导入 (AGENTS.md §硬规则 #11)

---

## 2. 模板改动 (`web_ui/templates/_section_segment_win.html`)

### 2.1 新增位置
紧跟现有"30 段胜率趋势概览" (segOverviewChart) 后面 (在 30×12 矩阵折叠之前), 与现有图共用 toolbar (12/30/90/全部切换 + 段选择器)

### 2.2 新增组件 (复用现有 toolbar, §3c reverse trigger 合并方案)
- **不**重复实现 12/30/90/全部 4 档按钮和段选择器, 直接复用现有 segOverviewChart 的 toolbar (HTML 不变)
- 新图 (segMergedChart) 注册为同一组切换的第二个 chart, toolbar 按钮同时刷新两个 chart 的数据
- 段选择器 solo 逻辑也同时作用于两个 chart

```html
<h3>30 段合并胜率趋势概览 (截至当日累计合并)</h3>
<p class="muted">数据源: summary/result/segment_win_rates.parquet (T+1 日 forward_return_1d 计算) · 算法 cumsum_wins/cumsum_total · 与上方"30 段胜率趋势"区别: 上方=每日 wr%, 下方=截至当日累计合并胜率</p>
<div class="chart-wrap">
    <canvas id="segMergedChart" data-chart-key="segMergedChart" height="280"></canvas>
</div>
```

### 2.3 视觉一致性 (R29 颜色统一)
- 复用 segOverviewChart 的 COLORS 15 色 + SENTRY token
- 复用现有 solo/范围切换逻辑 (window._segOverview 已有 4 档按钮) — **扩展为同时切换两个 chart**
- **不** 触碰 segOverviewChart 任何代码 (除了 toolbar 函数同步切两个 chart 的 1 行扩展)

---

## 3. Python 改动

### 3.1 新增 `web_ui/common/segment_win_db.py`
```python
"""web_ui/common/segment_win_db.py — v0.4.8 R38 Stage 6

§18 fork pattern (与 txt_parser 对齐): web_ui 内部读 parquet, 不直接 import summary 模块
不修改 data_loaders / summary/report/segment_win_db.py (H1.1 严守)
"""
from __future__ import annotations
import logging
from pathlib import Path
import pandas as pd
from paths import PROJECT_ROOT

_PARQUET_PATH = PROJECT_ROOT / "summary" / "result" / "segment_win_rates.parquet"

def load_merged_win_trend(
    pipeline: str = "ob_quality",
    weight_method: str = "rolling_icir_weight",
    logger: logging.Logger | None = None,
) -> dict | None:
    """读 segment_win_rates.parquet, 算截至每日的累计合并胜率.

    Returns:
        {
            "dates": ["06-15", ...],
            "segments": [
                {"label": "S1", "merged_running": [46.30, ...], "merged_final": 46.30},
                ...
            ],
            "source": "parquet",
        }
    """
    if not _PARQUET_PATH.exists():
        logger.warning("segment_win_rates.parquet 不存在: %s", _PARQUET_PATH)
        return None
    try:
        df = pd.read_parquet(_PARQUET_PATH)
    except Exception as e:
        logger.warning("读 segment_win_rates.parquet 失败: %s", e)
        return None
    df = df[(df["pipeline"] == pipeline) & (df["weight_method"] == weight_method)]
    if df.empty:
        return None
    df = df.sort_values(["segment_label", "selection_date"])
    df["cum_wins"] = df.groupby("segment_label")["wins"].cumsum()
    df["cum_total"] = df.groupby("segment_label")["total"].cumsum()
    df["merged_running"] = df["cum_wins"] / df["cum_total"] * 100

    dates_mmdd = [d[5:] for d in sorted(df["selection_date"].unique())]
    segments = []
    for label, g in df.groupby("segment_label"):
        merged_running = g["merged_running"].tolist()
        segments.append({
            "label": label,
            "merged_running": merged_running,
            "merged_final": merged_running[-1],
        })
    # 按段号排序
    segments.sort(key=lambda s: int(s["label"][1:]))
    return {"dates": dates_mmdd, "segments": segments, "source": "parquet"}
```

### 3.2 改 `web_ui/app.py`
- L46-52 增 `from web_ui.common.segment_win_db import load_merged_win_trend` (H1.1: web_ui 内部模块, 不影响 data_loaders)
- L135 上下文注入 `merged_win_trend = load_merged_win_trend(logger=logger)`

---

## 4. 测试改动

### 4.1 新增 `test_load_merged_win_trend` 
- mock pd.read_parquet 返回 3 天 × 5 段 fixture
- 断言: dates 长度=3, segments 长度=5, merged_running 末日 = strict sum(wins)/sum(total)*100
- 断言: merged_final == merged_running[-1]
- 断言: empty parquet → return None

### 4.2 不动现有测试 (§3 surgical + §5c)
- test_segment_win_handles_no_data / test_segOverviewChart / 30×12 matrix 测试**全部不动**
- 新增测试与现有 12 测试并存, mock 字段不重叠

---

## 5. V0-V4 Verification Gate (§18.2)

### V0 静态检查
- `ruff check --fix web_ui/common/segment_win_db.py web_ui/app.py web_ui/templates/_section_segment_win.html`
- `ruff format web_ui/common/segment_win_db.py web_ui/app.py`

### V1 单元测试
- `pytest web_ui/test_cases/test_app.py -k merged` 至少 3 个新断言通过
- 现有 test_app.py 全 12 测试**不 fail** (§3 surgical + §5c)

### V2 真 server 启动 (V2' zombie 验证 4 步, karpathy v1.5.3)
- `pgrep -af app.py` 看 PID 活着
- `ps -o pid,ppid -p <pid>` PPID != 1 (不是 systemd zombie)
- `ls -la /proc/<pid>/exe` 看真实 venv 路径
- `cat /proc/<pid>/cmdline` 看真实 entry script

### V3 curl 验证
- `curl -s http://localhost:9001/report/<date> | grep segMergedChart` → 期望 1 命中 (canvas tag)
- `curl -s http://localhost:9001/report/<date> | grep merged_running` → 期望多命中 (JSON 数据)
- 算 HTML size, 与 R31 修过的基准对比 (不能爆增 > 50KB)

### V4 程序性 console (karpathy §18.2d)
- 用 browser_console 跑 `Chart.getChart(document.getElementById('segMergedChart'))` → 检查 `data.datasets[0].data.length == 30` (段数) + `rectH ∈ [200, 500]` (不撑爆)
- 检查 `merged_running.length` 每段 == dates.length

---

## 6. Commit 计划 (§19 Stage 6 单点 + §4b 默认走 + §17 简化触发边界)

按用户原话 "新增一个组件" = 1 个 R38 commit. 不拆多 commit (R30 Stage 6 实战模式).

**commit message**:
```
v0.4.8 R38 (Stage 6): 新增 30 段合并胜率趋势概览 (segMergedChart)

按用户 2026-07-06 原话: "web_ui 中展示 30 段胜率趋势概览的折线图, 下面新增一个组件,
展示 30 段合并胜率趋势概览的折线图"

数据契约 (H1.1 严守 + §18.1g 已验证):
- 数据源: summary/result/segment_win_rates.parquet (T+1 日 forward_return_1d 计算)
- 算法: cumsum_wins/cumsum_total * 100 (严格 sum 算法, 与 txt 第九节 merged 列一致)
- 验证: 末日 merged_running vs txt merged = 0/30 段偏差 > 0.5%, max diff 0.05%

改动 (3 文件, ~80 行):
- 新增 web_ui/common/segment_win_db.py (§18 fork pattern, 读 parquet 不写)
- 改 web_ui/app.py 注入 merged_win_trend context (1 行 + 1 import)
- 改 web_ui/templates/_section_segment_win.html 加 segMergedChart canvas + factory (~50 行) +
  扩展现有 window._segOverview 函数同步切两个 chart (1 行扩展, §3c reverse trigger)

不动 (§3 surgical + §5c):
- 现有 segOverviewChart / 30×12 矩阵 / decile_stats 表 / 全部现有测试
- summary 模块 (txt 报告生成 + segment_win_db.py) — web_ui 只读 parquet

verification (§18.2 V0-V4): ruff ✅ / pytest 14+ ✅ / 真 server ✅ / console rectH ✅
```

**§17 简化触发边界审计**:
- 用户原话 "新增一个组件" = 1 个 R commit
- 邻近模块 (现有 segOverviewChart toolbar / decile_stats / 30×12 矩阵) **不动**
- 颜色统一 / 性能 / 适配 全部不动 (§19 Stage 5/2/3 已落地, 不回退)

---

## 7. 风险与回退

### 风险 1: parquet 文件不存在 (T+2 数据未到)
- `load_merged_win_trend()` 返回 None → 模板 fallback "本节所需 Parquet 实时计算未就绪" (与现有 decile_stats fallback 文案一致)
- 现有 segOverviewChart 仍可看 (txt 来源, 不依赖 parquet)

### 风险 2: 末日期非 txt 报告日期
- 当前 parquet 末日期 07-01, txt 报告 07-04 — dates 维度可能有 1-3 天差异
- 影响: 曲线最后 1-3 点与 txt 报告矩阵对不上 (txt 矩阵是 12 天, parquet 可能更多天)
- 解决: 显示曲线但加 muted 注释 "末 3 天 parquet 与 txt 报告时间窗可能错位"

### 风险 3: 用户对位置/视觉不满意
- `git revert <commit>` 1 键回退 (R30 + R31 实战模式)
- 不破坏现有 segOverviewChart