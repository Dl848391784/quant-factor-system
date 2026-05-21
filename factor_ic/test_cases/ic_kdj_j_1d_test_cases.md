# KDJ_J_1D IC 计算器测试用例

> 测试脚本: `ic_kdj_j_1d.py`
> 流程文档: `docs/ic_kdj_j_1d_flow.md`
> 更新时间: 2026-05-21 19:00 北京时间
> 更新内容: 同步公共模块重构，删除过时测试用例
> 测试人员: 云汐

---

## 测试环境

### 数据来源
- 因子缓存目录: `cache/factor_data/`（包含 close, high, low 列）
- 收益缓存目录: `cache/factor_data/`（包含 forward_return_1d 列）
- 公共模块自动加载，无需手动指定路径

### 数据要求
1. 因子数据应包含至少 500 天的交易日数据
2. 股票数量不少于 10 只
3. 价格数据需要连续（每只股票至少 9 天历史数据用于 RSV 计算）

### 依赖模块（公共模块）
- `factor_ic.common.factor_ic_runner` - 主入口 run_complex_factor_ic()
- `factor_ic.common.data_loader` - 数据加载
- `factor_ic.common.ic_calculator` - IC 计算 + 五维度判断
- `factor_ic.common.incremental_engine` - 增量更新

---

## 功能测试

### TC001: 正常流程 - KDJ_J 因子计算和 IC 计算
**前置条件**: 
- 缓存文件存在且数据完整
- close/high/low 数据连续

**测试步骤**:
1. 执行脚本: `python factor_ic/ic_kdj_j_1d.py --force-full`
2. 观察输出日志，确认公共模块调用成功
3. 检查因子计算步骤（RSV → K → D → J）
4. 检查 IC 计算结果（五维度判断）
5. 验证输出文件生成

**预期结果**:
- 日志显示公共模块调用链
- 输出文件: `factor_ic/result/ic_kdj_j_1d_analysis_result.json`
- IC 指标正常计算（ic_mean, ic_std, icir, p_value）
- 五维度判断输出完整

**实际结果**: PASS（2026-05-21 18:58）
- IC均值: -0.0160
- ICIR: 0.1117
- p_value: 0.0090
- 统计显著，反向因子

---

### TC002: KDJ_J 因子计算验证 - RSV 计算
**前置条件**: 
- 单只股票数据已加载

**测试步骤**:
1. 取单只股票 9 天数据
2. 验证 RSV 计算:
   - rolling_high = 过去 9 天最高价最大值（min_periods=9）
   - rolling_low = 过去 9 天最低价最小值（min_periods=9）
   - RSV = (Close - rolling_low) / (rolling_high - rolling_low) × 100
3. 边界检查: high == low 时 RSV = 50（EPSILON=1e-10）

**预期结果**:
- RSV 值范围 [0, 100]
- 边界情况返回 50
- 前 8 天为 NaN（min_periods=9，需完整窗口）

**实际结果**: (测试时填写)

---

### TC003: KDJ_J 因子计算验证 - K/D/J 计算
**前置条件**: 
- RSV 已计算

**测试步骤**:
1. 验证 K 值计算（EWM 平滑，alpha=1/3，initial=50）
2. 验证 D 值计算（EWM 平滑，alpha=1/3，initial=50）
3. 验证 J 值计算: J = 3K - 2D
4. 检查 ewm 参数：adjust=False, ignore_na=False

**预期结果**:
- K 值平滑递进
- D 值更加平滑
- J 值范围无限制（实际常见 [-50, 150]）
- ewm 参数正确处理 NaN 前缀

**实际结果**: (测试时填写)

---

### TC004: 输出文件结构验证
**前置条件**: 
- IC 计算完成

**测试步骤**:
1. 打开输出文件 `factor_ic/result/ic_kdj_j_1d_analysis_result.json`
2. 检查 JSON 结构完整性
3. 验证字段类型

