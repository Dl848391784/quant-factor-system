# composite_runner 方向统一化流程文档

> 创建日期: 2026-06-10
> v2.47 更新 (2026-06-23): 方向语义对齐到 positive（设计：`designs/direction_align_to_positive_v247.md`）
> 对应规范: MODULE.md M56 (N 类规则)
> 对应代码: `comprehensive_factor/common/composite_runner.py` Step 5

---

## 版本历史

| 版本 | 日期 | 行为 |
|------|------|------|
| v2.13 | 2026-06-10 | 正向因子（ic_mean>0）取反 → 统一到 **negative** 语义，composite 低值=好 |
| **v2.47** | **2026-06-23** | **反向因子（ic_mean<0）取反 → 对齐到 positive 语义，composite 高值=好** |

数学等价：`composite_v247 = -composite_v213`，选股结果完全一致，仅符号镜像翻转，报告语义更直观。

---

## 1. 方向统一化原理（v2.47）

### 第一性原理推导

定义 `signal_i = sign(IC_i) × z_i`，不论 IC 方向，**signal 大 = 看好**。

加权和：
```
composite = Σ w_i × sign(IC_i) × z_i = Σ w_i × signal_i
```

composite 方向永远为 positive（值大 = 好），不依赖因子 IC 分布。

### 问题背景

综合因子组合了方向不同的因子：
- **正向因子** (ic_mean > 0): 如 `tail_price_position`（值大=好信号 → 标准化正值=好信号）
- **反向因子** (ic_mean < 0): 如 `turnover_surge`（缩量=好信号 → 标准化负值=好信号）

如果不统一方向，两类因子加权后**信号抵消**而非叠加。

### 解决方案（v2.47）

反向因子标准化值取反 (`-*_std`)，使所有因子对齐到**正向语义**：

| 因子类型 | ic_mean | 标准化值语义 | 取反后语义 |
|---------|---------|------------|-----------|
| 正向因子 | > 0 | 正值=好信号 | 保持不变（正值=好信号） |
| 反向因子 | < 0 | 负值=好信号 | 取反后正值=好信号 |

取反后综合因子对齐到正向因子：**高值 = 好信号** → `factor_direction='positive'`

---

## 2. 流程图

```
Step 4: 标准化 (M9)
  factor_std = (factor - μ) / σ
  → 生成 *_std 列
                              ↓
Step 5: 方向统一化 (M56, v2.47)
  ├─ 输入: factor_df (含 *_std 列), ic_results (含 ic_mean)
  ├─ 遍历每个因子:
  │   ├─ ic_mean < 0 (反向) → factor_df[*_std] = -factor_df[*_std]
  │   ├─ ic_mean ≥ 0 (正向) → 保持不变
  │   └─ ic_mean = None (缺失) → 保持原值, direction_map[factor] = 'unknown'
  ├─ 输出: direction_map (因子名→原始IC方向), flipped_factors (被取反的反向因子列表)
  └─ 写入 JSON config.direction_map + config.flipped_factors
                              ↓
Step 5b: 计算因子相关性（基于方向统一化后的数据）
                              ↓
Step 6: 加权计算综合因子 (B 类规则)
  所有因子 *_std 已对齐到正向语义
  → composite_factor 高值=好信号
                              ↓
Step 7: 分层回测
  factor_direction = 'positive' (高值做多，低值做空)
  long_layers = [4, 5]，short_layers = [1, 2]
```

---

## 3. 数据流

### 输入

| 输入 | 来源 | 字段 |
|------|------|------|
| ic_results | `factor_ic/result/*.json` | `ic_mean` |
| factor_df | `data_fetchers/result/factor_ic_data.parquet` | `*_std` 列 |

### 输出

| 输出 | 写入位置 | 说明 |
|------|---------|------|
| direction_map | JSON `config.direction_map` | `{factor_name: 'negative'\|'positive'\|'unknown'}`（记录原始 IC 方向） |
| flipped_factors | JSON `config.flipped_factors` | v2.47: 被取反的**反向**因子名称列表（含义已反转） |

### direction_map 示例（v2.47）

```json
{
  "direction_map": {
    "turnover_surge": "negative",
    "momentum_strength": "negative",
    "tail_price_position": "positive",
    "tail_price_volume_intensity": "positive"
  },
  "flipped_factors": [
    "turnover_surge",
    "momentum_strength"
  ]
}
```

注意：v2.47 后 `flipped_factors` 含义反转——现在列出的是 IC<0 的反向因子（被翻到 positive），不再是 IC>0 的正向因子。

---

## 4. 下游一致性要求

### stock_selector.py 必须同步方向统一化

stock_selector 在计算综合因子时，必须执行相同的方向统一化步骤：
1. 从 composite 结果 JSON 读取 `config.direction_map`
2. 对反向因子（direction='negative'）的标准化值取反
3. 计算综合因子值与回测时一致

**如果不做方向统一化**：stock_selector 的综合因子值与回测时不一致，选股结果错误。

---

## 5. 边界情况

| 场景 | 处理 |
|------|------|
| ic_mean = None (IC缺失) | direction_map[factor]='unknown', 保持原值 |
| ic_mean = 0 (恰好为0) | 按正向处理（保持不变），因为 ic_mean=0 无明确方向 |
| 全部正向因子 | 无需取反，composite_factor 已是正向语义 |
| 全部反向因子 | 全部取反，composite_factor 对齐到正向语义 |

---

## 6. 与 v2.13 旧版的关系

v2.13 取反到 negative，v2.47 取反到 positive，两者数学完全镜像对称：

| | v2.13 | v2.47 |
|---|---|---|
| 取反对象 | ic_mean > 0（正向因子） | ic_mean < 0（反向因子） |
| composite 方向 | 'negative' (低值=好) | 'positive' (高值=好) |
| Layer 选择 | long_layers=[1,2], short=[4,5] | long_layers=[4,5], short=[1,2] |
| 选股结果 | argmin(composite) | argmax(composite) |
| 数学关系 | composite_old | composite_new = −composite_old |

**修改动机**：v2.45 实验启用 `require_positive_ic=True` 后，全部 IC>0 因子被强制取反，composite 全负 + factor_values_std 全负，反直觉且难排查。v2.47 镜像翻转后，IC>0 因子保持原值，composite 大 = 好，所见即所得。
