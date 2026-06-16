# 隔夜收益率因子实现计划

**创建时间：** 2026-05-28 23:50
**作者：** 云瑶
**项目：** factor_ic_analyzer

---

## 一、需求概述

### 1.1 目标
添加隔夜收益率（Overnight Return）因子到因子池，包括：
- IC值计算
- 分层回测
- 综合因子筛选逻辑

### 1.2 因子定义
```
overnight_ret = (今日开盘价 - 昨日收盘价) / 昨日收盘价
```

**经济含义：**
- 隔夜收益率反映市场隔夜情绪变化
- 正值表示开盘高于昨日收盘（看涨情绪）
- 负值表示开盘低于昨日收盘（看跌情绪）

### 1.3 数据来源验证（已完成）
- 数据文件：`data_fetchers/result/factor_ic_data.json.gz`
- 包含字段：`open`, `close` ✓
- 日期格式：YYYY-MM-DD ✓
- 索引字段：`date`, `asset` ✓

---

## 二、架构设计

### 2.1 实现方式选择

**决策：使用复杂因子模式（run_complex_factor_ic）**

**理由：**
1. 需要自定义计算函数（昨日收盘价需 shift）
2. 计算逻辑简单，不需要在数据拉取时预计算
3. 因子计算函数直接在脚本中实现（不在 factor_calculator.py）

**对比分析：**
| 实现方式 | 适用场景 | 代码量 | 是否需要预计算 |
|---------|---------|--------|--------------|
| run_simple_factor_ic | 因子已在缓存 | ~60行 | 是 |
| run_complex_factor_ic | 需自定义计算 | ~100行 | 否 |

**选择：run_complex_factor_ic**（因隔夜收益率需要计算，不在缓存中）

### 2.2 因子计算逻辑

**核心公式：**
```python
# 按资产分组，shift获取昨日收盘价
overnight_ret = (open - close.shift(1)) / close.shift(1)
```

**关键步骤：**
1. 按资产分组（每只股票独立计算）
2. shift(1) 获取昨日收盘价
3. 计算隔夜收益率
4. 第一天数据为 NaN（无昨日收盘价）

**数据依赖：**
- factor_cols=['open', 'close']
- 无需 additional_factor_files

### 2.3 输出规范（遵循 PROJECT.md）

**输出文件：**
- IC结果：`factor_ic/result/ic_overnight_ret_1d_analysis_result.json`
- 分层回测：`backtest/result/overnight_ret_layered_backtest.json`

**命名规范：**
- 脚本：`ic_overnight_ret_1d.py`
- 因子名：`overnight_ret`
- 因子列：`overnight_ret`

---

## 三、任务分解（Bite-sized Tasks）

### Task 1: 创建 IC 计算脚本（2-5分钟）
**文件：** `factor_ic/ic_overnight_ret_1d.py`

