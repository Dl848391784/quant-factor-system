# 全天价格位置因子 IC 计算实现计划

> 创建时间: 2026-05-29
> 项目: factor_ic_analyzer
> 模块: factor_ic

---

## 一、因子定义

**全天价格位置（Price Position）**

```
Price Position = (Close - Low) / (High - Low)
```

- 含义：收盘价在全天振幅中的相对位置
- 取值范围：0 ~ 1（极端情况可能略超出）
- 0 = 收盘价等于最低价（全天最低收盘）
- 1 = 收盘价等于最高价（全天最高收盘）
- 0.5 = 收盘价在振幅中位

---

## 二、数据确认

| 检查项 | 状态 | 说明 |
|--------|------|------|
| 数据源 | ✓ | `data_fetchers/result/factor_ic_data.json.gz` |
| 包含 high | ✓ | data[0] 字段包含 'high' |
| 包含 low | ✓ | data[0] 字段包含 'low' |
| 包含 close | ✓ | data[0] 字段包含 'close' |
| 数据量 | ✓ | 148万条记录，545天 |
| 日期范围 | ✓ | 2024-02-26 ~ 2026-05-27 |

---

## 三、公共模块复用检查

| 公共模块 | 是否复用 | 说明 |
|---------|---------|------|
| `run_complex_factor_ic()` | ✓ | 主入口（需要自定义因子计算） |
| `calculate_ic_with_direction_verification()` | ✓ | IC计算（run_complex_factor_ic 内部调用） |
| `build_ic_result()` | ✓ | 结果构建（run_complex_factor_ic 内部调用） |
| `factor_calculator.py` | ✗ | 无价格位置计算函数，需自定义 |

**判断结论**：复杂因子，使用 `run_complex_factor_ic()` + 自定义计算函数。

---

## 四、实现任务清单

### 任务1: 创建因子计算函数

**文件**：`data_fetchers/factor_calculator.py`

**新增内容**：
```python
# 常量
_COL_PRICE_POSITION = 'price_position'
_DEFAULT_PRICE_POSITION_EPSILON = 1e-10

def calculate_price_position(factor_df, logger_arg=None):
    """
    计算全天价格位置因子
    
    公式: Price Position = (Close - Low) / (High - Low)
    
    Args:
        factor_df: 包含 close, high, low 列的 DataFrame
        logger_arg: 日志记录器（可选）
    
    Returns:
        添加 price_position 列的 DataFrame
    
    边界处理:
        - High - Low = 0 时，使用 epsilon 防止除零
        - 结果值在 [0, 1] 范围，极端情况可能略超出
    """
    if logger_arg is None:
        logger_arg = logging.getLogger(__name__)
    
    # 入口 copy（遵循 MODULE.md 约束）
    df = factor_df.copy()
    
    # 计算
    range_val = df['high'] - df['low']
    # 防止除零
    df[_COL_PRICE_POSITION] = np.where(
        np.abs(range_val) < _DEFAULT_PRICE_POSITION_EPSILON,
        0.5,  # 振幅为零时设为中位
        (df['close'] - df['low']) / range_val
    )
    
    return df
```

**同步更新**：
- `__all__` 添加 `'calculate_price_position'`
- 版本历史添加 v1.6

---

### 任务2: 创建因子脚本

**文件**：`factor_ic/ic_price_position_1d.py`

**代码模板**（约60行）：
```python
#!/usr/bin/env python3
"""全天价格位置因子 IC 计算器"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from factor_ic.common.factor_ic_runner import run_complex_factor_ic
from factor_ic.common.logger_config import get_logger
from data_fetchers.factor_calculator import calculate_price_position

logger = get_logger(__name__)
DEFAULT_MIN_STOCKS = 10

def main():
    import argparse
    parser = argparse.ArgumentParser(description='全天价格位置因子 IC 计算器')
    parser.add_argument('--force-full', action='store_true')
    parser.add_argument('--min-stocks', type=int, default=DEFAULT_MIN_STOCKS)
    args = parser.parse_args()
    
    logger.info(f"启动价格位置因子IC计算: min_stocks={args.min_stocks}")
    
    result = run_complex_factor_ic(
        factor_name='price_position',
        factor_col='price_position',
        factor_cols=['close', 'high', 'low'],
        custom_factor_calculation=calculate_price_position,
        min_stocks=args.min_stocks,
        force_full=args.force_full,
        _logger=logger
    )
    
    # 输出结果摘要
    logger.info("=" * 60)
    logger.info(f"因子名称: {result.get('factor_name')}")
    logger.info(f"更新模式: {result.get('update_mode')}")
    ic_metrics = result.get('ic_metrics', {})
    logger.info(f"IC均值: {ic_metrics.get('ic_mean', 0):.4f}")
    logger.info(f"ICIR: {ic_metrics.get('icir', 0):.2f}")
    
    return result

if __name__ == '__main__':
    try:
        main()
    except Exception:
        logger.exception("计算失败")
        sys.exit(1)
```

---

### 任务3: 创建流程文档

**文件**：`factor_ic/docs/ic_price_position_1d_flow.md`

**内容框架**：
```markdown
# 全天价格位置因子 IC 计算流程文档

> 生成时间: 2026-05-29
> 版本: v1.0

## 一、因子定义
...

## 二、计算流程
Step 1: 数据加载
Step 2: 因子计算
Step 3: IC计算
Step 4: 结果输出

## 三、输出结构
（遵循 MODULE.md 输出结构模板）

## 四、实测结果
（运行后补充）
```

---

### 任务4: 创建测试文件

**文件**：`factor_ic/test_cases/test_ic_price_position_1d.py`

**测试覆盖**：
- 正常计算
- 边界情况（high=low）
- 输出结构验证

---

### 任务5: 运行验证

**命令**：
```bash
cd /home/admin/projects/factor_ic_analyzer
python -m factor_ic.ic_price_position_1d
```

**验证项**：
- 输出文件生成
- IC值计算
- 五维度判断完整

---

### 任务6: 同步更新规范文档

**MODULE.md**：
- 版本历史添加 v3.14 → v3.15
- 更新记录添加新增因子

---

## 五、执行顺序

```
[1] factor_calculator.py 添加函数
[2] ic_price_position_1d.py 创建脚本
[3] 运行验证
[4] 创建流程文档（补充实测结果）
[5] 创建测试文件
[6] 更新 MODULE.md 版本历史
[7] Git commit
```

---

## 六、预计代码量

| 文件 | 行数 |
|------|------|
| factor_calculator.py 新增 | ~30行 |
| ic_price_position_1d.py | ~60行 |
| docs/ic_price_position_1d_flow.md | ~100行 |
| test_cases/test_ic_price_position_1d.py | ~50行 |

---

*计划完成，待用户确认后执行*