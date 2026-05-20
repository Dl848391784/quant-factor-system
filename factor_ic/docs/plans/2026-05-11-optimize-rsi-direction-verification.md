# RSI IC 方向验证优化 实现计划

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** 实现因子方向验证流程，先用原始值计算正向 IC，再根据结果判断因子方向。

**Architecture:** 
- 创建通用 IC 计算函数 `calculate_ic_with_direction_verification`（支持方向验证）
- 修改 ic_rsi_1d.py 使用新函数，不再直接调用 reverse_rank_ic
- 输出结构增加 factor_direction 和 direction_confidence 字段

**Tech Stack:** Python 3.10+, pandas, numpy, scipy, pytest

**Constraints:**
- 数据中只有 rsi_6，暂无法实现参数稳健性验证（需 data_fetchers 先支持）
- 输出结构必须符合 PROJECT.md 规范
- 不能破坏现有测试用例

---

## Task 1: 创建通用 IC 计算函数

**Objective:** 创建 `calculate_ic_with_direction_verification` 函数，支持因子方向验证流程

**Files:**
- Create: `/home/admin/projects/factor_ic_analyzer/factor_ic/common/ic_calculator.py`

**Step 1: Write function with direction verification**

```python
"""
通用 IC 计算模块 - 支持因子方向验证

遵循 PROJECT.md 规范：
1. 先用原始值计算正向 IC
2. 根据 IC 均值和显著性判断因子方向
3. 输出 factor_direction 和 direction_confidence

作者: 云瑶
日期: 2026-05-11
"""

import pandas as pd
import numpy as np
from scipy import stats
from typing import Dict, Optional, Tuple
import math


def calculate_ic_with_direction_verification(
    factor_df: pd.DataFrame,
    return_df: pd.DataFrame,
    factor_col: str,
    return_col: str = 'forward_return',
    date_col: str = 'date',
    asset_col: str = 'asset',
    min_stocks: int = 10,
    ic_threshold: float = 0.02,
    p_threshold: float = 0.05
) -> Dict:
    """
    计算因子 IC，同时验证因子方向
    
    流程：
    1. 使用原始因子值计算正向 IC（Spearman 秩相关）
    2. 根据 ic_mean 和 p_value 判断因子方向
    3. 返回方向信息和 IC 结果
    
    参数:
    ---
    factor_df : DataFrame
        因子数据，包含 [date_col, asset_col, factor_col]
    return_df : DataFrame
        收益数据，包含 [date_col, asset_col, return_col]
    factor_col : str
        因子列名
    return_col : str
        收益列名，默认 'forward_return'
    date_col : str
        日期列名，默认 'date'
    asset_col : str
        资产列名，默认 'asset'
    min_stocks : int
        每日最少股票数，默认 10
    ic_threshold : float
        IC 显著性阈值，默认 0.02
    p_threshold : float
        p 值阈值，默认 0.05
        
    返回:
    ---
    dict: {
        'ic_series': pd.Series,
        'ic_mean': float,
        'ic_std': float,
        'icir': float,
        'p_value': float,
        't_stat': float,
        'factor_direction': 'negative' | 'positive' | 'invalid',
        'direction_confidence': {
            'ic_mean': float,
            'p_value': float,
            'conclusion': str
        },
        'positive_ratio': float,
        'n_days': int,
        'summary': str
    }
    """
    # ========== 输入验证 ==========
    if factor_df.empty:
        raise ValueError("factor_df 不能为空")
    
    if return_df.empty:
        raise ValueError("return_df 不能为空")
    
    required_factor_cols = [date_col, asset_col, factor_col]
    required_return_cols = [date_col, asset_col, return_col]
    
    for col in required_factor_cols:
        if col not in factor_df.columns:
            raise KeyError(f"factor_df 缺少列: '{col}'")
    
    for col in required_return_cols:
        if col not in return_df.columns:
            raise KeyError(f"return_df 缺少列: '{col}'")
    
    # ========== 数据合并 ==========
    merged = pd.merge(
        factor_df[[date_col, asset_col, factor_col]],
        return_df[[date_col, asset_col, return_col]],
        on=[date_col, asset_col],
        how='inner'
    )
    
    if merged.empty:
        raise ValueError("factor_df 和 return_df 无法匹配")
    
    merged = merged.dropna(subset=[factor_col, return_col])
    
    if merged.empty:
        raise ValueError("合并后数据全部为缺失值")
    
    # ========== 按日期计算正向 IC ==========
    ic_list = []
    
    for date, daily_data in merged.groupby(date_col):
        if len(daily_data) < min_stocks:
            continue
        
        if daily_data[factor_col].nunique() == 1:
            ic_list.append({'date': date, 'ic': 0.0})
            continue
        
        if daily_data[return_col].nunique() == 1:
            ic_list.append({'date': date, 'ic': 0.0})
            continue
        
        # 使用 Spearman 秩相关计算正向 IC（不反转）
        ic_value = daily_data[factor_col].corr(
            daily_data[return_col], 
            method='spearman'
        )
        
        if pd.isna(ic_value):
            ic_value = 0.0
        
        ic_list.append({'date': date, 'ic': ic_value})
    
    if not ic_list:
        raise ValueError(f"没有有效的交易日（每交易日股票数 < {min_stocks}）")
    
    ic_df = pd.DataFrame(ic_list)
    ic_series = ic_df.set_index('date')['ic']
    
    # ========== 计算统计量 ==========
    ic_mean = ic_series.mean()
    ic_std = ic_series.std()
    
    if ic_std == 0:
        icir = 0.0
    else:
        icir = abs(ic_mean) / ic_std  # 使用绝对值（PROJECT.md 规范）
    
    n = len(ic_series)
    
    # Newey-West 调整的 t 统计量和 p 值
    t_stat, p_value = _newey_west_t_stat(ic_series, lag=5)
    
    # IC > 0 的比例
    positive_count = (ic_series > 0).sum()
    positive_ratio = positive_count / n
    
    # ========== 判断因子方向 ==========
    factor_direction, conclusion = _determine_factor_direction(
        ic_mean, p_value, ic_threshold, p_threshold
    )
    
    direction_confidence = {
        'ic_mean': round(ic_mean, 6),
        'p_value': round(p_value, 6),
        'conclusion': conclusion
    }
    
    # ========== 生成摘要 ==========
    significance = _get_significance_marker(abs(t_stat))
    
    summary = (
        f"IC均值={ic_mean:.4f}, "
        f"ICIR={icir:.2f}, "
        f"p值={p_value:.4f}, "
        f"方向={factor_direction}, "
        f"正比例={positive_ratio:.1%}"
    )
    
    return {
        'ic_series': ic_series,
        'ic_mean': ic_mean,
        'ic_std': ic_std,
        'icir': icir,
        'p_value': p_value,
        't_stat': round(t_stat, 4),
        'factor_direction': factor_direction,
        'direction_confidence': direction_confidence,
        'positive_ratio': positive_ratio,
        'n_days': n,
        'significance': significance,
        'summary': summary
    }


def _newey_west_t_stat(ic_series: pd.Series, lag: int = 5) -> Tuple[float, float]:
    """
    Newey-West 调整的 t 统计量
    
    参数:
        ic_series: 日 IC 序列
        lag: 滞后阶数
        
    返回:
        (t_stat, p_value)
    """
    n = len(ic_series)
    ic_mean = ic_series.mean()
    
    # 计算自协方差
    autocov = []
    for k in range(lag + 1):
        if k == 0:
            cov = np.var(ic_series, ddof=1)
        else:
            cov = np.cov(ic_series[:-k], ic_series[k:])[0, 1]
        weight = 1 - k / (lag + 1)
        autocov.append(weight * cov)
    
    # 调整后的方差
    nw_var = sum(autocov)
    
    if nw_var <= 0:
        nw_var = np.var(ic_series, ddof=1)
    
    # 调整后的标准误
    nw_se = np.sqrt(nw_var / n)
    
    # t 统计量
    if nw_se == 0:
        t_stat = 0.0
    else:
        t_stat = ic_mean / nw_se
    
    # p 值 (双尾)
    p_value = 2 * (1 - stats.norm.cdf(abs(t_stat)))
    
    return t_stat, p_value


def _determine_factor_direction(
    ic_mean: float,
    p_value: float,
    ic_threshold: float,
    p_threshold: float
) -> Tuple[str, str]:
    """
    判断因子方向
    
    参数:
        ic_mean: IC 均值
        p_value: p 值
        ic_threshold: IC 显著性阈值
        p_threshold: p 值阈值
        
    返回:
        (factor_direction, conclusion)
    """
    abs_ic = abs(ic_mean)
    
    if p_value >= p_threshold:
        # IC 不显著
        factor_direction = 'invalid'
        conclusion = f"IC不显著(p={p_value:.4f}>={p_threshold})，因子无预测能力"
    elif ic_mean < -ic_threshold:
        # IC 显著为负 → 反向因子
        factor_direction = 'negative'
        conclusion = f"反向因子(IC={ic_mean:.4f}<{-(ic_threshold)})，应使用 reverse_rank_ic"
    elif ic_mean > ic_threshold:
        # IC 显著为正 → 正向因子
        factor_direction = 'positive'
        conclusion = f"正向因子(IC={ic_mean:.4f}>{ic_threshold})，应使用原始 IC"
    else:
        # IC 绝对值较小，虽显著但预测力弱
        factor_direction = 'invalid'
        conclusion = f"IC绝对值较小({abs_ic:.4f}<={ic_threshold})，预测能力较弱"
    
    return factor_direction, conclusion


def _get_significance_marker(abs_t_stat: float) -> str:
    """
    获取 t 统计量显著性标识
    
    参数:
        abs_t_stat: t 统计量绝对值
        
    返回:
        显著性标识 ('***', '**', '*', '')
    """
    if abs_t_stat > 3.29:
        return '***'
    elif abs_t_stat > 2.58:
        return '**'
    elif abs_t_stat > 1.96:
        return '*'
    else:
        return ''
```

