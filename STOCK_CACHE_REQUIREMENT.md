# 需求文档: 股票列表缓存定时任务

## 1. 任务概述

### 目标
创建一个定时任务，每日自动获取**所有主板非ST非创业板**的股票列表，生成缓存文件供后续因子分析使用。

### 核心原则
**数据完整性优先** - 必须确保获取的是"所有"主板股票，不能有遗漏。

### 范围

| 包含 | 排除 |
|------|------|
| 沪市主板（60开头） | 创业板（30开头） |
| 深市主板（00开头，含003） | 科创板（688开头） |
| | 北交所（8开头、4开头） |
| | ST类股票（名称含ST、*ST等） |
| | 退市股票（名称含"退市"） |

---

## 2. 定时任务配置

### 运行时间
- **执行日**：周二、周三、周四、周五、周六
- **执行时刻**：凌晨 02:00（避开交易日数据更新高峰，确保前一日数据完整）

### Cron 表达式
```
0 2 * * 2-6
```

说明：
- `0 2` - 凌晨2点整
- `* *` - 每月每日
- `2-6` - 周二到周六（周日=0，周一=1）

### 为什么选周二到周六？
- A股交易日：周一至周五
- 任务目的：获取前一交易日的完整股票列表
- 周二凌晨：获取周一交易日后数据
- 周六凌晨：获取周五交易日后数据
- 周日、周一凌晨不执行：周末无新数据

---

## 3. 数据源

### 新浪财经 API（已验证可用）
```
https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeData
```

### 请求参数
| 参数 | 值 | 说明 |
|------|-----|------|
| page | 1, 2, 3... | 分页获取 |
| num | 80 | 每页数量 |
| sort | symbol | 按代码排序 |
| asc | 1 | 升序 |
| node | hs_a | A股市场 |
| symbol | | 筛选条件 |

### 响应字段（关键字段）
| 字段 | 说明 | 示例 |
|------|------|------|
| symbol | 股票代码 | "600000" |
| name | 股票名称 | "浦发银行" |
| trade | 当前价 | "10.50" |

---

## 4. 数据完整性保障

### 4.1 如何确保获取所有主板股票

**分页策略**：
```python
# 伪代码
all_stocks = []
page = 1
while True:
    data = fetch_page(page, num=80)
    if not data:
        break
    all_stocks.extend(data)
    page += 1
```

**完整获取检查点**：
1. 持续请求直到返回空数据
2. 记录总页数和总数量
3. 与预期数量对比验证

### 4.2 股票筛选规则

```python
def is_valid_main_board_stock(symbol: str, name: str) -> bool:
    """
    判断是否为有效的主板股票
    
    Args:
        symbol: 股票代码（如 "600000"）
        name: 股票名称（如 "浦发银行"）
    
    Returns:
        True: 有效主板股票，应保留
        False: 应剔除
    """
    # 剔除规则 - 先判断剔除条件
    
    # 1. 创业板（30开头）
    if symbol.startswith('30'):
        return False
    
    # 2. 科创板（688开头）
    if symbol.startswith('688'):
        return False
    
    # 3. 北交所（8开头、4开头）
    if symbol.startswith('8') or symbol.startswith('4'):
        return False
    
    # 4. ST类股票
    st_keywords = ['ST', '*ST', 'SST', 'S*ST', 'S']
    for keyword in st_keywords:
        if keyword in name.upper():
            return False
    
    # 5. 退市股票
    if '退市' in name:
        return False
    
    # 保留规则 - 判断是否为主板
    
    # 沪市主板（60开头）
    if symbol.startswith('60'):
        return True
    
    # 深市主板（00开头，含003）
    if symbol.startswith('00'):
        return True
    
    # 其他情况剔除
    return False
```

### 4.3 完整性验证

**预期数量范围**：
- 沪市主板：约 1700-1900 只
- 深市主板：约 1400-1600 只
- **总计：约 3000-3500 只**（动态变化）

**验证机制**：
1. **数量阈值检查**：
   - 总数 < 2800：⚠️ 警告，可能数据缺失
   - 总数 < 2500：❌ 错误，数据不完整，任务失败

2. **分板块统计**：
   - 沪市主板数量
   - 深市主板数量
   - 记录日志供审计

3. **异常代码检测**：
   - 检查是否有30、688、8、4开头的代码混入
   - 检查是否有ST股票名称混入

---

## 5. 缓存格式

### 文件路径
```
~/.openclaw/workspace/yunzhou/factor_ic_analyzer/cache/stock_list.json
```

