# 需求文档: 因子分析数据缓存优化

## 背景

当前因子分析页面存在以下问题：
1. **参数冗余**：用户需要手动选择股票数量和交易日数量，但实际业务场景中这些参数基本固定
2. **重复拉取**：Rank IC 分析和分层回测使用同一份数据，但每次调用都会重新从新浪API拉取，浪费大量时间（约3-5分钟）

## 需求1：简化参数设置

### 删除的功能

| 删除项 | 原默认值 | 删除原因 |
|--------|----------|----------|
| 股票数量选择器 | 500 | 业务场景固定使用全部主板股票 |
| 交易日数量选择器 | 250 | 业务场景固定使用近2年数据 |

### 新的默认值

| 参数 | 新默认值 | 说明 |
|------|----------|------|
| 股票数量 | 0（全部） | 使用当天缓存列表里的所有股票（约3000+只） |
| 交易日数量 | 500 | 近2年数据（约500个交易日） |

### 修改点

#### 后端修改 (web_app.py)

```python
# api_factor_analysis 函数中的参数获取
# 修改前：
n_days = request.args.get('n_days', default=250, type=int)
max_stocks = request.args.get('max_stocks', default=500, type=int)

# 修改后：
n_days = 500  # 固定值，近2年数据
max_stocks = 0  # 固定值，获取全部股票

# api_layered_backtest 函数同理
```

#### 前端修改 (templates/factor_analysis.html)

- 删除 `n_days` 和 `max_stocks` 的输入控件
- 删除相关的参数传递逻辑
- 页面加载时直接调用分析接口，无需用户选择参数

---

## 需求2：数据缓存方案

### 缓存策略

```
cache/
├── stock_list.json           # 股票列表缓存（已有）
├── factor_data_YYYYMMDD.json # 因子数据缓存（新增）
└── return_data_YYYYMMDD.json # 收益数据缓存（新增）
```

### 缓存文件格式

#### factor_data_YYYYMMDD.json

```json
{
  "meta": {
    "generated_at": "2026-04-02T18:00:00",
    "source": "sina_api",
    "n_days": 500,
    "n_assets": 3125,
    "date_range": {
      "start": "2024-04-02",
      "end": "2026-04-02"
    },
    "version": "1.0"
  },
  "data": [
    {"date": "2024-04-02", "asset": "600000", "rsi_6": 45.32},
    {"date": "2024-04-02", "asset": "600001", "rsi_6": 52.18},
    // ... 更多数据
  ]
}
```

#### return_data_YYYYMMDD.json

```json
{
  "meta": {
    "generated_at": "2026-04-02T18:00:00",
    "source": "sina_api",
    "n_days": 500,
    "n_assets": 3125,
    "date_range": {
      "start": "2024-04-02",
      "end": "2026-04-02"
    },
    "version": "1.0"
  },
  "data": [
    {"date": "2024-04-02", "asset": "600000", "forward_return": 0.0123},
    {"date": "2024-04-02", "asset": "600001", "forward_return": -0.0089},
    // ... 更多数据
  ]
}
```

### 缓存读取/写入逻辑

#### 流程图

```
开始分析
    │
    ▼
检查当天缓存是否存在
    │
    ├── 存在 ──────────────────┐
    │       │                   │
    │       ▼                   │
    │   加载缓存文件             │
    │   - factor_data_YYYYMMDD  │
    │   - return_data_YYYYMMDD  │
    │       │                   │
    │       ▼                   │
    │   校验缓存有效性            │
    │   - n_days >= 500         │
    │   - n_assets > 3000       │
    │       │                   │
    │       ├── 有效 ───────────┼──▶ 直接使用缓存数据
    │       │                   │
    │       └── 无效 ──┐         │
    │                   │         │
    └── 不存在 ─────────┘         │
            │                     │
            ▼                     │
    从新浪API拉取数据              │
            │                     │
            ▼                     │
    计算因子和收益                 │
            │                     │
            ▼                     │
    保存到缓存文件                 │
    - factor_data_YYYYMMDD.json   │
    - return_data_YYYYMMDD.json   │
            │                     │
            └─────────────────────┘
```

#### 伪代码

