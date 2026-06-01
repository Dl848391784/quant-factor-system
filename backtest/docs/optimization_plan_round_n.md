# backtest 模块优化计划 Round N

**创建日期**: 2026-06-01
**状态**: ✅ 已完成

---

## 优化目标

按照 MODULE.md v1.22 理想形态，对 backtest 模块进行批量优化，确保：
1. 所有脚本符合 v1.22 架构规范
2. 流程文档命名一致且完整
3. 测试用例文档配套完整

---

## 诊断结果

### 脚本状态（已符合 v1.22）

| 脚本 | factor_name | layer_names | ic_source | factor_cli_main | 状态 |
|------|-------------|-------------|-----------|-----------------|------|
| layered_backtest_overnight_ret_1d.py | ✅ ClassVar | ✅ ClassVar | ✅ | ✅ | 符合 |
| layered_backtest_rsi_1d.py | ✅ ClassVar | ✅ ClassVar | ✅ | ✅ | 符合 |
| layered_backtest_volume_ratio_1d.py | ✅ ClassVar | ✅ ClassVar | ✅ | ✅ | 符合 |
| layered_backtest_return_5d_1d.py | ✅ ClassVar | ✅ ClassVar | ✅ | ✅ | 符合 |
| layered_backtest_bollinger_pb_1d.py | ✅ ClassVar | ✅ ClassVar | ✅ | ✅ | 符合 |
| layered_backtest_kdj_j_1d.py | ✅ ClassVar | ✅ ClassVar | ✅ | ✅ | 符合 |
| layered_backtest_turnover_surge_1d.py | ✅ ClassVar | ✅ ClassVar | ✅ | ✅ | 符合 |
| layered_backtest_price_position_1d.py | ✅ ClassVar | ✅ ClassVar | ✅ | ✅ | 符合 |
| layered_backtest_amplitude_1d.py | ✅ ClassVar | ✅ ClassVar | ✅ | ✅ | 符合 |
| layered_backtest_return_3d_1d.py | ✅ ClassVar | ✅ ClassVar | ✅ | ✅ | 符合 |

**结论**: 所有脚本已符合 v1.22 理想形态，无需重构代码。

---

## 优化任务清单

### 任务 1: 重命名 RSI 流程文档 ✅ 已完成

**问题**: `layered_backtest_rsi_flow.md` 缺少 `_1d` 后缀，与脚本命名不一致

**操作**: 
```bash
mv docs/layered_backtest_rsi_flow.md docs/layered_backtest_rsi_1d_flow.md
```

---

### 任务 2: 创建 amplitude_1d 流程文档 ✅ 已完成

**问题**: 缺少 `layered_backtest_amplitude_1d_flow.md`

**操作**: 创建完整流程文档

---

### 任务 3: 创建 return_3d_1d 流程文档 ✅ 已完成

**问题**: 缺少 `layered_backtest_return_3d_1d_flow.md`

**操作**: 创建完整流程文档

---

### 任务 4: 创建缺失的 MD 测试用例文档 ✅ 已完成

**问题**: 缺少 5 个因子的测试用例 MD 文档

**操作**: 创建以下文档：
- `amplitude_layered_backtest_test_cases.md`
- `bollinger_pb_layered_backtest_test_cases.md`
- `price_position_layered_backtest_test_cases.md`
- `return_3d_layered_backtest_test_cases.md`
- `rsi_layered_backtest_test_cases.md`

---

## 验证结果

### 文档完整性

| 类型 | 数量 | 状态 |
|------|------|------|
| 流程文档 | 10/10 | ✅ 完整 |
| MD 测试用例 | 10/10 | ✅ 完整 |
| pytest 文件 | 10/10 | ✅ 完整 |

### pytest 结果

```
168 passed, 24 skipped in 0.75s
```

- 24 个 skipped 是因为结果文件不存在，属于正常的跳过测试
- 所有配置测试、因子计算测试通过

---

## 完成总结

**优化完成时间**: 2026-06-01 15:06

**变更清单**:
1. 重命名 1 个流程文档：`layered_backtest_rsi_flow.md` → `layered_backtest_rsi_1d_flow.md`
2. 创建 2 个流程文档：`layered_backtest_amplitude_1d_flow.md`、`layered_backtest_return_3d_1d_flow.md`
3. 创建 5 个测试用例 MD 文档

**无代码变更**: 所有脚本已符合 v1.22 架构规范

---

## 后续建议

1. 运行完整分层回测生成结果文件，使 skipped 测试可以验证
2. 补充边界值测试用例（close=0、high=low 等）
3. 定期检查新增因子是否同步创建三套文档