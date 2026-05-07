# 详情 API 性能分析报告

## 问题反馈

用户反馈：选股结果的详情不是打不开，而是比较慢

## 数据量统计

| 数据源 | 文件大小 | 记录数 | 说明 |
|--------|----------|--------|------|
| factor_data.json.gz | 30MB | 1,513,871 条 | 主因子数据 |
| return_data.json.gz | 21MB | - | 收益数据 |
| turnover_rate_data.json.gz | 9.2MB | - | 换手率数据 |
| kdj_j_history.json.gz | 73MB | - | KDJ数据 |
| bollinger_pb_history.json.gz | 23MB | - | 布林带数据 |

**关键指标：**
- 总记录数：1,513,871 条
- 日期数：545 天
- 股票数：3,060 只
- 因子数：6 个

---

## 性能瓶颈分析

### 🔴 问题 1: calculate_scores 方法的 O(n²) 复杂度（最严重）

**位置：** `scoring_engine.py` 第 793-808 行

```python
for idx, row in daily_df.iterrows():  # 遍历 ~3000 只股票
    ...
    for factor_name, factor_col in factor_columns.items():  # 遍历 6 个因子
        ...
        # 🚨 每只股票、每个因子都重新计算一次标准化！
        daily_values = daily_df[factor_col].dropna()
        norm_value = self.normalize(daily_values, normalize_method)  # O(n) 操作
```

**问题：**
- 外层循环：~3000 只股票
- 内层循环：6 个因子
- `normalize` 方法会对 3000 个元素进行 `rank` 操作
- **总计：3000 × 6 × 3000 = 54,000,000 次比较操作**

**正确的做法应该是：** 先对每个因子计算一次标准化，然后再遍历股票。

### 🔴 问题 2: iterrows() 是最慢的遍历方式

**位置：** `scoring_engine.py` 多处

```python
for idx, row in daily_df.iterrows():  # 最慢的遍历方式
```

`iterrows()` 是 pandas 中最慢的遍历方式，比 `itertuples()` 慢 100 倍以上。

### 🟡 问题 3: _get_price_history 效率低

**位置：** `scoring_engine.py` 第 970-987 行

```python
def _get_price_history(self, code: str, days: int = 20) -> List[Dict]:
    stock_df = self.factor_df[self.factor_df['asset'] == code].tail(days)
    
    history = []
    for _, row in stock_df.iterrows():  # iterrows 又出现了
        history.append({...})
    return history
```

虽然只遍历 20 条记录，但：
1. 先在 150 万条数据中过滤
2. 再用 `iterrows()` 遍历

### 🟡 问题 4: 详情 API 不必要的 calculate_scores 调用

**位置：** `web_app.py` 第 3782-3807 行

```python
weights = request.args.get('weights')
if weights:
    score_result = engine.calculate_scores(...)  # 触发 O(n²) 计算
```

前端每次调用详情 API 都会传入 weights 参数，导致每次都触发 `calculate_scores`。

---

## 前端调用链分析

```javascript
// templates/stock_scoring.html 第 1620 行
const weightsParam = encodeURIComponent(JSON.stringify(config.weights));
const apiUrl = `/api/scoring/stock/${code}?date=${date}&weights=${weightsParam}`;
```

**调用流程：**
1. 用户点击"详情"按钮
2. 前端调用 `showStockDetail(code, date)`
3. 请求带上 weights 参数
4. 后端收到 weights 后调用 `calculate_scores`
5. `calculate_scores` 触发 O(n²) 计算
6. 响应延迟 2-5 秒

---

## 优化方案

### 方案 1: 预计算标准化值（推荐，效果最大）

**修改 calculate_scores 方法：**

```python
def calculate_scores(self, date: str, weights: Dict[str, float], ...):
    daily_df = self.factor_df[self.factor_df['date'] == date].copy()
    
    # ✅ 先计算每个因子的标准化值（一次性计算）
    factor_norms = {}
    for factor_name, factor_col in factor_columns.items():
        if factor_col in daily_df.columns:
            daily_values = daily_df[factor_col].dropna()
            factor_norms[factor_name] = self.normalize(daily_values, method)
    
    # ✅ 然后遍历股票，直接使用预计算的标准化值
    for idx, row in daily_df.iterrows():
        for factor_name, factor_col in factor_columns.items():
            if factor_name in factor_norms:
                norm_score = factor_norms[factor_name].get(idx, 0.5)
                # 后续处理...
```

