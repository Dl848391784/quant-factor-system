# Design: glibc malloc 碎片 OOM 修复（模式 7）

## 问题

`composite_rolling_icir_weight_1d.py` 在标准化阶段被 OOM SIGKILL（~6.1GB anon-rss）。
根因：`standardize_factors` 两次调用（auto_select 72因子 + 主流程 35因子 = 107次循环），
每次循环 `gc.collect()` 回收 Python 对象但不归还 glibc arena 碎片给 OS，RSS 只增不减。

- 活跃数据仅 ~600MB，glibc 碎片占 ~5.6GB
- 已有 v2.49-v2.51 的 del+gc.collect() 修复，但对 glibc 碎片无效

## 修复方案

pandas-oom skill 模式 7：在 `gc.collect()` 后加 `ctypes.CDLL("libc.so.6").malloc_trim(0)`。

### 改动点

**文件 1: `comprehensive_factor/common/factor_loader.py`**
- 位置：`standardize_factors` 函数循环末尾（L854 `gc.collect()` 之后）
- 改动：加 `malloc_trim(0)` 调用
- 封装为模块级辅助函数 `_trim_arena()`，避免重复 ctypes 加载

**文件 2: `comprehensive_factor/common/composite_runner.py`**
- 位置：auto_select 结束释放中间数据后（L418 `gc.collect()` 之后）
- 改动：加 `_trim_arena()` 调用，确保第一次标准化的碎片在第二次标准化前归还 OS

### 不改的

- `weight_engine.py` 的 `RollingICIRWeightMethod.calculate` 内的 `gc.collect()` 不加——
  那里是单次调用（非循环），且已用 pd.concat 批量添加（模式 3c），碎片不严重
- 不设 `MALLOC_TRIM_THRESHOLD_` 环境变量——改动面大，需改启动脚本，且 malloc_trim 已足够

## 影响范围

```
□ 短名单 (30~50) ← 量化职责（间接：修复后 rolling_icir 可正常产出 composite 结果）
□ 最终持仓 (3~5) ← 用户职责
□ Layer 1 候选池 (549) ← 量化基础设施
```

## 验证

1. ruff check + format
2. pytest comprehensive_factor/test_cases/
3. 端到端：`python run_pipeline.py --start-script composite_rolling_icir` 不再 OOM
