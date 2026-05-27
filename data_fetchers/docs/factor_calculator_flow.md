# factor_calculator 流程文档

> 版本: v1.0
> 生成时间: 2026-05-27 17:00 北京时间
> 作者: 云瑶

---

## 概述

factor_calculator.py 是因子计算统一模块，提供所有因子计算函数的单一数据源。

---

## 整体架构

```
┌─────────────────────────────────────────────────────────────────┐
│                    factor_calculator.py                          │
├─────────────────────────────────────────────────────────────────┤
│  公共函数                                                         │
│  ├── calculate_rsi(close_prices, period) → pd.Series             │
│  ├── calculate_volume_ratio(volume, window) → pd.Series          │
│  ├── calculate_forward_return(close_prices, shift) → pd.Series   │
│  ├── calculate_bollinger_pb(df, n, k, logger_arg) → pd.DataFrame │
│  ├── calculate_kdj_j(df, n, m1, m2, logger_arg) → pd.DataFrame   │
│  └── calculate_turnover_surge(df, surge_window, logger_arg) → DataFrame │
├─────────────────────────────────────────────────────────────────┤
│  辅助函数                                                         │
│  ├── _wilder_smoothing_rsi(series, n) → pd.Series（模块私有）      │
│  ├── _calculate_ewm_with_initial(series, alpha, initial) → Series │
│  └── get_module_logger(logger_arg) → Logger                       │
├─────────────────────────────────────────────────────────────────┤
│  模块级常量                                                       │
│  ├── EPSILON = 1e-10                                             │
│  ├── DEFAULT_RSI_PERIOD = 6                                      │
│  ├── DEFAULT_BOLLINGER_N = 20                                    │
│  ├── DEFAULT_BOLLINGER_K = 2.0                                   │
│  ├── DEFAULT_KDJ_N = 9                                           │
│  ├── DEFAULT_KDJ_M1 = 3                                          │
│  ├── DEFAULT_KDJ_M2 = 3                                          │
│  └── DEFAULT_SURGE_WINDOW = 5                                    │
└─────────────────────────────────────────────────────────────────┘
```

---

## 规范遵循

遵循 PROJECT.md 和 MODULE.md 规范：

| 规范 | 约束编号 | 说明 |
|-----|---------|------|
| 导入分组注释 | 约束 63 | 标准库/第三方库/类型导入分组 |
| logger 参数命名 | 约束 77 | 使用 logger_arg 避免遮蔽 |
| logger 类型注解 | 约束 76 | Optional[logging.Logger] |
| __all__ 不含私有名称 | 约束 60 | 移除 _ 开头名称 |
| 函数入口 .copy() | PROJECT.md | 避免修改原始数据 |
| get_module_logger fallback | PROJECT.md | 模块级 _MODULE_LOGGER |

---

## 版本历史

| 版本 | 时间 | 更新内容 |
|-----|------|---------|
| v1.0 | 2026-05-27 17:00 | 初始创建：导入规范化、logger参数化、__all__修复、docstring补全 |

---

*文档生成时间: 2026-05-27 17:00 北京时间*
