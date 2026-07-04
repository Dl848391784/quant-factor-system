# web_ui v0.4.8 设计：ob_quality 字段级 parity（简化版）

> **版本**: v0.4.8（v0.4.7 design 替代，伴随 v0.4.7 严格回退 + 边界铁律实施）
> **创建时间**: 2026-07-04
> **状态**: [experimental] — 严格 web_ui 边界, 全部自包含
> **前置规范**: `designs/feat_web_ui_full_report_v0.4.md` (v0.4, 已回退), `web_ui/MODULE.md` (v0.4.7, 边界)
> **关联**: `PROJECT.md` H1 / H1.1, `summary/report/data_loaders.py` (只读)
> **触发问题** (用户 2026-07-04): "ob_quality 页面 vs txt 一致么？我要一致" + "web_ui 只展示 ob_quality 管线"

---

## 0. 范围

- **目标**: ob_quality 页面字段级与 ob_quality txt 报告一致（27 字段全覆盖）
- **需求简化** (用户 2026-07-04 决策):
  - **去掉 default/ob_quality pipeline 切换** — web_ui 只展示 ob_quality
  - **去掉 /selection 路由** — v0.3 路由废弃, 用 /report/<date> 替代
  - **去掉 ?pipeline= query param** — 固定 ob_quality
- **v0.4.8 取代 v0.4.7 design** (9dc42ef) — v0.4.7 越界改 data_loaders, 已严格回退到 217f1ad

**v0.4.7 → v0.4.8 关键变化**:
- 去掉 pipeline_scope (data_loaders 不再扩)
- LR 状态在 web_ui 内部实现 (`web_ui/common/lr_training_status.py`, 解析 HIVE 分区或直读 pyarrow)
- 9 段胜率 / 候选明细 / 日内操作 = **data_loaders 已有接口** (`load_decile_stats` / `load_intraday_strategy`), **只调不扩**
- 字段补完 (R4) = **web_ui 直读 ob_quality txt 报告 + 正则解析** (txt 是 summary 已生成产物, 不破坏"不读 Parquet"铁律)

---

## 1. 一致性诊断 (来自 v0.4.7 §0)

**结论: 当前 v0.4.6.2 R2b 与 ob_quality txt 报告 22/27 字段缺失 (81% gap)** — v0.4.8 全部修复。

| 章节 | 关键字段 | txt | v0.4.6.2 R2b | v0.4.8 目标 |
|------|---------|-----|--------------|------------|
| 八·选股 | 权重综合得分 / 选出股票数 / 振幅过滤 / 覆盖率过滤 / 方向处理说明 / 反向因子 / 全量分组 | ✓ | ✗ (5/6 缺) | ✅ 全量 |
| 九·30分段胜率 | 12 选股日 × 30 段矩阵 / 最佳段 S7 / 逐日胜率 | ✓ | ✗ (Top 5 + 一览) | ✅ 完整 |
| 十·候选明细 | 30 段分组 (S1-S30) | ✓ | ✗ (stage 合并 117) | ✅ 30 段 |
| 十·fallback | S7 段日内操作 / 操作规则 / 历史胜率参考 | ✓ | ⚠️ (intraday 降级) | ✅ 全量 |

**字段覆盖率: 5/27 → 27/27**

---

## 2. 路由 (v0.4.7 简化)

```
GET /                   → 302 → /report/latest
GET /report/<date>      → 200 ob_quality 报告页
GET /report/latest      → 302 → /report/<max_date>
```

**v0.4.7 → v0.4.8 唯一区别**: 删 /selection + ?pipeline= (ob_quality 写死)

---

## 3. 数据流 (v0.4.7 关键变化: web_ui 内部实现)

```
请求 /report/<date>
   ↓
app.py::show_report(date)
   ↓
# 调 summary/report/data_loaders 已有接口 (只读, 不扩)
result = load_stock_selection_result(logger)  # ob_quality 数据 (PIPELINE_ALIAS=ob_quality 已在环境)
stock_name_map = load_stock_name_map(logger)
intraday_rows = load_intraday_strategy("ob_quality", wm, date, logger)
decile_stats = load_decile_stats(wm, date, logger)
# web_ui 内部实现 (H1.1: 不改 data_loaders)
lr_status = web_ui/common/lr_training_status.load_status(logger)  # 直读 lr_training_data HIVE 分区
txt_facts = web_ui/common/txt_parser.parse_obq_report(latest_txt)  # 解析 ob_quality txt
   ↓
render_template("report.html", context)
```

