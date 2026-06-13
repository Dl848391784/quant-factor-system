# 因子汇总报告5项问题修复设计方案

> 创建时间: 2026-06-11
> 遵循: superpowers-workflow Plan阶段 + AGENTS.md Design-First（涉及2+文件）

## 问题清单与根因

| # | 问题 | 根因 | 修复位置 |
|---|------|------|----------|
| 1 | overnight_ret方向处理不透明 | composite JSON正确记录direction_map/flipped_factors，但报告第5、8节未展示 | summary/generate_factor_summary_report.py |
| 2 | 缺失因子值股票仍排名高 | stock_selector无最小权重覆盖门槛 | comprehensive_factor/stock_selector.py |
| 3 | 综合因子收益低于单因子 | 方向处理已正确(已验证JSON)，问题2+4导致选股不可信 | 报告需补充方向说明(修问题1+4自然改善) |
| 4 | 短样本因子权重62.2% | validate_factor无样本量门槛 | comprehensive_factor/common/factor_selector.py |
| 5 | tail_volume_shrink被剔除 | ic_mean豁免门槛0.01太严格+ICIR无回测豁免 | comprehensive_factor/common/factor_selector.py |

## 任务拆分（≤3文件/任务）

### 任务A: 因子筛选逻辑修复（问题4+5）
**文件**: factor_selector.py + MODULE.md (2文件)

#### 修复4: 短样本因子样本量门槛

**What**: 添加 `min_sample_days=30` 阈值到 DEFAULT_THRESHOLDS，valid_days<30的因子标记为无效

**How**:
1. DEFAULT_THRESHOLDS 新增 `"min_sample_days": 30`
2. validate_factor 新增样本量检查：
   - valid_days < min_sample_days → 标记为无效（理由: "有效天数=18<30，样本不足ICIR统计不可靠"）
   - 小样本豁免: 当 |icir| > 0.5 且 |sharpe| > 3 且 |mono_corr| > 0.7 时豁免（极端强劲回测可容忍小样本）
3. ICIR加权惩罚: 短样本因子的ICIR乘以 `sqrt(valid_days / min_sample_days)` 惩罚系数

**Don't**: 不排除所有<30天因子（极端强劲可豁免）；不简单截断权重（惩罚系数更平滑）

**Why**: 18天ICIR=0.8是统计噪声，p(t>2)=p(ICIR>2/sqrt(N))随N变化；30天是统计学最小可靠样本量

#### 修复5: 反向因子豁免扩展

**What**: 降低ic_mean豁免门槛从0.01→0.005，新增ICIR回测豁免通道

**How**:
1. is_reverse_factor_candidate 条件调整:
   - abs(ic_mean) >= 0.005（从0.01降低）
   - |sharpe| > 1.5（保持）
   - |mono_corr| > 0.5（保持）
2. 新增ICIR回测豁免通道:
   - abs(icir) < icir_abs_min 时检查回测指标
   - 条件: abs(ic_mean)>=0.005 AND |sharpe|>1.5 AND |mono_corr|>0.5
   - 豁免后跳过ICIR阈值检查

**Don't**: 不完全取消ic_mean/icir阈值（仍需最低预测能力信号）；不硬编码豁免因子名

**Why**: tail_volume_shrink(ic_mean=0.006, Sharpe=6.64, mono=-0.79)回测极强但IC统计弱，因18天数据线性IC被噪声淹没

---

### 任务B: 选股逻辑修复（问题2+方向信息输出）
**文件**: stock_selector.py + MODULE.md (2文件)

#### 修复2: 最小权重覆盖率门槛

**What**: 排名前检查每只股票的有效因子权重覆盖率，< 70% 的股票排除

**How**:
1. StockSelectorConfig 新增 `min_weight_coverage: float = 0.7`
2. sort_and_select 新增覆盖率检查:
   - 计算每只股票的有效因子权重占比 = sum(valid_factor_weights) / sum(all_factor_weights)
   - 覆盖率 < min_weight_coverage → 标记为不可信，不参与排序
   - 排序前先过滤不可信股票
3. 结果中记录 excluded_stocks（排除原因：权重覆盖率不足）

**Don't**: 不简单排除所有有NaN的股票（部分NaN可接受）；不设100%覆盖门槛（太严格）

**Why**: 600500缺失27%权重因子仍排第2，综合因子值失真；70%门槛确保至少7成权重有数据

#### 修复1部分: 选股结果输出direction信息

**What**: stock_selection_result.json 的 meta 新增 direction_map 和 flipped_factors

**How**:
1. build_result 新增 meta 字段: direction_map, flipped_factors
2. 从 composite 结果或自行计算的方向映射写入结果

**Don't**: 不改变排序逻辑（已正确）

---

### 任务C: 报告展示修复（问题1+2+3）
**文件**: generate_factor_summary_report.py + MODULE.md (2文件)

#### 修复1: 报告第5、8节展示方向信息

**What**: 第五节综合因子权重表增加direction_map说明，第八节选股结果增加方向处理说明

**How**:
1. 第五节：读取composite JSON的direction_map，在权重表后添加方向说明行
   - 格式: "方向统一化: overnight_ret(正向)→取反，其余6因子(负向)→保持，综合因子统一为负向语义"
2. 第八节：选股结果后添加方向处理说明
   - 格式: "方向处理: 综合因子为反向因子(negative)，正向因子overnight_ret已取反参与加权"

**Don't**: 不硬编码因子方向（从composite JSON动态读取）

#### 修复2: 报告第8节标记缺失因子和不可信股票

**What**: 选股结果中标记缺失因子值，并标注权重覆盖率

**How**:
1. 因子值=0.00且实际为缺失时标记为"缺失"而非"0.00"
2. 每只选股股票显示权重覆盖率: "覆盖率: 73% (缺失tail_price_position 27%权重)"
3. 覆盖率<70%的股票标注⚠不可信

**Don't**: 不隐藏缺失因子（用户需看到）；不自动排除（让用户判断）

#### 修复3: 报告第6节补充方向说明

**What**: 综合因子vs单因子对比时，补充方向统一化解释

**How**:
1. 在"数据覆盖差异说明"之后追加"方向统一化说明"
   - 格式: "方向统一化说明: 正向因子overnight_ret(ic_mean>0)在加权前取反，统一为负向语义。综合因子低值=好信号，与所有成分单因子方向一致。不存在二次反向问题。"

---

## 修复优先级

1. **任务A** → 筛选逻辑修复（根因层：问题4+5影响后续所有结果）
2. **任务B** → 选股逻辑修复（根因层：问题2直接影响选股可信度）
3. **任务C** → 报告展示修复（展示层：问题1+3是信息透明度问题）

## 验证计划

每个任务完成后：
1. ruff check + format
2. pytest 相关测试用例
3. 运行 pipeline 生成新报告
4. 对照5个问题逐一验证修复效果

## 规范引用

- M12: 无效因子判定标准（行556-583，factor_selector.py）
- M56: 因子方向统一化（行1742-1821，MODULE.md）
- M8: 向量化加权实现（行464-484，MODULE.md）
- AGENTS.md 行30-36: 4阶段流程
- AGENTS.md 行40-42: Design-First + 任务粒度约束