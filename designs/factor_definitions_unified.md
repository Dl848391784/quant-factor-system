# Design: 因子定义统一管理

## 背景

当前 `FACTOR_DEFINITIONS` 硬编码在 `summary/generate_factor_summary_report.py`（108-123行），存在以下问题：
1. 维护分散：新增因子需同时修改 factor_calculator.py docstring + summary 模块字典
2. 不一致风险：两处定义可能不同步
3. 无法复用：其他模块无法引用因子定义信息

## 方案

### 文件改动

| 文件 | 改动类型 | 内容 |
|------|----------|------|
| `factor_definitions.py` | 新增 | 项目级因子定义模块，包含 `FACTOR_DEFINITIONS` 字典 + 辅助函数 |
| `summary/generate_factor_summary_report.py` | 修改 | 移除硬编码字典，从 factor_definitions 导入 |
| `MODULE.md` (data_fetchers) | 修改 | 添加 factor_definitions.py 使用说明 |

### 模块位置

**选择：根目录 `/factor_definitions.py`**

理由：
- 因子定义是项目级公共信息，不应归属于特定模块
- 被 data_fetchers（计算）、summary（报告）、factor_ic（分析）多模块共用
- 符合 PROJECT.md "跨模块数据契约"定位

### 模块设计

```python
# factor_definitions.py
"""
因子定义统一管理模块

提供因子名称、计算公式、业务含义的单一数据源。
新增因子时只需在此模块添加定义，所有依赖模块自动同步。

版本历史：
- v1.0 (2026-06-02): 初始版本，整合 14 个因子定义
"""

from typing import Dict

__all__ = ['FACTOR_DEFINITIONS', 'get_factor_definition', 'get_all_factor_names']

# 因子定义字典：因子逻辑名 → 定义信息
FACTOR_DEFINITIONS: Dict[str, str] = {
    # 基础因子（来自 factor_calculator.py）
    'rsi': 'RSI(6日): 相对强弱指标, 公式: RSI=100-100/(1+RS)',
    'volume_ratio': '量比(5日): 当日成交量/过去5日成交量均值',
    'kdj_j': 'KDJ J值: J=3K-2D, K/D为RSV(9日)的平滑值',
    'bollinger_pb': '布林带%B: 收盘价在布林带中位置, %B=(close-lower)/(upper-lower)',
    'turnover_surge': '换手率突增(5日): 当日换手率/过去5日换手率均值',
    'amplitude': '振幅: (high-low)/close, 当日价格波动强度',
    'price_position': '价格位置: (close-low)/(high-low), 收盘价在振幅中位置',
    'return_3d': '3日累计涨幅: close[t]/close[t-3]-1',
    'return_5d': '5日累计涨幅: close[t]/close[t-5]-1',
    'overnight_ret': '隔夜收益: (今日开盘-昨日收盘)/昨日收盘',
    
    # 尾盘因子（来自 factor_ic/ic_tail_*_1d.py）
    'tail_price_position': '尾盘价格位置: (收盘-尾盘最低)/(尾盘最高-尾盘最低)',
    'tail_price_slope': '尾盘趋势斜率: 线性回归斜率/均价(百分比)',
    'tail_price_volume_intensity': '尾盘量价强度: 尾盘涨跌幅×尾盘量比',
    'tail_volume_acceleration': '尾盘量能加速度: 后半段成交量/前半段成交量',
}

def get_factor_definition(factor_name: str, default: str = '') -> str:
    """获取单个因子定义
    
    Args:
        factor_name: 因子逻辑名
        default: 未找到时的默认值
    
    Returns:
        因子定义字符串
    """
    return FACTOR_DEFINITIONS.get(factor_name, default)

def get_all_factor_names() -> list:
    """获取所有已定义的因子名称列表
    
    Returns:
        因子名称列表（按字典序）
    """
    return sorted(FACTOR_DEFINITIONS.keys())
```

### 导入方式

```python
# summary/generate_factor_summary_report.py
from factor_definitions import FACTOR_DEFINITIONS, get_factor_definition
```

## 测试计划

| 测试文件 | 测试内容 |
|----------|----------|
| `test_factor_definitions.py` (新增) | 模块导出、函数签名、定义完整性 |
| `test_generate_factor_summary_report.py` (已有) | 验证导入后功能不变 |

## 验收标准

1. pytest 全部通过
2. ruff check 无新增错误
3. 报告生成功能不变（定义列正确展示）
4. factor_definitions.py 可被其他模块导入

## 执行顺序

1. 创建 factor_definitions.py
2. 创建 test_factor_definitions.py
3. 修改 summary/generate_factor_summary_report.py（导入 + 移除硬编码）
4. 运行 pytest + ruff 验证
5. 更新 MODULE.md（如有）
6. Git commit