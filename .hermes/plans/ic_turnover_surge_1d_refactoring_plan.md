# ic_turnover_surge_1d.py 重构优化计划

**时间**: 2026-05-21 23:XX
**版本**: v1.25 → v2.0（重大重构）
**类型**: 代码重构 + 规范合规

---

## PHASE 1: Plan - 诊断与决策

### 1.1 探索代码库

**检查项**:
- [x] 读取 ic_turnover_surge_1d.py（当前版本，389行）
- [x] 读取 ic_rsi_1d.py（参照脚本 - 简单因子，253行）
- [x] 读取 ic_bollinger_pb_1d.py（参照脚本 - 复杂因子，167行）
- [x] 读取 factor_ic_runner.py（公共模块主入口，支持 additional_factor_files）
- [x] 读取 PROJECT.md（公共模块强制复用规范）
- [x] 读取 README.md（additional_factor_files 使用示例）

### 1.2 诊断结论

**违规点**（PROJECT.md 第92行）:
```
❌ 公共模块已封装主流程（如 run_complex_factor_ic），脚本自行实现三模式分支
```

**当前代码违规**:
- 第279-342行：手写 SKIP/INCREMENTAL/FULL 三模式分支（~63行冗余）
- 第218-277行：手写全量计算流程 `do_full_recalculate()`（~59行冗余）
- 第112-143行：手写数据加载函数 `load_turnover_data()`（~32行冗余）
- 第294-339行：手写增量计算流程（~45行冗余）
- **总冗余代码**: ~199行

**公共模块已有功能**:
- `run_complex_factor_ic()`：三模式分支 + 流程控制
- `load_factor_return_data(additional_factor_files)`：自动加载 + 合并额外数据
- `calculate_ic_with_direction_verification()`：IC计算 + 五维度判断
- `build_ic_result()`：结果构建
- `save_ic_result()`：结果保存
- `incremental_update_ic()`：增量更新

### 1.3 重构决策

**正确做法**（PROJECT.md 第145-156行示例）:
```python
# 仅实现因子特有逻辑
def calculate_turnover_surge(factor_df, surge_window=5):
    """换手率突增计算（因子特有逻辑）"""
    ...

# 调用公共模块主入口
result = run_complex_factor_ic(
    factor_name='turnover_surge',
    factor_col='turnover_surge',
    factor_cols=['close', 'turnover_rate'],  # turnover_rate 通过 additional_factor_files 加载
    custom_factor_calculation=calculate_turnover_surge,
    additional_factor_files={
        'turnover_rate': DEFAULT_CACHE_DIR / 'turnover_rate_data.json.gz'
    }
)
```

**代码量预期**:
- 当前：389行
- 重构后：~100行（因子计算 50行 + CLI 50行）
- 降幅：~75%

---

## PHASE 2: Execute - Bite-sized Tasks

### Task 1: 重构 calculate_turnover_surge 函数（保留核心逻辑）

**当前版本**（第61-109行）:
- ✅ 已遵循 .copy() 规范
- ✅ 因子计算逻辑完整
- ⚠️ 需检查是否遵循 MODULE.md DataFrame 参数副本规范

**修改**:
- 无需修改，保留当前实现
- 确保注释符合规范

**验证**:
- 检查 factor_df.copy() 调用（第79行）
- 检查 rolling 窗口参数（surge_window）

---

### Task 2: 删除冗余函数 load_turnover_data

**删除内容**（第112-143行）:
```python
def load_turnover_data(factor_df: pd.DataFrame) -> pd.DataFrame:
    """加载并合并换手率数据"""
    ...
```

**替代方案**:
- 使用 `run_complex_factor_ic(additional_factor_files)` 参数
- 公共模块自动加载 + 合并

---

### Task 3: 删除冗余主函数 generate_turnover_surge_ic_data

**删除内容**（第150-342行）:
```python
def generate_turnover_surge_ic_data(...):
    """从缓存数据计算换手率突增 IC（支持三模式）"""
    # 手写模式判断
    # 手写 SKIP 分支
    # 手写 INCREMENTAL 分支
    # 手写 FULL 分支
    ...
```

**替代方案**:
- 使用 `run_complex_factor_ic()` 公共模块主入口

---

### Task 4: 重写 CLI 入口（使用 run_complex_factor_ic）

**参照模板**（ic_bollinger_pb_1d.py 第123-157行）:
```python
def main():
    """CLI 主入口"""
    import argparse
    
    parser = argparse.ArgumentParser(...)
    args = parser.parse_args()
    
    result = run_complex_factor_ic(
        factor_name='turnover_surge',
        factor_col='turnover_surge',
        factor_cols=['close'],
        custom_factor_calculation=calculate_turnover_surge,
        custom_factor_calculation_params={'surge_window': args.surge_window},
        additional_factor_files={
            'turnover_rate': DEFAULT_CACHE_DIR / 'turnover_rate_data.json.gz'
        },
        min_stocks=args.min_stocks,
        force_full=args.force_full,
        _logger=logger
    )
    
    # 防御性访问结果
    ic_metrics = result.get('ic_metrics', {})
    logger.info("结果摘要:")
    logger.info(f"IC 均值: {ic_metrics.get('ic_mean', 0):.4f}")
    ...
    
    return result
```

