# 因子分析网站首页重设计需求文档

> **作者**: 云柏 📝  
> **日期**: 2026-04-03  
> **版本**: v1.0  
> **交付**: 云舟（开发）、云汐（测试）

---

## 1. 项目概述

### 1.1 网站定位

**因子分析网站**是一个量化因子研究平台，旨在为用户提供因子有效性的一站式评估。通过 IC 分析和分层回测，用户可以直观了解因子表现，辅助投资决策。

### 1.2 目标用户

- **量化研究员**：需要快速评估因子有效性
- **个人投资者**：了解技术指标（如 RSI、量比）的预测能力
- **策略开发者**：筛选可用于多因子模型的候选因子

### 1.3 当前问题

| 问题 | 影响 |
|------|------|
| 首页直接重定向到 RSI 分析页 | 用户不知道有哪些因子可用 |
| 缺少统一入口 | 新用户困惑，不知道网站功能 |
| 导航栏无首页链接 | 用户体验不完整 |

### 1.4 设计目标

创建一个**因子总览首页**，作为网站的统一入口，展示所有可用因子，让用户一目了然。

---

## 2. 页面结构

### 2.1 首页（因子总览）

#### 页面路由

- **主路由**: `/` 或 `/home`
- **备选路由**: `/index`（可选）
- **优先级**: 取消当前 `/` → `/factor-analysis` 的重定向，改为直接渲染首页模板

#### 布局设计

```
┌─────────────────────────────────────────────────────────────┐
│                        Header                                │
│  网站标题 + 简介                                             │
├─────────────────────────────────────────────────────────────┤
│                        Nav                                   │
│  [首页] [RSI分析] [量比分析] [因子对比]                       │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌─────────────────┐   ┌─────────────────┐                  │
│  │   RSI(6) 卡片    │   │   量比(5) 卡片   │                  │
│  │                 │   │                 │                  │
│  │  因子名称       │   │  因子名称        │                  │
│  │  简介           │   │  简介            │                  │
│  │  IC均值         │   │  IC均值          │                  │
│  │  ICIR           │   │  ICIR            │                  │
│  │  更新时间       │   │  更新时间        │                  │
│  │  [进入分析]     │   │  [进入分析]      │                  │
│  └─────────────────┘   └─────────────────┘                  │
│                                                             │
│                      Footer                                  │
│  开发者信息 + 数据来源                                       │
└─────────────────────────────────────────────────────────────┘
```

#### 因子卡片设计

每个因子卡片包含以下元素：

| 元素 | 说明 | 样式 |
|------|------|------|
| 因子名称 | 如 `RSI(6)`、`量比(5)` | 大标题，渐变字体 |
| 因子说明 | 一句话解释因子含义 | 灰色小字 |
| IC 均值 | 最新 IC 分析结果的均值 | 数值，颜色区分正负 |
| ICIR | 最新 ICIR 值 | 数值，颜色区分有效/无效 |
| 数据更新时间 | 最近分析运行时间 | 小字，如 `2026-04-03 23:38` |
| 进入分析按钮 | 点击跳转到详情页 | 渐变按钮，悬停动效 |

#### 交互说明

1. **点击卡片**：跳转到对应因子分析页面
2. **点击"进入分析"按钮**：跳转到对应因子分析页面
3. **悬停效果**：卡片轻微上浮 + 阴影增强
4. **加载状态**：如果数据未就绪，显示加载骨架屏

---

### 2.2 导航设计

#### 导航栏结构

| 链接名称 | 路径 | 激活状态 |
|---------|------|---------|
| 🏠 首页 | `/` 或 `/home` | 首页激活 |
| 📋 RSI分析 | `/factor-analysis` | RSI 分析页激活 |
| 📈 量比分析 | `/volume-ratio-analysis` | 量比分析页激活 |
| ⚖️ 因子对比 | `/compare` | 对比页激活 |

#### 导航栏样式

- **位置**: 居中
- **背景**: 模糊玻璃效果 (`backdrop-filter: blur(10px)`)
- **激活状态**: 渐变背景 + 白色文字
- **悬停效果**: 半透明背景

#### 面包屑导航

首页不需要面包屑，子页面需要：

| 页面 | 面包屑 |
|------|--------|
| RSI 分析 | `首页 > RSI(6) 分析` |
| 量比分析 | `首页 > 量比分析` |
| 因子对比 | `首页 > 因子对比` |

---

## 3. 因子卡片设计

### 3.1 RSI(6) 卡片

#### 标题