**Step 2: Verify function can be imported**

Run: `python3 -c "from factor_ic.common.ic_calculator import calculate_ic_with_direction_verification; print('OK')"`

Expected: OK

**Step 3: Commit**

```bash
git add factor_ic/common/ic_calculator.py
git commit -m "feat: add ic_calculator with direction verification"
```

---

## Task 2: 修改 ic_rsi_1d.py 使用新函数

**Objective:** 修改 RSI IC 计算脚本，使用方向验证流程

**Files:**
- Modify: `/home/admin/projects/factor_ic_analyzer/factor_ic/ic_rsi_1d.py`

**Step 1: Replace import and call**

修改第 26 行导入：
```python
# 原代码
from factor_ic.common.reverse_rank_ic import reverse_rank_ic

# 新代码
from factor_ic.common.ic_calculator import calculate_ic_with_direction_verification
```

修改第 92-174 行的 calculate_daily_ic_series 函数，使用新函数：

```python
def calculate_daily_ic_series(
    factor_df: pd.DataFrame,
    return_df: pd.DataFrame,
    period_start: str = None,
    period_end: str = None
) -> dict:
    """
    计算每日的 IC 时间序列（带方向验证）
    
    参数:
        factor_df: 因子数据
        return_df: 收益数据
        period_start: 数据起始日期
        period_end: 数据结束日期
    
    返回:
        dict: IC 计算结果（符合 PROJECT.md 规范）
    """
    # 使用方向验证 IC 计算
    result = calculate_ic_with_direction_verification(
        factor_df=factor_df,
        return_df=return_df,
        factor_col='rsi_6',
        return_col='forward_return',
        date_col='date',
        asset_col='asset',
        min_stocks=10
    )
    
    ic_series = result['ic_series']
    
    # 获取日期范围
    if period_start is None:
        period_start = str(factor_df['date'].min())
    if period_end is None:
        period_end = str(factor_df['date'].max())
    
    # 转换为 JSON 友好格式
    dates = [str(d) for d in ic_series.index]
    ic_values = [round(v, 6) for v in ic_series.values]
    
    # 计算 20 日滚动均值
    rolling_mean = ic_series.rolling(window=20, min_periods=1).mean()
    rolling_ic_mean = [round(v, 6) for v in rolling_mean.values]
    
    # 符合 PROJECT.md 规范的数据结构（增加 factor_direction）
    return {
        # 规范必需字段
        'factor_name': 'rsi_1d',
        'calculation_date': datetime.now().strftime('%Y-%m-%d'),
        'period': {
            'start': period_start,
            'end': period_end
        },
        'ic_metrics': {
            'ic_mean': round(result['ic_mean'], 6),
            'ic_std': round(result['ic_std'], 6),
            'icir': round(result['icir'], 4),
            'p_value': round(result['p_value'], 6)
        },
        'sample_stats': {
            'total_days': len(dates),
            'valid_days': len(dates),
            'avg_stocks_per_day': int(factor_df.groupby('date').size().mean())
        },
        
        # 新增：因子方向信息
        'factor_direction': result['factor_direction'],
        'direction_confidence': result['direction_confidence'],
        
        # 额外字段（保留原有功能）
        'dates': dates,
        'ic_values': ic_values,
        'rolling_ic_mean': rolling_ic_mean,
        'positive_ratio': round(result['positive_ratio'], 4),
        't_stat': result['t_stat'],
        'significance': result['significance'],
        'n_assets': factor_df['asset'].nunique(),
        'summary': result['summary']
    }
```