---

### Task 5: 更新文件头注释

**当前版本**（第2-21行）:
- ✅ 已有因子定义说明
- ⚠️ 缺少"遵循 PROJECT.md 公共模块强制复用规范"声明

**修改**:
```python
"""
换手率突增因子 IC 计算器（重构版） - 1日收益周期

遵循 PROJECT.md 公共模块强制复用规范：
- 主流程使用 run_complex_factor_ic()（禁止手写三模式分支）
- 仅实现因子特有计算逻辑（换手率突增公式）

代码量：~100行（仅换手率计算），而非 ~300行手写主流程。

因子定义：
- 换手率突增 = 当日换手率 / 过去5日换手率均值

筛选条件：
- 换手率突增 > 1（当日换手率高于近期均值）
- 当日涨跌幅 > 0（上涨）
- 不满足条件的股票因子值设为 NaN

作者: 云瑶
重构日期: 2026-05-21
原版作者: 云舟
原版日期: 2026-05-08
"""
```

---

### Task 6: 更新导入语句

**删除导入**:
```python
from factor_ic.common import (
    load_factor_return_data,
    calculate_ic_with_direction_verification,
    build_ic_result,
    incremental_update_ic,
    save_ic_result
)
from factor_ic.common.incremental_engine import UpdateMode, should_use_incremental
from factor_ic.common.data_completeness import get_ic_output_path
from factor_ic.common.data_loader import DEFAULT_CACHE_DIR
```

**新增导入**:
```python
from factor_ic.common.factor_ic_runner import run_complex_factor_ic
from factor_ic.common.data_loader import DEFAULT_CACHE_DIR
from factor_ic.common.logger_config import get_logger
```

---

### Task 7: 更新流程文档 ic_turnover_surge_1d_flow.md

**修改点**:
- ASCII 流程图：删除手写三模式分支，改为 `run_complex_factor_ic()` 调用
- 添加"遵循 PROJECT.md 公共模块强制复用规范"章节
- 版本号：v1.24 → v2.0
- 时间标注：2026-05-21

---

## PHASE 3: Review - Spec Compliance 检查

### 检查清单

- [ ] PROJECT.md 第92行：禁止手写三模式分支
- [ ] PROJECT.md 第121-143行：违规示例对比
- [ ] PROJECT.md 第145-156行：正确示例对比
- [ ] ic_bollinger_pb_1d.py 参照模板对比
- [ ] README.md 第333-340行：additional_factor_files 使用规范
- [ ] MODULE.md DataFrame 参数副本规范（.copy()）

### 验证方法

1. **代码量对比**:
   ```bash
   wc -l ic_turnover_surge_1d.py ic_bollinger_pb_1d.py
   ```

2. **导入语句检查**:
   ```bash
   grep "run_complex_factor_ic" ic_turnover_surge_1d.py
   ```

3. **三模式分支检查**:
   ```bash
   grep "UpdateMode.SKIP\|UpdateMode.INCREMENTAL" ic_turnover_surge_1d.py
   # 期望结果：无匹配（已删除）
   ```

---

## PHASE 4: Debug - 边缘案例与陷阱

### 已知陷阱（memory + factor-ic-analyzer skill）

1. **numpy/pandas 混用陷阱**（2026-05-22）:
   - ❌ `np.where` 与 Series 混用（返回 ndarray 丢失 index）
   - ✅ 使用 `Series.clip()` + `Series.where()`

2. **DataFrame 参数副本规范**（MODULE.md）:
   - ❌ 直接修改传入的 DataFrame
   - ✅ 函数入口先 `.copy()`

3. **嵌套字典访问陷阱**（2026-05-22）:
   - ❌ `.get('key', {})` 在键存在但值为 None 时返回 None
   - ✅ `.get('key') or {}`

### 检查点

- [ ] calculate_turnover_surge 第79行：`factor_df.copy()`
- [ ] CLI 结果访问：使用 `.get()` 防御性访问
- [ ] additional_factor_files 参数传递正确

---

## 执行顺序

1. Task 1-2: 保留 calculate_turnover_surge，删除 load_turnover_data
2. Task 3: 删除 generate_turnover_surge_ic_data
3. Task 4: 重写 CLI 入口
4. Task 5-6: 更新注释和导入
5. Task 7: 更新流程文档

---

## 风险评估

**低风险**:
- 因子计算逻辑不变（calculate_turnover_surge 保留）
- 公共模块已验证（ic_bollinger_pb_1d.py 使用相同模式）
- 测试用例不变（功能一致性）

**验证方法**:
- 运行现有测试用例
- 对比输出结果（IC 均值、ICIR 等）

---

## 预期结果

- 代码量：389行 → ~100行
- 规范合规：符合 PROJECT.md 第92行
- 维护性：公共模块统一管理三模式分支
- 可扩展性：新增因子直接复用公共模块