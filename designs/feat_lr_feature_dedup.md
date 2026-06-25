# Design: LR 特征同族去重 — 修复多变量系数翻转

## 状态: [experimental]

## 背景

### 问题现象
LR 过滤后的 Top30 股票在 2026-06-25 暴跌日中 8/9 只大跌（平均 -4.39%），
与模型预测方向完全相反。

### 根因（已验证）
1. `_discover_features` 按 Cohen's d 选 top 10 特征，不检查特征间相关性
2. 同一底层因子（如 `price_position`）的原始值（`factor_price_position`）和
   标准化值（`factor_interaction_price_pos__ret1d_pos_std`）同时入选
3. 原始与 _std 特征高度相关（|r| ≈ 0.78~0.85），但方向相反（标准化时做了方向翻转）
4. 多变量 LR 在共线性下系数翻转：`price_position` 单变量 coef=+0.21 → 多变量 coef=-0.25
5. 模型学反了 `price_position` 的方向，保留了 PP 低的股票（当天跌得最狠的）

### 验证证据
- `price_position` 单变量与 T+1 涨概率: r=+0.10, p=1.2e-103（高 PP → 涨）
- 模型多变量系数: -0.25（高 PP → 跌，**方向相反**）
- 原始与 _std 特征相关性: r=-0.78~-0.85

## 方案

### What
在 `_discover_features` 中，Cohen's d 排序后加一步贪心同族去重：
按 |d| 降序遍历候选特征，每次选入前检查它与已选特征的 Pearson 相关性，
若 |r| > 0.7 则跳过。

### How
1. 计算所有候选特征的 Cohen's d（现有逻辑不变）
2. 按 |d| 降序排序
3. 贪心选取：
   - 对每个候选特征 f，计算 f 与所有已选特征的 Pearson r
   - 若任意 |r| > 0.7，跳过 f
   - 否则选入 f
4. 直到选满 top_n 个或候选耗尽

### Why（第一性原理）
- LR 的假设是特征独立。共线性特征破坏了这个假设，
  导致系数在特征间任意分配，甚至符号翻转。
- 同族因子的原始值和 _std 值携带相同信息（只是线性变换 + 方向翻转），
  同时入选不会增加信息量，只会引入共线性。
- 贪心去重保证选入的特征之间 |r| ≤ 0.7，满足 LR 的独立性假设。
- 阈值 0.7 是统计学惯例（>0.7 视为强相关）。

### Don't
- ❌ 不要在 LR 训练时加 L1/L2 正则化来"自动处理"共线性——
  正则化只是让系数分散到共线性特征上，不解决方向翻转问题
- ❌ 不要手动维护"同族特征列表"——这违反数据驱动原则，
  且无法适应未来新增因子
- ❌ 不要在 apply_lr_filter 侧做映射修复——问题在训练侧，不在应用侧

### When
适用于 `calibrate_lr_filter` 中 `_discover_features` 的特征选择阶段。
所有 weight_method 共用同一逻辑。

### Verify
1. 修复后特征列表中不应有同一底层因子的原始 + _std 同时出现
2. price_position 的多变量系数应为正（与单变量方向一致）
3. OOS AUC 可能下降（因为一部分"预测力"来自错误方向），但下降后的 AUC 是真实的
4. pytest 全通过

## 影响范围
- 修改文件: `comprehensive_factor/stock_selector.py`（`_discover_features` 函数）
- 测试文件: `comprehensive_factor/test_cases/test_two_stage_selector.py`
- 不涉及路径变更、不涉及数据格式变更