### JSON 结构
```json
{
  "meta": {
    "generated_at": "2026-04-02T02:00:00+08:00",
    "source": "sina_api",
    "total_count": 3256,
    "sh_count": 1852,
    "sz_count": 1404,
    "api_pages": 41,
    "version": "1.0"
  },
  "stocks": [
    {
      "code": "000001",
      "name": "平安银行",
      "market": "sz",
      "updated_at": "2026-04-01"
    },
    {
      "code": "600000",
      "name": "浦发银行",
      "market": "sh",
      "updated_at": "2026-04-01"
    }
    // ... 更多股票
  ],
  "codes": ["000001", "000002", "000004", ...]
}
```

### 字段说明

**meta 部分**：
| 字段 | 类型 | 说明 |
|------|------|------|
| generated_at | string | 生成时间（ISO 8601） |
| source | string | 数据源标识 |
| total_count | int | 股票总数 |
| sh_count | int | 沪市主板数量 |
| sz_count | int | 深市主板数量 |
| api_pages | int | API请求总页数 |
| version | string | 格式版本号 |

**stocks 部分**：
| 字段 | 类型 | 说明 |
|------|------|------|
| code | string | 股票代码（6位） |
| name | string | 股票名称 |
| market | string | 市场：sh/sz |
| updated_at | string | 数据更新日期 |

**codes 部分**：
- 纯代码数组，便于快速遍历使用

---

## 6. 错误处理

### 6.1 网络错误

```python
# 重试策略
max_retries = 3
retry_delay = 5  # 秒

for attempt in range(max_retries):
    try:
        data = fetch_from_sina_api()
        break
    except NetworkError as e:
        if attempt < max_retries - 1:
            time.sleep(retry_delay * (attempt + 1))
        else:
            raise TaskFailedError(f"API请求失败: {e}")
```

### 6.2 数据验证错误

| 错误类型 | 处理方式 |
|---------|---------|
| 总数异常（<2500） | 任务失败，保留旧缓存，发送告警 |
| API返回空数据 | 重试3次，仍失败则告警 |
| JSON解析失败 | 记录错误日志，任务失败 |
| 文件写入失败 | 重试写入，告警通知 |

### 6.3 告警机制

**告警触发条件**：
- 连续2次任务失败
- 数据完整性验证失败
- 缓存文件超过24小时未更新

**告警方式**（供云舟选择实现）：
- 日志记录到 `logs/stock_cache_error.log`
- 可选：企业微信/钉钉通知
- 可选：邮件通知

---

## 7. 验证检查点

### 7.1 任务执行后自检

```python
def validate_cache(cache_data: dict) -> dict:
    """
    验证缓存数据完整性
    
    Returns:
        验证结果，包含是否通过和详细信息
    """
    result = {
        "passed": True,
        "warnings": [],
        "errors": []
    }
    
    stocks = cache_data["stocks"]
    
    # 1. 数量检查
    total = len(stocks)
    if total < 2800:
        result["warnings"].append(f"股票总数偏低: {total}")
    if total < 2500:
        result["errors"].append(f"股票总数异常: {total}，预期3000+")
        result["passed"] = False
    
    # 2. ST股票混入检查
    st_stocks = [s for s in stocks if 'ST' in s['name'].upper()]
    if st_stocks:
        result["errors"].append(f"发现ST股票混入: {[s['code'] for s in st_stocks[:5]]}")
        result["passed"] = False
    
    # 3. 创业板/科创板混入检查
    invalid_codes = [
        s for s in stocks 
        if s['code'].startswith('30') or s['code'].startswith('688')
    ]
    if invalid_codes:
        result["errors"].append(f"发现创业板/科创板混入: {[s['code'] for s in invalid_codes[:5]]}")
        result["passed"] = False
    
    # 4. 北交所混入检查
    bjb_stocks = [
        s for s in stocks 
        if s['code'].startswith('8') or s['code'].startswith('4')
    ]
    if bjb_stocks:
        result["errors"].append(f"发现北交所股票混入: {[s['code'] for s in bjb_stocks[:5]]}")
        result["passed"] = False
    
    # 5. 市场分布检查
    sh_count = len([s for s in stocks if s['market'] == 'sh'])
    sz_count = len([s for s in stocks if s['market'] == 'sz'])
    
    if sh_count < 1500:
        result["warnings"].append(f"沪市主板数量偏低: {sh_count}")
    if sz_count < 1200:
        result["warnings"].append(f"深市主板数量偏低: {sz_count}")
    
    return result
```

### 7.2 人工可验证项

