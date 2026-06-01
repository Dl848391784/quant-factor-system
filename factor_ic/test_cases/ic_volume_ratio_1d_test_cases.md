     1|# ic_volume_ratio_1d 测试用例
     2|
     3|> 版本: v1.9
     4|> 生成时间: 2026-05-23 22:55 北京时间
     5|> 实测数据时间: 2026-05-23 22:55（验证输出结构符合MODULE.md规范）
     6|> 脚本: ic_volume_ratio_1d.py（252行）
     7|> 测试目的: 验证量比因子IC计算脚本的功能完整性、输出结构合规性、边界处理正确性
     8|> 更新内容:
     9|>   1. v1.5 测试用例创建（2026-05-21 02:15）
    10|>   2. v1.6 Newey-West 重构同步（2026-05-21 02:25）：
    11|>      - TC001预期日志更新：Newey-West 调整版日志格式
    12|>      - statistical_significance 字段添加 nw_lag, nw_lag_method, conclusion
    13|>      - 五维度判断字段结构对齐公共模块标准
    14|>   3. v1.7 废弃代码清理同步（2026-05-21 02:35）：
    15|>      - 删除 calculate_daily_ic_series 函数引用（已改用公共模块）
    16|>      - 流程文档架构图更新：calculate_daily_ic_series → calculate_ic_with_direction_verification
    17|>   4. v1.8 SKIP模式修复同步（2026-05-23 22:45）：
    18|>      - TC001预期日志更新：步骤编号 [N/4]
    19|>      - TC004预期结果更新：SKIP模式不修改缓存对象
    20|>      - 异常处理测试更新：分开处理多种异常类型
    21|>   5. v1.9 CLI参数解析同步（2026-05-23 22:55）：
    22|>      - TC001预期日志更新：添加 [2/4] 步骤日志
    23|>      - 新增 TC007：CLI 参数测试（--force-full、--output、--min-stocks）
    24|>      - 验证结果摘要格式更新：因子名称、更新模式字段
    25|
    26|---
    27|
    28|## 测试用例概述
    29|
    30|| 用例ID | 测试类型 | 测试内容 | 优先级 |
    31||--------|---------|---------|--------|
    32|| TC001 | 核心流程 | 正常数据加载与IC计算 | P0 |
    33|| TC002 | 输出验证 | JSON结构完整性检查 | P0 |
    34|| TC003 | 输出验证 | 五维度字段完整性检查 | P0 |
    35|| TC004 | 边界条件 | 空数据分支处理 | P1 |
    36|| TC005 | 输入验证 | 缓存文件不存在处理 | P1 |
    37|| TC006 | 数据对齐 | 因子与收益日期不对齐处理 | P1 |
    38|
    39|---
    40|
    41|## TC001: 核心流程测试
    42|
    43|**测试目的:** 验证正常数据加载与IC计算的完整流程
    44|
    45|**前置条件:**
    46|- 缓存文件存在：`data_fetchers/result/factor_data.json.gz`
    47|- 缓存文件存在：`data_fetchers/result/factor_ic_data.json.gz`
    48|- 数据包含 volume_ratio_5 列
    49|- 数据包含 forward_return_1d 列
    50|
    51|**测试步骤:**
    52|```
    53|1. 运行脚本: python ic_volume_ratio_1d.py
    54|2. 观察输出日志
    55|3. 检查输出文件: factor_ic/result/ic_volume_ratio_1d_analysis_result.json
    56|```
    57|
    58|**预期结果:**
    59|```
    60|✓ 脚本正常执行，无异常抛出
    61|✓ 输出日志包含：
    62|  - "[数据加载] 从缓存读取数据..."
    63|  - "[2/4] 计算每日 IC（Newey-West 调整）..."
    64|  - "t 统计量（NW调整）: -X.XX"
    65|  - "NW lag: X"
    66|  - "[3/4] 执行分层回测..."
    67|  - "完成！共计算 X 天有效 IC 数据（原始数据 Y 天）"
    68|✓ 输出文件存在且非空
    69|✓ 输出文件JSON格式正确
    70|```
    71|
    72|**验证方法:**
    73|```bash
    74|# 检查输出文件是否存在
    75|ls -lh factor_ic/result/ic_volume_ratio_1d_analysis_result.json
    76|
    77|# 检查JSON格式
    78|python -c "import json; json.load(open('factor_ic/result/ic_volume_ratio_1d_analysis_result.json'))"
    79|
    80|# 检查关键字段
    81|python -c "
    82|import json
    83|result = json.load(open('factor_ic/result/ic_volume_ratio_1d_analysis_result.json'))
    84|print('factor_name:', result.get('factor_name'))
    85|print('ic_mean:', result.get('ic_metrics', {}).get('ic_mean'))
    86|print('valid_days:', result.get('sample_stats', {}).get('valid_days'))
    87|"
    88|```
    89|
    90|---
    91|
    92|## TC002: 输出结构完整性测试
    93|
    94|**测试目的:** 验证输出JSON结构符合MODULE.md规范
    95|
    96|**前置条件:** TC001执行成功
    97|
    98|**测试步骤:**
    99|```
   100|1. 加载输出文件JSON
   101|2. 检查顶层字段列表
   102|3. 检查嵌套字段结构
   103|```
   104|
   105|**预期结果（顶层字段）:**
   106|```
   107|✓ factor_name: 'volume_ratio_1d'
   108|✓ calculation_date: 存在（YYYY-MM-DD格式）
   109|✓ period: 存在且包含 start, end
   110|✓ ic_metrics: 存在且包含 ic_mean, ic_std, icir, p_value, p_value_display
   111|✓ sample_stats: 存在且包含 total_days, valid_days, avg_stocks_per_day, avg_stocks_period
   112|✓ statistical_significance: 存在且包含 t_stat, p_value, p_value_display, nw_lag, nw_lag_method, is_significant, conclusion
   113|✓ factor_direction: 存在且包含 ic_mean, ic_mean_sign, direction_usage, conclusion
   114|✓ economic_significance: 存在且包含 abs_ic_mean, level, is_economically_significant, conclusion
   115|✓ icir_stability: 存在且包含 icir, level, is_stable, conclusion
   116|✓ ic_distribution_consistency: 存在且包含 positive_ratio, ic_mean_sign, is_consistent, consistency_type, conclusion
   117|✓ dates: 存在且为非空数组
   118|✓ ic_values: 存在且为非空数组
   119|✓ rolling_ic_mean: 存在且为数组（前9个可为None）
   120|✓ positive_ratio: 存在且为数值
   121|✓ n_assets: 存在且为整数
   122|✓ summary: 存在且包含相关字段
   123|✓ factor_stats: 存在且包含相关字段
   124|✓ update_mode: 存在（'full'/'incremental'/'failed'）
   125|```
   126|
   127|**验证方法:**
   128|```bash
   129|python -c "
   130|import json
   131|result = json.load(open('factor_ic/result/ic_volume_ratio_1d_analysis_result.json'))
   132|
   133|# 顶层字段检查
   134|required_fields = [
   135|    'factor_name', 'calculation_date', 'period', 'ic_metrics', 'sample_stats',
   136|    'statistical_significance', 'factor_direction', 'economic_significance',
   137|    'icir_stability', 'ic_distribution_consistency',
   138|    'dates', 'ic_values', 'rolling_ic_mean', 'positive_ratio', 'n_assets',
   139|    'summary', 'factor_stats', 'update_mode'
   140|]
   141|
   142|missing = [f for f in required_fields if f not in result]
   143|if missing:
   144|    print('❌ 缺少顶层字段:', missing)
   145|else:
   146|    print('✓ 所有顶层字段存在')
   147|
   148|# 嵌套字段检查（Newey-West 标准结构）
   149|nested_required = {
   150|    'ic_metrics': ['ic_mean', 'ic_std', 'icir', 'p_value', 'p_value_display'],
   151|    'sample_stats': ['total_days', 'valid_days', 'avg_stocks_per_day', 'avg_stocks_period'],
   152|    'statistical_significance': ['t_stat', 'p_value', 'p_value_display', 'nw_lag', 'nw_lag_method', 'is_significant', 'conclusion'],
   153|    'factor_direction': ['ic_mean', 'ic_mean_sign', 'direction_usage', 'conclusion'],
   154|    'economic_significance': ['abs_ic_mean', 'level', 'is_economically_significant', 'conclusion'],
   155|    'icir_stability': ['icir', 'level', 'is_stable', 'conclusion'],
   156|    'ic_distribution_consistency': ['positive_ratio', 'ic_mean_sign', 'is_consistent', 'consistency_type', 'conclusion']
   157|}
   158|
   159|for parent, children in nested_required.items():
   160|    parent_obj = result.get(parent, {})
   161|    missing_children = [c for c in children if c not in parent_obj]
   162|    if missing_children:
   163|        print(f'❌ {parent} 缺少字段:', missing_children)
   164|    else:
   165|        print(f'✓ {parent} 字段完整')
   166|"
   167|```
   168|
   169|---
   170|
   171|## TC003: 五维度判断测试
   172|
   173|**测试目的:** 验证五维度判断逻辑正确性
   174|
   175|**前置条件:** TC001执行成功
   176|
   177|**测试步骤:**
   178|```
   179|1. 获取 statistical_significance 字段
   180|2. 验证判断逻辑（|t| > 1.96 ↔ p < 0.05）
   181|3. 获取 factor_direction 字段
   182|4. 验证判断逻辑（ic_mean 符号）
   183|5. 获取 economic_significance 字段
   184|6. 验证判断逻辑（ICIR > 0.5）
   185|7. 获取 icir_stability 字段
   186|8. 验证判断逻辑（IC_std < 0.15）
   187|9. 获取 ic_distribution_consistency 字段
   188|10. 验证判断逻辑（positive_ratio 与 ic_mean_sign 匹配）
   189|```
   190|
   191|**预期结果:**
   192|```
   193|✓ statistical_significance.is_significant 与 |t_stat| > 1.96 一致
   194|✓ factor_direction.ic_mean_sign 根据实际 ic_mean 确定
   195|  - ic_mean > 0.03 → 'positive'
   196|  - ic_mean < -0.03 → 'negative'
   197|  - 其他 → 'neutral'
   198|✓ economic_significance.is_economically_significant 与 ICIR > 0.5 一致
   199|✓ icir_stability.is_stable 与 IC_std < 0.15 一致
   200|✓ ic_distribution_consistency.is_consistent 判断正确
   201|  - 正向因子：positive_ratio > 0.55 → True
   202|  - 反向因子：positive_ratio < 0.45 → True
   203|```
   204|
   205|**验证方法:**
   206|```bash
   207|python -c "
   208|import json
   209|import math
   210|
   211|result = json.load(open('factor_ic/result/ic_volume_ratio_1d_analysis_result.json'))
   212|
   213|# 第1维：统计显著性
   214|ss = result.get('statistical_significance', {})
   215|t_stat = ss.get('t_stat', 0)
   216|is_sig = ss.get('is_significant', False)
   217|expected_sig = abs(t_stat) > 1.96
   218|print(f'第1维: |t|={abs(t_stat):.2f}, is_significant={is_sig}, expected={expected_sig}')
   219|print(f'  ✓ 一致' if is_sig == expected_sig else f'  ❌ 不一致')
   220|
   221|# 第2维：因子方向
   222|fd = result.get('factor_direction', {})
   223|ic_mean = result.get('ic_metrics', {}).get('ic_mean', 0)
   224|ic_mean_sign = fd.get('ic_mean_sign')
   225|expected_sign = 'positive' if ic_mean > 0.03 else 'negative' if ic_mean < -0.03 else 'neutral'
   226|print(f'第2维: ic_mean={ic_mean:.4f}, sign={ic_mean_sign}, expected={expected_sign}')
   227|print(f'  ✓ 一致' if ic_mean_sign == expected_sign else f'  ❌ 不一致')
   228|
   229|# 第3维：经济显著性
   230|es = result.get('economic_significance', {})
   231|icir = result.get('ic_metrics', {}).get('icir', 0)
   232|is_eco_sig = es.get('is_economically_significant', False)
   233|expected_eco = icir > 0.5
   234|print(f'第3维: ICIR={icir:.2f}, is_economically_significant={is_eco_sig}, expected={expected_eco}')
   235|print(f'  ✓ 一致' if is_eco_sig == expected_eco else f'  ❌ 不一致')
   236|
   237|# 第4维：ICIR稳定性
   238|is_stable = result.get('icir_stability', {}).get('is_stable', False)
   239|ic_std = result.get('ic_metrics', {}).get('ic_std', 0)
   240|expected_stable = ic_std < 0.15
   241|print(f'第4维: IC_std={ic_std:.4f}, is_stable={is_stable}, expected={expected_stable}')
   242|print(f'  ✓ 一致' if is_stable == expected_stable else f'  ❌ 不一致')
   243|
   244|# 第5维：IC分布一致性
   245|idc = result.get('ic_distribution_consistency', {})
   246|is_consistent = idc.get('is_consistent', False)
   247|positive_ratio = result.get('positive_ratio', 0)
   248|print(f'第5维: positive_ratio={positive_ratio:.1%}, is_consistent={is_consistent}')
   249|"
   250|```
   251|
   252|---
   253|
   254|## TC004: 空数据分支测试
   255|
   256|**测试目的:** 验证数据加载失败时返回完整字段结构
   257|
   258|**前置条件:**
   259|- 缓存文件不存在或损坏
   260|
   261|**测试步骤:**
   262|```
   263|1. 删除缓存文件（临时）
   264|2. 运行脚本
   265|3. 检查返回结构
   266|4. 恢复缓存文件
   267|```
   268|
   269|**预期结果:**
   270|```
   271|✓ 脚本不崩溃，返回包含 'success': False 的结构
   272|✓ 返回结构包含所有五维度字段（值为默认值）
   273|✓ 返回结构包含 dates=[], ic_values=[], rolling_ic_mean=[]
   274|✓ 返回结构包含 error 字段描述失败原因
   275|```
   276|
   277|**验证方法:**
   278|```bash
   279|# 临时移除缓存文件
   280|mv data_fetchers/result/factor_data.json.gz data_fetchers/result/factor_data.json.gz.bak
   281|
   282|# 运行脚本
   283|python ic_volume_ratio_1d.py
   284|
   285|# 检查输出（如果脚本输出到stdout）
   286|# 或检查输出文件是否包含完整字段结构
   287|
   288|# 恢复缓存文件
   289|mv data_fetchers/result/factor_data.json.gz.bak data_fetchers/result/factor_data.json.gz
   290|```
   291|
   292|---
   293|
   294|## TC005: 缓存文件不存在测试
   295|
   296|**测试目的:** 验证 FileNotFoundError 处理
   297|
   298|**前置条件:**
   299|- `data_fetchers/result/factor_data.json.gz` 不存在
   300|
   301|**测试步骤:**
   302|```
   303|1. 运行脚本
   304|2. 观察错误输出
   305|```
   306|
   307|**预期结果:**
   308|```
   309|✓ 输出友好错误信息："[错误] 缓存文件不存在"
   310|✓ 输出建议："请先运行数据缓存脚本生成数据"
   311|✓ 脚本退出码非0
   312|```
   313|
   314|---
   315|
   316|## TC006: 数据对齐测试
   317|
   318|**测试目的:** 验证因子数据与收益数据日期不对齐时的处理
   319|
   320|**前置条件:**
   321|- 因子数据和收益数据日期范围不完全一致
   322|
   323|**测试步骤:**
   324|```
   325|1. 检查日志中的对齐信息
   326|2. 验证选择交集日期的处理
   327|```
   328|
   329|**预期结果:**
   330|```
   331|✓ 输出警告信息："[警告] 因子数据和收益数据日期不对齐"
   332|✓ 输出对齐后日期数
   333|✓ 使用交集日期进行IC计算
   334|```
   335|
   336|---
   337|
   338|## 测试执行顺序
   339|
   340|```
   341|TC001 → TC002 → TC003 → TC004 → TC005 → TC006
   342|核心流程 → 输出验证 → 五维度验证 → 边界条件 → 异常处理 → 数据对齐
   343|```
   344|
   345|---
   346|
   347|## 测试报告格式
   348|
   349|执行测试后，输出以下格式的报告：
   350|
   351|```
   352|测试报告：ic_volume_ratio_1d.py
   353|执行时间：YYYY-MM-DD HH:MM
   354|
   355|| 用例ID | 状态 | 结果 |
   356||--------|------|------|
   357|| TC001  | ✓/❌ | 正常执行/异常描述 |
   358|| TC002  | ✓/❌ | 结构完整/缺失字段 |
   359|| TC003  | ✓/❌ | 判断正确/逻辑错误 |
   360|| TC004  | ✓/❌ | 正确处理/结构不完整 |
   361|| TC005  | ✓/❌ | 友好提示/错误穿透 |
   362|| TC006  | ✓/❌ | 对齐正确/数据丢失 |
   363|
   364|总通过率：X/Y
   365|```
   366|
   367|---
   368|
   369|## 参考规范
   370|
   371|- PROJECT.md: 脚本配套文件规范（测试用例命名）
   372|- MODULE.md: 输出结构统一性规范
   373|- MODULE.md: 五维度判断规范
   374|- MODULE.md: 数据对齐验证规范
   375|
   376|---
   377|
   378|## 更新记录
   379|
   380|| 版本 | 时间 | 更新内容 |
   381||------|------|---------|
   382|| v1.5 | 2026-05-21 02:15 | 同步代码v1.4优化：TC001日志添加min_stocks参数、statistical_significance添加p_value_display字段 |
   383|| v1.0 | 2026-05-21 01:30 | 首次创建测试用例文件 |