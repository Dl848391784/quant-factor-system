# ic_turnover_surge_1d.py 优化计划

> 生成时间: 2026-05-21 21:30 (北京时间)
> 版本: v1.0

## 诊断结论

基于参照脚本 ic_rsi_1d.py 和 factor-ic-analyzer skill 规范检查，发现以下问题：

### 问题清单

| # | 问题类型 | 位置 | 描述 | 优先级 |
|---|---------|------|------|--------|
| 1 | 代码bug | 第269行 | 日志格式字符串缺少 f-string：`"保存数据到: {output_file}"` → 应为 `f"..."` | P0 |
| 2 | 规范遗漏 | 第269行 | 保存逻辑应使用 `save_ic_result()` 而非裸 `json.dump` | P1 |
| 3 | 代码bug | 第371-386行 | `__main__` 异常处理使用 `logger.error()` 应改为 `logger.exception()` 保留堆栈 | P1 |
| 4 | 规范遗漏 | 全量模式 | 全量模式日志应使用 `result['ic_metrics']` 而非 `ic_result`（虽然代码已正确） | - |

## 修复步骤（Bite-sized Tasks）

### Step 1: 修复日志格式字符串（第269行）
- 时间: 2分钟
- 修改: `"保存数据到: {output_file}"` → `f"保存数据到: {output_file}"`

### Step 2: 使用 save_ic_result 替代裸 json.dump（第269-270行）
- 时间: 3分钟
- 修改: 删除手写保存逻辑，调用 `save_ic_result(result, output_file)`
- 原因: PROJECT.md 强制规范，统一保存逻辑

### Step 3: 修复 __main__ 异常处理（第371-386行）
- 时间: 2分钟
- 修改: `logger.error()` → `logger.exception()`
- 原因: 保留完整堆栈信息，便于调试

### Step 4: 验证 SKIP 模式缓存处理（第279-292行）
- 时间: 1分钟
- 检查: 确认不修改 cached_data，直接返回
- 当前状态: 正确（已有注释"不修改 cached_data"）

### Step 5: 同步更新流程文档
- 时间: 5分钟
- 文件: docs/ic_turnover_surge_1d_flow.md
- 更新: 版本号、时间标注、修复内容说明

### Step 6: Git commit
- 时间: 1分钟
- 命令: `git add -A && git commit -m "..."`

## 验证清单

```
□ 运行脚本验证输出结构
□ 检查日志文件生成正确
□ 检查 JSON 输出格式正确
□ 确认三模式（skip/incremental/full）正常工作
```

## 规范依据

- PROJECT.md 第76-210行：公共模块强制复用规范
- factor-ic-analyzer skill：__main__ 异常处理堆栈保留规范
- factor-ic-analyzer skill：保存逻辑统一规范
- MODULE.md 第845-862行：增量更新返回结构统一规范