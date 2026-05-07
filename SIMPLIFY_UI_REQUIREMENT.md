# 需求文档: 简化因子IC分析器UI

## 背景

当前页面有两个按钮【运行分析】和【加载缓存】，用户操作复杂。经过分析发现存在两层缓存机制：
- **因子数据缓存**（`factor_data.json.gz`）- 原始数据
- **分析结果缓存**（`factor_analysis_result.json`）- 计算结果

两层缓存导致逻辑冗余，用户体验可以简化。

## 目标

将两个按钮合并为一个【运行分析】，实现智能化缓存检测，用户只需点击一次即可获得最新结果。

---

## 功能需求

### 1. 删除【加载缓存】按钮

- 移除前端页面中的"加载缓存"按钮
- 简化用户界面，只保留一个【运行分析】按钮

### 2. 【运行分析】智能缓存检测

**逻辑流程**：

```
用户点击【运行分析】
    ↓
检测因子数据缓存（factor_data.json.gz）
    ↓
┌─ 有缓存 → 增量更新（几秒）
│  ↓
│  计算 IC 和分层回测
│
└─ 无缓存 → 全量拉取（首次5分钟）
   ↓
   计算 IC 和分层回测
    ↓
保存分析结果到 factor_analysis_result.json
    ↓
显示图表
```

**关键点**：
- 自动检测 `factor_data.json.gz` 是否存在
- 存在：增量拉取新数据，快速计算
- 不存在：全量拉取500天数据
- 无论哪种情况，计算完成后自动保存结果

### 3. 页面加载时自动显示上次结果

**逻辑流程**：

```
页面加载
    ↓
检测 factor_analysis_result.json 是否存在
    ↓
┌─ 存在 → 自动加载并显示图表
│
└─ 不存在 → 显示空白或提示"请点击运行分析"
```

**用户体验**：
- 用户打开页面，立即看到上次分析结果
- 如需更新，只需点击【运行分析】

---

## 技术需求（给云舟）

### 后端 API

#### 1. 修改运行分析接口

**接口**: `POST /api/factor/analyze`

**返回字段增加**:
```json
{
  "code": 200,
  "data": {
    "ic_analysis": {...},
    "layered_backtest": {...},
    "cache_type": "incremental" | "full",  // 新增：标识本次分析类型
    "data_points": 5000,                   // 新增：数据点数
    "last_update": "2024-01-15 10:30:00"   // 新增：最后更新时间
  }
}
```

**逻辑修改**:
```python
def analyze_factor():
    # 1. 检测因子数据缓存
    if os.path.exists('factor_data.json.gz'):
        # 增量更新
        data = load_incremental_data()
        cache_type = "incremental"
    else:
        # 全量拉取
        data = fetch_full_data()
        cache_type = "full"
    
    # 2. 计算 IC 和分层回测
    result = calculate_ic_and_backtest(data)
    
    # 3. 保存结果
    save_result(result, 'factor_analysis_result.json')
    
    return {
        **result,
        "cache_type": cache_type,
        "last_update": datetime.now()
    }
```

#### 2. 新增获取上次结果接口

**接口**: `GET /api/factor/last_result`

**用途**: 页面加载时自动获取上次分析结果

**返回**:
```json
{
  "code": 200,
  "data": {
    "ic_analysis": {...},
    "layered_backtest": {...},
    "last_update": "2024-01-15 10:30:00"
  }
}
```

或无缓存时:
```json
{
  "code": 404,
  "error": "暂无分析结果"
}
```

### 前端修改

#### 1. 移除按钮

```html
<!-- 删除 -->
<button id="loadCacheBtn">加载缓存</button>

<!-- 保留 -->
<button id="runAnalysisBtn">运行分析</button>
```

#### 2. 页面加载逻辑

```javascript
// 页面加载时自动获取上次结果
document.addEventListener('DOMContentLoaded', async () => {
  try {
    const response = await fetch('/api/factor/last_result');
    if (response.ok) {
      const data = await response.json();
      renderCharts(data.data);
      showLastUpdateTime(data.data.last_update);
    }
  } catch (e) {
    console.log('暂无历史结果');
  }
});
```

#### 3. 运行分析按钮优化

```javascript
// 按钮状态提示
runAnalysisBtn.addEventListener('click', async () => {
  showLoading('正在分析...');
  
  try {
    const response = await fetch('/api/factor/analyze', { method: 'POST' });
    const data = await response.json();
    
    renderCharts(data.data);
    showToast(`分析完成 (${data.data.cache_type === 'incremental' ? '增量更新' : '全量拉取'})`);
  } catch (e) {
    showError('分析失败：' + e.message);
  }
});
```

---

## 测试用例（给云汐）

| 场景 | 前置条件 | 操作 | 预期结果 |
|------|---------|------|---------|
| 首次使用 | 无任何缓存 | 点击【运行分析】 | 按钮显示加载状态，等待约5分钟，显示完整分析结果 |
| 二次使用（有缓存） | 有因子数据缓存 | 点击【运行分析】 | 几秒内完成，显示增量更新后的结果 |
| 页面加载（有历史结果） | 有分析结果缓存 | 打开页面 | 自动显示上次分析结果，底部显示"最后更新时间" |
| 页面加载（无历史结果） | 无分析结果缓存 | 打开页面 | 显示空白或提示"请点击运行分析" |
| 按钮状态 | 任意 | 点击【运行分析】 | 按钮禁用并显示加载中，完成后恢复并可再次点击 |
| 缓存一致性 | 有缓存但数据过期 | 点击【运行分析】 | 自动增量更新，结果正确 |
| 异常处理 | 网络中断 | 点击【运行分析】 | 显示错误提示，不崩溃 |

---

## 验收标准

### 功能验收

- [x] 页面无【加载缓存】按钮
- [x] 只有一个【运行分析】按钮
- [x] 首次运行能正确拉取全量数据
- [x] 二次运行能正确使用增量缓存
- [x] 页面加载时自动显示上次结果（如果有）
- [x] 结果保存到 `factor_analysis_result.json`

### 性能验收

- [x] 首次运行：< 6分钟
- [x] 增量运行：< 10秒
- [x] 页面加载：< 2秒（有缓存时）

### 用户体验验收

- [x] 按钮数量从2个减少到1个
- [x] 操作步骤从"判断是否需要加载缓存"简化为"直接点击运行"
- [x] 打开页面即可看到结果，无需手动加载

---

## 变更影响

### 代码变更

| 文件 | 变更类型 | 说明 |
|------|---------|------|
| `analyzer.html` | 修改 | 删除按钮，添加自动加载逻辑 |
| `analyzer.py` | 修改 | 智能缓存检测，新增获取上次结果接口 |

### 数据变更

- 保留 `factor_data.json.gz`（因子数据缓存）
- 保留 `factor_analysis_result.json`（分析结果缓存）
- 两个缓存文件都会被自动管理

### 用户影响

- **正面**：操作简化，体验提升
- **负面**：无（功能完全保留，只是自动化了）

---

## 备注

- 原有缓存逻辑保留，只是增加了自动检测
- 用户无感知，点击按钮即可获得最新结果
- 如需清除缓存重新分析，可删除 `factor_data.json.gz` 后再运行