**Step 2: Run script to verify**

Run: `cd /home/admin/projects/factor_ic_analyzer && python3 factor_ic/ic_rsi_1d.py`

Expected: 脚本正常执行，输出包含 factor_direction 字段

**Step 3: Commit**

```bash
git add factor_ic/ic_rsi_1d.py
git commit -m "feat: ic_rsi_1d uses direction verification flow"
```

---

## Task 3: 更新测试用例

**Objective:** 更新测试用例，验证新的输出结构

**Files:**
- Modify: `/home/admin/projects/factor_ic_analyzer/factor_ic/test_cases/ic_rsi_1d_test_cases.py`

**Step 1: Add test for factor_direction field**

在 TestOutputStructure 类中添加：

```python
class TestOutputStructure:
    """测试输出数据结构规范"""
    
    REQUIRED_FIELDS = [
        'factor_name',
        'calculation_date',
        'period',
        'ic_metrics',
        'sample_stats',
        'factor_direction',  # 新增
        'direction_confidence'  # 新增
    ]
    
    IC_METRICS_FIELDS = ['ic_mean', 'ic_std', 'icir', 'p_value']
    SAMPLE_STATS_FIELDS = ['total_days', 'valid_days', 'avg_stocks_per_day']
    
    DIRECTION_CONFIDENCE_FIELDS = ['ic_mean', 'p_value', 'conclusion']
    
    def test_output_has_factor_direction(self, tmp_path):
        """输出应包含 factor_direction 字段"""
        output_file = tmp_path / 'ic_rsi_1d_analysis_result.json'
        
        expected_structure = {
            'factor_name': 'rsi_1d',
            'calculation_date': '2026-05-11',
            'period': {'start': '2024-01-01', 'end': '2026-05-11'},
            'ic_metrics': {'ic_mean': -0.05, 'ic_std': 0.18, 'icir': 0.28, 'p_value': 0.001},
            'sample_stats': {'total_days': 500, 'valid_days': 500, 'avg_stocks_per_day': 4500},
            'factor_direction': 'negative',
            'direction_confidence': {
                'ic_mean': -0.05,
                'p_value': 0.001,
                'conclusion': '反向因子'
            }
        }
        
        output_file.write_text(json.dumps(expected_structure, ensure_ascii=False))
        data = json.loads(output_file.read_text())
        
        assert 'factor_direction' in data
        assert data['factor_direction'] in ['negative', 'positive', 'invalid']
        
        assert 'direction_confidence' in data
        for field in self.DIRECTION_CONFIDENCE_FIELDS:
            assert field in data['direction_confidence']
    
    def test_factor_direction_values(self):
        """factor_direction 应为合法值"""
        valid_directions = ['negative', 'positive', 'invalid']
        
        # 测试各方向判断逻辑
        # IC < -0.02 且 p < 0.05 → negative
        # IC > 0.02 且 p < 0.05 → positive
        # 其他 → invalid
        assert 'negative' in valid_directions
        assert 'positive' in valid_directions
        assert 'invalid' in valid_directions
```

