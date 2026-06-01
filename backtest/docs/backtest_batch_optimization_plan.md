# backtest 模块批量优化计划 (Round N)

> 创建时间: 2026-06-01
> 状态: 待执行

---

## 诊断结果

### 脚本现状（符合 v1.22 理想形态）

| 检查项 | 状态 |
|-------|------|
| 删除 @dataclass 装饰器 | ✓ 全部已删除 |
| layer_names: ClassVar[Sequence[str]] | ✓ 全部使用 tuple |
| field(default_factory) 已删除 | ✓ 无冗余 |
| factor_cli_main 公共入口 | ✓ 全部使用 |
| LayerConfigBase 继承 | ✓ 全部继承 |
| ClassVar 元数据声明 | ✓ 全部使用 |

**结论**: 11个脚本已符合 MODULE.md v1.22 理想形态，无需重构。

---

## 发现的问题

### 问题1: 流程文档缺失（高优先）

| 脚本 | 流程文档 | 状态 |
|-----|---------|------|
| amplitude_1d | layered_backtest_amplitude_1d_flow.md | ❌ 缺失 |
| return_3d_1d | layered_backtest_return_3d_1d_flow.md | ❌ 缺失 |
| bollinger_pb_1d | layered_backtest_bollinger_pb_1d_flow.md | ✓ 存在 |
| kdj_j_1d | layered_backtest_kdj_j_1d_flow.md | ✓ 存在 |
| overnight_ret_1d | layered_backtest_overnight_ret_1d_flow.md | ✓ 存在 |
| price_position_1d | layered_backtest_price_position_1d_flow.md | ✓ 存在 |
| return_5d_1d | layered_backtest_return_5d_1d_flow.md | ✓ 存在 |
| rsi_1d | layered_backtest_rsi_flow.md | ⚠️ 命名不一致（缺少 _1d） |
| turnover_surge_1d | layered_backtest_turnover_surge_1d_flow.md | ✓ 存在 |
| volume_ratio_1d | layered_backtest_volume_ratio_1d_flow.md | ✓ 存在 |

### 问题2: MD 测试用例文档缺失（高优先）

| 脚本 | MD 测试用例文档 | pytest 文件 | 状态 |
|-----|----------------|-------------|------|
| amplitude_1d | amplitude_layered_backtest_test_cases.md | ✓ 存在 | ❌ 缺失 MD |
| bollinger_pb_1d | bollinger_pb_layered_backtest_test_cases.md | ✓ 存在 | ❌ 缺失 MD |
| kdj_j_1d | kdj_j_layered_backtest_test_cases.md | ✓ 存在 | ✓ 完整 |
| overnight_ret_1d | overnight_ret_layered_backtest_test_cases.md | ✓ 存在 | ✓ 完整 |
| price_position_1d | price_position_layered_backtest_test_cases.md | ✓ 存在 | ❌ 缺失 MD |
| return_3d_1d | return_3d_layered_backtest_test_cases.md | ✓ 存在 | ❌ 缺失 MD |
| return_5d_1d | return_5d_layered_backtest_test_cases.md | ✓ 存在 | ✓ 完整 |
| rsi_1d | rsi_layered_backtest_test_cases.md | ✓ 存在 | ❌ 缺失 MD |
| turnover_surge_1d | turnover_surge_layered_backtest_test_cases.md | ✓ 存在 | ✓ 完整 |
| volume_ratio_1d | volume_ratio_layered_backtest_test_cases.md | ✓ 存在 | ✓ 完整 |

### 问题3: 流程文档命名不一致（低优先）

- `layered_backtest_rsi_flow.md` → 应重命名为 `layered_backtest_rsi_1d_flow.md`

---

## 执行计划

### 任务1: 创建缺失流程文档（amplitude_1d）

**文件**: `backtest/docs/layered_backtest_amplitude_1d_flow.md`

**模板参考**: `layered_backtest_overnight_ret_1d_flow.md`

**内容要点**:
- 因子定义说明
- 分层规则（percentile 5层）
- 输出结构说明
- 实测数据示例（需运行脚本获取）

### 任务2: 创建缺失流程文档（return_3d_1d）

**文件**: `backtest/docs/layered_backtest_return_3d_1d_flow.md`

**模板参考**: `layered_backtest_return_5d_1d_flow.md`

### 任务3: 重命名 RSI 流程文档

**原文件**: `layered_backtest_rsi_flow.md`
**目标文件**: `layered_backtest_rsi_1d_flow.md`

### 任务4: 创建缺失 MD 测试用例文档（6个）

**缺失列表**:
1. amplitude_layered_backtest_test_cases.md
2. bollinger_pb_layered_backtest_test_cases.md
3. price_position_layered_backtest_test_cases.md
4. return_3d_layered_backtest_test_cases.md
5. rsi_layered_backtest_test_cases.md

**模板参考**: `overnight_ret_layered_backtest_test_cases.md`

---

## 验证检查清单

执行完成后验证：

```
□ 流程文档数量 = 11（与脚本数一致）
□ 流程文档命名格式统一（layered_backtest_<因子名>_1d_flow.md）
□ MD 测试用例数量 = 11（与脚本数一致）
□ pytest 测试文件数量 = 11（已存在）
□ 所有文档有时间标注和版本号
□ Git commit 完成但未 push
```

---

## 预计工作量

| 任务 | 预计时间 | 优先级 |
|-----|---------|--------|
| 创建 amplitude 流程文档 | 2分钟 | 高 |
| 创建 return_3d 流程文档 | 2分钟 | 高 |
| 重命名 RSI 流程文档 | 1分钟 | 低 |
| 创建 5 个 MD 测试用例文档 | 5分钟 | 高 |

**总计**: 约 10 分钟

---

## 执行顺序

1. 重命名 RSI 流程文档（先修复命名）
2. 创建 amplitude 流程文档
3. 创建 return_3d 流程文档
4. 创建 5 个 MD 测试用例文档
5. 验证文档完整性
6. Git commit

---

*计划文档结束*