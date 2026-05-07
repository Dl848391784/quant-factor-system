# 需求文档: RSI(6) 因子分析总览页面整合

## 背景

当前 RSI(6) 因子分析功能分散在两个独立页面：
1. `/rsi-ic` - Rank IC 时间序列分析
2. `/layered-backtest` - 分层回测分析

两个功能都在验证 RSI(6) 因子的有效性，用户希望整合到一个统一的"因子分析总览"页面，提供完整的因子评估视角。

### 整合价值

- **一站式评估**：用户无需切换页面即可获得完整的因子分析报告
- **数据一致性**：共享同一份底层数据，避免数据不一致问题
- **效率提升**：一次数据加载，多维度展示，减少网络请求次数
- **用户体验**：统一的参数设置，一致的视觉风格

---

## 页面布局设计

### 整体结构

```
+------------------------------------------------------------------+
|                     📊 RSI(6) 因子分析总览                         |
+------------------------------------------------------------------+
|                          参数控制面板                               |
|  [股票数量] [交易日数] [分层数量] [🚀 运行分析] [🔄 刷新数据]         |
+------------------------------------------------------------------+
|                          进度显示区域                               |
|  [进度条] [状态消息] [预计剩余时间]                                  |
+------------------------------------------------------------------+
|                         核心指标卡片组                              |
|  +-------+ +-------+ +-------+ +-------+ +-------+ +-------+       |
|  |IC均值 | | ICIR  | |t-stat | |多空收益| |夏普比率| |单调性 |       |
|  |0.0342| | 0.52  | | 3.15** | | 12.5% | | 1.23  | |  ✓ 通过|       |
|  +-------+ +-------+ +-------+ +-------+ +-------+ +-------+       |
+------------------------------------------------------------------+
|                          图表区域                                   |
|  +----------------------------------+ +------------------------+    |
|  |      📈 IC 时间序列图             | |  📊 分层收益柱状图       |    |
|  |   (每日IC + 20日滚动均值)          | |  (各层年化收益对比)      |    |
|  +----------------------------------+ +------------------------+    |
|  +----------------------------------+ +------------------------+    |
|  |      📈 多空净值曲线              | |  📉 各层净值叠加图       |    |
|  |   (Long-Short 累计净值)           | |  (Layer 1~5 收益对比)   |    |
|  +----------------------------------+ +------------------------+    |
+------------------------------------------------------------------+
|                          数据表格区域                               |
|  +----------------------------------+ +------------------------+    |
|  |      IC 统计指标表                | |   分层统计指标表         |    |
|  |  IC均值 | ICIR | Std | 正比例    | | Layer | 年化 | t | Sharpe|    |
|  +----------------------------------+ +------------------------+    |
+------------------------------------------------------------------+
|                          说明区域                                   |
|  指标说明、显著性标注、数据来源等                                    |
+------------------------------------------------------------------+
```

### 响应式布局

- **大屏幕 (>1400px)**：图表区域 2x2 网格布局
- **中等屏幕 (900-1400px)**：图表区域 2 列，表格区域 2 列
- **小屏幕 (<900px)**：所有元素单列堆叠

---

## 功能整合方案

### 1. 数据统一加载

**现状问题**：
- `/rsi-ic` 页面通过 `/api/rsi-ic` 获取数据
- `/layered-backtest` 页面通过 `/api/layered-backtest` 获取数据
- 两个 API 分别加载股票数据，存在数据不一致风险

**整合方案**：

```python
# 新增统一数据加载 API
@app.route('/api/factor-analysis')
def api_factor_analysis():
    """一次性加载所有因子分析数据"""
    
    # 参数获取
    n_days = request.args.get('n_days', default=250, type=int)
    max_stocks = request.args.get('max_stocks', default=500, type=int)
    num_layers = request.args.get('num_layers', default=5, type=int)
    
    # 统一数据源
    loader = RealDataLoader(...)
    factor_df, return_df = loader.load_data(...)
    
    # 计算 IC 指标
    ic_result = calculate_ic_metrics(factor_df, return_df)
    
    # 执行分层回测
    backtest = LayeredBacktest(num_layers=num_layers)
    layered_result = backtest.run(factor_df, return_df)
    
    # 返回整合结果
    return jsonify({
        'ic_metrics': ic_result,      # IC 统计指标
        'ic_series': ic_series,       # IC 时间序列
        'layered_result': layered_result  # 分层回测结果
    })
```

### 2. 参数统一设置

**参数面板设计**：