**Step 2: Run tests**

Run: `pytest factor_ic/test_cases/ic_rsi_1d_test_cases.py -v`

Expected: 所有测试通过

**Step 3: Commit**

```bash
git add factor_ic/test_cases/ic_rsi_1d_test_cases.py
git commit -m "test: add factor_direction field tests"
```

---

## Task 4: 更新流程文档

**Objective:** 更新 ic_rsi_1d_flow.md 流程文档，反映新的方向验证流程

**Files:**
- Modify: `/home/admin/projects/factor_ic_analyzer/factor_ic/docs/ic_rsi_1d_flow.md`

**Step 1: Read current flow doc**

Run: `read_file factor_ic/docs/ic_rsi_1d_flow.md`

**Step 2: Update flow diagram and steps**

更新流程图，增加方向验证步骤：

```
┌─────────────────────────────────────────────────────────────────┐
│                    RSI_1D IC 计算流程（带方向验证）                  │
└─────────────────────────────────────────────────────────────────┘

   ┌──────────────┐     ┌──────────────┐     ┌──────────────┐
   │  加载缓存数据  │────▶│  合并因子收益  │────▶│  计算正向IC  │
   │ factor_data  │     │   按日期+资产  │     │ Spearman法   │
   │ return_data  │     │              │     │              │
   └──────────────┘     └──────────────┘     └──────────────┘
                                                     │
                                                     ▼
   ┌──────────────┐     ┌──────────────┐     ┌──────────────┐
   │  输出结果JSON │◀────│  判断因子方向 │◀────│  计算统计量  │
   │ ic_metrics   │     │ ic_mean/p值  │     │ Newey-West   │
   │ factor_      │     │              │     │ t_stat/p值   │
   │ direction    │     │              │     │              │
   └──────────────┘     └──────────────┘     └──────────────┘

```

