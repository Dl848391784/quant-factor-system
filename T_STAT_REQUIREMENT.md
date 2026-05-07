# 需求文档: RSI(6) Rank IC 页面添加 t_stat（t统计量）

## 背景

当前 RSI(6) Rank IC 页面展示了以下指标：
- IC 均值 (ic_mean)
- ICIR (icir = ic_mean / ic_std)
- 正比例 (positive_ratio)
- IC 标准差 (ic_std)
- 交易日数 (n_days)
- 资产数量 (n_assets)

**缺失**：t_stat（t统计量），用于检验 IC 是否显著不为 0。

### t_stat 的意义

t统计量用于检验因子的 IC 是否具有统计显著性。公式：

```
t_stat = ic_mean / (ic_std / sqrt(n))
```

其中：
- `ic_mean`: IC 均值
- `ic_std`: IC 标准差
- `n`: 样本数量（交易日数）

### 显著性判断标准

| t_stat 绝对值 | 置信水平 | 标识 |
|--------------|---------|------|
| > 1.96 | 95% | `*` |
| > 2.58 | 99% | `**` |
| > 3.29 | 99.9% | `***` |

---

## 技术需求（给云舟）

### 1. 修改 `reverse_rank_ic.py`

**位置**: `~/.openclaw/workspace/yunzhou/reverse_rank_ic.py`

**修改点**: `reverse_rank_ic()` 函数返回值

```python
# 当前返回（第 245-254 行）
return {
    'ic_series': ic_series,
    'ic_mean': ic_mean,
    'ic_std': ic_std,
    'icir': icir,
    'positive_ratio': positive_ratio,
    'summary': summary
}

# 修改后
import math

n = len(ic_series)  # 样本数量（交易日数）
t_stat = ic_mean / (ic_std / math.sqrt(n)) if ic_std > 0 else 0.0

return {
    'ic_series': ic_series,
    'ic_mean': ic_mean,
    'ic_std': ic_std,
    'icir': icir,
    'positive_ratio': positive_ratio,
    't_stat': t_stat,        # 新增
    'n_days': n,             # 新增（样本数量）
    'summary': summary
}
```

**输出格式要求**:
- `t_stat`: float，保留 4 位小数
- `n_days`: int

---

### 2. 修改 `rsi_ic_generator.py`

**位置**: `~/.openclaw/workspace/yunzhou/factor_ic_analyzer/rsi_ic_generator.py`

**修改点**: `calculate_daily_ic_series()` 函数返回值（约第 50-70 行）

```python
# 当前返回
return {
    'dates': dates,
    'ic_values': ic_values,
    'rolling_ic_mean': rolling_ic_mean,
    'ic_mean': round(result['ic_mean'], 6),
    'ic_std': round(result['ic_std'], 6),
    'icir': round(result['icir'], 4),
    'positive_ratio': round(result['positive_ratio'], 4),
    'summary': result['summary'],
    'n_days': len(dates),
    'n_assets': factor_df['asset'].nunique()
}

# 修改后
return {
    'dates': dates,
    'ic_values': ic_values,
    'rolling_ic_mean': rolling_ic_mean,
    'ic_mean': round(result['ic_mean'], 6),
    'ic_std': round(result['ic_std'], 6),
    'icir': round(result['icir'], 4),
    'positive_ratio': round(result['positive_ratio'], 4),
    't_stat': round(result['t_stat'], 4),        # 新增
    'n_days': len(dates),
    'n_assets': factor_df['asset'].nunique(),
    'summary': result['summary']
}
```

**注意**: `t_stat` 保留 4 位小数，与 `icir` 格式一致。

---

### 3. 修改 `rsi_ic.html`

**位置**: `~/.openclaw/workspace/yunzhou/factor_ic_analyzer/templates/rsi_ic.html`

#### 3.1 添加 t_stat 卡片

在 `stats-grid` 区域（约第 250-290 行）添加新的 stat-card：

```html
<!-- 在 "IC 标准差" 卡片后添加 -->
<div class="stat-card">
    <div class="label">t 统计量</div>
    <div class="value" id="tStat">--</div>
    <div class="subtitle" id="tStatSubtitle">T-Statistic</div>
</div>
```

#### 3.2 更新 `updateStats()` 函数

在 JavaScript 的 `updateStats()` 函数中（约第 420 行）添加：

```javascript
// t 统计量
const tStat = document.getElementById('tStat');
const tStatSubtitle = document.getElementById('tStatSubtitle');
const absTStat = Math.abs(data.t_stat);
let significance = '';

if (absTStat > 3.29) {
    significance = ' ***';  // 99.9% 显著
    tStat.className = 'value positive';
} else if (absTStat > 2.58) {
    significance = ' **';   // 99% 显著
    tStat.className = 'value positive';
} else if (absTStat > 1.96) {
    significance = ' *';    // 95% 显著
    tStat.className = 'value positive';
} else {
    significance = '';
    tStat.className = 'value';  // 不显著
}

tStat.textContent = data.t_stat.toFixed(4) + significance;
tStatSubtitle.textContent = `T-Statistic (n=${data.n_days})`;
```