```html
<div class="control-panel">
    <div class="control-row">
        <!-- 股票数量 -->
        <div class="control-group">
            <label>股票数量</label>
            <input type="number" id="max_stocks" value="500" min="50" max="3000">
            <span class="hint">A股主板股票，限制数量可加快加载</span>
        </div>
        
        <!-- 交易日数 -->
        <div class="control-group">
            <label>交易日数量</label>
            <input type="number" id="n_days" value="250" min="30" max="750">
            <span class="hint">近 N 个交易日的数据</span>
        </div>
        
        <!-- 分层数量 -->
        <div class="control-group">
            <label>分层数量</label>
            <select id="num_layers">
                <option value="5" selected>5层（每层20%）</option>
                <option value="10">10层（每层10%）</option>
            </select>
            <span class="hint">分层越细，单调性检验更敏感</span>
        </div>
        
        <!-- 运行按钮 -->
        <button class="btn-primary" id="runBtn">
            🚀 运行分析
        </button>
        
        <!-- 刷新按钮 -->
        <button class="btn-secondary" id="refreshBtn">
            🔄 刷新数据
        </button>
    </div>
</div>
```

### 3. 指标卡片整合

**IC 指标卡片（来自 rsi_ic.html）**：

| 指标 | 说明 | 显示格式 | 显著性标注 |
|------|------|----------|------------|
| IC均值 | Rank IC 平均值 | 0.0342 | >0.03 为有效 |
| ICIR | IC 信息比率 | 0.52 | >0.5 为稳定 |
| t-stat | t 统计量 | 3.15** | * p<0.05, ** p<0.01, *** p<0.001 |
| IC>0比例 | 正 IC 占比 | 56.8% | >50% 为正向 |

**分层回测指标卡片（来自 layered_backtest.html）**：

| 指标 | 说明 | 显示格式 | 显著性标注 |
|------|------|----------|------------|
| 多空年化收益 | Layer1 - LayerN | 12.5% | >0 为有效因子 |
| 夏普比率 | 多空组合夏普 | 1.23 | >1 为优秀 |
| 单调性检验 | 分层收益单调性 | ✓ 通过 | 收益递减为通过 |
| 最大回撤 | 多空组合回撤 | -5.2% | <10% 为稳定 |

### 4. 图表整合

**图表区域布局**：

| 图表 | 来源 | 整合位置 | 数据来源 |
|------|------|----------|----------|
| IC 时间序列图 | rsi_ic.html | 左上 | ic_series |
| 分层收益柱状图 | layered_backtest.html | 右上 | layered_result.statistics |
| 多空净值曲线 | layered_backtest.html | 左下 | layered_result.long_short |
| 各层净值叠加图 | layered_backtest.html | 右下 | layered_result.cumulative_returns |

---

## API 接口设计

### 1. 统一分析 API

```
GET /api/factor-analysis

参数:
    n_days: int (默认250) - 交易日数量
    max_stocks: int (默认500) - 股票数量上限
    num_layers: int (默认5) - 分层数量

返回:
{
    "code": 200,
    "data": {
        // IC 分析结果
        "ic_metrics": {
            "ic_mean": 0.0342,
            "ic_std": 0.1120,
            "icir": 0.3054,
            "t_stat": 8.3541,
            "p_value": 0.0001,
            "positive_ratio": 0.568,
            "n_days": 250,
            "n_assets": 500
        },
        
        // IC 时间序列
        "ic_series": {
            "dates": ["2024-01-01", ...],
            "ic_values": [0.012, -0.005, ...],
            "rolling_ic_mean": [0.031, ...]
        },
        
        // 分层回测结果
        "layered_result": {
            "layer_returns": [...],
            "cumulative_returns": [...],
            "statistics": [...],
            "long_short": [...],
            "num_layers": 5,
            "n_days": 250,
            "n_stocks": 500,
            
            // 新增综合指标
            "summary": {
                "long_short_annual_return": 0.125,
                "long_short_sharpe": 1.23,
                "long_short_max_drawdown": -0.052,
                "monotonicity_passed": true
            }
        }
    }
}
```

### 2. 进度查询 API

```
GET /api/factor-analysis/progress

返回:
{
    "status": "running",  // idle, running, completed, error
    "progress": 45,
    "message": "正在执行分层回测...",
    "estimated_remaining_seconds": 30,
    "start_time": 1712345678.9,
    "last_update": "2024-04-02T17:08:00"
}
```

### 3. 缓存结果 API

```
GET /api/factor-analysis/result

返回上次运行的缓存结果（从文件读取）
{
    "code": 200,
    "data": { ... }  // 同 /api/factor-analysis 返回结构
}
```

---

## 前端展示要求