**Step 3: Commit**

```bash
git add factor_ic/docs/ic_rsi_1d_flow.md
git commit -m "docs: update rsi flow with direction verification"
```

---

## Task 5: 运行完整测试验证

**Objective:** 运行完整测试套件，验证无回归

**Files:**
- No new files

**Step 1: Run all factor_ic tests**

Run: `pytest factor_ic/test_cases/ -v`

Expected: 所有测试通过

**Step 2: Run ic_rsi_1d.py end-to-end**

Run: `cd /home/admin/projects/factor_ic_analyzer && python3 factor_ic/ic_rsi_1d.py`

Expected: 正常执行，输出文件包含 factor_direction 字段

**Step 3: Verify output file structure**

Run: `python3 -c "
import json
from pathlib import Path
result_file = Path('factor_ic/result/ic_rsi_1d_analysis_result.json')
if result_file.exists():
    data = json.loads(result_file.read_text())
    print('factor_direction:', data.get('factor_direction'))
    print('direction_confidence:', data.get('direction_confidence'))
else:
    print('result file not found')
"`

Expected: 显示 factor_direction 和 direction_confidence 字段

---

## Dependencies

**参数稳健性验证依赖项：**
- data_fetchers 需先支持生成 rsi_5、rsi_9 数据
- 当前 factor_data.json.gz 只有 rsi_6
- 该功能标记为后续优化

---

## Summary

| 任务 | 文件 | 状态 |
|-----|------|------|
| Task 1 | factor_ic/common/ic_calculator.py | 新建 |
| Task 2 | factor_ic/ic_rsi_1d.py | 修改 |
| Task 3 | factor_ic/test_cases/ic_rsi_1d_test_cases.py | 修改 |
| Task 4 | factor_ic/docs/ic_rsi_1d_flow.md | 修改 |
| Task 5 | 测试验证 | 执行 |

---

*计划创建时间: 2026-05-11 13:10:00 (北京时间)*