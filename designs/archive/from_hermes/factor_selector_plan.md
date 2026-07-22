# 因子筛选模块实现计划

> 创建时间: 2026-05-24
> 任务: 补充 Step 2 因子筛选自动化逻辑

---

## 背景

comprehensive_factor 模块已完成 Step 1, 3, 4, 5，但 Step 2 因子筛选缺失自动逻辑：
- 目前只有高相关警告，无自动筛选
- 无效因子判断需手动配置

---

## 需求

1. 自动加载所有因子 IC 结果 + 回测结果
2. 自动判断无效因子（阈值标准）
3. 自动识别高相关组并筛选（保留最强）
4. 输出筛选结果供 Step 3-5 使用

---

## 阈值标准（基于业界惯例）

### 无效因子判定

| 指标 | 阈值 | 理由 |
|-----|------|-----|
| |ic_mean| | < 0.03 | IC 太低无预测能力 |
| p_value | > 0.05 | 统计不显著 |
| |icir| | < 0.2 | 稳定性差（波动大） |
| |monotonicity_corr| | < 0.5 | 分层收益不单调 |
| long_short_return_annual | < 5% | 经济意义弱 |

**判定规则：任一指标不满足即无效**

### 高相关组筛选

| 指标 | 阈值 | 理由 |
|-----|------|-----|
| |corr| | > 0.7 | 高相关因子冗余 |

**保留规则：组内保留 |ICIR| 最高的因子**

---

## 实现计划

### Task 1: 创建 factor_selector.py（约5分钟）

**文件路径:** `comprehensive_factor/common/factor_selector.py`

**核心函数:**

```python
def load_all_factor_results(
    ic_result_dir: Path,
    backtest_result_dir: Path,
    return_period: str = '1d',
    logger: Logger = None
) -> Dict[str, Dict]:
    """加载所有因子的 IC 结果 + 回测结果
    
    返回结构:
    {
        'rsi': {
            'ic_metrics': {'ic_mean': -0.037, 'icir': 0.25, ...},
            'backtest': {'monotonicity': {'correlation': -0.46}, 'long_short': {...}}
        },
        'volume_ratio': {...}
    }
    """
```

```python
def validate_factor(
    factor_name: str,
    factor_data: Dict,
    thresholds: Dict = None
) -> Tuple[bool, List[str]]:
    """判断因子是否有效
    
    返回: (is_valid, reasons)
    - is_valid: True/False
    - reasons: 无效原因列表（如 ['|ic_mean|=0.02<0.03', 'p_value=0.08>0.05']）
    """
```

```python
def filter_invalid_factors(
    all_factors: Dict[str, Dict],
    thresholds: Dict = None,
    logger: Logger = None
) -> Dict[str, Dict]:
    """筛选无效因子
    
    返回: {'valid': {...}, 'invalid': {factor_name: reasons}}
    """
```

```python
def identify_high_corr_groups(
    valid_factors: Dict[str, Dict],
    corr_matrix: pd.DataFrame,
    threshold: float = 0.7,
    logger: Logger = None
) -> List[List[str]]:
    """识别高相关因子组
    
    返回: [['rsi', 'bollinger_pb'], ['volume_ratio', 'turnover_surge']]
    """
```

```python
def select_best_from_groups(
    high_corr_groups: List[List[str]],
    valid_factors: Dict[str, Dict],
    logger: Logger = None
) -> Tuple[List[str], Dict[str, str]]:
    """从高相关组中选择最优因子（ICIR最高）
    
    返回: (selected_factors, dropped_factors_with_reason)
    - selected_factors: ['volume_ratio', 'rsi']
    - dropped_factors_with_reason: {'turnover_surge': '与volume_ratio高相关(0.99)，ICIR较低'}
    """
```

```python
def select_factors(
    ic_result_dir: Path = None,
    backtest_result_dir: Path = None,
    corr_matrix: pd.DataFrame = None,
    thresholds: Dict = None,
    logger: Logger = None
) -> Dict:
    """完整筛选流程入口
    
    返回:
    {
        'selected': ['volume_ratio', 'rsi'],
        'valid_count': 5,
        'invalid': {'kdj_j': ['|ic_mean|=0.01<0.03']},
        'high_corr_dropped': {'turnover_surge': '...'},
        'selection_reason': '低相关性组合，ICIR加权最优'
    }
    """
```

---

### Task 2: 集成到 composite_runner.py（约3分钟）

**修改文件:** `comprehensive_factor/common/composite_runner.py`

**修改位置:** 第131-189行（现有逻辑）

**修改内容:**

```python
# 原逻辑：手动配置 factor_list
factor_list = ['rsi', 'volume_ratio']  # 手动

# 新逻辑：自动筛选
from comprehensive_factor.common.factor_selector import select_factors

selection_result = select_factors(
    ic_result_dir=ic_result_dir,
    backtest_result_dir=backtest_result_dir,
    corr_matrix=corr_matrix,  # 已计算
    logger=logger
)

factor_list = selection_result['selected']
```

---

### Task 3: 更新 MODULE.md（约2分钟）

**修改文件:** `comprehensive_factor/MODULE.md`

**修改位置:** Step 2 章节

**修改内容:**

```markdown
## Step 2: 因子筛选（自动化）

### 无效因子判定标准

| 指标 | 阈值 | 判断逻辑 |
|-----|------|---------|
| |ic_mean| | < 0.03 | 无效 |
| p_value | > 0.05 | 无效 |
| |icir| | < 0.2 | 无效 |
| |monotonicity_corr| | < 0.5 | 无效 |
| long_short_return_annual | < 5% | 无效 |

### 高相关组筛选标准

| 指标 | 阈值 | 处理方式 |
|-----|------|---------|
| |corr| | > 0.7 | 组内保留 ICIR 最高 |

### 公共模块

- `factor_selector.py` — 因子筛选逻辑
```

---

## 验证步骤

1. 运行 `select_factors()` 验证筛选结果
2. 对比手动配置结果（应一致）
3. 运行综合因子回测验证输出不变

---

## Git 提交计划

```
Task 1 → commit "feat: 新增 factor_selector.py 因子筛选模块"
Task 2 → commit "refactor: composite_runner.py 集成自动筛选"
Task 3 → commit "docs: MODULE.md 补充 Step 2 自动化规范"
```

---

## 检查清单

```
□ factor_selector.py 符合 PROJECT.md 模块边界规范
□ 函数参数类型注解正确（Path | str | None）
□ 阈值标准有业界依据（写在注释）
□ 集成后运行验证输出不变
□ MODULE.md 同步更新
□ Git 分步提交（3个commit）
```