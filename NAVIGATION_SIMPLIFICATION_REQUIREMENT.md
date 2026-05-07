# 导航简化需求文档

## 背景

当前系统有多个入口页面，导航复杂：

| Tab 名称 | 路由 | 模板文件 | 状态 |
|----------|------|----------|------|
| 因子池纵览 | `/` | `index.html` | ❌ 删除 |
| 因子对比 | `/compare` | `compare.html` | ❓ 待定 |
| IC时间序列 | `/rsi-ic` | `rsi_ic.html` | ❌ 删除 |
| 分层回测 | `/layered-backtest` | `layered_backtest.html` | ❌ 删除 |
| 因子分析总览 | `/factor-analysis` | `factor_analysis.html` | ✅ 保留 |

**目标**：简化为单一入口，用户直接进入「因子分析总览」。

---

## 修改清单

### 1. 删除路由（web_app.py）

```python
# 删除以下路由
@app.route('/rsi-ic')  # 第 77 行
@app.route('/layered-backtest')  # 第 153 行
```

### 2. 首页重定向（web_app.py）

```python
# 方案 A：重定向
@app.route('/')
def index():
    from flask import redirect, url_for
    return redirect('/factor-analysis')

# 方案 B：直接渲染（推荐）
@app.route('/')
def index():
    return render_template('factor_analysis.html')
```

### 3. 删除模板文件

```bash
rm templates/rsi_ic.html
rm templates/layered_backtest.html
rm templates/index.html  # 如果采用方案 A，保留重定向页面
```

### 4. 更新导航菜单（所有保留的模板）

**简化后的导航**（只保留必要的）：

```html
<nav>
    <a href="/" class="active">📋 因子分析总览</a>
    <!-- 可选：保留因子对比入口 -->
    <a href="/compare">⚖️ 因子对比</a>
</nav>
```

**需要更新的文件**：
- `templates/factor_analysis.html`（第 509-514 行）
- `templates/compare.html`（如果保留）

### 5. 保留的 API 路由

**重要**：以下 API 路由必须保留，因为前端页面依赖：

```python
# IC 相关 API（被 factor_analysis.html 调用）
@app.route('/api/rsi-ic')  # 第 82 行
@app.route('/api/rsi-ic/progress')  # 第 106 行
@app.route('/api/rsi-ic/refresh')  # 第 128 行

# 分层回测 API（被 factor_analysis.html 调用）
@app.route('/api/layered-backtest')  # 第 158 行
@app.route('/api/layered-backtest/progress')  # 第 234 行
@app.route('/api/layered-backtest/result')  # 第 251 行

# 因子分析 API
@app.route('/api/factor-analysis')  # 第 273 行
@app.route('/api/factor-analysis/progress')  # 第 407 行
@app.route('/api/factor-analysis/result')  # 第 434 行
```

### 6. 保留的 Python 文件

以下文件必须保留（API 依赖）：

```
rsi_ic_generator.py       ✅ 被 /api/rsi-ic 调用
layered_backtest.py      ✅ 被 /api/layered-backtest 调用
real_data_loader.py      ✅ 被多个 API 调用
```

---

## 实施步骤

### 步骤 1：更新首页路由

修改 `web_app.py` 第 36-39 行：

```python
@app.route('/')
def index():
    """首页 - 因子分析总览"""
    return render_template('factor_analysis.html')
```

### 步骤 2：删除冗余路由

删除 `web_app.py` 中的以下函数：

- `rsi_ic()` 函数（第 77-79 行）
- `layered_backtest_page()` 函数（第 153-155 行）

### 步骤 3：更新导航菜单

修改 `templates/factor_analysis.html` 第 509-514 行：

```html
<nav>
    <a href="/" class="active">📋 因子分析总览</a>
    <a href="/compare">⚖️ 因子对比</a>
</nav>
```

同步更新 `templates/compare.html` 的导航菜单。

### 步骤 4：删除冗余模板

```bash
cd ~/.openclaw/workspace/yunzhou/factor_ic_analyzer
rm templates/rsi_ic.html
rm templates/layered_backtest.html
rm templates/index.html  # 可选：保留作为备份
```

### 步骤 5：测试验证

访问以下路径确认：

- [ ] `http://localhost:8765/` → 显示因子分析总览
- [ ] `http://localhost:8765/factor-analysis` → 显示因子分析总览
- [ ] `http://localhost:8765/rsi-ic` → 404（已删除）
- [ ] `http://localhost:8765/layered-backtest` → 404（已删除）
- [ ] API 路由正常工作

---

## 风险评估

| 风险点 | 影响 | 缓解措施 |
|--------|------|----------|
| 用户收藏了旧链接 | 中 | 旧路由返回 404 或重定向到首页 |
| API 路由误删 | 高 | 只删除页面路由，保留所有 `/api/*` |
| 导航菜单不一致 | 低 | 统一更新所有保留模板 |

---

## 验收标准

- [ ] 访问 `/` 直接显示因子分析总览
- [ ] `/rsi-ic` 和 `/layered-backtest` 已移除
- [ ] 所有 `/api/*` 路由正常工作
- [ ] 导航菜单简洁，只显示必要入口
- [ ] 无残留文件或代码

---

**生成时间**：2026-04-02  
**作者**：云柏（需求文档专家）