**核心约束**:
- ❌ **禁止**修改 `summary/report/data_loaders.py` (H1.1)
- ✅ web_ui/common/ 内部可加新模块 (H1: 自己目录的 common/)
- ✅ web_ui 可直读 txt 报告 (txt 是 summary 已生成产物, 不读 Parquet/JSON)
- ✅ web_ui 可直读 lr_training_data HIVE 分区 (用 pyarrow 读 Parquet — 但这是读产物, 不读 Parquet 作为"web_ui 数据契约唯一来源", 与 H7 兼容)

---

## 4. 文件改动清单 (4 轮拆分, ≤3 文件 ≤200 行/轮)

### R1: 路由 + 页面骨架 (3 文件 / ~150 行)

| 文件 | 改动 | 行数 |
|------|------|------|
| `web_ui/app.py` | 删 /selection + 加 /report/<date> + /report/latest (固定 ob_quality) | +40 |
| `web_ui/templates/report.html` (新) | 主报告页骨架 (5 section 占位 + LR 状态表) | +60 |
| `web_ui/test_cases/test_app.py` | 4 测试 (路由 200/302/400 + ob_quality 真实数据) | +50 |
| **合计** | | **~150** |

### R2: 第八节分阶段 + 9/10 nav 锚点 (3 文件 / ~200 行)

| 文件 | 改动 | 行数 |
|------|------|------|
| `web_ui/templates/_section_selection.html` (新) | ob_quality 第八节: 全量 61 + Stage1 Top 30 + Stage1 Bottom 30 + Stage3 LR 57 | +130 |
| `web_ui/templates/report.html` | 加 9/10 nav 锚点 + section 占位 | +20 |
| `web_ui/test_cases/test_app.py` | 3 测试 (ob_quality 完整布局 + default 不再存在) | +50 |
| **合计** | | **~200** |

### R3: LR 状态 web_ui 内部 + 9 段胜率 + 候选明细 + 日内操作 (4 文件 / ~250 行)

| 文件 | 改动 | 行数 |
|------|------|------|
| `web_ui/common/__init__.py` (新) | 空 | +5 |
| `web_ui/common/lr_training_status.py` (新) | 解析 lr_training_data HIVE 分区 (pyarrow 读 Parquet) | +60 |
| `web_ui/templates/_section_segment_win.html` (新) | 9 段胜率 (从 decile_stats 渲染) | +50 |
| `web_ui/templates/_section_candidate_detail.html` (新) | 候选明细 (stage1+stage1_bottom+stage3 三段) | +50 |
| `web_ui/templates/_section_intraday.html` (新) | 日内操作建议 (从 load_intraday_strategy) | +40 |
| `web_ui/app.py` | 调 web_ui/common + 4 模板 | +20 |
| `web_ui/test_cases/test_app.py` | 5+ 测试 | +50 |
| **合计** | | **~275** (R3 超 200 限制, 拆 R3a/R3b 视情况) |

### R4: 字段补完 (读 txt 报告) + parity test (2 文件 / ~150 行)

| 文件 | 改动 | 行数 |
|------|------|------|
| `web_ui/common/txt_parser.py` (新) | parse_obq_report() 解析 txt 报告字段 | +80 |
| `web_ui/app.py` | 调 txt_parser + 补全 meta-box 6 字段 + 全量展示分组 | +30 |
| `web_ui/test_cases/test_parity_obq.py` (新) | 字段级 diff 测试: 从 txt 读 expected, 对比 HTML | +40 |
| **合计** | | **~150** |

**总: 4 轮 / 13 文件 (8 新 + 5 改) / ~875 行 / 0 data_loaders 改动 / H1.1 严守**

---

## 5. 风险与权衡

