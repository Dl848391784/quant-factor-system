# web_ui v1 MVP 设计

> **版本**: v0.2（草案，待审核）
> **创建时间**: 2026-07-04
> **状态**: [experimental]
> **触发规则**: PROJECT.md §主动读取触发条件 — "新增模块" + §H8 — "2+ 文件改动必须先 design.md"
> **作者**: AI 协作
> **前置 design**: `designs/feat_web_ui_module.md`（v0.1 草案）

---

## 1. 背景

`factor_ic_analyzer/web_ui/` 是 2026-07-04 新建的前端展示模块。
- v0.1 design（`designs/feat_web_ui_module.md`）确立了"模块定位 + 规范注册"两步走
- 本 design（v0.2）将"前端模块形态"具体化到 **FastAPI + 纯静态前端 + 读 Parquet 预生成产物** 的 MVP

### 1.1 关键事实（2026-07-04 实测）

- `comprehensive_factor/result/default/stock_selection_history/` 是 Hive 分区 Parquet
- 分区键 = `selection_date=YYYY-MM-DD`（**不是 `date=`**，命名要严格匹配）
- 每天 1 个 part-0.parquet，最新 = `2026-07-03`，**150 行 × 23 列**（Stage 1/2/3 各 Top 50）
- 核心列：`stage / rank / code / composite_value / weight_method / created_at / run_id`
- `factor_values_json` 是字符串形式的因子值快照（前端不直接解析，v1 不展示）

### 1.2 v1 范围（用户 2026-07-04 确认）

- ✅ 展示每天的 stock_selection 结果（3 个 stage 全部展示）
- ❌ IC 值 / 分层回测 / 综合因子（**v1 不做**，迭代到 v2/v3）
- ❌ 不做交互（无筛选、无排序、无搜索）
- ❌ 不写回数据
- ❌ 不动其他模块的代码

---

## 2. 架构设计

### 2.1 数据流（v1）

```
┌─────────────────┐     离线生成（已存在）
│ stock_selector  │ ───────────────────► comprehensive_factor/result/default/
│ (Python 脚本)   │                       stock_selection_history/selection_date=YYYY-MM-DD/
└─────────────────┘                       └─ part-0.parquet (150 行 × 23 列)
                                                  │
                                                  │ 读（只读，不写）
                                                  ▼
┌─────────────────┐
│  web_ui/app.py  │  FastAPI 后端
│  (本 design 新建)│  - /  路由：HTML 页面
└─────────────────┘  - /api/selection/{date}  路由：返回该日 JSON
        │                - /api/selection/latest  路由：返回最新日
        ▼
┌─────────────────┐
│  web_ui/static/ │  纯静态前端
│  - index.html   │  fetch + 简单表格
│  - app.js       │
│  - styles.css   │
└─────────────────┘
```