**预期结果**（遵循 MODULE.md 输出结构）:
- JSON 包含:
  - `factor_name`: "kdj_j_1d"
  - `calculation_date`: ISO 时间字符串
  - `period`: {start, end, description}
  - `ic_metrics`: {ic_mean, ic_std, icir, p_value}（4字段）
  - `statistical_significance`: {t_stat, p_value, nw_lag, is_significant, conclusion}（7字段）
  - `factor_direction`: {direction, ic_mean, conclusion}
  - `economic_significance`: {abs_ic_mean, level, is_economically_significant, threshold_used, conclusion}
  - `sample_stats`: {total_days, valid_days, avg_stocks_per_day, avg_stocks_period}
  - `dates`: 有效日期列表
  - `ic_values`: 每日 IC 值
  - `rolling_ic_mean`: 20 日滚动均值（前 9 个为 null）
  - `positive_ratio`: IC 正值比例
  - `summary`: 五维度摘要
  - `update_mode`: "full" 或 "incremental"

**实际结果**: PASS（2026-05-21 18:58）
- 所有字段完整存在
- rolling_ic_mean 前 9 个为 null（符合 min_periods=10）

---

### TC005: 增量模式验证
**前置条件**: 
- 存在已计算的 IC 结果
- 新数据已添加到缓存

**测试步骤**:
1. 执行脚本不带 --force-full 参数: `python factor_ic/ic_kdj_j_1d.py`
2. 观察增量判断结果
3. 检查只计算缺失日期

**预期结果**:
- 日志显示 "模式判断: incremental"
- 只计算缺失日期 IC
- 合并后重算统计指标
- update_mode 字段为 "incremental"

**实际结果**: (测试时填写)

---

## 边界测试

### TC006: 价格数据边界 - High == Low
**前置条件**: 
- 某日某股票最高价等于最低价

**测试步骤**:
1. 构造数据: high == low
2. 执行因子计算
3. 检查 RSV 处理（EPSILON=1e-10）

**预期结果**:
- RSV = 50（避免除零）
- 不抛出异常

**实际结果**: (测试时填写)

---

### TC007: 价格数据缺失
**前置条件**: 
- close/high/low 包含 NaN

**测试步骤**:
1. 构造数据包含缺失价格
2. 执行因子计算
3. 检查缺失值统计和处理

**预期结果**:
- 公共模块自动过滤缺失值
- 不抛出异常

**实际结果**: (测试时填写)

---

### TC008: 数据天数不足 - 少于9天
**前置条件**: 
- 某股票历史数据少于 9 天

**测试步骤**:
1. 构造数据: 股票只有 5 天历史
2. 执行因子计算
3. 检查 min_periods=n 的处理（前 N-1 天为 NaN）

**预期结果**:
- 使用 min_periods=n 计算（前 N-1 天为 NaN）
- 因子值可计算但不稳定
- 不抛出异常

**实际结果**: (测试时填写)

---

### TC009: 单日股票数量边界 - 10只
**前置条件**: 
- 某日恰好 10 只股票有效

**测试步骤**:
1. 构造数据: 单日 10 只股票
2. 执行 IC 计算
3. 检查是否正常计算

**预期结果**:
- 正常计算该日 IC（min_stocks=10）
- 不跳过该日

**实际结果**: (测试时填写)

---

### TC010: 单日股票数量不足 - 9只
**前置条件**: 
- 某日只有 9 只股票有效

**测试步骤**:
1. 构造数据: 单日 9 只股票
2. 执行 IC 计算
3. 检查处理方式

**预期结果**:
- 跳过该日，不计算 IC
- 不抛出异常

**实际结果**: (测试时填写)

---

### TC011: 因子值全相同
**前置条件**: 
- 某日所有股票 J 值相同

**测试步骤**:
1. 构造数据: 所有股票 J=50
2. 执行 IC 计算
3. 检查处理

**预期结果**:
- 跳过该日或 IC=0
- 不抛出异常

**实际结果**: (测试时填写)

---

## 异常测试