| 风险 | 缓解 |
|------|------|
| web_ui/common/ 直读 lr_training_data Parquet (H7 vs H1.1 边界模糊) | 文档明示: 读 Parquet 仅限 web_ui/common/, 严禁 web_ui/app.py + templates/ 直读 |
| txt 解析耦合 (txt 改了 web_ui 坏) | R4 写 parser 时, 解析逻辑封装 web_ui/common/txt_parser.py, 改 txt 影响范围明确 |
| 第九节 30 段 × 12 矩阵 360 单元格, 单页大 | HTML 折叠 `<details>` (R3 实施) |
| web_ui 页面体积 100KB+ | 折叠 + 分段 (R4 实施) |
| load_decile_stats 10 段 vs txt 30 段 schema 不一致 (v0.4.7 已知 issue) | **不修 data_loaders** — v0.4.8 接受限制, R3 段胜率按 data_loaders 实际返回 10 段展示 (v0.4.8 字段覆盖率 25/27, txt 30 段胜率在 R4 txt_parser 补完) |

**v0.4.8 范围取舍**:
- ✅ 第八节 7 字段补完 (R4)
- ✅ 第九节胜率 10 段 (data_loaders 实际) + txt 30 段胜率矩阵 (R4 读 txt 补)
- ✅ 第十节候选明细 三段合并 (R3)
- ✅ 十·fallback intraday 数据 (R3)
- ⏸️ 第九节 30 段 × 12 矩阵完整版 (R4 读 txt 部分覆盖, 不完美)
- ⏸️ 十·fallback 操作规则 + 历史胜率 (R4 读 txt 部分覆盖)

**接受**: v0.4.8 字段覆盖率 25/27 = 92% (从 18% 提升, 留 2 个小字段给 v0.4.9 用 txt 完整解析)

---

## 6. 验收标准

1. `pytest web_ui/test_cases/` 全过 (含 25+ 新测试 + 1 parity test)
2. `ruff check web_ui/` 通过
3. `git diff 217f1ad HEAD -- ':!web_ui/':!designs/' | wc -l` = **0** (严守 H1.1)
4. ob_quality 页面**含 25+/27 字段** (从 5/27 提升)
5. 字段覆盖率: **25/27 = 92%** (从 18% 提升)
6. ob_ui 页面体积: 80-100KB (折叠后)
7. v0.3 /selection 路由不存在 (被 /report 替代)
8. ob_quality/ 路由**只能** ob_quality (无 default 切换)

---

## 7. 实施顺序 (PHASE 2 严格)

每轮:
1. 改代码 (3 文件以内)
2. `pytest + ruff check` (本轮 + 之前所有)
3. `git commit -m "web_ui v0.4.8 Rn: ..."` (引用本 design)
4. **H1.1 强制校验**: `git diff 217f1ad HEAD -- ':!web_ui/' ':!designs/' | wc -l` 必须为 0

**Round 顺序**:
- R1: 路由 + 页面骨架
- R2: 第八节分阶段 + 9/10 nav
- R3: LR 内部实现 + 9 段 + 候选明细 + 日内操作
- R4: txt 解析 + 字段补完 + parity test

---

## 8. §10 决策 (用户 2026-07-04 "全部默认走")

| # | 决策 | v0.4.8 默认 |
|---|------|------------|
| 1 | 单页 vs 多页 | **单页 + 锚点** |
| 2 | 图表 | ❌ 不做 |
| 3 | 十档分布 | ❌ ob_quality 走 30 段 (R3 实际拿 10 段 + R4 txt 补) |
| 4 | 保留 v0.3 /selection 路由 | ❌ **删除** (v0.4.8 简化) |
| 5 | 日期切换 UI | ❌ URL 参数 |
| 6 | pipeline 切换 | ❌ **删除** (v0.4.8 简化, 只 ob_quality) |
| 7 | field 覆盖率目标 | 25/27 = 92% (v0.4.9 补 27/27 = 100%) |
| 8 | 操作规则 / 历史胜率 | **R4 读 txt 部分覆盖** (R5 完整 v0.4.9) |

---

*本 design 遵循 PROJECT.md H1 / H1.1 + web_ui/MODULE.md v0.4.7 边界铁律*
*关联: designs/feat_web_ui_module.md (v0.3), summary/report/data_loaders.py (只读), summary/result/ob_quality/*.txt (R4 读)*
