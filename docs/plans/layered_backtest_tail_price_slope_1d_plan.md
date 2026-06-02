# 分层回测脚本开发计划 - tail_price_slope 因子

> 版本: v1.0
> 创建时间: 2026-06-02 18:15 北京时间

---

## 1. 任务概述

开发尾盘价格趋势斜率因子（tail_price_slope）的分层回测脚本，评估因子的分层收益表现。

**因子定义**：
- 线性回归斜率：对 prices 数组（13根5分钟K线收盘价）做回归
- 百分比斜率：factor_value = slope / mean_price

**因子方向**：从 IC 结果文件自动派生（ic_mean = -0.0822 < 0 → negative）

---

## 2. 开发模式

**采用薄声明模式**（遵循 thin-declaration-layered-backtest-pattern skill）：
- 脚本仅定义 `factor_name` 和 `layer_names`
- `factor_direction` 从 IC 文件自动派生
- `n_layers` / `long_layers` / `short_layers` 由基类派生

---

## 3. 文件清单

| 序号 | 文件类型 | 文件路径 | 操作 |
|------|---------|---------|------|
| 1 | 主脚本 | `backtest/layered_backtest_tail_price_slope_1d.py` | 新建 |
| 2 | 流程文档 | `backtest/docs/layered_backtest_tail_price_slope_1d_flow.md` | 新建 |
| 3 | 测试文件 | `backtest/test_cases/test_layered_backtest_tail_price_slope_1d.py` | 新建 |

---

## 4. 实现方案

### 4.1 主脚本结构

```python
#!/usr/bin/env python3
"""
尾盘价格趋势斜率因子分层回测脚本

因子定义：
- 线性回归：对 prices 数组（13根5分钟K线收盘价）做回归
- 百分比斜率：factor_value = slope / mean_price

分层模式：percentile 5层（每层约20%）

因子元数据派生机制（基类 LayerConfigBase）：
- factor_direction: 从 ic_source IC 文件加载，ic_mean < 0 为 negative
- n_layers: 由 len(layer_names) 派生
- long_layers/short_layers: 由 n_layers 和 factor_direction 派生

数据依赖：
- factor_ic_data.json.gz（主数据源）
- tail_trading_data.json.gz（尾盘5分钟K线数据）

作者: 云瑶
创建日期: 2026-06-02
版本历史:
  v1.0 (2026-06-02): 初始版本
"""

import sys
from collections.abc import Sequence
from pathlib import Path
from typing import ClassVar

sys.path.insert(0, str(Path(__file__).parent.parent))

from backtest.common.factor_cli import factor_cli_main
from backtest.common.layered_backtest_runner import LayerConfigBase
from factor_ic.ic_tail_price_slope_1d import calculate_tail_price_slope


class TailPriceSlopeLayerConfig(LayerConfigBase):
    """尾盘价格趋势斜率因子分层配置
    
    薄声明：仅定义因子名称与分层命名，逻辑完全下沉基类。
    """
    
    factor_name: ClassVar[str] = "tail_price_slope"
    
    layer_names: ClassVar[Sequence[str]] = ("lowest", "lower", "normal", "higher", "highest")
    
    layer_descriptions: ClassVar[Sequence[str]] = (
        "极低层(趋势斜率最小，下跌趋势最明显)",
        "偏低层(趋势斜率较小，下跌趋势较明显)",
        "正常层(趋势斜率适中)",
        "偏高层(趋势斜率较大，上涨趋势较明显)",
        "极高层(趋势斜率最大，上涨趋势最明显)",
    )


if __name__ == "__main__":
    factor_cli_main(
        config_cls=TailPriceSlopeLayerConfig,
        factor_calculator=calculate_tail_price_slope
    )
```

### 4.2 因子方向派生

**IC 结果文件**：`factor_ic/result/ic_tail_price_slope_1d_analysis_result.json`

**IC 均值**：-0.0822 < 0 → `factor_direction = "negative"`

**多空组合派生**：
- `long_layers = [1, 2]`（低层做多）
- `short_layers = [4, 5]`（高层做空）

---

## 5. 验证检查清单

| 检查项 | 说明 |
|--------|------|
| □ ruff check 通过 | lint 检查 |
| □ ruff format 通过 | 格式化检查 |
| □ pytest 通过 | 测试文件验证 |
| □ 脚本运行成功 | 实际运行分层回测 |
| □ 输出结果完整 | result 目录生成 JSON |

---

## 6. 执行顺序

```
Step 1: 创建主脚本 → ruff check/format
Step 2: 创建测试文件 → pytest 验证
Step 3: 创建流程文档 → 版本历史记录
Step 4: 运行脚本验证 → 输出结果检查
Step 5: Git commit → 提交修改
```

---

## 7. 参考

- 参照脚本：`backtest/layered_backtest_tail_price_volume_intensity_1d.py`
- 因子 IC 脚本：`factor_ic/ic_tail_price_slope_1d.py`
- Skill：`thin-declaration-layered-backtest-pattern`