```python
def load_factor_and_return_data(n_days=500):
    """
    加载因子和收益数据（带缓存）
    
    优先级：
    1. 检查当天缓存
    2. 缓存有效则直接使用
    3. 缓存无效或不存在则重新拉取
    """
    cache_date = datetime.now().strftime('%Y%m%d')
    factor_cache_path = f'cache/factor_data_{cache_date}.json'
    return_cache_path = f'cache/return_data_{cache_date}.json'
    
    # Step 1: 检查缓存是否存在
    if os.path.exists(factor_cache_path) and os.path.exists(return_cache_path):
        # Step 2: 加载缓存
        factor_data = load_json(factor_cache_path)
        return_data = load_json(return_cache_path)
        
        # Step 3: 校验缓存有效性
        if validate_cache(factor_data, return_data, n_days):
            print(f"[缓存] 使用当天缓存数据")
            return parse_to_dataframe(factor_data), parse_to_dataframe(return_data)
        else:
            print(f"[缓存] 缓存数据无效，重新拉取")
    
    # Step 4: 缓存不存在或无效，从API拉取
    print(f"[API] 从新浪API拉取数据...")
    loader = RealDataLoader(enable_cache=True)
    factor_df, return_df = loader.load_data_multithreaded(n_days=n_days, max_stocks=0)
    
    # Step 5: 保存缓存
    save_json(factor_cache_path, factor_df.to_dict('records'))
    save_json(return_cache_path, return_df.to_dict('records'))
    print(f"[缓存] 数据已保存到缓存文件")
    
    return factor_df, return_df

def validate_cache(factor_data, return_data, n_days):
    """
    校验缓存有效性
    
    条件：
    1. meta.n_days >= n_days
    2. meta.n_assets >= 3000
    3. 数据完整性（无缺失字段）
    """
    factor_meta = factor_data.get('meta', {})
    return_meta = return_data.get('meta', {})
    
    # 检查交易日数
    if factor_meta.get('n_days', 0) < n_days:
        return False
    
    # 检查股票数量
    if factor_meta.get('n_assets', 0) < 3000:
        return False
    
    # 检查数据完整性
    if len(factor_data.get('data', [])) == 0:
        return False
    if len(return_data.get('data', [])) == 0:
        return False
    
    return True
```

---

## 实现步骤

### 第一阶段：简化参数（预计工作量：0.5小时）

| 步骤 | 文件 | 修改内容 |
|------|------|----------|
| 1 | web_app.py | `api_factor_analysis` 函数参数固定为 n_days=500, max_stocks=0 |
| 2 | web_app.py | `api_layered_backtest` 函数参数固定 |
| 3 | templates/factor_analysis.html | 删除参数选择器UI |

### 第二阶段：缓存实现（预计工作量：1.5小时）

| 步骤 | 文件 | 修改内容 |
|------|------|----------|
| 1 | real_data_loader.py | 新增 `_get_factor_cache_path()` 方法 |
| 2 | real_data_loader.py | 新增 `_get_return_cache_path()` 方法 |
| 3 | real_data_loader.py | 新增 `_save_factor_cache()` 方法 |
| 4 | real_data_loader.py | 新增 `_save_return_cache()` 方法 |
| 5 | real_data_loader.py | 新增 `_load_factor_cache()` 方法 |
| 6 | real_data_loader.py | 新增 `_load_return_cache()` 方法 |
| 7 | real_data_loader.py | 新增 `_validate_cache()` 方法 |
| 8 | real_data_loader.py | 修改 `load_data_multithreaded()` 支持缓存 |
| 9 | web_app.py | 调整 API 使用缓存逻辑 |

### 第三阶段：测试验证（预计工作量：0.5小时）

| 测试场景 | 预期结果 |
|----------|----------|
| 首次访问 | 从API拉取数据，保存缓存 |
| 同一天再次访问 | 直接使用缓存，跳过API拉取 |
| 第二天访问 | 缓存日期过期，重新拉取 |
| 缓存数据不完整 | 自动重新拉取 |

---

## 性能预期

| 场景 | 当前耗时 | 优化后耗时 | 提升 |
|------|----------|------------|------|
| 首次分析 | 3-5分钟 | 3-5分钟 | 无变化 |
| 同一天二次分析 | 3-5分钟 | 5-10秒 | **快18-60倍** |
| Rank IC + 分层回测 | 6-10分钟 | 5-10秒 | **快36-120倍** |

---

## 测试用例（给云汐）

### 功能测试

| 场景 | 操作 | 预期结果 |
|------|------|----------|
| 首次运行因子分析 | 点击"开始分析" | 显示进度条，约3-5分钟完成 |
| 同一天再次运行 | 再次点击"开始分析" | 约5-10秒完成，控制台显示"使用缓存" |
| 查看缓存文件 | 检查 cache/ 目录 | 存在 factor_data_YYYYMMDD.json 和 return_data_YYYYMMDD.json |
| 缓存文件格式 | 打开缓存文件 | JSON格式，包含 meta 和 data 字段 |
| 第二天运行 | 次日点击"开始分析" | 重新拉取数据，生成新日期的缓存文件 |

### 异常测试

| 场景 | 操作 | 预期结果 |
|------|------|----------|
| 缓存文件损坏 | 手动删除部分JSON内容 | 自动重新拉取数据 |
| 缓存目录不存在 | 删除 cache/ 目录 | 自动创建目录并保存缓存 |
| API请求失败 | 模拟网络异常 | 显示错误信息，不使用损坏的缓存 |

---

## 验收标准

- [ ] 前端不再显示参数选择器
- [ ] 分析时默认使用 n_days=500, max_stocks=0
- [ ] 首次运行生成缓存文件
- [ ] 同一天再次运行使用缓存
- [ ] 缓存文件按日期命名
- [ ] 缓存文件包含完整的 meta 信息
- [ ] 第二天自动重新拉取数据
- [ ] 控制台正确显示缓存状态日志

---

## 文档版本

- 创建时间：2026-04-02
- 作者：云柏
- 审核：待审核