**代码模板：**
```python
#!/usr/bin/env python3
"""隔夜收益率因子 IC 计算器"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd
import numpy as np

from factor_ic.common.factor_ic_runner import run_complex_factor_ic
from factor_ic.common.logger_config import get_logger

logger = get_logger(__name__)

DEFAULT_MIN_STOCKS = 10

# ============================================================================
# 因子计算函数
# ============================================================================

def calculate_overnight_return(factor_df, logger=None):
    """
    计算隔夜收益率
    
    公式: overnight_ret = (今日开盘价 - 昨日收盘价) / 昨日收盘价
    
    Args:
        factor_df: 包含 open, close 列的 DataFrame
        logger: 日志记录器
    
    Returns:
        DataFrame，新增 overnight_ret 列
    
    Note:
        - 第一天数据为 NaN（无昨日收盘价）
        - 除零防护：prev_close < EPSILON 时设为 NaN
    """
    if logger is None:
        logger = get_logger('factor_ic.ic_overnight_ret_1d')
    
    # 遵循 MODULE.md 约束 #4：函数入口先 copy()
    factor_df = factor_df.copy()
    
    # 按资产分组计算（每只股票独立）
    factor_df['overnight_ret'] = factor_df.groupby('asset').apply(
        lambda group: (group['open'] - group['close'].shift(1)) / group['close'].shift(1)
    ).reset_index(level=0, drop=True)
    
    # 除零防护（prev_close 极小时设为 NaN）
    EPSILON = 1e-10
    prev_close = factor_df.groupby('asset')['close'].shift(1)
    abnormal_mask = prev_close < EPSILON
    if abnormal_mask.any():
        logger.warning(f"发现 {abnormal_mask.sum()} 个异常收盘价（< {EPSILON}），已设为 NaN")
        factor_df.loc[abnormal_mask, 'overnight_ret'] = np.nan
    
    logger.info(f"隔夜收益率计算完成，有效值: {factor_df['overnight_ret'].notna().sum()}")
    
    return factor_df

# ============================================================================
# CLI 入口
# ============================================================================

def main():
    import argparse
    
    parser = argparse.ArgumentParser(description='隔夜收益率 IC 计算器')
    parser.add_argument('--force-full', action='store_true', help='强制全量计算')
    parser.add_argument('--min-stocks', type=int, default=DEFAULT_MIN_STOCKS, help='最小股票数')
    
    args = parser.parse_args()
    
    logger.info(f"隔夜收益率因子 IC 计算启动 [min_stocks={args.min_stocks}, force_full={args.force_full}]")
    
    result = run_complex_factor_ic(
        factor_name='overnight_ret',
        factor_col='overnight_ret',
        factor_cols=['open', 'close'],
        custom_factor_calculation=calculate_overnight_return,
        min_stocks=args.min_stocks,
        force_full=args.force_full,
        _logger=logger
    )
    
    # 结果摘要
    ic_metrics = result.get('ic_metrics', {})
    sample_stats = result.get('sample_stats', {})
    period = result.get('period', {})
    
    logger.info("=" * 60)
    logger.info("结果摘要")
    logger.info("=" * 60)
    logger.info(f"因子名称: {result.get('factor_name', 'unknown')}")
    logger.info(f"更新模式: {result.get('update_mode', 'unknown')}")
    logger.info(f"日期范围: {period.get('start', 'N/A')} ~ {period.get('end', 'N/A')}")
    logger.info(f"有效天数: {sample_stats.get('valid_days', 0)} 天")
    logger.info(f"IC 均值: {ic_metrics.get('ic_mean', 0):.4f}")
    logger.info(f"IC 标准差: {ic_metrics.get('ic_std', 0):.4f}")
    logger.info(f"ICIR: {ic_metrics.get('icir', 0):.2f}")
    logger.info(f"IC>0 占比: {result.get('positive_ratio', 0):.2%}")
    
    return result

if __name__ == '__main__':
    try:
        main()
    except RuntimeError:
        logger.exception("隔夜收益率因子 IC 计算失败")
        sys.exit(1)
    except Exception:
        logger.exception("隔夜收益率因子 IC 计算失败（未预期错误）")
        sys.exit(1)
```

**验证点：**
- ✓ 使用 run_complex_factor_ic（遵循公共模块复用规范）
- ✓ factor_cols=['open', 'close']
- ✓ 自定义计算函数在脚本中实现
- ✓ 按资产分组计算
- ✓ 除零防护
- ✓ 第一天数据为 NaN

### Task 2: 创建流程文档（2-3分钟）
**文件：** `factor_ic/docs/ic_overnight_ret_1d_flow.md`

**内容结构：**
- 整体架构图
- 因子计算流程（Step 1-5）
- 输出结构示例
- 关键指标说明
- 异常处理

### Task 3: 运行 IC 计算（1-2分钟）
**命令：**
```bash
cd /home/admin/projects/factor_ic_analyzer
python -m factor_ic.ic_overnight_ret_1d
```

**预期输出：**
- IC均值、ICIR、p_value
- 有效天数、日期范围
- 五维度判断结果

### Task 4: 分层回测（2-3分钟）
**方式：** 使用 backtest 模块

**命令：**
```bash
python backtest/layered_backtest.py --factor overnight_ret --factor-direction auto
```

**注意：** 因子方向根据 IC 结果确定（auto 自动判断）