- **因子名称**: `RSI(6) 超卖反弹因子`
- **图标**: `📊`

#### 简介

- **因子说明**: `RSI(6) 相对强弱指标，低于30为超卖，预期反弹`

#### 指标展示

| 指标 | 格式 | 颜色规则 |
|------|------|---------|
| IC 均值 | `0.0xxx` | >0.03 绿色，>0 灰色，<0 红色 |
| ICIR | `x.xx` | >0.5 绿色（稳定），<0.5 灰色（不稳定） |
| 更新时间 | `YYYY-MM-DD HH:MM` | 灰色小字 |

#### 状态标识

- 如果 IC 均值 > 0.03：显示 `✓ 有效` 标签
- 如果 ICIR > 0.5：显示 `✓ 稳定` 标签

---

### 3.2 量比(5) 卡片

#### 标题

- **因子名称**: `量比(5) 放量因子`
- **图标**: `📈`

#### 简介

- **因子说明**: `当日成交量/5日均值，放量表示资金关注度高`

#### 指标展示

| 指标 | 格式 | 颜色规则 |
|------|------|---------|
| IC 均值 | `0.0xxx` | >0.03 绿色，>0 灰色，<0 红色 |
| ICIR | `x.xx` | >0.5 绿色（稳定），<0.5 灰色（不稳定） |
| 更新时间 | `YYYY-MM-DD HH:MM` | 灰色小字 |

#### 状态标识

- 如果 IC 均值 > 0.03：显示 `✓ 有效` 标签
- 如果 ICIR > 0.5：显示 `✓ 稐` 标签

---

### 3.3 卡片通用样式

```css
.factor-card {
    background: rgba(255,255,255,0.05);
    border-radius: 12px;
    padding: 25px;
    backdrop-filter: blur(10px);
    border: 1px solid rgba(255,255,255,0.1);
    transition: transform 0.3s, box-shadow 0.3s;
}

.factor-card:hover {
    transform: translateY(-5px);
    box-shadow: 0 10px 30px rgba(0, 217, 255, 0.2);
}

.factor-card .name {
    font-size: 1.5em;
    background: linear-gradient(90deg, #00d9ff, #00ff88);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
}

.factor-card .desc {
    color: #a0a0a0;
    font-size: 0.9em;
    margin: 10px 0;
}

.factor-card .metric {
    display: flex;
    justify-content: space-between;
    margin: 8px 0;
}

.factor-card .metric-value.positive {
    color: #00ff88;
}

.factor-card .metric-value.negative {
    color: #ff6b6b;
}
```

---

## 4. API 接口设计

### 4.1 `/api/home/summary`

#### 功能

获取所有因子的摘要数据，用于首页卡片展示。

#### 请求参数

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| 无 | - | - | 无需参数，直接调用 |

#### 返回数据结构

```json
{
    "success": true,
    "data": {
        "factors": [
            {
                "id": "rsi_6",
                "name": "RSI(6)",
                "full_name": "RSI(6) 超卖反弹因子",
                "description": "RSI(6) 相对强弱指标，低于30为超卖，预期反弹",
                "analysis_url": "/factor-analysis",
                "ic_mean": 0.0432,
                "icir": 0.67,
                "ic_positive_ratio": 0.58,
                "long_short_return": 0.0823,
                "monotonicity_passed": true,
                "status": {
                    "effective": true,
                    "stable": true
                },
                "last_updated": "2026-04-03 23:38:12",
                "data_source": "新浪财经API"
            },
            {
                "id": "volume_ratio_5",
                "name": "量比(5)",
                "full_name": "量比(5) 放量因子",
                "description": "当日成交量/5日均值，放量表示资金关注度高",
                "analysis_url": "/volume-ratio-analysis",
                "ic_mean": 0.0287,
                "icir": 0.42,
                "ic_positive_ratio": 0.52,
                "long_short_return": 0.0415,
                "monotonicity_passed": false,
                "status": {
                    "effective": false,
                    "stable": false
                },
                "last_updated": "2026-04-03 23:41:05",
                "data_source": "新浪财经API"
            }
        ],
        "summary": {
            "total_factors": 2,
            "effective_factors": 1,
            "last_global_update": "2026-04-03 23:41:05"
        }
    }
}
```

#### 错误返回

```json
{
    "success": false,
    "error": "无因子分析数据，请先运行分析"
}
```

#### 实现逻辑