### 1. 视觉风格统一

**配色方案**（延续现有风格）：

```
背景: 深色渐变 (linear-gradient(135deg, #1a1a2e, #16213e))
卡片: rgba(255,255,255,0.05) + backdrop-filter blur
主色调: #00d9ff (科技蓝)
正向色: #00ff88 (成功绿)
负向色: #ff6b6b (警告红)
中性色: #adb5bd (灰色)
```

**字体规范**：

```
标题: 2em, bold, 渐变色
卡片值: 2em, bold, 条件渐变色
说明文字: 1em, #a0a0a0
```

### 2. 交互设计

**进度显示**：

```javascript
// 统一进度管理
async function runAnalysis() {
    showProgressPanel();
    updateProgress(0, '正在加载数据...');
    
    try {
        // 启动分析
        const response = await fetch('/api/factor-analysis?...');
        
        // 轮询进度
        pollProgress();
        
    } catch (error) {
        showError(error);
    }
}

// 进度轮询
async function pollProgress() {
    while (status === 'running') {
        const progress = await fetch('/api/factor-analysis/progress');
        updateProgressUI(progress);
        
        if (progress.status === 'completed') {
            loadResults();
            break;
        }
        
        await sleep(1000);
    }
}
```

**图表交互**：

```javascript
// 图表联动
function setupChartInteraction() {
    // 点击柱状图某一层，高亮对应净值曲线
    barChart.options.onClick = (event, elements) => {
        const layerIndex = elements[0].index;
        highlightLayer(layerIndex);
    };
    
    // 悬停显示详细信息
    // 使用 Chart.js tooltip 配置
}
```

### 3. 数据表格

**IC 统计指标表**：

```
| 指标 | 值 | 说明 | 状态 |
|------|-----|------|------|
| IC均值 | 0.0342 | Rank IC 平均值 | ✓ 有效 (>0.03) |
| IC标准差 | 0.1120 | IC 波动性 | - |
| ICIR | 0.52 | IC均值/IC标准差 | ✓ 稳定 (>0.5) |
| t统计量 | 3.15** | 显著性检验 | ✓ 显著 |
| p值 | 0.001 | 显著性概率 | ✓ 显著 |
| IC>0比例 | 56.8% | 正 IC 占比 | ✓ 正向 (>50%) |
```

**分层统计指标表**：

```
| 分层 | 年化收益 | t统计量 | p值 | 夏普比率 | 标准差 |
|------|----------|---------|-----|----------|--------|
| Layer 1 (最超卖) | 15.2% | 2.31* | 0.021 | 1.12 | 13.5% |
| Layer 2 | 10.5% | 1.85 | 0.065 | 0.78 | 13.5% |
| Layer 3 | 5.3% | 0.92 | 0.358 | 0.39 | 13.5% |
| Layer 4 | -2.1% | -0.36 | 0.718 | -0.16 | 13.5% |
| Layer 5 (最超买) | -8.5% | -1.47 | 0.142 | -0.63 | 13.5% |
| Long-Short | 23.7% | 3.15** | 0.002 | 1.23 | 19.2% |
```

**高亮规则**：

- 年化收益 > 0: `#00ff88` (绿色)
- 年化收益 < 0: `#ff6b6b` (红色)
- p值 < 0.05: 加粗显示
- 多空收益 > 0: 整行高亮

### 4. 单调性检验展示

```html
<div class="monotonicity-indicator">
    <!-- 通过状态 -->
    <span class="pass">✓ 单调性检验通过</span>
    <p>Layer 1 → Layer 5 收益递减，符合因子预期方向</p>
    
    <!-- 失败状态 -->
    <span class="fail">✗ 单调性检验未通过</span>
    <p>存在分层收益反转，因子有效性存疑</p>
</div>
```

---

## 实现步骤

### Phase 1: 后端整合

**任务列表**：

1. **创建统一 API** (`web_app.py`)
   - [ ] 实现 `/api/factor-analysis` 接口
   - [ ] 统一数据加载流程
   - [ ] 整合 IC 计算和分层回测
   - [ ] 添加综合指标计算（单调性检验等）

2. **进度管理**
   - [ ] 实现 `/api/factor-analysis/progress` 接口
   - [ ] 添加进度回调机制
   - [ ] 支持取消正在运行的任务

3. **缓存机制**
   - [ ] 实现 `/api/factor-analysis/result` 接口
   - [ ] 结果保存到 `factor_analysis_result.json`
   - [ ] 页面加载时自动读取缓存结果

### Phase 2: 前端页面

**任务列表**：

