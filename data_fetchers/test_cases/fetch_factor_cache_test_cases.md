# fetch_factor_cache.py 测试用例

> 版本: v1.0
> 创建时间: 2026-05-26
> 更新时间: 2026-05-26 03:30 北京时间

---

## 测试用例概览

| TC | 类型 | 描述 |
|----|------|------|
| TC001 | 正常 | 分批拉取完整流程 |
| TC002 | 正常 | N-way merge 合并 |
| TC003 | 正常 | 数据验证 |
| TC004 | 正常 | 格式化输出 |
| TC005 | 边界 | 空股票列表 |
| TC006 | 边界 | 单批次拉取 |
| TC007 | 边界 | 内存超阈值处理 |
| TC008 | 异常 | 网络请求失败 |
| TC009 | 异常 | 批次文件损坏 |
| TC010 | 异常 | 最终输出写入失败 |

---

## TC001: 分批拉取完整流程

**前置条件：**
- 网络正常
- 股票列表可用
- cache/factor_data/ 目录存在

**测试步骤：**
1. 执行 `fetch_factor_cache.main()`
2. 检查临时批次文件是否生成
3. 检查最终输出文件是否生成

**预期结果：**
- 批次文件数量 = ceil(股票数 / BATCH_SIZE)
- factor_data.json.gz 存在
- return_data.json.gz 存在
- regenerate_stats.json 存在

---

## TC002: N-way merge 合并

**前置条件：**
- 至少2个批次文件存在
- 批次文件已按 (date, asset) 排序

**测试步骤：**
1. 调用 `n_way_merge_deduplicate(total_batches, 'factor')`
2. 检查合并结果文件

**预期结果：**
- merged_factor.json.gz 存在
- 记录数 = 所有批次去重后的记录数
- 记录按 (date, asset) 排序

---

## TC003: 数据验证

**前置条件：**
- factor_data.json.gz 存在

**测试步骤：**
1. 调用 `validate_final_data()`
2. 检查返回值

**预期结果：**
- is_valid = True（交易日数 >= N_DAYS * 0.9）
- n_days 在合理范围内
- RSI(6) 样本范围 [0, 100]

---

## TC004: 格式化输出

**前置条件：**
- merged_factor.json.gz 存在
- merged_return.json.gz 存在

**测试步骤：**
1. 调用 `format_final_output(factor_merged_path, return_merged_path)`
2. 检查输出文件结构

**预期结果：**
- factor_data.json.gz 包含 meta 和 data 字段
- meta.n_days = 实际交易日数
- meta.fields = ["date", "asset", "open", "close", "high", "low", "rsi_6", "volume_ratio_5"]

---

## TC005: 空股票列表

**前置条件：**
- 股票列表为空

**测试步骤：**
1. 调用 `fetch_batch_stocks(loader, [], 0, 1)`
2. 检查返回值

**预期结果：**
- 返回 (None, None)
- 无批次文件生成

---

## TC006: 单批次拉取

**前置条件：**
- 股票数量 <= BATCH_SIZE

**测试步骤：**
1. 执行单批次拉取
2. 检查临时文件数量

**预期结果：**
- 批次文件数量 = 1
- 合并后记录数 = 批次记录数

---

## TC007: 内存超阈值处理

**前置条件：**
- 模拟内存超阈值场景

**测试步骤：**
1. 设置 MEMORY_THRESHOLD_MB = 100（低阈值）
2. 执行拉取流程
3. 观察内存暂停行为

**预期结果：**
- 检测到内存超阈值
- 执行 GC 和暂停
- 继续执行不中断

---

## TC008: 网络请求失败

**前置条件：**
- 网络不可用或 API 返回错误

**测试步骤：**
1. 模拟网络失败
2. 检查批次拉取结果

**预期结果：**
- fail_count > 0
- 批次文件仍生成（包含成功拉取的数据）

---

## TC009: 批次文件损坏

**前置条件：**
- 某个批次文件损坏（非有效 JSON）

**测试步骤：**
1. 创建损坏的批次文件
2. 调用 `n_way_merge_deduplicate()`
3. 检查异常处理

**预期结果：**
- 损坏批次被跳过
- 合并继续执行
- 日志记录损坏信息

---

## TC010: 最终输出写入失败

**前置条件：**
- 输出目录无写入权限

**测试步骤：**
1. 模拟权限错误
2. 调用 `format_final_output()`
3. 检查异常处理

**预期结果：**
- 抛出 PermissionError 或 OSError
- 日志记录错误信息

---

## 版本历史

- v1.0 (2026-05-26): 测试用例文档创建

---

*最后更新: 2026-05-26 03:30 北京时间*