# factor_summary_report 9项问题修复设计

## 问题清单

| # | 问题 | 涉及文件 | 根因 |
|---|------|----------|------|
| 1 | volume_ratio权重矛盾（第四节9.6% vs 第五节11% vs 第六节9.6%） | generate_factor_summary_report.py | 权重来源不一致（第四节/六节用ICIR加权，第五节用各方法权重），未说明 |
| 2 | ICIR加权优于IC加权但最优选了IC加权 | weight_selector.py | 评分逻辑可能有问题 |
| 3 | 第七节日期2026-06-05 vs 第八节2026-06-04不一致 | generate_factor_summary_report.py | weight_selection vs stock_selection日期来源不同 |
| 4 | turnover_surge剔除条件 `|ICIR|=0.32<0.32` 边界错误 | factor_selector.py | 高相关剔除逻辑边界判断 `<` 应为 `<=` |
| 5 | tail_volume_shrink 11天 vs 其他尾盘14天缺失未说明 | generate_factor_summary_report.py | 数据完整性检查无说明 |
| 6 | overnight_ret IC均值正方向异常未分析 | factor_selector.py | 剔除原因只看绝对值，未标注方向异常 |
| 7 | intraday_intensity_1d vs intraday_intensity命名不一致 | generate_factor_summary_report.py + backtest脚本 | 第二节显示文件名后缀，其他节显示因子名 |
| 8 | 相关性矩阵未展示高相关剔除对 | generate_factor_summary_report.py | 只展示选中因子，未展示剔除依据 |
| 9 | IC加权权重标签两个tai无法区分 | generate_factor_summary_report.py | 权重标签缩写冲突 |

## 修复方案

### 问题1：权重显示来源说明
- **修复**：在第四节和第六节添加说明"权重来自ICIR加权方法"，第五节已说明各方法权重

### 问题2：权重选择评分逻辑检查
- **诊断**：检查weight_selector.py评分逻辑，ICIR加权在多空收益、夏普、单调性三指标均优为何选IC加权
- **可能原因**：评分指标权重配置或归一化问题

### 问题3：日期不一致说明
- **修复**：第七节添加说明"权重选择计算日期"，第八节添加说明"选股执行日期（使用T-1数据）"

### 问题4：高相关剔除边界逻辑
- **修复**：factor_selector.py高相关剔除逻辑 `|ICIR| < retained_ICIR` 改为 `|ICIR| <= retained_ICIR`
- **位置**：factor_selector.py 约第400行

### 问题5：数据天数缺失说明
- **修复**：在第一节表格后添加异常数据说明："tail_volume_shrink 有效天数11天（其他尾盘因子14天），数据可能缺失"

### 问题6：方向异常标注
- **修复**：overnight_ret剔除原因添加"方向异常（IC均值正，与其他因子相反）"

### 问题7：因子名统一
- **修复**：第二节显示因子名而非文件名后缀，检查backtest脚本命名

### 问题8：高相关对展示
- **修复**：第三节添加"剔除高相关因子对"表格，展示corr=0.86和corr=0.98两对

### 问题9：权重标签缩写区分
- **修复**：权重标签改为完整缩写：`tp_vol:33%`（tail_price_volume_intensity）、`tp_pos:22%`（tail_price_position）

## 执行顺序

1. 先诊断问题2（weight_selector评分逻辑）
2. 修复generate_factor_summary_report.py（问题1,3,5,7,8,9）
3. 修复factor_selector.py（问题4,6）
4. 验证测试
5. Git commit

## 验证检查

- [ ] 报告各节权重显示一致且有说明
- [ ] weight_selector评分逻辑验证
- [ ] 日期不一致有说明
- [ ] 高相关剔除边界 `<=` 而非 `<`
- [ ] 数据天数异常有说明
- [ ] overnight_ret方向异常有标注
- [ ] 因子名统一为intraday_intensity
- [ ] 高相关对有展示
- [ ] 权重标签可区分