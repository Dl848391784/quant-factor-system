# composite_runner 方向统一化流程文档

> 创建日期: 2026-06-10
> 对应规范: MODULE.md M56 (N 类规则)
> 对应代码: `composite_runner/common/composite_runner.py` 第 387-429 行

---

## 1. 方向统一化原理

### 问题背景

综合因子组合了方向不同的因子：
- **负向因子** (ic_mean < 0): 如 `turnover_surge`（缩量=好信号 → 标准化负值=好信号）
- **正向因子** (ic_mean > 0): 如 `tail_price_position`（值大=好信号 → 标准化正值=好信号）

如果不统一方向，正向和负向因子加权后**信号抵消**而非叠加。

### 解决方案

正向因子标准化值取反 (`-*_std`)，使所有因子统一为**负向语义**：

| 因子类型 | ic_mean | 标准化值语义 | 取反后语义 |
|---------|---------|------------|-----------|
| 负向因子 | < 0 | 负值=好信号 | 保持不变（负值=好信号） |
| 正向因子 | > 0 | 正值=好信号 | 取反后负值=好信号 |

取反后综合因子统一为负向因子：**低值 = 好信号** → `factor_direction='negative'`

---

## 2. 流程图

```
Step 4: 标准化 (M9)
  factor_std = (factor - μ) / σ
  → 生成 *_std 列
                              ↓
Step 5: 方向统一化 (M56)
  ├─ 输入: factor_df (含 *_std 列), ic_results (含 ic_mean)
  ├─ 遍历每个因子:
  │   ├─ ic_mean > 0 (正向) → factor_df[*_std] = -factor_df[*_std]
  │   ├─ ic_mean ≤ 0 (负向) → 保持不变
  │   └─ ic_mean = None (缺失) → 保持原值, direction_map[factor] = 'unknown'
  ├─ 输出: direction_map (因子名→方向), flipped_factors (取反列表)
  └─ 写入 JSON config.direction_map + config.flipped_factors
                              ↓
Step 5b: 计算因子相关性（基于方向统一化后的数据）
                              ↓
Step 6: 加权计算综合因子 (B 类规则)
  所有因子 *_std 已统一为负向语义
  → composite_factor 低值=好信号
                              ↓
Step 7: 分层回测
  factor_direction = 'negative' (低值做多，高值做空)
```

---

## 3. 数据流

### 输入

| 输入 | 来源 | 字段 |
|------|------|------|
| ic_results | `factor_ic/result/*.json` | `ic_mean` |
| factor_df | `factor_ic_data.json.gz` | `*_std` 列 |

### 输出

| 输出 | 写入位置 | 说明 |
|------|---------|------|
| direction_map | JSON `config.direction_map` | `{factor_name: 'negative'|'positive'|'unknown'}` |
| flipped_factors | JSON `config.flipped_factors` | 取反的因子名称列表 |

### direction_map 示例

```json
{
  "direction_map": {
    "turnover_surge": "negative",
    "momentum_strength": "negative",
    "tail_price_position": "positive",
    "tail_price_volume_intensity": "positive"
  },
  "flipped_factors": [
    "tail_price_position",
    "tail_price_volume_intensity"
  ]
}
```

---

## 4. 下游一致性要求

### stock_selector.py 必须同步方向统一化

stock_selector 在计算综合因子时，必须执行相同的方向统一化步骤：
1. 从 composite 结果 JSON 读取 `config.direction_map`
2. 对正向因子（direction='positive'）的标准化值取反
3. 计算综合因子值与回测时一致

**如果不做方向统一化**：stock_selector 的综合因子值与回测时不一致，选股结果错误。

---

## 5. 边界情况

| 场景 | 处理 | 代码位置 |
|------|------|---------|
| ic_mean = None (IC缺失) | direction_map[factor]='unknown', 保持原值 | 行 402-409 |
| ic_mean = 0 (恰好为0) | 按负向处理(保持不变)，因为 ic_mean=0 无方向意义 | 行 421-423 |
| 全部正向因子 | 全部取反，composite_factor 仍为负向语义 | 正常流程 |
| 全部负向因子 | 无需取反，composite_factor 保持负向语义 | 正常流程 |

---

## 6. 与 Pitfall 40 的关系

Pitfall 40 规定：
- 正向因子（IC>0）在综合因子中取反 `*_std` 列以统一负向语义
- `direction_map` 存入 meta 供下游读取

M56 是 Pitfall 40 的规范化版本，补充了 What/Why/How/Don't/When/Verify 完整框架。