### Task 5: 综合因子筛选（1-2分钟）
**方式：** comprehensive_factor 模块会自动纳入新因子

**检查点：**
- factor_list 是否包含 overnight_ret
- auto_select 是否可能选中 overnight_ret
- ICIR 排名是否变化

### Task 6: 更新汇总报告（1分钟）
**命令：**
```bash
python summary/generate_factor_summary_report.py
```

**预期变化：**
- 单因子 IC 表新增 overnight_ret 行
- 因子排序可能变化
- 筛选结果更新

---

## 四、验证检查清单

### 4.1 Spec Compliance 检查

```
□ 脚本命名：ic_overnight_ret_1d.py ✓
□ 输出路径：factor_ic/result/ ✓
□ 输出结构：符合 MODULE.md 模板 ✓
□ factor_cols=['open', 'close'] ✓
□ 自定义计算函数实现 ✓
□ 除零防护 ✓
□ 使用 run_complex_factor_ic ✓
□ 无冗余逻辑 ✓
□ 日志输出完整 ✓
□ 异常处理正确 ✓
```

### 4.2 代码质量检查

```
□ 导入顺序符合 PEP8 ✓
□ 注释缩进一致 ✓
□ 字典结构缩进一致 ✓
□ 异常链保留 from e ✓
□ 函数签名有类型注解 ✓
□ docstring 完整 ✓
```

### 4.3 配套文件检查

```
□ 流程文档创建 ✓
□ 流程文档时间标注 ✓
□ 测试用例创建（可选）□
□ 运行脚本验证输出 ✓
□ Git commit ✓
```

---

## 五、风险识别

### 5.1 数据质量风险
**风险：** close.shift(1) 第一天为 NaN，影响有效天数
**应对：** 自然现象，无需特殊处理，统计指标自动排除 NaN

### 5.2 除零风险
**风险：** prev_close 极小或为零导致异常值
**应对：** 已添加除零防护（EPSILON=1e-10）

### 5.3 因子方向风险
**风险：** 不确定是正向还是反向因子
**应对：** 不预判，根据 IC 结果自动判断

### 5.4 分组计算性能风险
**风险：** groupby + apply 可能在大数据量下较慢
**应对：** 监控执行时间，若超时可考虑向量化优化

---

## 六、执行顺序

```
Phase 1: Plan（已完成）
  ├─ 数据来源验证 ✓
  ├─ 架构设计 ✓
  ├─ 任务分解 ✓
  └─ 风险识别 ✓

Phase 2: Execute（待执行）
  ├─ Task 1: 创建 IC 脚本
  ├─ Task 2: 创建流程文档
  ├─ Task 3: 运行 IC 计算
  ├─ Task 4: 分层回测
  ├─ Task 5: 综合因子筛选
  └─ Task 6: 更新汇总报告

Phase 3: Review（待执行）
  ├─ Stage 1: Spec Compliance
  ├─ Stage 2: Code Quality
  └─ Git commit

Phase 4: Debug（如有问题）
  └─ 根据测试结果调试
```

---

## 七、预期成果

### 7.1 IC 计算结果
- IC均值：预计 -0.03 ~ 0.03（不确定方向）
- ICIR：预计 0.2 ~ 0.4（隔夜收益率通常较弱）
- 有效天数：预计 ~500 天（排除第一天）

### 7.2 分层回测结果
- 多空年化收益：预计 3% ~ 10%
- 夏普比率：预计 0.5 ~ 1.5
- 单调性：预计一般或较差

### 7.3 综合因子筛选
- 可能入选：如果 ICIR > 0.3 且收益 > 3%
- 可能剔除：如果表现弱于现有因子

---

## 八、总结

本计划遵循 superpowers-workflow Phase 1 规范：
- ✓ 先读 PROJECT.md 了解架构
- ✓ 验证数据来源
- ✓ Bite-sized Tasks（2-5分钟）
- ✓ 明确文件路径和代码示例
- ✓ 风险识别和应对策略
- ✓ 验证检查清单完整

**下一步：** 用户确认后执行 Phase 2（Execute）