#### 3.3 添加显著性说明

在 `info-section` 区域（约第 330 行）的指标说明中添加：

```html
<p><strong>t 统计量</strong>：检验 IC 是否显著不为 0。<code>|t| > 1.96</code> 表示 95% 显著，<code>|t| > 2.58</code> 表示 99% 显著，<code>|t| > 3.29</code> 表示 99.9% 显著。</p>
```

---

## 测试用例（给云汐）

### 测试场景 1：正常计算

**前置条件**: 系统已有至少 20 个交易日的数据

| 步骤 | 操作 | 预期结果 |
|------|------|---------|
| 1 | 访问 `/rsi-ic` 页面 | 页面正常加载 |
| 2 | 检查统计卡片区域 | 显示 "t 统计量" 卡片 |
| 3 | 检查 t_stat 值 | 显示数值，保留 4 位小数 |
| 4 | 检查显著性标识 | 根据 \|t_stat\| 显示对应的 `*` 标识 |

### 测试场景 2：显著性标识验证

| t_stat 值 | 预期显示 | 预期样式 |
|-----------|---------|---------|
| 1.50 | `1.5000` | 默认颜色 |
| 2.10 | `2.1000 *` | positive（绿色） |
| 2.80 | `2.8000 **` | positive（绿色） |
| 3.50 | `3.5000 ***` | positive（绿色） |
| -2.20 | `-2.2000 *` | positive（绿色） |

### 测试场景 3：边界值测试

| 场景 | 输入条件 | 预期结果 |
|------|---------|---------|
| IC 标准差为 0 | 所有 IC 值相同 | t_stat = 0，不显示显著性标识 |
| 样本数很少 | n_days < 10 | 正常计算，但 ICIR 和 t_stat 可能不稳定 |
| IC 均值为 0 | ic_mean ≈ 0 | t_stat ≈ 0，不显著 |

### 测试场景 4：API 返回值验证

| 步骤 | 操作 | 预期结果 |
|------|------|---------|
| 1 | GET `/api/rsi-ic` | 返回 JSON 包含 `t_stat` 字段 |
| 2 | 检查 t_stat 类型 | number 类型 |
| 3 | 检查 t_stat 精度 | 保留 4 位小数 |

### 测试场景 5：刷新数据后验证

| 步骤 | 操作 | 预期结果 |
|------|------|---------|
| 1 | 点击 "刷新数据" 按钮 | 显示进度条 |
| 2 | 等待数据刷新完成 | 显示完成统计 |
| 3 | 检查 t_stat 值 | 更新为新计算的值 |
| 4 | 检查显著性标识 | 与新值对应 |

---

## 验收标准

- [ ] `reverse_rank_ic.py` 正确计算并返回 `t_stat` 和 `n_days`
- [ ] `rsi_ic_generator.py` 正确传递 `t_stat` 到前端
- [ ] 前端页面显示 t_stat 卡片
- [ ] t_stat 值保留 4 位小数
- [ ] 显著性标识正确显示（`*` / `**` / `***`）
- [ ] API `/api/rsi-ic` 返回值包含 `t_stat` 字段
- [ ] 刷新数据后 t_stat 正确更新
- [ ] 边界值（ic_std=0）处理正确

---

## 文件修改清单

| 文件 | 修改内容 |
|------|---------|
| `~/.openclaw/workspace/yunzhou/reverse_rank_ic.py` | 添加 t_stat 计算，返回值增加 t_stat、n_days |
| `~/.openclaw/workspace/yunzhou/factor_ic_analyzer/rsi_ic_generator.py` | 传递 t_stat 到前端返回值 |
| `~/.openclaw/workspace/yunzhou/factor_ic_analyzer/templates/rsi_ic.html` | 添加 t_stat 卡片、更新 JS 逻辑、添加说明文案 |

---

## 附录：t_stat 计算示例

```python
import math

# 示例数据
ic_values = [0.05, 0.03, 0.08, -0.02, 0.06, 0.04, 0.07, 0.01, 0.09, 0.02]
n = len(ic_values)  # 10

ic_mean = sum(ic_values) / n  # 0.043
ic_std = math.sqrt(sum((x - ic_mean)**2 for x in ic_values) / (n - 1))  # ~0.033

# t_stat 计算
t_stat = ic_mean / (ic_std / math.sqrt(n))
# t_stat ≈ 4.12

# 显著性判断：|t_stat| > 3.29 → 99.9% 显著 → 显示 ***
```

---

**文档编写**: 云柏  
**日期**: 2026-04-02