**关键边界**：
- web_ui **不调用任何 Python 业务脚本**——只读预生成 Parquet
- web_ui **不写入任何业务模块的 result/**——只读
- web_ui **不依赖 paths.py**——Parquet 路径由 `paths.py` 的 `COMPREHENSIVE_FACTOR_RESULT` 解析后注入，**不在 web_ui 内复刻**

### 2.2 技术栈选型

| 层 | 选型 | 理由 |
|----|------|------|
| 后端 | **FastAPI** | 异步、自动 OpenAPI、Pydantic 强类型 |
| 启动 | **uvicorn** | 标准 FastAPI 部署 |
| 前端 | **纯 HTML + JS（vanilla）+ CSS** | MVP 不引框架，零构建步骤 |
| 数据 | **pandas + pyarrow**（已项目内） | 读 Parquet |
| 测试 | **pytest + httpx** | 已有 pytest，httpx 测试 FastAPI 客户端 |
| 依赖管理 | 追加到 `pyproject.toml` `[project] dependencies` | 走 H7 风格 |

### 2.3 目录结构（v1 落地后）

```
web_ui/
├── app.py                    # FastAPI 入口（含 3 个路由）
├── data_loader.py            # Parquet 读取 + 转换
├── schemas.py                # Pydantic response 模型
├── static/
│   ├── index.html            # 主页（含 3 个 stage 切换 Tab）
│   ├── app.js                # fetch + 渲染表格
│   └── styles.css            # 简单样式
├── logs/                     # （已存在，运行时填入）
├── test_cases/               # （已存在，运行时填入）
│   ├── test_app.py           # FastAPI 路由测试
│   ├── test_data_loader.py   # Parquet 读取测试
│   └── fixtures/             # 测试夹具 Parquet
└── MODULE.md                 # 规范（重写：删 factor_ic 复制，写 web_ui 专属）
```

**文件数 = 9 个**（含 MODULE.md，不含 logs/test_cases 空目录）。

### 2.4 三个 API 路由

| 路由 | 方法 | 返回 | 说明 |
|------|------|------|------|
| `/` | GET | HTML | 主页（默认展示最近一日） |
| `/api/selection/latest` | GET | JSON | 最新一日的 stock_selection（按 `max(selection_date)`） |
| `/api/selection/{date}` | GET | JSON | 指定日期的 stock_selection（YYYY-MM-DD 格式） |

**响应 schema**（Pydantic）：
```python
class StockSelectionItem(BaseModel):
    stage: int          # 1/2/3
    rank: int           # 1-50
    code: str           # 股票代码
    composite_value: float
    weight_method: str
    created_at: datetime
    run_id: str

class StockSelectionResponse(BaseModel):
    selection_date: date
    items: list[StockSelectionItem]
    total: int  # 期望 150
    weight_method: str  # 全局统一（来自第一条）
```

---

## 3. 实施变更清单

按 H9（任务粒度 ≤3 文件 ≤200 行），**必须拆成 3 个子任务**执行：

### 子任务 1 — 规范层（先做）

| 文件 | 操作 | 行数 |
|------|------|------|
| `web_ui/MODULE.md` | **完整重写**（2432 行 factor_ic 复制 → 80 行 web_ui 专属） | -2352 |
| `PROJECT.md` | §目录结构 +1 行（注册 `web_ui/`） | +1 |
| `PROJECT.md` | §业务模块统一约定 + 12 行（"前端模块豁免条款"） | +12 |

**净行数**: -2339（删除错误的复制，写入正确的 93 行）

### 子任务 2 — 脚手架层（必做）

| 文件 | 操作 | 行数 |
|------|------|------|
| `web_ui/app.py` | 新建（FastAPI 入口 + 3 路由 + 启动逻辑） | ~80 |
| `web_ui/data_loader.py` | 新建（Parquet 读取 → Pydantic 转换） | ~60 |
| `web_ui/schemas.py` | 新建（2 个 Pydantic 模型） | ~30 |
| `pyproject.toml` | 追加 `fastapi>=0.115,<1` + `uvicorn>=0.30,<1` + `httpx>=0.27,<1` | +3 |

**净行数**: +173

### 子任务 3 — 前端 + 测试（必做）

| 文件 | 操作 | 行数 |
|------|------|------|
| `web_ui/static/index.html` | 新建 | ~50 |
| `web_ui/static/app.js` | 新建 | ~60 |
| `web_ui/static/styles.css` | 新建 | ~40 |
| `web_ui/test_cases/test_app.py` | 新建（3 路由测试） | ~60 |
| `web_ui/test_cases/test_data_loader.py` | 新建（Parquet 读取测试） | ~50 |
| `web_ui/test_cases/fixtures/` | 目录 + 1 个 fixture parquet | ~30 |

**净行数**: +290

**总变更**: 12 个文件，净 +624 行（含删除 -2352），符合 H9（每子任务 ≤200 行）。

---

## 4. 关键设计决策

### 4.1 决策 1：路径来源

**不** 在 web_ui 内复刻 Parquet 路径。改：
- `data_loader.py` 顶部 `from paths import COMPREHENSIVE_FACTOR_RESULT`
- 拼出 `<COMPREHENSIVE_FACTOR_RESULT>/stock_selection_history/`

**理由**：PROJECT.md H7 硬规则要求 `from paths import`（路径单一来源）。

**注意**：PROJECT.md §目录结构 行 321-324 提到 "H7 路径导入待确认"——web_ui 用 `from paths import` 与 H7 文字一致，待路径问题在 H7 正式修复后再调整。本次实施按 H7 当前文字办。

### 4.2 决策 2：日期路由设计

- `/api/selection/latest` 内部扫描 `selection_date=*` 子目录，找最大日期
- `/api/selection/{date}` 校验 `date` 格式（YYYY-MM-DD），查 `selection_date={date}/part-0.parquet`
- **不存在的日期返回 404**（用 FastAPI `HTTPException(status_code=404)`）

### 4.3 决策 3：前端极简

- 不引 React/Vue，**纯 vanilla JS**（`fetch` + DOM 操作）
- 3 个 stage 各 1 个 `<table>`，Tab 切换
- 不做图表（v1 不做，避免 Chart.js 等额外依赖）
- CSS **不**用 Tailwind，**不**用 Bootstrap（手写 40 行 CSS 够用）

### 4.4 决策 4：测试范围

- 测 **API 路由**（3 个）
- 测 **data_loader**（read + transform + 404 场景）
- 测 **fixture**：用 `tmp_path` 生成 1 个 mock parquet（**不**复制真实 Parquet 避免污染测试）
- **不**做端到端 Playwright 测试（v1 范围过大）

### 4.5 决策 5：跨 pipeline 适配

v1 **只**支持 `default` pipeline（`comprehensive_factor/result/default/`）。原因：
- `ob_quality` pipeline 数据格式与 `default` 一致（v0.1 design 调研过）
- 但 v1 范围限定，按"first principles"做最小可用
- v2 迭代再做 pipeline 切换

### 4.6 决策 6：日志

- 启动日志走 uvicorn 自带
- 业务日志（每次 API 请求）走 `web_ui/logs/app.log`（项目惯例）
- **不**引入 logger_config（v1 单文件，YAGNI）

---

## 5. 风险与缓解

| 风险 | 严重度 | 缓解 |
|------|--------|------|
| Parquet 路径命名错（`date=` vs `selection_date=`） | 高 | **已实测**确认 = `selection_date=`，design.md 第 1.1 节记录 |
| 跨 pipeline 数据格式差异 | 低 | v1 只读 `default`，scope 限定 |
| H7 路径导入待确认（PROJECT.md 321-324 行） | 中 | 按 H7 当前文字实施，后续 H7 修复时同步调整 web_ui |
| `factor_values_json` 字符串解析 | 中 | **v1 不解析**，不展示该列；v2 再说 |
| fastapi/uvicorn 装不上（pyproject.toml 缺依赖） | 低 | 实施时跑 `pip install -e .` 验证 |
| Parquet 列 schema 变更（上游加列） | 中 | data_loader 用 Pydantic 严格校验，缺列 → 显式 raise 4 (DataSchemaError) |
| web_ui 被代理到公网 | 高 | v1 仅 `localhost:8000`，**不**部署到公网；v2 加 auth |

---

## 6. 验证清单（每子任务完成后跑）

### 子任务 1 验证
- [ ] `grep "factor_ic" web_ui/MODULE.md` 输出 0 行
- [ ] `grep "web_ui" PROJECT.md` 输出 ≥2 行（目录结构 + 业务模块约定）
- [ ] `wc -l web_ui/MODULE.md` ≤ 200 行

### 子任务 2 验证
- [ ] `python -c "from web_ui.app import app"` 不报错
- [ ] `pip install -e .` 成功
- [ ] `uvicorn web_ui.app:app --host 127.0.0.1 --port 8000` 启动成功
- [ ] `curl http://127.0.0.1:8000/api/selection/latest` 返回 150 行 JSON

### 子任务 3 验证
- [ ] `pytest web_ui/test_cases/ -q` 全过
- [ ] 浏览器打开 `http://127.0.0.1:8000/` 看到 3 个 stage Tab
- [ ] 切换 Tab 看到对应股票列表（每 stage 50 只）

### 整体验证
- [ ] ruff check web_ui/ 0 错
- [ ] ruff format --check web_ui/ 0 差
- [ ] pytest web_ui/test_cases/ -q 全过
- [ ] git diff --stat 显示 12 个文件
- [ ] git commit 成功（**不** push）

---

## 7. 不做（明确范围外）

- ❌ IC 值展示（v2）
- ❌ 分层回测图表（v2/v3）
- ❌ 综合因子权重详情（v2）
- ❌ 用户认证 / 鉴权（v2，公网部署前必须）
- ❌ pipeline 切换（v2）
- ❌ 实时刷新（v2，WebSocket）
- ❌ 历史多日对比（v2）
- ❌ 搜索 / 筛选 / 排序（v2）
- ❌ 移动端适配（v2）
- ❌ Playwright 端到端测试（v2）

---

## 8. 实施顺序（按 superpowers §PHASE 2 Execute）

按 H9 拆 3 个子任务，**每子任务一个 commit**（不 push）：

1. **子任务 1** — 规范层（改 PROJECT.md + 重写 MODULE.md）→ commit `docs(web_ui): 规范层注册与重写`
2. **子任务 2** — 脚手架层（app.py + data_loader.py + schemas.py + 依赖）→ commit `feat(web_ui): FastAPI 后端 + Parquet 读取`
3. **子任务 3** — 前端 + 测试（HTML/JS/CSS + pytest）→ commit `feat(web_ui): 前端 + 测试`

每个 commit 前必跑：
```bash
ruff check --fix web_ui/
ruff format web_ui/
ruff check web_ui/
pytest web_ui/test_cases/ -q
```

---

## 9. 引用

- `designs/feat_web_ui_module.md`（v0.1 草案）
- PROJECT.md §目录结构（行 291-326）
- PROJECT.md §业务模块统一约定（行 316-319）
- PROJECT.md §硬规则 H1/H2/H7/H8/H9/H10/H11/H12（行 380-396）
- `paths.py` 中 `COMPREHENSIVE_FACTOR_RESULT` 常量
- `comprehensive_factor/result/default/stock_selection_history/`（2026-07-04 实测结构）

---

## 10. 审核签字

- [ ] 用户（云瑶）审核通过本 design
- [ ] 实施前最后核查：今天 `selection_date` 最新值（预期 = 2026-07-03 或更新）