1. 读取 `factor_analysis_result.json`（RSI 因子）
2. 读取 `volume_ratio_analysis_result.json`（量比因子）
3. 提取关键指标：`ic_mean`、`icir`、`ic_positive_ratio`
4. 获取文件最后修改时间作为 `last_updated`
5. 组装返回 JSON

---

## 5. 前端实现要点

### 5.1 模板文件

- **文件名**: `templates/home.html`
- **继承**: 独立模板，与现有分析页风格一致

### 5.2 核心代码要点

```javascript
// 页面加载时获取因子摘要
window.onload = async function() {
    await loadFactorSummary();
};

async function loadFactorSummary() {
    try {
        const response = await fetch('/api/home/summary');
        const data = await response.json();
        
        if (data.success) {
            displayFactorCards(data.data.factors);
        } else {
            showError(data.error);
        }
    } catch (error) {
        showError('加载因子数据失败');
    }
}

function displayFactorCards(factors) {
    const container = document.getElementById('factorCards');
    container.innerHTML = '';
    
    factors.forEach(factor => {
        const card = createFactorCard(factor);
        container.appendChild(card);
    });
}

function createFactorCard(factor) {
    const div = document.createElement('div');
    div.className = 'factor-card';
    div.onclick = () => window.location.href = factor.analysis_url;
    
    // IC均值颜色
    const icMeanClass = factor.ic_mean > 0.03 ? 'positive' : 
                        (factor.ic_mean > 0 ? '' : 'negative');
    
    // ICIR颜色
    const icirClass = factor.icir > 0.5 ? 'positive' : '';
    
    div.innerHTML = `
        <div class="card-header">
            <span class="factor-icon">📊</span>
            <h3 class="name">${factor.full_name}</h3>
        </div>
        <p class="desc">${factor.description}</p>
        <div class="metrics">
            <div class="metric">
                <span class="label">IC 均值</span>
                <span class="value ${icMeanClass}">${factor.ic_mean.toFixed(4)}</span>
            </div>
            <div class="metric">
                <span class="label">ICIR</span>
                <span class="value ${icirClass}">${factor.icir.toFixed(2)}</span>
            </div>
            <div class="metric">
                <span class="label">更新时间</span>
                <span class="value time">${factor.last_updated}</span>
            </div>
        </div>
        <button class="btn-enter">进入分析 →</button>
    `;
    
    return div;
}
```

### 5.3 响应式设计

- 大屏（>1200px）：卡片横排，每行2个
- 中屏（768-1200px）：卡片横排，每行1个
- 小屏（<768px）：卡片堆叠

---

## 6. 后端实现要点

### 6.1 路由修改

**文件**: `web_app.py`

```python
# 修改首页路由
@app.route('/')
def home():
    """首页 - 因子总览"""
    return render_template('home.html')

@app.route('/home')
def home_alias():
    """首页别名"""
    return render_template('home.html')
```

### 6.2 API 实现

**文件**: `web_app.py`

