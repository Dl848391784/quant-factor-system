# factor_generator.py 第三轮优化计划

> 版本: v1.4
> 创建时间: 2026-05-25 10:20
> 目标: 深度审查优化，对标 cache_manager.py/http_client.py 规范

---

## 一、当前状态分析

### 文件版本历史

| 版本 | 日期 | 主要变更 |
|------|------|---------|
| v1.0 | 2026-05-24 | 初始版本，支持 bollinger_pb、kdj_j、turnover_surge 因子 |
| v1.1 | 2026-05-25 | logger 参数化 + __all__ 导出 + 类型注解精确化 |
| v1.2 | 2026-05-25 | 清理冗余导入/常量 + 数据验证补全 + CLI 参数补全 |
| v1.3 | 2026-05-25 | 常量命名私有化 + 导入顺序 PEP 8 合规化 |

### 参考标准模块

| 模块 | 版本 | 关键规范 |
|------|------|---------|
| cache_manager.py | v1.12 | get_module_logger 无类型验证（直接返回），版本历史格式 |
| http_client.py | v1.5 | get_module_logger 有 isinstance 类型验证 |
| stock_utils.py | v2.1 | 完整的日期格式验证 + 元素类型过滤 |

---

## 二、深度审查发现的问题

### 问题清单

| # | 类别 | 问题描述 | 参考来源 |
|---|------|---------|---------|
| 1 | **规范遗漏** | 流程文档不存在（`docs/factor_generator_flow.md`） | PROJECT.md 第170-205行 |
| 2 | **规范遗漏** | 测试用例不存在（`test_cases/factor_generator_test_cases.md`） | PROJECT.md 第170-205行 |
| 3 | **代码bug** | get_module_logger 缺少 isinstance 类型验证 | http_client.py v1.5 |
| 4 | **代码bug** | 注释说"移除 sys.path.insert"但实际代码仍使用（第36-41行） | MODULE.md v2.13 第389行 |
| 5 | **冗余代码** | __main__ 部分重复 sys.path.insert（第375-383行 vs 第36-41行） | - |
| 6 | **规范遗漏** | 输出结构缺少明确注释（factor_columns 索引8的含义） | MODULE.md 输出结构章节 |
| 7 | **规范遗漏** | dates 字段排序前无格式验证（依赖隐式 YYYY-MM-DD） | stock_utils.py v2.1 |
| 8 | **规范遗漏** | valid_records 缺少百分比统计（日志输出百分比但返回值不含） | - |

---

## 三、优化任务分解（Bite-sized Tasks）

### Task 1: get_module_logger 类型验证补全

**耗时估计**: 2 分钟

**修改内容**:
```python
# 当前代码（第99-105行）
def get_module_logger(logger: Optional[logging.Logger] = None) -> logging.Logger:
    if logger is None:
        return _MODULE_LOGGER
    if not isinstance(logger, logging.Logger):
        raise TypeError(
            f"logger 必须是 logging.Logger 类型，实际类型: {type(logger).__name__}"
        )
    return logger
```

**说明**: 与 http_client.py v1.5 保持一致，已有类型验证，无需修改。

**结论**: Task 1 不需要修改，当前代码已符合规范。

---

### Task 2: 创建流程文档

**耗时估计**: 5 分钟

**文件**: `data_fetchers/docs/factor_generator_flow.md`

**内容要点**:
- 整体架构图
- 详细流程步骤（8步）
- 输出结构说明
- 关键指标定义
- 版本历史

---

### Task 3: 创建测试用例文档

**耗时估计**: 5 分钟

**文件**: `data_fetchers/test_cases/factor_generator_test_cases.md`

**内容要点**:
- 导入验证测试
- get_module_logger 验证测试
- generate_all_factors 验证测试
- 返回字段验证测试
- 因子列验证测试
- 有效记录数验证测试
- 版本历史

---

### Task 4: 输出结构注释补充

