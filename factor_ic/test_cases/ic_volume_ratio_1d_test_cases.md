# ic_volume_ratio_1d 测试用例

> 版本: v1.8
> 生成时间: 2026-05-23 22:45 北京时间
> 实测数据时间: 2026-05-23 22:45（验证输出结构符合MODULE.md规范）
> 脚本: ic_volume_ratio_1d.py（236行）
> 测试目的: 验证量比因子IC计算脚本的功能完整性、输出结构合规性、边界处理正确性
> 更新内容:
>   1. v1.5 测试用例创建（2026-05-21 02:15）
>   2. v1.6 Newey-West 重构同步（2026-05-21 02:25）：
>      - TC001预期日志更新：Newey-West 调整版日志格式
>      - statistical_significance 字段添加 nw_lag, nw_lag_method, conclusion
>      - 五维度判断字段结构对齐公共模块标准
>   3. v1.7 废弃代码清理同步（2026-05-21 02:35）：
>      - 删除 calculate_daily_ic_series 函数引用（已改用公共模块）
>      - 流程文档架构图更新：calculate_daily_ic_series → calculate_ic_with_direction_verification
>   4. v1.8 SKIP模式修复同步（2026-05-23 22:45）：
>      - TC001预期日志更新：步骤编号 [N/4]
>      - TC004预期结果更新：SKIP模式不修改缓存对象
>      - 异常处理测试更新：分开处理多种异常类型

---

## 测试用例概述

| 用例ID | 测试类型 | 测试内容 | 优先级 |
|--------|---------|---------|--------|
| TC001 | 核心流程 | 正常数据加载与IC计算 | P0 |
| TC002 | 输出验证 | JSON结构完整性检查 | P0 |
| TC003 | 输出验证 | 五维度字段完整性检查 | P0 |
| TC004 | 边界条件 | 空数据分支处理 | P1 |
| TC005 | 输入验证 | 缓存文件不存在处理 | P1 |
| TC006 | 数据对齐 | 因子与收益日期不对齐处理 | P1 |

---

## TC001: 核心流程测试

**测试目的:** 验证正常数据加载与IC计算的完整流程

**前置条件:**
- 缓存文件存在：`cache/factor_data/factor_data.json.gz`
- 缓存文件存在：`cache/factor_data/return_data.json.gz`
- 数据包含 volume_ratio_5 列
- 数据包含 forward_return_1d 列

**测试步骤:**
```
1. 运行脚本: python ic_volume_ratio_1d.py
2. 观察输出日志
3. 检查输出文件: factor_ic/result/ic_volume_ratio_1d_analysis_result.json
```

**预期结果:**
```
✓ 脚本正常执行，无异常抛出
✓ 输出日志包含：
  - "[数据加载] 从缓存读取数据..."
  - "[2/4] 计算每日 IC（Newey-West 调整）..."
  - "t 统计量（NW调整）: -X.XX"
  - "NW lag: X"
  - "[3/4] 执行分层回测..."
  - "完成！共计算 X 天有效 IC 数据（原始数据 Y 天）"
✓ 输出文件存在且非空
✓ 输出文件JSON格式正确
```

**验证方法:**
```bash
# 检查输出文件是否存在
ls -lh factor_ic/result/ic_volume_ratio_1d_analysis_result.json

# 检查JSON格式
python -c "import json; json.load(open('factor_ic/result/ic_volume_ratio_1d_analysis_result.json'))"

# 检查关键字段
python -c "
import json
result = json.load(open('factor_ic/result/ic_volume_ratio_1d_analysis_result.json'))
print('factor_name:', result.get('factor_name'))
print('ic_mean:', result.get('ic_metrics', {}).get('ic_mean'))
print('valid_days:', result.get('sample_stats', {}).get('valid_days'))
"
```

---

## TC002: 输出结构完整性测试

**测试目的:** 验证输出JSON结构符合MODULE.md规范

**前置条件:** TC001执行成功

**测试步骤:**
```
1. 加载输出文件JSON
2. 检查顶层字段列表
3. 检查嵌套字段结构
```

**预期结果（顶层字段）:**
```
✓ factor_name: 'volume_ratio_1d'
✓ calculation_date: 存在（YYYY-MM-DD格式）
✓ period: 存在且包含 start, end
✓ ic_metrics: 存在且包含 ic_mean, ic_std, icir, p_value, p_value_display
✓ sample_stats: 存在且包含 total_days, valid_days, avg_stocks_per_day, avg_stocks_period
✓ statistical_significance: 存在且包含 t_stat, p_value, p_value_display, nw_lag, nw_lag_method, is_significant, conclusion
✓ factor_direction: 存在且包含 ic_mean, ic_mean_sign, direction_usage, conclusion
✓ economic_significance: 存在且包含 abs_ic_mean, level, is_economically_significant, conclusion
✓ icir_stability: 存在且包含 icir, level, is_stable, conclusion
✓ ic_distribution_consistency: 存在且包含 positive_ratio, ic_mean_sign, is_consistent, consistency_type, conclusion
✓ dates: 存在且为非空数组
✓ ic_values: 存在且为非空数组
✓ rolling_ic_mean: 存在且为数组（前9个可为None）
✓ positive_ratio: 存在且为数值
✓ n_assets: 存在且为整数
✓ summary: 存在且包含相关字段
✓ factor_stats: 存在且包含相关字段
✓ update_mode: 存在（'full'/'incremental'/'failed'）
```