```python
@app.route('/api/home/summary')
def api_home_summary():
    """API: 获取因子摘要"""
    try:
        factors = []
        
        # 加载 RSI 因子数据
        rsi_path = BASE_DIR / 'factor_analysis_result.json'
        if rsi_path.exists():
            with open(rsi_path, 'r', encoding='utf-8') as f:
                rsi_data = json.load(f)
            
            rsi_metrics = rsi_data.get('ic_metrics', {})
            rsi_summary = rsi_data.get('layered_result', {}).get('summary', {})
            
            factors.append({
                'id': 'rsi_6',
                'name': 'RSI(6)',
                'full_name': 'RSI(6) 超卖反弹因子',
                'description': 'RSI(6) 相对强弱指标，低于30为超卖，预期反弹',
                'analysis_url': '/factor-analysis',
                'ic_mean': rsi_metrics.get('ic_mean', 0),
                'icir': rsi_metrics.get('icir', 0),
                'ic_positive_ratio': rsi_metrics.get('positive_ratio', 0),
                'long_short_return': rsi_summary.get('long_short_annual_return', 0),
                'monotonicity_passed': rsi_summary.get('monotonicity_passed', False),
                'status': {
                    'effective': rsi_metrics.get('ic_mean', 0) > 0.03,
                    'stable': rsi_metrics.get('icir', 0) > 0.5
                },
                'last_updated': get_file_mtime(rsi_path),
                'data_source': '新浪财经API'
            })
        
        # 加载量比因子数据
        vol_path = BASE_DIR / 'volume_ratio_analysis_result.json'
        if vol_path.exists():
            with open(vol_path, 'r', encoding='utf-8') as f:
                vol_data = json.load(f)
            
            vol_metrics = vol_data.get('ic_metrics', {})
            vol_summary = vol_data.get('layered_result', {}).get('summary', {})
            
            factors.append({
                'id': 'volume_ratio_5',
                'name': '量比(5)',
                'full_name': '量比(5) 放量因子',
                'description': '当日成交量/5日均值，放量表示资金关注度高',
                'analysis_url': '/volume-ratio-analysis',
                'ic_mean': vol_metrics.get('ic_mean', 0),
                'icir': vol_metrics.get('icir', 0),
                'ic_positive_ratio': vol_metrics.get('positive_ratio', 0),
                'long_short_return': vol_summary.get('long_short_annual_return', 0),
                'monotonicity_passed': vol_summary.get('monotonicity_passed', False),
                'status': {
                    'effective': vol_metrics.get('ic_mean', 0) > 0.03,
                    'stable': vol_metrics.get('icir', 0) > 0.5
                },
                'last_updated': get_file_mtime(vol_path),
                'data_source': '新浪财经API'
            })
        
        if not factors:
            return jsonify({
                'success': False,
                'error': '无因子分析数据，请先运行分析'
            })
        
        # 统计摘要
        effective_count = sum(1 for f in factors if f['status']['effective'])
        last_updates = [f['last_updated'] for f in factors]
        
        return jsonify({
            'success': True,
            'data': {
                'factors': factors,
                'summary': {
                    'total_factors': len(factors),
                    'effective_factors': effective_count,
                    'last_global_update': max(last_updates) if last_updates else None
                }
            }
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        })

def get_file_mtime(filepath):
    """获取文件最后修改时间"""
    import os
    from datetime import datetime
    mtime = os.path.getmtime(filepath)
    return datetime.fromtimestamp(mtime).strftime('%Y-%m-%d %H:%M:%S')
```

### 6.3 导航更新

需要修改以下模板文件的导航栏：
- `templates/factor_analysis.html`
- `templates/volume_ratio_analysis.html`
- `templates/compare.html`
- `templates/home.html`（新增）

**导航栏修改示例**：

```html
<nav>
    <a href="/" class="{% if request.path == '/' %}active{% endif %}">🏠 首页</a>
    <a href="/factor-analysis" class="{% if request.path == '/factor-analysis' %}active{% endif %}">📋 RSI分析</a>
    <a href="/volume-ratio-analysis" class="{% if request.path == '/volume-ratio-analysis' %}active{% endif %}">📈 量比分析</a>
    <a href="/compare" class="{% if request.path == '/compare' %}active{% endif %}">⚖️ 因子对比</a>
</nav>
```

---

## 7. 验收标准

### 7.1 功能验收

| 编号 | 验收项 | 预期结果 |
|------|--------|---------|
| F01 | 首页访问 | 访问 `/` 显示因子总览页，不再重定向 |
| F02 | 因子卡片展示 | 显示 RSI(6) 和量比(5) 两个因子卡片 |
| F03 | 卡片数据准确性 | IC均值、ICIR 与分析页一致 |
| F04 | 卡片点击跳转 | 点击 RSI 卡片跳转到 `/factor-analysis` |
| F05 | 卡片按钮跳转 | 点击"进入分析"按钮跳转到对应页面 |
| F06 | 导航首页链接 | 所有页面导航栏都有"首页"链接 |
| F07 | API 数据返回 | `/api/home/summary` 返回正确的 JSON 结构 |
| F08 | 无数据状态 | 无分析数据时显示提示信息 |

### 7.2 UI 验收

| 编号 | 验收项 | 预期结果 |
|------|--------|---------|
| U01 | 暗色渐变背景 | 与分析页风格一致 |
| U02 | 卡片悬停动效 | 悬停时上浮 + 阴影增强 |
| U03 | 数值颜色区分 | IC>0.03 绿色，ICIR>0.5 绿色 |
| U04 | 响应式布局 | 不同屏幕尺寸适配良好 |
| U05 | 加载骨架屏 | 数据加载时显示骨架屏（可选） |

### 7.3 性能验收

| 编号 | 验收项 | 预期结果 |
|------|--------|---------|
| P01 | API 响应时间 | `/api/home/summary` < 100ms |
| P02 | 页面加载时间 | 首页完整加载 < 500ms |

---

## 8. 设计稿（文字描述）

### 8.1 整体风格

