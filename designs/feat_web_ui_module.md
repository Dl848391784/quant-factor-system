# web_ui v0.3 设计（v0.2 推翻重写）

> **版本**: v0.3（草案，待审核）
> **创建时间**: 2026-07-04
> **状态**: [experimental]
> **作者**: AI 协作
> **v0.2 已归档**: `designs/archive/feat_web_ui_module_v0.2.md`（**作废**——把 web_ui 当独立子系统设计，违反"复用 summary 展示逻辑"的核心需求）

---

## 1. v0.2 错在哪里（按 PHASE 4 systematic-debugging 复盘）

**v0.2 错误假设**：
- ❌ "web_ui 不调用任何 Python 业务脚本"
- ❌ "web_ui 不依赖 paths.py"
- ❌ "web_ui 自己读 Parquet"

**真实需求**（用户 2026-07-04 二次澄清）：
> "summary 脚本读数据生成 txt 文档，web_ui 读数据生成 HTML 页面——展示逻辑应该一致"

**根因**：我用 codegraph 查 summary 时只查了 `report.*` 子模块的**结构**，没查 summary 的**数据契约**（`data_loaders.load_xxx` 返回什么），也没意识到 web_ui 是 summary 的"前端分支"而非独立子系统。

**v0.3 修复方向**：web_ui = summary 的"另一渲染器"，**复用** `summary/report/data_loaders.py` 和 `formatters.py`，**新增** 1 个 Jinja2 模板 + 1 个最小 Flask 入口。

---

## 2. 核心架构（v0.3）

```
                    ┌──────────────────────────────────────┐
                    │   summary/report/data_loaders.py     │  ← 数据契约源（复用）
                    │   load_ic_results()  → list[dict]    │
                    │   load_backtest_results() → list[dict]│
                    │   load_stock_selection_result() → dict│
                    │   load_weight_selection_result() → dict│
                    └──────────────────┬───────────────────┘
                                       │  list[dict] / dict
                                       │
                  ┌────────────────────┴────────────────────┐
                  │                                         │
                  ▼                                         ▼
      ┌──────────────────────────┐         ┌──────────────────────────┐
      │  summary/report/         │         │  web_ui/                 │
      │  sections.py             │         │  app.py (Flask)          │
      │  _generate_xxx_section() │         │  routes.py               │
      │  → list[str] (txt)       │         │  templates/*.html        │
      │                          │         │   (Jinja2)               │
      │  txt 输出               │         │   HTML 输出              │
      └──────────────────────────┘         └──────────────────────────┘
      ✓ 已有，不动                ✓ 新建（v0.3 任务）
```

**关键约束**：
- ✅ web_ui 复用 `summary/report/data_loaders.py`（**不重写**）
- ✅ web_ui 复用 `summary/report/formatters.py`（**不重写**）
- ❌ web_ui 不读 Parquet（让 data_loaders 干）
- ❌ web_ui 不写自己的 schemas/ 校验（数据已校验过）
- ❌ web_ui 不引入 fastapi（YAGNI，Flask 单文件足矣）

---

## 3. v1 范围（v0.3 收敛版）

**只做 1 个页面**：
- URL: `/` 或 `/selection/2026-07-03`（路由 = 日期）
- 展示：当天 stock_selection 全部 150 行（Stage 1/2/3 × 50）
- 复用：`load_stock_selection_result()`（已存在，return dict）

**其他页面**（v2/v3）：
- IC 排名 / 分层回测 / 综合因子权重 → 用相同模式做（每加一个 = 1 个新模板 + 1 个新路由）

---

## 4. 实施变更清单（按 H9 拆 ≤3 文件 ≤200 行）

### 子任务 1 — 规范层

| 文件 | 操作 | 行数 |
|------|------|------|
| `web_ui/MODULE.md` | **完整重写**（2432 行 factor_ic 复制 → 80 行 web_ui 专属） | -2352 |
| `PROJECT.md` | §目录结构 +1 行（注册 `web_ui/`） | +1 |
| `PROJECT.md` | §业务模块统一约定 + 12 行（"前端模块豁免条款"） | +12 |

**净行数**: -2339

### 子任务 2 — 后端层

| 文件 | 操作 | 行数 |
|------|------|------|
| `web_ui/app.py` | 新建（Flask 入口 + 1 个路由 `/selection/<date>`） | ~50 |
| `pyproject.toml` | 追加 `flask>=3.0,<4` | +1 |

**净行数**: +51

### 子任务 3 — 模板 + 测试

| 文件 | 操作 | 行数 |
|------|------|------|
| `web_ui/templates/selection.html` | 新建（Jinja2 表格） | ~40 |
| `web_ui/test_cases/test_app.py` | 新建（Flask 路由 + 模板渲染测试） | ~50 |
| `web_ui/test_cases/fixtures/` | mock dict | +20 |

**净行数**: +110

**总变更**: 7 个文件，净 +2 行（删除 -2352 错复制 + 写入 +2354 正确内容）。符合 H9。

---

## 5. 关键设计决策

### 5.1 决策 1：复用 data_loaders（不重写读取逻辑）

**web_ui/app.py**：
```python
from summary.report.data_loaders import load_stock_selection_result
from summary.report.formatters import get_date_str
from flask import Flask, render_template, abort

app = Flask(__name__)

@app.route("/selection/<date>")
def show_selection(date: str):
    # 复用 summary 的数据加载器
    result = load_stock_selection_result(logger=app.logger)
    if result is None:
        abort(404)
    return render_template("selection.html", result=result, date=date)
```

