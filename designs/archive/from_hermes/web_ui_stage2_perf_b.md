# web_ui Stage 2 — Performance (v0.4.8 R31-R33)

> 用户反馈: PC 端性能很卡 / 元素一直在加载不稳定 / 手机端 OK
> 方案: **B 方案** = A (lazy canvas + 按需渲染 + cache) + 加 30×12 矩阵折叠展开 + Chart.js deferred
> 严格边界 (karpathy §3 surgical): **只动性能问题, 不动现代感/颜色/卡片/适配**

## 诊断 (R21-R30 已落地 + 363KB HTML + 10 chart + 30×12 矩阵 = 雪崩)

| 指标 | 数据 | 来源 |
|---|---|---|
| 真 listener | 127.0.0.1:9001 (PID 522975) | 用户原话 + ss -ltnp |
| 真 server 渲染耗时 | 0.264s (curl /report/2026-07-03) | 这次会话实测 |
| **返回 HTML 大小** | **362.86 KB** | curl `size_download` |
| Chart.js 实例 (PC/移动全局) | **10 个 new Chart(** | grep `new Chart(` |
| `<canvas>` 元素 | **20 个** (含 sparkline 复用) | grep `<canvas` |
| `_section_segment_win.html` | **16.46 KB** (单模板最大) | wc -c |
| `report.html` 主模板 | 35.15 KB | wc -c |
| `_section_segment_win` 内 `<canvas>` | **4 个** (segBar/segLine/segOverview/segDaily) | _section_segment_win.html L48/52/181/244 |
| **30×12 矩阵表格 cell 数** | **390 cells** (= 30行 × 13列) | txt_s9_matrix.dates(N dates) + 30 segment + 合并胜率列 |
| daily_rates 明细 | **已 R30-4c 折叠** (`<details>`) | _section_segment_win.html L246-264 |
| 30×12 矩阵 | **未折叠** | _section_segment_win.html L293-321 |

**根因**: 移动端 viewport 小 + Chart.js 自适应计算量小 → PC 反而雪崩。

## Stage 2 拆分 (R21-R30 6 阶段模式 + 每阶段独立 commit)

| Round | Stage | 内容 | 风险 |
|---|---|---|---|
| **R31** | Stage 2.1 — Chart lazy | IntersectionObserver helper + 4 个 canvas 加 `data-chart-*` 包裹 + 同步 `new Chart()` → 视口可见才渲染 | 低 (纯加 lazy 机制, 不动 options) |
| **R32** | Stage 2.2 — 30×12 矩阵折叠 | `<details>` 包裹矩阵表格 (模仿 R30-4c daily_rates 折叠)+ `<details>` 深色样式 override | 低 (折叠, 关闭时 DOM 不渲染表格) |
| **R33** | Stage 2.3 — Cache-Control | `<meta>` 静态资源 + `Cache-Control: max-age=300` on `/report/` | 极低 (加 response header) |

## 不动 (避免 §3 surgical 越界)

- R17 heatmap 颜色 / R22-3 组件化 (`render_rank_bar` macro) / R21-R30 全部 commit 内容
- Chart 类型 / options / 颜色 / tooltip / legend 配置
- 现代感 CSS / 卡片化 / 颜色统一 (R27 R28 R29)
- 移动端适配 (R25-1 @media, R30-4b 移动端隐藏 legend/pointRadius=0)
- 任何 meta / muted / empty 文本措辞
- pytest 测试 (R30 测试已 mock 4 个 chart)

## R31 — Chart lazy (IntersectionObserver)

### 边界

| 改 | 不改 |
|---|---|
| **加** `lazy_chart.js` helper (IntersectionObserver + chart type/call factory map) | 现有 4 个 `new Chart()` options/data/colors |
| **加** `<canvas data-chart-key="segBarChart" ...>` 包裹 | chart instance semantics |
| **加** chart registry: `window._chartFactories = { segBarChart: (canvas, data) => new Chart(canvas, {...}), ... }` | |
| 4 个 `<script>` 块调 `_renderChart('segBarChart', data)` 而非 `new Chart(canvas, {...})` | |
| rootMargin: '100px' (提前 100px 渲染, 用户感知无延迟) | |

### Implementation 逻辑

```js
// report.html head end + body end
window._chartFactories = {};  // 由各 _section 注册
window._renderChart = function(key) {
  const el = document.querySelector(`[data-chart-key="${key}"]`);
  if (el && el._chart_rendered !== true && window._chartFactories[key]) {
    window._chartFactories[key](el);
    el._chart_rendered = true;
  }
};
// IntersectionObserver 监听所有 [data-chart-key]
const io = new IntersectionObserver((entries) => {
  entries.forEach(e => { if (e.isIntersecting) window._renderChart(e.target.dataset.chartKey); });
}, { rootMargin: '100px' });
document.querySelectorAll('[data-chart-key]').forEach(el => io.observe(el));
// 页面加载完成时观察 + 立即渲染已在视口的
window.addEventListener('load', () => {
  document.querySelectorAll('[data-chart-key]').forEach(el => {
    if (el.getBoundingClientRect().top < window.innerHeight) window._renderChart(el.dataset.chartKey);
  });
});
```

### Section 改动 (4 个 canvas)

| Section | canvas id | factory body (data from `segs/...)` |
|---|---|---|
| `_section_segment_win` L48 | `segBarChart` | (function) { Chart(ctx, { type: 'bar', data: {labels, datasets: [...]}, options: {...} }) } |
| `_section_segment_win` L52 | `segLineChart` | 同上 line config |
| `_section_segment_win` L181 | `segOverviewChart` | 同上 + window._segOverview 范围切换 (R30-3 已有) |
| `_section_segment_win` L244 | `segDailyChart` | bar + 颜色按 v>=60/v<40 |

**其他 6 个 canvas** (`_section_candidate_detail` × 2 / `_section_freshness` × 2 / `_section_intraday` × 2) — **按 §3 surgical 不动**, 留给后续 round (R34+)。Stage 2.1 一次性只动主 source (segment_win 的 4 个) 而非 N 个, 留余地观察验证效果。

**等等 — 等等 ⏸ 重要回归**: 检查 `_section_candidate_detail` / `_section_freshness` / `_section_intraday` 里的 canvas 是 `<script>` 直接 `new Chart()` 还是有什么 wrapper 已 lazy? 必须先 grep 看现况, 决定 R31 范围。**design in progress → 实测后再 finalize R31 section list.**

## R32 — 30×12 矩阵 `<details>` 折叠

### 边界

| 改 | 不改 |
|---|---|
| `<table class="heatmap">` 外包 `<details><summary>` | R17 颜色 / class / R22-3 组件化 |
| `<summary>` 显示 "▼ 30 分段 × 12 选股日 完整胜率矩阵 (390 cells, 12 选股日)" | 表格内容 cell 值 |
| **CSS** `<details>` / `<summary>` 深色样式 override (现默认是白色 + 黑色三角) | Sentry 玻璃 / rgba 配色 |
| 默认 `open=false` (折叠) → 360 cells 不进 DOM 树 | |

### Style override (新加, 不动现有)

```css
details > summary {
  cursor: pointer; padding: 10px 14px;
  background: rgba(22,27,34,0.5); border-radius: 6px;
  border: 1px solid #21262d; color: #f0f0f5;
  font-weight: 600; font-size: 13px;
}
details > summary:hover { background: rgba(31,111,235,0.15); }
details[open] > summary { border-bottom-left-radius: 0; border-bottom-right-radius: 0; }
```

## R33 — Cache-Control header

### 边界

| 改 | 不改 |
|---|---|
| `app.py` route `/report/<date>` → `response.headers['Cache-Control'] = 'max-age=300'` | data loader / template render |
| (注意: 这个是 report 路由, 不是静态资源; Cache-Control 让浏览器 300s 内重访走 304) | 任何其他 route |
| set Cache-Control 在 `_render_report_html` 结束, Flask response before_send | response body |

### 不要做
- ❌ ETag (超阶段, 含风险 — 留 R34+)
- ❌ Content-Encoding / gzip (中间件做, application-layer 不管)
- ❌ CDN-style 静态资源 cache (web_ui 资源全 inline, 没静态)

## 验证 (V0-V4 + 真 server + 真浏览器)

### V0: stage1 基础设施
- 真浏览器 (Chrome DevTools Performance) 录首屏, 记录当前 baseline (PC 端 DCL ~ ?ms, 4 chart 渲染各 ~?ms)
- curl 9001 记录 HTML size + time_total baseline

### V1: 实现
- R31: 改 report.html head + _section_segment_win.html 4 个 `<script>` 块
- R32: 改 _section_segment_win.html L293-321 包 `<details>`
- R33: 改 app.py `/report/<date>` route

### V2: 验证 (每 commit 后立即)
- git diff (每个 commit 应清晰单 stage)
- ruff 不动 (无 .py 改动只在 R33, .py 改动 ruff 走 1 遍)
- pytest 全绿 (R30 已 30+ 测试)
- kill+restart web_ui (避免 §18.2(d) template cache stale)
- curl 9001 HTML size 验证 (从 363KB → R31 后估 363KB (HTML 体不变, canvas 不在 DOM 但 script 还在) → R32 后估 270KB (矩阵折叠) → R33 后 size 不变只 header 改)

### V3: 真浏览器 (Playwright or manual)
- 打开 Chrome DevTools Performance → 录首屏 → 看 DCL 时长 (期望: < 0.8s vs baseline ?s)
- 录滚动 → 看 chart 渲染时机 (期望: 进入视口前 100px 才渲染)
- 录 30×12 矩阵展开 → 看 360 cells 进 DOM 时间

### V4: 移动端回归 (用户说手机 OK, 不能 regress)
- Chrome DevTools 切换 iPhone X viewport, 录首屏
- 期望: 不卡顿 (Stage 2.1 不应破坏 mobile, canvas lazy 在 mobile 也有触发)

### 退出条件 (任一不达 → 不算完成)

1. ✅ PC DCL 比 baseline 改善 ≥ 30%
2. ✅ PC 滚动到 chart 时**才**渲染 (DevTools Network/Performance 看 chart.js canvas 不在 DCL 时计算)
3. ✅ 30×12 矩阵初始不渲染 (`details` open=false + body 看不到 table)
4. ✅ pytest 全绿
5. ✅ ruff pass
6. ✅ 移动端不 regress (mobile viewport 录屏 vs baseline)

## R30 → R31-R33 audit trail (commit chain)

```
(R30 已有 commit 锚点 — 本次新)
stage2_1_perf_lazy_canvas  web_ui v0.4.8 R31 (perf: lazy canvas — IntersectionObserver + 4 chart 懒渲染)
stage2_2_perf_matrix_fold  web_ui v0.4.8 R32 (perf: 30×12 矩阵折叠 — <details> 默认折叠)
stage2_3_perf_cache_hdr    web_ui v0.4.8 R33 (perf: Cache-Control max-age=300)
```

每条 commit message 标注 `Stage 2.1 / 2.2 / 2.3`, 便于 `git log --grep "Stage 2"` 一键审计。

## 4b — Clarify 超时协议

用户已用 "B" 短答 (karpathy §15 触发 short-answer mode) → 我按 design.md 默认方案落地。

如果用户在 R31-R33 中**任何阶段反馈**, 立即停手 + 听。

**不**做:
- ❌ 加 ETag / CDN / service worker (越 R34+ 阶段)
- ❌ 改 chart.js plugin (chaos, 不验证其他 chart)
- ❌ webpack/bundle split (over-engineering, Flask inline 模式根深)
- ❌ 重构 _section_*.html (越界)

**做**:
- ✅ IntersectionObserver 是 web standard, 无新依赖
- ✅ `<details>` 是 HTML5 原生, 无新依赖
- ✅ Cache-Control header 是 Flask `make_response()` 1 行, 无新依赖

## 相关 reference

- AGENTS.md §7 规范补充结构 (What / How / Don't / Why / When / Examples / Verify)
- karpathy §3 surgical — 用户说 X 只动 X
- karpathy §3b user-said-X — 邻近模块不动, 默认不扩展
- karpathy §4b — 短答模式 + clarify timeout → 默认推进 + audit trail
- karpathy §15 — short-answer mode 触发 (用户连续 2+ 短答)
- karpathy §19 — 6 阶段 (Stage 2 = 性能, 紧跟 Stage 1 = 现代化 R21-R29 已完成)
- karpathy §18.2 — kill+restart 真 server 验证 (避免 template cache stale)
- superpowers/refactor-budget-and-stage-decisions — 1-2 反向 commit 是 cost 不是失败
