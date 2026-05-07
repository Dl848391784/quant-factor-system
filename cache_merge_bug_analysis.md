# 因子数据缓存增量合并 Bug 分析报告

## 问题现象
用户报告凌晨增量更新后：
- 日志显示：缓存日期范围 2025-01-01 ~ 2026-04-01（约1年多）
- 日志显示：缓存大小 0.00 MB
- 实际结果：合并后只有 1 天数据

## 根本原因分析

### 问题1：`_get_cache_date_range` 只读元数据，不验证实际数据

代码位置：`real_data_loader.py` 第 487-505 行

```python
def _get_cache_date_range(self, cache_data: dict) -> Tuple[Optional[str], Optional[str]]:
    meta = cache_data.get('meta', {})
    date_range = meta.get('date_range', {})
    
    if date_range:
        return date_range.get('start'), date_range.get('end')  # ⚠️ 直接返回元数据
    
    # 兼容旧格式：从数据中提取
    data = cache_data.get('data', [])
    if data:
        dates = sorted(set(d.get('date') for d in data if d.get('date')))
        if dates:
            return dates[0], dates[-1]
    
    return None, None
```

**问题**：
- 如果 `meta.date_range` 存在，直接返回，**不检查 `data` 是否为空**
- 导致日志显示 "缓存日期范围: 2025-01-01 ~ 2026-04-01"，但实际数据可能为空

### 问题2：`_merge_cache_data` 没有验证现有数据是否有效

代码位置：`real_data_loader.py` 第 507-586 行

```python
def _merge_cache_data(self, existing_data: dict, ...):
    # 提取现有数据
    existing_factor_records = existing_data.get('factor', {}).get('data', [])
    ...
    existing_factor_df = pd.DataFrame(existing_factor_records) if existing_factor_records else pd.DataFrame()
    
    # 合并数据
    if len(existing_factor_df) > 0:
        combined_factor_df = pd.concat([existing_factor_df, new_factor_df], ignore_index=True)
    else:
        combined_factor_df = new_factor_df  # ⚠️ 只使用新数据！
```

**问题**：
- 如果 `existing_factor_records` 为空（`data` 字段缺失或为空列表）
- 合并结果只有新拉取的增量数据（1天）

### 问题链条

凌晨增量更新时的完整问题链条：

1. **读取缓存文件**（`_load_cache_gzip`）
   - 文件存在，但可能 `data` 字段为空
   - 文件大小很小 → 日志显示 "缓存大小: 0.00 MB"

2. **获取日期范围**（`_get_cache_date_range`）
   - 从元数据读取：`meta.date_range = {'start': '2025-01-01', 'end': '2026-04-01'}`
   - 日志显示 "缓存日期范围: 2025-01-01 ~ 2026-04-01"
   - **但实际 data 字段可能为空！**

3. **设置增量模式**
   - `need_fetch_start_date = '2026-04-01'`
   - `existing_cache = {'factor': factor_cache_data, 'return': return_cache_data}`

4. **拉取增量数据**
   - 只拉取 15 天数据
   - 筛选后只保留 2026-04-01 之后的数据（约 1-3 天）

5. **合并数据**（`_merge_cache_data`）
   - `existing_factor_records = []`（因为 `data` 为空）
   - `combined_factor_df = new_factor_df`（只使用新数据）
   - 结果：只有 1 天数据

6. **保存缓存**
   - 合并后的缓存只有 1 天数据

## 可能的原始原因

为什么凌晨时缓存文件的 `data` 字段为空？

可能情况：
1. **写入中断**：昨天全量生成时，程序在写入 `data` 后、写入 `meta` 前被中断
2. **文件损坏**：gzip 写入过程中出现问题
3. **数据被清空**：其他进程/操作清空了 data 字段
4. **代码 Bug**：保存缓存时出现异常，但 meta 已写入

## 修复建议

### 修复1：`_get_cache_date_range` 应验证实际数据

```python
def _get_cache_date_range(self, cache_data: dict) -> Tuple[Optional[str], Optional[str]]:
    # 首先检查实际数据
    data = cache_data.get('data', [])
    if data:
        dates = sorted(set(d.get('date') for d in data if d.get('date')))
        if dates:
            return dates[0], dates[-1]
    
    # 只有在数据有效时才使用元数据
    meta = cache_data.get('meta', {})
    date_range = meta.get('date_range', {})
    if date_range:
        # 验证元数据与实际数据一致性
        n_days = meta.get('n_days', 0)
        n_assets = meta.get('n_assets', 0)
        if n_days > 0 and n_assets > 0 and len(data) > 0:
            return date_range.get('start'), date_range.get('end')
    
    return None, None
```

### 修复2：增量更新前验证缓存数据有效性

在设置 `existing_cache` 前，应验证 `data` 字段不为空：

```python
# 第 1180 行附近
if cache_end_date < today_str:
    # 验证缓存数据是否有效
    factor_records = factor_cache_data.get('data', [])
    return_records = return_cache_data.get('data', [])
    
    if len(factor_records) > 0 and len(return_records) > 0:
        print(f"  需要增量更新: {cache_end_date} -> {today_str}")
        existing_cache = {
            'factor': factor_cache_data,
            'return': return_cache_data
        }
        need_fetch_start_date = cache_end_date
    else:
        print(f"  ✗ 缓存数据为空（元数据有日期范围但 data 字段为空），将全量拉取")
        cache_start_date = None
        cache_end_date = None
```

### 修复3：保存缓存时确保完整性

在 `_save_cache_gzip` 中添加完整性检查：

```python
def _save_cache_gzip(self, cache_path: str, data: dict) -> None:
    # 验证数据完整性
    records = data.get('data', [])
    meta = data.get('meta', {})
    
    if len(records) == 0:
        raise ValueError(f"缓存数据为空，不应保存！")
    
    if meta.get('n_days', 0) != len(set(r.get('date') for r in records)):
        raise ValueError(f"元数据 n_days 与实际数据不一致！")
    
    # 继续保存...
```

## 验证方法

1. 检查凌晨时缓存文件的实际内容
2. 对比 `meta.n_days` 与 `len(data)` 是否一致
3. 如果不一致，说明数据写入有问题

## 总结

**根本原因**：缓存文件的 `data` 字段为空（或不存在），但 `meta.date_range` 存在，导致：
1. 日志显示日期范围正确（从元数据读取）
2. 合并时只使用新数据（因为 `existing_factor_records = []`）
3. 最终只有 1 天数据

**修复要点**：
1. `_get_cache_date_range` 应验证实际数据而非只读元数据
2. 增量更新前验证 `data` 字段不为空
3. 保存缓存时验证完整性

---

生成时间：2026-04-03
分析者：Subagent