**验证方法:**
```bash
python -c "
import json
result = json.load(open('factor_ic/result/ic_volume_ratio_1d_analysis_result.json'))

# 顶层字段检查
required_fields = [
    'factor_name', 'calculation_date', 'period', 'ic_metrics', 'sample_stats',
    'statistical_significance', 'factor_direction', 'economic_significance',
    'icir_stability', 'ic_distribution_consistency',
    'dates', 'ic_values', 'rolling_ic_mean', 'positive_ratio', 'n_assets',
    'summary', 'factor_stats', 'update_mode'
]

missing = [f for f in required_fields if f not in result]
if missing:
    print('❌ 缺少顶层字段:', missing)
else:
    print('✓ 所有顶层字段存在')

# 嵌套字段检查（Newey-West 标准结构）
nested_required = {
    'ic_metrics': ['ic_mean', 'ic_std', 'icir', 'p_value', 'p_value_display'],
    'sample_stats': ['total_days', 'valid_days', 'avg_stocks_per_day', 'avg_stocks_period'],
    'statistical_significance': ['t_stat', 'p_value', 'p_value_display', 'nw_lag', 'nw_lag_method', 'is_significant', 'conclusion'],
    'factor_direction': ['ic_mean', 'ic_mean_sign', 'direction_usage', 'conclusion'],
    'economic_significance': ['abs_ic_mean', 'level', 'is_economically_significant', 'conclusion'],
    'icir_stability': ['icir', 'level', 'is_stable', 'conclusion'],
    'ic_distribution_consistency': ['positive_ratio', 'ic_mean_sign', 'is_consistent', 'consistency_type', 'conclusion']
}

for parent, children in nested_required.items():
    parent_obj = result.get(parent, {})
    missing_children = [c for c in children if c not in parent_obj]
    if missing_children:
        print(f'❌ {parent} 缺少字段:', missing_children)
    else:
        print(f'✓ {parent} 字段完整')
"
```

---

## TC003: 五维度判断测试

**测试目的:** 验证五维度判断逻辑正确性

**前置条件:** TC001执行成功

**测试步骤:**
```
1. 获取 statistical_significance 字段
2. 验证判断逻辑（|t| > 1.96 ↔ p < 0.05）
3. 获取 factor_direction 字段
4. 验证判断逻辑（ic_mean 符号）
5. 获取 economic_significance 字段
6. 验证判断逻辑（ICIR > 0.5）
7. 获取 icir_stability 字段
8. 验证判断逻辑（IC_std < 0.15）
9. 获取 ic_distribution_consistency 字段
10. 验证判断逻辑（positive_ratio 与 ic_mean_sign 匹配）
```

**预期结果:**
```
✓ statistical_significance.is_significant 与 |t_stat| > 1.96 一致
✓ factor_direction.ic_mean_sign 根据实际 ic_mean 确定
  - ic_mean > 0.03 → 'positive'
  - ic_mean < -0.03 → 'negative'
  - 其他 → 'neutral'
✓ economic_significance.is_economically_significant 与 ICIR > 0.5 一致
✓ icir_stability.is_stable 与 IC_std < 0.15 一致
✓ ic_distribution_consistency.is_consistent 判断正确
  - 正向因子：positive_ratio > 0.55 → True
  - 反向因子：positive_ratio < 0.45 → True
```

