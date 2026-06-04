# volume_ratio factor_name 统一修复计划

## 问题诊断

**根因：** IC 脚本和回测脚本的 `factor_name` 定义不一致

| 脚本 | factor_name | factor_col | 输出文件 |
|------|-------------|------------|----------|
| `ic_volume_ratio_1d.py` | `volume_ratio` | `volume_ratio_5` | `ic_volume_ratio_1d_analysis_result.json` |
| `layered_backtest_volume_ratio_1d.py` | `volume_ratio_5` | `volume_ratio_5` | `volume_ratio_5_layered_backtest.json` |

**冲突结果：**
- 筛选器从 IC 文件名解析出因子名 `volume_ratio`
- 筛选器从回测文件名解析出因子名 `volume_ratio_5`
- 同一个因子被识别为两个不同名称
- `volume_ratio_5` 因无 IC 数据被标记为无效（ic_mean/icir 缺失）

**PROJECT.md 规范（第320-321行）：**
- IC 文件命名：`ic_<因子>_<周期>_analysis_result.json`
- 回测文件命名：`<因子>_layered_backtest.json`

## 修复方案

**统一命名：** 将回测脚本的 `factor_name` 改为 `volume_ratio`（不带 `_5` 后缀）

**理由：**
1. `factor_col` 和 `factor_name` 可以不同（数据列名 vs 因子名）
2. IC 文件已使用 `volume_ratio` 命名
3. 回测脚本已有 `ic_source` 覆盖配置指向正确的 IC 文件

## 任务清单

### Task 1: 修改回测脚本 factor_name
- 文件：`backtest/layered_backtest_volume_ratio_1d.py`
- 修改：第33行 `factor_name='volume_ratio_5'` → `factor_name='volume_ratio'`
- 同步修改：第29-30行注释中提到的 `volume_ratio_5`

### Task 2: 同步更新流程文档
- 文件：`backtest/docs/layered_backtest_volume_ratio_1d_flow.md`（如果存在）
- 检查是否存在并更新 factor_name 描述

### Task 3: 验证修复
- 删除旧的回测结果文件：`backtest/result/volume_ratio_5_layered_backtest.json`
- 重新运行回测脚本生成新文件：`backtest/result/volume_ratio_layered_backtest.json`
- 验证筛选器不再报 `volume_ratio_5 缺失 ic_mean/icir`

## 影响范围

- 回测结果文件名变更（需删除旧文件）
- 综合因子筛选结果可能变化（volume_ratio_5 将不再被误识别）
- 其他因子脚本无需修改（无类似命名问题）

## 预期结果

修复后：
- IC 文件：`ic_volume_ratio_1d_analysis_result.json` → factor_name=`volume_ratio`
- 回测文件：`volume_ratio_layered_backtest.json` → factor_name=`volume_ratio`
- 筛选器不再出现 `volume_ratio_5 缺失 ic_mean/icir` 警告
- volume_ratio 正常参与筛选和综合因子计算