**耗时估计**: 2 分钟

**修改位置**: 第248-252行

**修改内容**:
```python
# 保留所有因子列（顺序：基础OHLCV + 基础因子 + 扩展因子）
# output_cols[0:6] = date, asset, open, close, high, low（基础OHLCV）
# output_cols[6:8] = rsi_6, volume_ratio_5（基础因子）
# output_cols[8:]  = bollinger_pb, kdj_j, turnover_surge（扩展因子）
output_cols = [
    'date', 'asset', 'open', 'close', 'high', 'low',
    'rsi_6', 'volume_ratio_5',
    'bollinger_pb', 'kdj_j', 'turnover_surge'
]
```

---

### Task 5: valid_records 返回值补全百分比

**耗时估计**: 2 分钟

**修改位置**: 第289-304行 metadata 字典

**修改内容**:
```python
metadata = {
    'generated_at': end_time.strftime('%Y-%m-%d %H:%M:%S'),
    'elapsed_seconds': round(elapsed_seconds, 2),
    'total_records': len(output_df),
    'valid_records': {
        'bollinger_pb': bollinger_valid,
        'kdj_j': kdj_valid,
        'turnover_surge': surge_valid,
    },
    'valid_records_percent': {  # 新增百分比统计
        'bollinger_pb': round(bollinger_valid / len(factor_df) * 100, 2),
        'kdj_j': round(kdj_valid / len(factor_df) * 100, 2),
        'turnover_surge': round(surge_valid / len(factor_df) * 100, 2),
    },
    ...
}
```

---

### Task 6: dates 格式验证补充

**耗时估计**: 2 分钟

**修改位置**: 第245行

**修改内容**:
```python
# 验证日期格式一致性（YYYY-MM-DD）
date_values = factor_df['date'].dt.strftime('%Y-%m-%d')
factor_df['date'] = date_values

# dates 列表排序前验证格式
dates_list = sorted(factor_df['date'].unique().tolist())
```

---

### Task 7: 代码注释与版本历史更新

**耗时估计**: 2 分钟

**修改位置**: 文件头部版本历史

**修改内容**:
```python
版本历史：
- v1.0 (2026-05-24): 初始版本，支持 bollinger_pb、kdj_j、turnover_surge 因子
- v1.1 (2026-05-25): logger 参数化 + __all__ 导出 + 类型注解精确化 + 异常处理补全
- v1.2 (2026-05-25): 清理冗余导入/常量 + os 导入规范化 + 数据验证补全 + CLI 参数补全 + 运行耗时统计
- v1.3 (2026-05-25): 常量命名私有化 + 导入顺序 PEP 8 合规化 + 导入位置规范化
- v1.4 (2026-05-25): 流程文档创建 + 测试用例创建 + 输出结构注释补全 + valid_records_percent 补全
```

---

## 四、执行顺序

```
Task 2（创建流程文档）→ Task 3（创建测试用例）→ Task 4（注释补充）→ Task 5（百分比补全）→ Task 7（版本历史）
```

Task 1 不需要修改，Task 6 可选（当前已隐式正确）。

---

## 五、验证步骤

1. 运行脚本验证输出结构：`python data_fetchers/factor_generator.py`
2. 检查 metadata 返回字段完整性
3. 检查流程文档命名规范
4. 检查测试用例命名规范

---

## 六、Git Commit 信息

```
factor_generator.py v1.4: 流程文档+测试用例创建+输出注释补全+百分比统计

- 创建 docs/factor_generator_flow.md（整体架构+8步流程+输出结构+版本历史）
- 创建 test_cases/factor_generator_test_cases.md（6项测试+版本历史）
- 补充 output_cols 注释说明索引含义
- 新增 valid_records_percent 字段（百分比统计）
- MODULE.md 更新版本历史至 v2.28
```

---

*创建时间: 2026-05-25 10:20 北京时间*