1. **创建总览页面** (`templates/factor_analysis.html`)
   - [ ] 参数控制面板
   - [ ] 进度显示区域
   - [ ] 核心指标卡片组（6个）
   - [ ] 图表区域（4个图表）
   - [ ] 数据表格区域（2个表格）
   - [ ] 说明区域

2. **图表实现**
   - [ ] IC 时间序列图（移植自 rsi_ic.html）
   - [ ] 分层收益柱状图（移植自 layered_backtest.html）
   - [ ] 多空净值曲线（移植自 layered_backtest.html）
   - [ ] 各层净值叠加图（移植自 layered_backtest.html）

3. **交互逻辑**
   - [ ] 参数设置联动
   - [ ] 进度实时更新
   - [ ] 图表交互（悬停、点击）
   - [ ] 结果自动刷新

### Phase 3: 集成测试

**任务列表**：

1. **功能测试**
   - [ ] API 返回数据完整性
   - [ ] 指标计算正确性
   - [ ] 图表渲染准确性
   - [ ] 表格数据一致性

2. **性能测试**
   - [ ] 数据加载时间（500股票，250天）
   - [ ] 图表渲染流畅性
   - [ ] 内存占用合理

3. **兼容性测试**
   - [ ] 原有页面功能保留
   - [ ] 导航菜单更新
   - [ ] 移动端适配

---

## 技术需求（给云舟）

### 1. 新增后端接口

```python
# web_app.py 新增

@app.route('/factor-analysis')
def factor_analysis_page():
    """因子分析总览页面"""
    return render_template('factor_analysis.html')


@app.route('/api/factor-analysis', methods=['GET'])
def api_factor_analysis():
    """统一因子分析 API"""
    global factor_analysis_state
    
    # 参数获取
    n_days = request.args.get('n_days', default=250, type=int)
    max_stocks = request.args.get('max_stocks', default=500, type=int)
    num_layers = request.args.get('num_layers', default=5, type=int)
    
    # 状态检查
    if factor_analysis_state['status'] == 'running':
        return jsonify({'success': False, 'error': '分析正在运行中'})
    
    # 启动后台任务
    factor_analysis_state['status'] = 'running'
    thread = threading.Thread(target=run_factor_analysis_task, args=(n_days, max_stocks, num_layers))
    thread.start()
    
    return jsonify({'success': True})


@app.route('/api/factor-analysis/progress')
def api_factor_analysis_progress():
    """获取分析进度"""
    with factor_analysis_lock:
        state = factor_analysis_state.copy()
    return jsonify(state)


@app.route('/api/factor-analysis/result')
def api_factor_analysis_result():
    """获取缓存结果"""
    result_file = BASE_DIR / 'factor_analysis_result.json'
    if result_file.exists():
        with open(result_file, 'r') as f:
            return jsonify(json.load(f))
    return jsonify({'error': '暂无分析结果'})
```

### 2. 综合指标计算

```python
# 新增函数

def calculate_monotonicity(statistics: pd.DataFrame) -> bool:
    """
    检验分层收益单调性
    
    规则:
        对于 RSI(6) 反向因子（低RSI预期高收益）
        Layer 1 (最超卖/最低RSI) 应有最高收益
        Layer N (最超买/最高RSI) 应有最低收益
        
    返回:
        True: 单调递减（符合预期）
        False: 存在反转
    """
    layer_returns = statistics.filter(like='layer_', axis=0)['annual_return']
    returns_list = layer_returns.tolist()
    
    # 检查是否单调递减
    for i in range(len(returns_list) - 1):
        if returns_list[i] < returns_list[i+1]:
            return False
    return True


def calculate_max_drawdown(nav_series: pd.Series) -> float:
    """
    计算最大回撤
    
    公式:
        MaxDD = max(NAV[t] / max(NAV[0:t]) - 1)
    """
    peak = nav_series.expanding(min_periods=1).max()
    drawdown = (nav_series / peak) - 1
    return drawdown.min()


def build_summary(layered_result: LayeredResult) -> dict:
    """
    构建综合指标摘要
    """
    long_short_stats = layered_result.statistics.loc['long_short']
    
    return {
        'long_short_annual_return': long_short_stats['annual_return'],
        'long_short_sharpe': long_short_stats['sharpe'],
        'long_short_max_drawdown': calculate_max_drawdown(
            layered_result.long_short['cumulative_nav']
        ),
        'monotonicity_passed': calculate_monotonicity(layered_result.statistics)
    }
```

### 3. 数据处理