**理由**：
- 数据契约唯一来源（data_loaders.py 已有完整校验、错误处理、404 语义）
- summary 改 schema，web_ui 自动同步（**这正是用户说的"展示逻辑一致"**）

### 5.2 决策 2：Flask 而非 FastAPI

- FastAPI 的优势（异步、OpenAPI）在 v1 **用不上**（只有 1 个路由）
- Flask 单文件启动、模板集成最简单
- 未来 v3 切 FastAPI 只需改 30 行（route 改 APIRouter 即可）

### 5.3 决策 3：Jinja2 而非前后端分离

- v1 只展示表格，无交互
- Jinja2 服务端渲染 = 无 JS 框架 = 零构建步骤 = 调试简单
- 未来 v2 加交互时再切前后端分离

### 5.4 决策 4：路由设计

| URL | 展示 |
|-----|------|
| `/` | 重定向到 `/selection/<今天>` |
| `/selection/<date>` | 该日 stock_selection（YYYY-MM-DD） |
| `/selection/latest` | 最新日期（解析 `load_stock_selection_result` 中的 date 字段） |

### 5.5 决策 5：日志

- Flask 自带 logger → `web_ui/logs/app.log`（与现有约定一致）
- **不**引入 logger_config

### 5.6 决策 6：测试

- 测 **路由**：GET `/selection/2026-07-03` 返回 200 + 模板渲染
- 测 **404**：不存在日期 → 404
- 测 **data_loaders 集成**：mock 一次 `load_stock_selection_result` 返回，验证 web_ui 正确传递
- **不**测模板渲染细节（YAGNI）

### 5.7 决策 7：路径与依赖

- ✅ `from summary.report.data_loaders import ...`（项目内导入，H7 风格）
- ❌ 不直接 `from paths import`（H7 是 Python 业务模块的规则，web_ui 走 summary 内部 API）
- ✅ 复用 `summary/report/constants.py` 里的 DATA_PATHS（如果有的话）

---

## 6. 风险与缓解

| 风险 | 严重度 | 缓解 |
|------|--------|------|
| data_loaders 改 schema → web_ui 受影响 | **低**（其实是优势） | 这是设计目标：复用即同步 |
| data_loaders 跑得慢 | 中 | v1 数据量小（150 行），可接受；v2 加缓存 |
| web_ui 与 summary 循环导入 | 低 | data_loaders 是底层，不依赖 web_ui；单向导入安全 |
| 跨 pipeline 适配（default / ob_quality） | 中 | v1 只支持 default；v2 加 `?pipeline=default` query param |
| 部署形态 | 低 | v1 仅 `flask run --host 127.0.0.1`（与 design 一致） |
| 模板中文编码 | 低 | Jinja2 默认 UTF-8，html 头加 `<meta charset="utf-8">` |

---

## 7. 验证清单（每子任务后跑）

### 子任务 1（规范层）
- [ ] `grep "factor_ic" web_ui/MODULE.md` 输出 0 行
- [ ] `grep "web_ui" PROJECT.md` ≥ 2 行
- [ ] `wc -l web_ui/MODULE.md` ≤ 200

### 子任务 2（后端层）
- [ ] `python -c "from web_ui.app import app"` 不报错
- [ ] `flask --app web_ui.app run --host 127.0.0.1` 启动成功
- [ ] `curl http://127.0.0.1:5000/selection/2026-07-03` 返回 200 + HTML
- [ ] `curl http://127.0.0.1:5000/selection/2026-07-99` 返回 404

### 子任务 3（模板 + 测试）
- [ ] `pytest web_ui/test_cases/ -q` 全过
- [ ] 浏览器看到 Stage 1/2/3 三个表格（各 50 行）
- [ ] 切换日期 URL 显示对应日期数据

### 整体
- [ ] `ruff check --fix web_ui/` 0 错
- [ ] `ruff format web_ui/` 已格式
- [ ] `git diff --stat` 显示 7 个文件
- [ ] commit（**不** push）

---

## 8. 不做（明确范围外）

- ❌ IC 值 / 分层回测 / 综合因子展示（v2）
- ❌ FastAPI / JSON API（v3）
- ❌ 前端 JS 框架（v3）
- ❌ 用户认证（v4）
- ❌ 跨 pipeline 切换（v2）
- ❌ 实时刷新 / WebSocket（v4）
- ❌ 移动端适配（v4）
- ❌ Playwright 端到端测试（v3）

---

## 9. 实施顺序（3 commit，不 push）

1. **子任务 1** — 规范层 → `docs(web_ui): 规范层注册与重写`
2. **子任务 2** — 后端层 → `feat(web_ui): Flask 后端复用 summary data_loaders`
3. **子任务 3** — 模板 + 测试 → `feat(web_ui): Jinja2 模板与 pytest`

每子任务前：`ruff check --fix + ruff format + pytest + commit`

---

## 10. 引用

- v0.2 design（已作废）：`designs/archive/feat_web_ui_module_v0.2.md`
- `summary/report/data_loaders.py`（**关键复用目标**）
- `summary/report/formatters.py`（**关键复用目标**）
- `summary/report/sections.py`（**参考实现**，web_ui 模板是其 HTML 版）
- PROJECT.md §目录结构 / §业务模块统一约定 / §H1-H13

---

## 11. 审核签字

- [ ] 用户（云瑶）审核通过本 v0.3 design
- [ ] 确认 v1 范围（只做 stock_selection 1 个页面）