**预期效果：** 性能提升 **100 倍以上**

### 方案 2: 使用向量化计算（最佳）

```python
def calculate_scores(self, date: str, weights: Dict[str, float], ...):
    daily_df = self.factor_df[self.factor_df['date'] == date].copy()
    
    # ✅ 向量化计算所有因子的标准化值
    for factor_name, factor_col in factor_columns.items():
        if factor_col in daily_df.columns:
            # 批量标准化
            daily_df[f'{factor_name}_norm'] = self.normalize(
                daily_df[factor_col].dropna(), method
            )
            # 反向因子反转
            if factor_name in self.REVERSE_FACTORS:
                daily_df[f'{factor_name}_norm'] = 1 - daily_df[f'{factor_name}_norm']
            # 计算 sigmoid 得分
            daily_df[f'{factor_name}_score'] = self.sigmoid_score(
                daily_df[f'{factor_name}_norm'], k_value
            )
    
    # ✅ 向量化计算总得分
    daily_df['total_score'] = sum(
        daily_df[f'{name}_score'] * weights.get(name, 0)
        for name in factor_columns.keys()
        if f'{name}_score' in daily_df.columns
    )
    
    # ✅ 直接排序取 Top N
    top_stocks = daily_df.nlargest(top_n, 'total_score')
    return top_stocks.to_dict('records')
```

**预期效果：** 性能提升 **500 倍以上**

### 方案 3: 详情 API 分离计算

```python
@app.route('/api/scoring/stock/<code>')
def api_scoring_stock_detail(code):
    result = engine.get_stock_detail(code, date)
    
    # ✅ 不再每次都计算全量得分
    # 改为：只在用户查看排名时才计算
    # 或者：缓存当日得分结果
    
    return jsonify(result)

@app.route('/api/scoring/stock/<code>/rank')
def api_scoring_stock_rank(code):
    """单独的排名计算 API，按需调用"""
    weights = request.args.get('weights')
    # 这里才调用 calculate_scores
```

### 方案 4: 缓存当日得分结果

```python
class ScoringEngine:
    def __init__(self):
        self._daily_scores_cache = {}  # {date: {code: score_data}}
        self._cache_date = None
    
    def calculate_scores(self, date: str, weights: Dict[str, float], ...):
        # 检查缓存
        cache_key = f"{date}_{hash(frozenset(weights.items()))}"
        if cache_key in self._daily_scores_cache:
            return self._daily_scores_cache[cache_key]
        
        # 计算并缓存
        result = self._calculate_scores_impl(date, weights, ...)
        self._daily_scores_cache[cache_key] = result
        return result
```

---

## 推荐实施步骤

### 第一步：修复 O(n²) 问题（紧急）

修改 `calculate_scores` 方法，预计算标准化值。

**预期效果：** 从 2-5 秒降到 50-100ms

### 第二步：向量化优化（推荐）

使用 pandas 向量化操作替代循环。

**预期效果：** 降到 10-20ms

### 第三步：添加缓存（可选）

对于相同日期和权重，缓存计算结果。

**预期效果：** 二次请求 < 5ms

---

## 测试建议

优化后应进行以下测试：

1. **单元测试：** 验证计算结果不变
2. **性能测试：** 对比优化前后的响应时间
3. **压力测试：** 连续请求 100 次，检查内存和响应时间

---

## 总结

| 问题 | 影响程度 | 修复难度 | 优先级 |
|------|----------|----------|--------|
| O(n²) 复杂度 | 🔴 严重 | 🟢 低 | P0 |
| iterrows 遍历 | 🟡 中等 | 🟢 低 | P1 |
| 不必要的计算 | 🟡 中等 | 🟢 低 | P1 |
| 无缓存机制 | 🟢 轻微 | 🟡 中 | P2 |

**核心问题：** `calculate_scores` 方法在循环内重复计算标准化值，导致 O(n²) 复杂度。

**解决方案：** 将标准化计算移到循环外，一次性计算所有因子的标准化值，再遍历股票赋值。