```python
# 日期格式统一处理

def convert_dates_for_json(df_dict: list) -> list:
    """统一转换日期格式为字符串"""
    converted = []
    for row in df_dict:
        new_row = {}
        for k, v in row.items():
            if k == 'date' or k == 'trade_date':
                if hasattr(v, 'strftime'):
                    new_row[k] = v.strftime('%Y-%m-%d')
                elif isinstance(v, str):
                    new_row[k] = v
                else:
                    new_row[k] = str(v)
            else:
                new_row[k] = v
        converted.append(new_row)
    return converted
```

---

## 测试用例（给云汐）

### 正常场景

| 场景 | 操作 | 预期结果 |
|------|------|---------|
| 基础分析 | 设置默认参数，点击运行 | 显示6个核心指标、4个图表、2个表格 |
| 参数调整 | 股票数量改为100，运行 | 数据加载更快，结果正确 |
| 分层10层 | 分层数量改为10，运行 | 10层分层结果，单调性检验更敏感 |
| 刷新数据 | 点击刷新按钮 | 重新获取最新数据，更新所有指标 |

### 边界场景

| 场景 | 操作 | 预期结果 |
|------|------|---------|
| 短时间范围 | 交易日数设为30 | 正常返回，提示样本量较少 |
| 少量股票 | 股票数量设为50 | 正常返回，分层可能不均匀 |
| 已有结果 | 页面加载 | 自动显示上次缓存结果 |

### 异常场景

| 场景 | 操作 | 预期结果 |
|------|------|---------|
| 重复运行 | 分析进行中再次点击运行 | 提示"分析正在运行中，请稍候" |
| 无数据 | 无可用股票数据 | 显示错误提示 |
| 网络错误 | akshare 数据获取失败 | 显示具体错误信息 |

### UI 测试

| 场景 | 操作 | 预期结果 |
|------|------|---------|
| 图表交互 | 点击柱状图某一层 | 对应净值曲线高亮 |
| 悬停提示 | 悬停在数据点 | 显示具体数值和日期 |
| 响应式 | 缩小浏览器窗口 | 自动调整为单列布局 |
| 导航 | 点击顶部导航 | 正确跳转到其他页面 |

---

## 验收标准

### 功能验收

- [ ] 核心指标卡片完整显示（IC均值、ICIR、t-stat、多空收益、夏普比率、单调性）
- [ ] 4个图表正确渲染
- [ ] 2个数据表格数据完整
- [ ] 参数设置功能正常
- [ ] 进度实时更新
- [ ] 缓存结果自动加载

### 数据验收

- [ ] IC 指标计算正确（与原 rsi_ic 页面一致）
- [ ] 分层统计计算正确（与原 layered_backtest 页面一致）
- [ ] 单调性检验逻辑正确
- [ ] 最大回撤计算正确

### UI 验收

- [ ] 视觉风格与现有页面统一
- [ ] 响应式布局适配
- [ ] 图表交互流畅
- [ ] 显著性标注正确显示

### 性能验收

- [ ] 500股票、250天数据加载 < 30秒
- [ ] 图表渲染无明显延迟
- [ ] 页面内存占用 < 100MB

---

## 附录

### A. 原页面保留方案

整合后，原有页面保留作为独立功能入口：

```
导航菜单:
- 首页 (/)
- 因子分析总览 (/factor-analysis) [新增]
- IC分析 (/rsi-ic) [保留]
- 分层回测 (/layered-backtest) [保留]
- 因子对比 (/compare) [保留]
```

### B. 数据文件

```
缓存文件:
- factor_analysis_result.json  # 总览页面整合结果
- rsi_ic_data.json             # IC 原始数据（保留）
- layered_backtest_result.json # 分层回测结果（保留）
```

### C. 关键指标阈值

```
IC有效性判断:
- IC均值 > 0.03: 因子有效
- ICIR > 0.5: 因子稳定
- |t-stat| > 1.96: 95%显著
- |t-stat| > 2.58: 99%显著
- |t-stat| > 3.29: 99.9%显著

分层回测有效性:
- 多空年化收益 > 0: 因子有效
- 夏普比率 > 1: 优秀因子
- 最大回撤 < 10%: 稳定因子
- 单调性检验通过: 因子可信
```

---

## 更新日志

| 日期 | 版本 | 说明 |
|------|------|------|
| 2026-04-02 | v1.0 | 初始版本，整合 RSI(6) IC 和分层回测 |

---

*本文档由云柏生成，供云舟开发、云汐测试使用*

**输出路径**: `~/.openclaw/workspace/yunzhou/factor_ic_analyzer/FACTOR_ANALYSIS_INTEGRATION_REQUIREMENT.md`