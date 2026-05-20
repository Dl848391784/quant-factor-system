# 优化计划：factor_ic 目录其他脚本

## 背景

`ic_rsi_1d.py` 已完成优化，作为参考模板。需要对其余脚本进行相同风格的优化。

## 问题分析

| 脚本 | 行数 | 主要问题 |
|-----|------|---------|
| ic_kdj_j_1d.py | ~1479 | 内存监控冗余、无公共函数复用、输出路径不规范 |
| ic_bollinger_pb_1d.py | ~1233 | 内存监控冗余、convert_to_native_types 重复定义 |
| ic_volume_ratio_1d.py | ~565 | convert_to_native_types 重复、正向因子但无公共模块 |
| ic_turnover_surge_1d.py | ~648 | 无公共函数复用、convert_to_native_types 重复 |

## 优化目标

1. **统一使用公共模块**
   - `reverse_rank_ic.py` → 反向因子 IC 计算
   - `data_completeness.py` → 输出路径规范化、增量检查
   - 新增 `common/convert_types.py` → 类型转换函数

2. **移除冗余代码**
   - 内存监控函数（对于当前数据规模不需要）
   - 重复的 convert_to_native_types 函数

3. **统一输出结构**
   - 目录：`factor_ic/result/`
   - 命名：`ic_<因子名>_周期_analysis_result.json`
   - JSON 结构符合 PROJECT.md 规范

4. **保持核心逻辑**
   - 因子计算逻辑保留（每个因子有不同的计算方法）
   - IC 计算使用公共函数

## 任务清单

### Task 1: 创建公共类型转换模块
- 文件：`factor_ic/common/convert_types.py`
- 内容：`convert_to_native_types` 函数
- 时长：2分钟

### Task 2: 优化 ic_kdj_j_1d.py（反向因子）
- 移除内存监控代码
- 导入 `reverse_rank_ic`
- 导入 `convert_to_native_types`
- 修正输出路径使用 `get_ic_output_path`
- 保留因子计算核心逻辑
- 时长：5分钟

### Task 3: 优化 ic_bollinger_pb_1d.py（反向因子）
- 移除内存监控代码
- 导入 `reverse_rank_ic`
- 导入 `convert_to_native_types`
- 简化数据加载函数
- 时长：5分钟

### Task 4: 优化 ic_volume_ratio_1d.py（正向因子）
- 导入 `convert_to_native_types`
- 正向因子不使用 reverse_rank_ic（逻辑不同）
- 保持分层回测功能
- 时长：3分钟

### Task 5: 优化 ic_turnover_surge_1d.py（正向因子）
- 导入 `convert_to_native_types`
- 导入 `get_ic_output_path`
- 简化代码结构
- 时长：3分钟

### Task 6: 运行测试验证
- 运行所有测试
- 确保无回归
- 时长：2分钟

## 因子方向说明

| 因子 | 方向 | IC 计算方式 |
|-----|------|-----------|
| RSI | 反向 | `reverse_rank_ic` |
| KDJ_J | 反向 | `reverse_rank_ic` |
| Bollinger %B | 反向 | `reverse_rank_ic` |
| Volume Ratio | 正向 | Spearman 直接计算 |
| Turnover Surge | 正向 | Spearman 直接计算 |

## 验收标准

1. 所有脚本使用公共模块
2. 输出路径符合 PROJECT.md 规范
3. 无重复定义的函数
4. 测试通过
5. 代码行数显著减少

---

*创建时间: 2026-05-10 00:00:00 (北京时间)*