### TC012: 缓存文件不存在
**前置条件**: 
- 缓存目录不存在

**测试步骤**:
1. 删除缓存目录
2. 执行脚本
3. 观察错误处理

**预期结果**:
- 抛出 RuntimeError（公共模块包装 FileNotFoundError）
- 清晰的错误提示

**实际结果**: (测试时填写)

---

### TC013: 缺少必需列 - close/high/low
**前置条件**: 
- 缓存缺少价格列

**测试步骤**:
1. 准备不含 close/high/low 的缓存
2. 执行脚本
3. 观察错误处理

**预期结果**:
- 公共模块输出友好错误信息（显示可用列）
- 返回空结果或抛出错误

**实际结果**: (测试时填写)

---

### TC014: numpy 类型序列化
**前置条件**: 
- 计算结果包含 numpy 类型

**测试步骤**:
1. 执行计算
2. 检查 JSON 序列化

**预期结果**:
- 公共模块 convert_to_native_types() 正确转换
- JSON 正常保存

**实际结果**: (测试时填写)

---

## 数据质量测试

### TC015: IC 统计指标验证
**前置条件**: 
- IC 计算完成

**测试步骤**:
1. 检查 IC 均值、标准差
2. 验证 ICIR 计算: ICIR = |ic_mean| / ic_std（使用 abs）
3. 验证 Newey-West t 统计量（样本量 T=valid_days）
4. 验证显著性判断（p < 0.05）

**预期结果**:
- ICIR 计算正确（使用 abs(ic_mean)）
- t 统计量计算正确（Newey-West 校正）
- 显著性判断与阈值对应正确

**实际结果**: PASS（2026-05-21 18:58）
- ICIR = |-0.0160| / 0.1435 ≈ 0.1117（正确使用 abs）
- p_value = 0.0090 < 0.05，统计显著

---

## 回归测试

### TC016: 与标准 KDJ 公式对比
**前置条件**: 
- 有标准 KDJ 计算结果参考

**测试步骤**:
1. 使用相同参数（N=9, M1=3, M2=3）
2. 计算因子值
3. 与标准计算结果对比

**预期结果**:
- RSV、K、D、J 值一致（误差 < 0.1）
- ewm 参数处理一致（adjust=False, ignore_na=False）

**实际结果**: (测试时填写)

---

### TC017: p_value 字段验证
**前置条件**: 
- IC 计算完成
- 输出 JSON 文件已生成

**测试步骤**:
1. 读取输出文件，获取 p_value 字段
2. 验证 p_value 类型为 float
3. 验证 p_value 范围在 [0, 1] 之间

**预期结果**:
- p_value 字段类型正确（float）
- p_value 范围正确
- is_significant 字段与 p_value 对应（p < 0.05）

**实际结果**: PASS（2026-05-21 18:58）
- p_value = 0.0090（float）
- is_significant = true（正确对应）

---

## 测试总结

| 测试类别 | 用例数量 | 通过数 | 失败数 | 备注 |
|---------|---------|-------|-------|------|
| 功能测试 | 5 | 2 | 0 | TC001/TC004 已验证 |
| 边界测试 | 6 | 0 | 0 | 待测试 |
| 异常测试 | 3 | 0 | 0 | 待测试 |
| 数据质量测试 | 1 | 1 | 0 | TC015 已验证 |
| 回归测试 | 2 | 1 | 0 | TC017 已验证 |
| **总计** | **17** | **4** | **0** | 删除过时用例（原33→17） |

---

## 已删除的过时测试用例

以下测试用例因公共模块重构已移除：

| 原编号 | 原名称 | 移除原因 |
|-------|--------|---------|
| TC006 | 增量判断功能 | 公共模块自动处理 |
| TC021-TC024 | 内存优化测试 | 公共模块自动管理 |
| TC025-TC027 | 性能测试 | 公共模块优化 |
| TC032 | p_value 与 significance 对应 | significance 星号字段已废弃 |

---

*测试用例文档结束*