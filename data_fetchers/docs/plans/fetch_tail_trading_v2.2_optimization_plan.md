# fetch_tail_trading.py 第六轮深度优化计划

> 版本: v2.2
> 创建时间: 2026-05-29 18:00
> 审查轮次: 第六轮（深度迭代审查模式）

---

## 审查发现的问题

| # | 问题 | 位置 | Pitfall | 说明 |
|---|------|------|---------|------|
| 1 | 输出版本号不一致 | 第88行 | Pitfall 169 | `_OUTPUT_VERSION='2.0'` 但版本历史显示 v2.1 |
| 2 | main 异常处理过宽 | 第632行 | Pitfall 175 | 捕获 `requests.RequestException`，但 `load_main_board_stock_list` 是本地文件操作 |
| 3 | CLI 异常处理过宽 | 第719行 | Pitfall 175 | 同样捕获网络异常，但 main 内部已无网络请求 |
| 4 | merge_records 虚假引用 | 第508行 | Pitfall 174 | 引用 `MODULE.md 约束 #93`，但该约束不存在 |

---

## 修复方案

### 1. 输出版本号同步（Pitfall 169）

**问题**：
```python
_OUTPUT_VERSION = '2.0'  # 第88行
```
版本历史已更新到 v2.1，但常量未同步。

**修复**：
```python
_OUTPUT_VERSION = '2.1'  # v2.1: 第六轮深度优化
```

---

### 2. main 函数 Step 1 异常处理精确化（Pitfall 175）

**问题**：
```python
except (requests.RequestException, json.JSONDecodeError, OSError) as e:  # 第632行
```

`load_main_board_stock_list` 从公共模块导入，读取本地缓存文件，不涉及网络请求。

**修复**：
```python
except (json.JSONDecodeError, OSError) as e:
```

---

### 3. CLI 入口异常处理精确化（Pitfall 175）

**问题**：
```python
except (requests.RequestException, json.JSONDecodeError, OSError) as e:  # 第719行
```

main 函数内部已不涉及网络请求（股票列表从本地加载，API 请求在 fetch_tail_trading_batch 内部处理）。

**修复**：
```python
except (json.JSONDecodeError, OSError) as e:
```

---

### 4. merge_records Note 节虚假引用修复（Pitfall 174）

**问题**：
```python
数据源合并逻辑：遵循 MODULE.md 约束 #93  # 第508行
```

MODULE.md 约束编号从 #1 到约 #86，不存在 #93。

**修复**：
删除虚假引用，改为实际说明：
```python
数据源合并逻辑：优先使用现有缓存的 source，若新旧数据源不同则标记为 'mixed'
```

---

## 执行步骤

1. PATCH 第88行：`_OUTPUT_VERSION = '2.0' → '2.1'`
2. PATCH 第632行：删除 `requests.RequestException`
3. PATCH 第719行：删除 `requests.RequestException`
4. PATCH 第508行：删除虚假引用
5. PATCH 版本历史：新增 v2.2 记录
6. RUN pytest 验证
7. GIT commit v2.2

---

## 验证方法

```bash
# 检查输出版本号是否同步
grep -n "_OUTPUT_VERSION" fetch_tail_trading.py

# 检查异常处理是否精确
grep -n "except.*RequestException" fetch_tail_trading.py

# 检查虚假引用是否删除
grep -n "约束 #93" fetch_tail_trading.py

# 运行测试
pytest data_fetchers/test_cases/test_fetch_tail_trading.py -v
```