**验证方法:**
```bash
python -c "
import json
import math

result = json.load(open('factor_ic/result/ic_volume_ratio_1d_analysis_result.json'))

# 第1维：统计显著性
ss = result.get('statistical_significance', {})
t_stat = ss.get('t_stat', 0)
is_sig = ss.get('is_significant', False)
expected_sig = abs(t_stat) > 1.96
print(f'第1维: |t|={abs(t_stat):.2f}, is_significant={is_sig}, expected={expected_sig}')
print(f'  ✓ 一致' if is_sig == expected_sig else f'  ❌ 不一致')

# 第2维：因子方向
fd = result.get('factor_direction', {})
ic_mean = result.get('ic_metrics', {}).get('ic_mean', 0)
ic_mean_sign = fd.get('ic_mean_sign')
expected_sign = 'positive' if ic_mean > 0.03 else 'negative' if ic_mean < -0.03 else 'neutral'
print(f'第2维: ic_mean={ic_mean:.4f}, sign={ic_mean_sign}, expected={expected_sign}')
print(f'  ✓ 一致' if ic_mean_sign == expected_sign else f'  ❌ 不一致')

# 第3维：经济显著性
es = result.get('economic_significance', {})
icir = result.get('ic_metrics', {}).get('icir', 0)
is_eco_sig = es.get('is_economically_significant', False)
expected_eco = icir > 0.5
print(f'第3维: ICIR={icir:.2f}, is_economically_significant={is_eco_sig}, expected={expected_eco}')
print(f'  ✓ 一致' if is_eco_sig == expected_eco else f'  ❌ 不一致')

# 第4维：ICIR稳定性
is_stable = result.get('icir_stability', {}).get('is_stable', False)
ic_std = result.get('ic_metrics', {}).get('ic_std', 0)
expected_stable = ic_std < 0.15
print(f'第4维: IC_std={ic_std:.4f}, is_stable={is_stable}, expected={expected_stable}')
print(f'  ✓ 一致' if is_stable == expected_stable else f'  ❌ 不一致')

# 第5维：IC分布一致性
idc = result.get('ic_distribution_consistency', {})
is_consistent = idc.get('is_consistent', False)
positive_ratio = result.get('positive_ratio', 0)
print(f'第5维: positive_ratio={positive_ratio:.1%}, is_consistent={is_consistent}')
"
```

---

## TC004: 空数据分支测试

**测试目的:** 验证数据加载失败时返回完整字段结构

**前置条件:**
- 缓存文件不存在或损坏

**测试步骤:**
```
1. 删除缓存文件（临时）
2. 运行脚本
3. 检查返回结构
4. 恢复缓存文件
```

**预期结果:**
```
✓ 脚本不崩溃，返回包含 'success': False 的结构
✓ 返回结构包含所有五维度字段（值为默认值）
✓ 返回结构包含 dates=[], ic_values=[], rolling_ic_mean=[]
✓ 返回结构包含 error 字段描述失败原因
```

**验证方法:**
```bash
# 临时移除缓存文件
mv cache/factor_data/factor_data.json.gz cache/factor_data/factor_data.json.gz.bak

# 运行脚本
python ic_volume_ratio_1d.py

# 检查输出（如果脚本输出到stdout）
# 或检查输出文件是否包含完整字段结构

# 恢复缓存文件
mv cache/factor_data/factor_data.json.gz.bak cache/factor_data/factor_data.json.gz
```

---

## TC005: 缓存文件不存在测试

**测试目的:** 验证 FileNotFoundError 处理

**前置条件:**
- `cache/factor_data/factor_data.json.gz` 不存在

**测试步骤:**
```
1. 运行脚本
2. 观察错误输出
```

**预期结果:**
```
✓ 输出友好错误信息："[错误] 缓存文件不存在"
✓ 输出建议："请先运行数据缓存脚本生成数据"
✓ 脚本退出码非0
```

---

## TC006: 数据对齐测试

**测试目的:** 验证因子数据与收益数据日期不对齐时的处理

**前置条件:**
- 因子数据和收益数据日期范围不完全一致

**测试步骤:**
```
1. 检查日志中的对齐信息
2. 验证选择交集日期的处理
```

**预期结果:**
```
✓ 输出警告信息："[警告] 因子数据和收益数据日期不对齐"
✓ 输出对齐后日期数
✓ 使用交集日期进行IC计算
```

---

## 测试执行顺序

```
TC001 → TC002 → TC003 → TC004 → TC005 → TC006
核心流程 → 输出验证 → 五维度验证 → 边界条件 → 异常处理 → 数据对齐
```

---

## 测试报告格式

执行测试后，输出以下格式的报告：

```
测试报告：ic_volume_ratio_1d.py
执行时间：YYYY-MM-DD HH:MM

| 用例ID | 状态 | 结果 |
|--------|------|------|
| TC001  | ✓/❌ | 正常执行/异常描述 |
| TC002  | ✓/❌ | 结构完整/缺失字段 |
| TC003  | ✓/❌ | 判断正确/逻辑错误 |
| TC004  | ✓/❌ | 正确处理/结构不完整 |
| TC005  | ✓/❌ | 友好提示/错误穿透 |
| TC006  | ✓/❌ | 对齐正确/数据丢失 |

总通过率：X/Y
```

---

## 参考规范

- PROJECT.md: 脚本配套文件规范（测试用例命名）
- MODULE.md: 输出结构统一性规范
- MODULE.md: 五维度判断规范
- MODULE.md: 数据对齐验证规范

---

## 更新记录

| 版本 | 时间 | 更新内容 |
|------|------|---------|
| v1.5 | 2026-05-21 02:15 | 同步代码v1.4优化：TC001日志添加min_stocks参数、statistical_significance添加p_value_display字段 |
| v1.0 | 2026-05-21 01:30 | 首次创建测试用例文件 |