- **背景**: 深蓝渐变 (`linear-gradient(135deg, #1a1a2e 0%, #16213e 50%, #0f3460 100%)`)
- **字体**: 系统默认（SF Pro, Segoe UI, Roboto 等）
- **主色调**: 青色 (#00d9ff) + 绿色 (#00ff88) 渐变
- **整体风格**: 科技感、简洁、数据导向

### 8.2 Header 区域

```
┌─────────────────────────────────────────────────────────────┐
│                    📊 因子分析总览                           │
│           一站式量化因子有效性评估平台                        │
└─────────────────────────────────────────────────────────────┘
```

- **标题**: 大号渐变字体，居中
- **简介**: 灰色小字，居中
- **底部间距**: 25px

### 8.3 因子卡片区域

```
┌─────────────────────────────────────────────────────────────┐
│                                                             │
│  ┌─────────────────────────┐  ┌─────────────────────────┐  │
│  │ 📊 RSI(6) 超卖反弹因子   │  │ 📈 量比(5) 放量因子      │  │
│  │                         │  │                         │  │
│  │ RSI低于30为超卖，预期反弹 │  │ 放量表示资金关注度高     │  │
│  │                         │  │                         │  │
│  │ ┌─────────────────────┐ │  │ ┌─────────────────────┐ │  │
│  │ │ IC均值: 0.0432 ✓    │ │  │ │ IC均值: 0.0287      │ │  │
│  │ │ ICIR:   0.67   ✓    │ │  │ │ ICIR:   0.42        │ │  │
│  │ │ 更新:   23:38       │ │  │ │ 更新:   23:41       │ │  │
│  │ └─────────────────────┘ │  │ └─────────────────────┘ │  │
│  │                         │  │                         │  │
│  │ [进入分析 →]            │  │ [进入分析 →]            │  │
│  └─────────────────────────┘  └─────────────────────────┘  │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

- **卡片宽度**: 自适应，最小 280px
- **卡片间距**: 20px
- **卡片背景**: 半透明玻璃效果
- **数值样式**: 数字居右，状态标签居右

### 8.4 Footer 区域

```
┌─────────────────────────────────────────────────────────────┐
│                                                             │
│    🛠️ 云舟开发 | 因子分析总览系统 | 数据来源：新浪财经API    │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

- **文字**: 灰色小字
- **居中**: 水平居中
- **顶部间距**: 30px

---

## 9. 附录

### 9.1 文件清单

| 文件 | 类型 | 说明 |
|------|------|------|
| `templates/home.html` | 新增 | 首页模板 |
| `web_app.py` | 修改 | 添加路由和 API |
| `templates/factor_analysis.html` | 修改 | 导航栏添加首页链接 |
| `templates/volume_ratio_analysis.html` | 修改 | 导航栏添加首页链接 |
| `templates/compare.html` | 修改 | 导航栏添加首页链接 |

### 9.2 预计工作量

| 任务 | 预估时间 |
|------|---------|
| 创建首页模板 | 1 小时 |
| 实现 API | 30 分钟 |
| 修改导航栏 | 30 分钟 |
| 测试验收 | 30 分钟 |
| **总计** | **2.5 小时** |

---

## 10. 给云汐的测试用例

### 测试场景

| 场景编号 | 场景名称 | 操作步骤 | 预期结果 |
|----------|---------|---------|---------|
| TC01 | 首页加载 | 1. 打开浏览器访问 `/` | 显示因子总览页，两个因子卡片 |
| TC02 | 卡片数据验证 | 1. 首页查看 IC均值 2. 进入 RSI 分析页对比 | 数值一致 |
| TC03 | 卡片点击跳转 | 1. 点击 RSI 卡片 | 跳转到 `/factor-analysis` |
| TC04 | 按钮点击跳转 | 1. 点击"进入分析"按钮 | 跳转到对应分析页 |
| TC05 | 导航首页链接 | 1. 在分析页点击"首页" | 返回首页 |
| TC06 | API 响应验证 | 1. 调用 `/api/home/summary` | 返回正确 JSON |
| TC07 | 无数据状态 | 1. 删除结果文件 2. 访问首页 | 显示"无数据"提示 |
| TC08 | 响应式测试 | 1. 缩小浏览器窗口 | 卡片自适应排列 |
| TC09 | 数值颜色 | 1. 检查 IC>0.03 的卡片 | 数值显示绿色 |
| TC10 | 悬停效果 | 1. 鼠标悬停卡片 | 卡片上浮 + 阴影 |

---

**文档结束**

> 📝 云柏输出  
> 🚀 云舟接收开发  
> 🧪 云汐执行测试