运行任务后，检查以下指标：

| 检查项 | 预期值 | 查看方式 |
|-------|-------|---------|
| 总股票数 | 3000-3500 | `meta.total_count` |
| 沪市主板 | 1700-1900 | `meta.sh_count` |
| 深市主板 | 1400-1600 | `meta.sz_count` |
| 无ST股票 | 0 | 搜索"name"字段 |
| 无30开头代码 | 0 | 搜索"code"字段 |
| 无688开头代码 | 0 | 搜索"code"字段 |

---

## 8. 实现要求

### 8.1 模块结构

```
factor_ic_analyzer/
├── stock_cache.py          # 主模块
├── cache/                  # 缓存目录
│   └── stock_list.json     # 缓存文件
└── logs/                   # 日志目录
    └── stock_cache.log     # 运行日志
```

### 8.2 主函数签名

```python
def refresh_stock_cache() -> dict:
    """
    刷新股票列表缓存
    
    Returns:
        {
            "success": True/False,
            "total_count": 3256,
            "sh_count": 1852,
            "sz_count": 1404,
            "message": "成功刷新股票列表缓存"
        }
    
    Raises:
        StockCacheError: 缓存刷新失败
    """
    pass
```

### 8.3 日志格式

```
[2026-04-02 02:00:00] INFO  开始刷新股票列表缓存
[2026-04-02 02:00:01] INFO  请求API第1页，获取80条
[2026-04-02 02:00:02] INFO  请求API第2页，获取80条
...
[2026-04-02 02:00:30] INFO  API请求完成，共41页，原始数据3280条
[2026-04-02 02:00:30] INFO  筛选后主板股票3256只（沪1852+深1404）
[2026-04-02 02:00:31] INFO  验证通过，写入缓存文件
[2026-04-02 02:00:31] INFO  刷新完成，耗时31秒
```

### 8.4 集成到定时任务

云舟可选择以下方式之一：

**方案A：使用系统 crontab**
```bash
# 编辑 crontab
crontab -e

# 添加任务
0 2 * * 2-6 cd /home/admin/.openclaw/workspace/yunzhou/factor_ic_analyzer && python stock_cache.py >> logs/cron.log 2>&1
```

**方案B：使用 Python 定时任务库**
```python
# 使用 schedule 或 APScheduler
from apscheduler.schedulers.blocking import BlockingScheduler

scheduler = BlockingScheduler()
scheduler.add_job(
    refresh_stock_cache,
    'cron',
    day_of_week='tue-sat',
    hour=2,
    minute=0
)
scheduler.start()
```

**方案C：OpenClaw 定时任务**
```yaml
# 使用 OpenClaw 的定时任务能力
# 由云舟根据实际框架决定
```

---

## 9. 测试用例（供云汐参考）

### 9.1 正常场景

| 用例 | 操作 | 预期结果 |
|------|------|---------|
| 首次运行 | 执行 `refresh_stock_cache()` | 生成缓存文件，总数3000+ |
| 增量更新 | 再次执行 | 覆盖旧缓存，更新时间戳 |
| 读取缓存 | 加载缓存文件 | 正确解析JSON，获取股票列表 |

### 9.2 异常场景

| 用例 | 模拟条件 | 预期结果 |
|------|---------|---------|
| 网络超时 | 断开网络 | 重试3次后失败，保留旧缓存 |
| API返回空 | Mock空响应 | 告警，任务失败 |
| 磁盘满 | Mock写入失败 | 重试，告警通知 |
| 数据异常 | Mock数据<2000条 | 验证失败，不更新缓存 |

### 9.3 验证场景

| 用例 | 操作 | 预期结果 |
|------|------|---------|
| 无ST股票 | 搜索 "ST" | 结果为空 |
| 无创业板 | 搜索 30开头code | 结果为空 |
| 无科创板 | 搜索 688开头code | 结果为空 |
| 无北交所 | 搜索 8/4开头code | 结果为空 |

---

## 10. 验收标准

- [ ] 定时任务配置正确，周二至周六凌晨2点执行
- [ ] 能正确获取所有主板股票（3000+只）
- [ ] 正确剔除ST、创业板、科创板、北交所股票
- [ ] 缓存文件格式符合规范
- [ ] 数据完整性验证通过
- [ ] 错误处理和重试机制生效
- [ ] 日志记录完整清晰
- [ ] 测试用例全部通过

---

**文档版本**: v1.0  
**创建时间**: 2026-04-02  
**创建者**: 云柏  
**接收者**: 云舟（开发）、云汐（测试）