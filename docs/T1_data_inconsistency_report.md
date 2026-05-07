# T1选股结果数据不一致问题排查报告

**排查时间**: 2026-05-02 22:30  
**排查人**: Hermes Agent  

---

## 问题概述

量化页面（累计净值页）显示的T1选股结果与v2优化文件`optimization_T_1.json`中的数据不一致。

---

## 数据对比

### 页面显示的T1选股结果
- **来源**: Web页面（http://localhost:8765 - 累计净值页 - 多周期策略对比）
- **股票列表**:
  1. 001207 联科科技 (10.8分)
  2. 000915 华特达因 (10.5分)
  3. 000930 中粮科技 (10.3分)
  4. 605577 龙版传媒 (10.2分)
  5. 600095 湘财股份 (10.1分)

### v2优化文件 (versions/v2/output/optimization_T_1.json)
- **股票列表**:
  1. 001207 联科科技 (43.65分)
  2. 002124 天邦食品 (43.56分)
  3. 000915 华特达因 (43.02分)
  4. 603568 伟明环保 (42.93分)
  5. 605086 龙高股份 (42.88分)

### v3优化文件 (versions/v3/output/optimization_T_1.json)
- **股票列表**:
  1. 001207 联科科技 (37.07分)
  2. 000915 华特达因 (36.48分)
  3. 000930 中粮科技 (36.02分)
  4. 002124 天邦食品 (35.71分)
  5. 600095 湘财股份 (35.67分)

**结论**: 页面显示的数据与v3版本一致，而非v2版本！

---

## 问题根源分析

### 数据流向追踪

1. **Web页面数据源**: 
   - 文件: `web_app.py` 第5395-5407行
   - 实际读取: `cache/v2/precompute/top_stocks_T1.json`

2. **cache/v2/precompute/top_stocks_T1.json数据**:
   - 内容与v3数据一致（包含000930中粮科技、605577龙版传媒等）
   - 权重与v2 T1优化文件一致：rsi=-0.05, kdj_j=-0.1

3. **generate_top_stocks.py脚本逻辑问题**:
   - 文件: `versions/v2/scripts/generate_top_stocks.py`
   - **关键问题**: 第79-87行优先读取`optimization_result_multi_period.json`的`top_stocks`字段
   - 该字段数据错误，使用了v3的选股结果
   - 虽然第93-125行会读取单周期文件，但由于已被跳过（第95行continue），v2的正确数据未被使用

4. **optimization_result_multi_period.json问题**:
   - 文件: `versions/v2/output/optimization_result_multi_period.json`
   - `top_stocks`字段（第9-43行）包含v3的数据
   - `all_periods.T+1`字段缺少`selections`，只有权重和指标数据

---

## 问题链路图

```
页面显示
  └── web_app.py读取 cache/v2/precompute/top_stocks_T1.json
       └── generate_top_stocks.py生成（错误数据）
            └── 优先读取 optimization_result_multi_period.json.top_stocks（v3数据）
                 └── 而非 optimization_T_1.json.selections（v2正确数据）
```

---

## 修复方案

### 方案1: 修复optimization_result_multi_period.json（推荐）

修改`optimization_result_multi_period.json`的`top_stocks`字段，使其从各周期的`optimization_T_X.json`文件中正确提取selections数据。

**步骤**:
1. 修改`all_periods`结构，为每个周期添加`selections`字段
2. 修改`top_stocks`字段，设置为从best_period的selections中获取
3. 重新运行generate_top_stocks.py脚本

### 方案2: 修改generate_top_stocks.py脚本优先级

调整读取顺序，优先从单周期文件读取selections，而非汇总文件的top_stocks。

**修改代码**（第79-87行）:
```python
# 当前逻辑：汇总文件top_stocks优先
# 改为：单周期文件优先

# 先尝试读取单周期文件
for period in ['T+1', 'T+3', 'T+5']:
    period_file = OUTPUT_DIR / f"optimization_{period.replace('+', '_')}.json"
    if period_file.exists():
        ...读取selections字段...

# 然后再检查汇总文件的top_stocks（作为fallback）
if 'top_stocks' in data and data['top_stocks'].get('stocks'):
    ...仅在单周期文件读取失败时使用...
```

### 方案3: 直接修改数据文件（快速修复）

直接更新`optimization_result_multi_period.json`的`top_stocks`字段，手动填充v2的selections数据。

---

## 建议采取的修复方案

**推荐方案2**: 修改generate_top_stocks.py脚本

原因：
- 解决根本问题，确保脚本逻辑正确
- 单周期优化文件（optimization_T_1.json）是权威数据源
- 汇总文件的top_stocks应该作为补充，而非主数据源

---

## 相关文件列表

| 文件路径 | 当前状态 | 问题 |
|---------|---------|------|
| `web_app.py` | 正常读取cache/v2目录 | 数据源配置正确 |
| `cache/v2/precompute/top_stocks_T1.json` | 数据错误 | 包含v3的选股结果 |
| `versions/v2/output/optimization_result_multi_period.json` | 数据错误 | top_stocks字段使用v3数据 |
| `versions/v2/output/optimization_T_1.json` | **数据正确** | v2的真实优化结果 |
| `versions/v2/scripts/generate_top_stocks.py` | **逻辑错误** | 读取优先级问题 |
| `versions/v3/output/optimization_T_1.json` | 数据正确 | v3的优化结果（不应出现在v2页面） |

---

## 附录：页面截图

页面路径: http://localhost:8765
登录凭证: admin/admin

![T1选股结果截图](/home/admin/.hermes/cache/screenshots/browser_screenshot_f616b8e7fb064d37929c24682474eecf.png)

---