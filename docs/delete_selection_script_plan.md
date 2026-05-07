# 删除选股脚本技术方案

## 一、背景与目标

### 现状问题
- `v2/scripts/generate_top_stocks.py` 选股脚本功能已冗余
- 多周期优化脚本 `multi_period_optimizer.py` 已在 `optimization_T_*.json` 中生成 `selections` 字段
- 存在两份重复数据：
  - **权威数据源**: `versions/v2/output/optimization_T_*.json` (selections 字段)
  - **冗余数据**: `cache/v2/precompute/top_stocks_T*.json` (stocks 字段)

### 目标
删除选股脚本，修改依赖模块直接读取 `optimization_T_*.json` 的 `selections` 字段。

---

## 二、依赖模块分析

### 2.1 数据结构对比

| 文件 | 路径 | 字段名 | 结构示例 |
|------|------|--------|----------|
| optimization_T_1.json | versions/v2/output/ | `selections` | `{ "selections": [{"code": "001207", "name": "联科科技", ...}] }` |
| top_stocks_T1.json | cache/v2/precompute/ | `stocks` | `{ "stocks": [{"code": "001207", "name": "联科科技", ...}] }` |

**字段映射关系**:
- `optimization.selections` → `top_stocks.stocks` (完全相同的数据)
- `optimization.weights` → `top_stocks.weights_used`
- `optimization.metrics` → `top_stocks.summary`

### 2.2 依赖模块定位

| 模块 | 文件 | 行号 | 当前读取路径 | 当前读取字段 |
|------|------|------|-------------|-------------|
| web_app.py | web_app.py | 5398 | `cache/v2/precompute/top_stocks_T*.json` | `stocks` |
| portfolio_tracker.py | portfolio_tracker.py | 1005 | `cache/v2/precompute/top_stocks_*.json` | `stocks` |
| precompute_optimizer.py | precompute_optimizer.py | 1236 | `cache/v2/precompute/top_stocks_*.json` | `stocks` |

---

## 三、修改方案详解

### 3.1 修改 web_app.py

**位置**: 第 5394-5408 行

**修改前代码**:
```python
# 读取各周期的股票数据（v3.15 新增）
precompute_dir = BASE_DIR / 'cache' / 'v2' / 'precompute'
stocks_data = {}
for period_key in ['T1', 'T3', 'T5']:
    stocks_file = precompute_dir / f'top_stocks_{period_key}.json'
    if stocks_file.exists():
        try:
            with open(stocks_file, 'r', encoding='utf-8') as f:
                stocks_data[period_key] = json.load(f)
        except Exception as e:
            print(f"Warning: Failed to load {stocks_file}: {e}")
            stocks_data[period_key] = None
    else:
        stocks_data[period_key] = None
```

**修改后代码**:
```python
# 读取各周期的股票数据（v3.16 优化：直接读取 optimization_T_*.json）
v2_output_dir = BASE_DIR / 'versions' / 'v2' / 'output'
stocks_data = {}
for period_key in ['T1', 'T3', 'T5']:
    # T1 -> T_1, T3 -> T_3, T5 -> T_5
    file_period = f"T_{period_key[1]}"  # T1 -> T_1
    stocks_file = v2_output_dir / f'optimization_{file_period}.json'
    if stocks_file.exists():
        try:
            with open(stocks_file, 'r', encoding='utf-8') as f:
                raw_data = json.load(f)
                # 转换格式：selections -> stocks
                stocks_data[period_key] = {
                    'success': raw_data.get('success', True),
                    'stocks': raw_data.get('selections', []),
                    'computed_at': raw_data.get('computed_at', ''),
                    'period': raw_data.get('period', f'T+{period_key[1]}'),
                    'weights_used': raw_data.get('weights', {}),
                    'summary': raw_data.get('metrics', {})
                }
        except Exception as e:
            print(f"Warning: Failed to load {stocks_file}: {e}")
            stocks_data[period_key] = None
    else:
        stocks_data[period_key] = None
```

**改动说明**:
1. 路径从 `cache/v2/precompute/` 改为 `versions/v2/output/`
2. 文件名从 `top_stocks_T*.json` 改为 `optimization_T_*.json`
3. 字段从 `stocks` 改为读取 `selections` 并转换为 `stocks`
4. 新增格式转换逻辑，保持下游兼容

---

### 3.2 修改 portfolio_tracker.py

**位置**: 第 1001-1031 行的 `load_precompute_result()` 函数

**修改前代码**:
```python
def load_precompute_result(period: str = 'T1') -> tuple:
    """
    加载v2预计算结果
    
    Args:
        period: 周期类型 T1/T3/T5，默认 T1
        
    Returns:
        (optimization_result, top_stocks)
    """
    # 验证period参数
    if period not in ['T1', 'T3', 'T5']:
        logger.warning(f"不支持的周期类型: {period}，使用默认值 T1")
        period = 'T1'
    
    # v2预计算数据路径
    precompute_dir = Path('/home/admin/.openclaw/workspace/yunzhou/factor_ic_analyzer/cache/v2/precompute')
    
    # 读取top_stocks文件（包含权重信息）
    top_stocks_file = precompute_dir / f'top_stocks_{period}.json'
    top_stocks_data = load_json_file(top_stocks_file)
    
    if not top_stocks_data:
        logger.warning(f"预计算结果不存在: {top_stocks_file}")
        return None, None
    
    # 构造optimization_result（从top_stocks中提取权重信息）
    optimization_result = {
        'computed_at': top_stocks_data.get('computed_at'),
        'period': top_stocks_data.get('period'),
        'date': top_stocks_data.get('date'),
        'weights_used': top_stocks_data.get('weights_used', {}),
        'summary': top_stocks_data.get('summary', {}),
        'best_combination': {
            'weights': top_stocks_data.get('weights_used', {}),
            'weights_display': top_stocks_data.get('weights_used', {}),
            'metrics': top_stocks_data.get('summary', {})
        }
    }
    
    # 提取股票列表
    top_stocks = top_stocks_data.get('stocks', [])
    
    logger.info(f"加载预计算结果: {period}, {len(top_stocks)}只股票, computed_at={top_stocks_data.get('computed_at')}")
    
    return optimization_result, top_stocks
```

**修改后代码**:
```python
def load_precompute_result(period: str = 'T1') -> tuple:
    """
    加载v2预计算结果（v3.16 优化：直接读取 optimization_T_*.json）
    
    Args:
        period: 周期类型 T1/T3/T5，默认 T1
        
    Returns:
        (optimization_result, top_stocks)
    """
    # 验证period参数
    if period not in ['T1', 'T3', 'T5']:
        logger.warning(f"不支持的周期类型: {period}，使用默认值 T1")
        period = 'T1'
    
    # v2优化结果路径（直接读取 optimization_T_*.json）
    v2_output_dir = Path('/home/admin/.openclaw/workspace/yunzhou/factor_ic_analyzer/versions/v2/output')
    
    # 转换周期格式：T1 -> T_1, T3 -> T_3, T5 -> T_5
    file_period = f"T_{period[1]}"  # T1 -> T_1
    optimization_file = v2_output_dir / f'optimization_{file_period}.json'
    
    if not optimization_file.exists():
        logger.warning(f"优化结果不存在: {optimization_file}")
        return None, None
    
    try:
        with open(optimization_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception as e:
        logger.error(f"读取优化结果失败: {e}")
        return None, None
    
    # 构造optimization_result（从optimization文件提取信息）
    optimization_result = {
        'computed_at': data.get('computed_at', ''),
        'period': data.get('period', f'T+{period[1]}'),
        'date': data.get('date', ''),
        'weights_used': data.get('weights', {}),
        'summary': data.get('metrics', {}),
        'best_combination': {
            'weights': data.get('weights', {}),
            'weights_display': data.get('weights', {}),
            'metrics': data.get('metrics', {})
        }
    }
    
    # 提取股票列表：从 selections 字段读取
    top_stocks = data.get('selections', [])
    
    logger.info(f"加载优化结果: {period}, {len(top_stocks)}只股票, computed_at={data.get('computed_at')}")
    
    return optimization_result, top_stocks
```

**改动说明**:
1. 路径从 `cache/v2/precompute/` 改为 `versions/v2/output/`
2. 文件名从 `top_stocks_T*.json` 改为 `optimization_T_*.json`
3. 字段从 `stocks` 改为 `selections`
4. 权重字段从 `weights_used` 改为 `weights`
5. 指标字段从 `summary` 改为 `metrics`

---

### 3.3 修改 precompute_optimizer.py

**位置**: 第 1220-1270 行的 `load_v2_precompute_result()` 函数

**修改前代码**:
```python
def load_v2_precompute_result(period: str = 'T1') -> Optional[Dict]:
    """
    加载v2预计算结果
    
    Args:
        period: 周期类型 T1/T3/T5，默认 T1
        
    Returns:
        Dict: 预计算结果，如果不存在返回 None
    """
    # 验证period参数
    if period not in ['T1', 'T3', 'T5']:
        logger.warning(f"不支持的周期类型: {period}，使用默认值 T1")
        period = 'T1'
    
    # v2预计算数据路径
    v2_precompute_dir = BASE_DIR / 'cache' / 'v2' / 'precompute'
    top_stocks_file = v2_precompute_dir / f'top_stocks_{period}.json'
    
    if not top_stocks_file.exists():
        logger.error(f"v2预计算结果不存在: {top_stocks_file}")
        return None
    
    try:
        with open(top_stocks_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        # 转换为兼容格式
        result = {
            'computed_at': data.get('computed_at', ''),
            'computed_at_iso': data.get('computed_at_iso', ''),
            'period': data.get('period', period),
            'date': data.get('date', ''),
            'best_combination': {
                'weights': data.get('weights_used', {}),
                'weights_display': {},
                'metrics': data.get('summary', {}),
                'score': data.get('summary', {}).get('avg_score', 0)
            },
            'top_stocks': data.get('stocks', []),
            'compute_summary': {
                'total_stocks': len(data.get('stocks', [])),
                'period': data.get('period', period)
            }
        }
        
        return result
        
    except Exception as e:
        logger.error(f"读取v2预计算结果失败: {e}")
        return None
```

**修改后代码**:
```python
def load_v2_precompute_result(period: str = 'T1') -> Optional[Dict]:
    """
    加载v2优化结果（v3.16 优化：直接读取 optimization_T_*.json）
    
    Args:
        period: 周期类型 T1/T3/T5，默认 T1
        
    Returns:
        Dict: 优化结果，如果不存在返回 None
    """
    # 验证period参数
    if period not in ['T1', 'T3', 'T5']:
        logger.warning(f"不支持的周期类型: {period}，使用默认值 T1")
        period = 'T1'
    
    # v2优化结果路径（直接读取 optimization_T_*.json）
    v2_output_dir = BASE_DIR / 'versions' / 'v2' / 'output'
    
    # 转换周期格式：T1 -> T_1, T3 -> T_3, T5 -> T_5
    file_period = f"T_{period[1]}"  # T1 -> T_1
    optimization_file = v2_output_dir / f'optimization_{file_period}.json'
    
    if not optimization_file.exists():
        logger.error(f"v2优化结果不存在: {optimization_file}")
        return None
    
    try:
        with open(optimization_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        # 转换为兼容格式（从 selections 字段读取股票列表）
        result = {
            'computed_at': data.get('computed_at', ''),
            'computed_at_iso': data.get('computed_at', ''),  # 使用同一字段
            'period': data.get('period', f'T+{period[1]}'),
            'date': data.get('date', ''),
            'best_combination': {
                'weights': data.get('weights', {}),
                'weights_display': data.get('weights', {}),
                'metrics': data.get('metrics', {}),
                'score': data.get('metrics', {}).get('sharpe_ratio', 0)
            },
            'top_stocks': data.get('selections', []),  # 关键修改：selections -> top_stocks
            'compute_summary': {
                'total_stocks': len(data.get('selections', [])),
                'period': data.get('period', f'T+{period[1]}')
            }
        }
        
        return result
        
    except Exception as e:
        logger.error(f"读取v2优化结果失败: {e}")
        return None
```

**改动说明**:
1. 路径从 `cache/v2/precompute/` 改为 `versions/v2/output/`
2. 文件名从 `top_stocks_T*.json` 改为 `optimization_T_*.json`
3. 字段从 `stocks` 改为 `selections`
4. 权重字段从 `weights_used` 改为 `weights`
5. 指标字段从 `summary` 改为 `metrics`

---

## 四、历史归档功能处理

### 4.1 现有归档功能分析

`generate_top_stocks.py` 的 `save_historical_results()` 函数：
- 归档位置: `cache/v2/precompute/history/YYYY-MM-DD/`
- 归档内容:
  - `optimization_summary.json`: 优化汇总
  - `top_stocks_T1.json`, `top_stocks_T3.json`, `top_stocks_T5.json`: 选股结果

### 4.2 推荐方案：迁移到多周期优化脚本

**原因**:
1. 数据源头在优化脚本，归档应由数据生产者负责
2. 减少脚本间依赖
3. 保证数据一致性

**迁移方案**:

在 `multi_period_optimizer.py` 末尾添加归档函数：

```python
def archive_optimization_results():
    """
    归档优化结果（替代原 generate_top_stocks.py 的归档功能）
    
    将当天的优化结果保存到历史目录，便于回溯和分析
    """
    from datetime import datetime
    import shutil
    
    # 历史归档目录
    history_dir = OUTPUT_DIR / 'history'
    today = datetime.now().strftime('%Y-%m-%d')
    today_dir = history_dir / today
    
    # 创建历史目录
    today_dir.mkdir(parents=True, exist_ok=True)
    logger.info(f"历史归档目录: {today_dir}")
    
    # 复制 optimization_result_multi_period.json
    multi_period_file = OUTPUT_DIR / 'optimization_result_multi_period.json'
    if multi_period_file.exists():
        dst = today_dir / 'optimization_result_multi_period.json'
        shutil.copy(multi_period_file, dst)
        logger.info(f"✓ 已归档: {dst.name}")
    
    # 复制各周期 optimization_T_*.json
    for period in ['T_1', 'T_3', 'T_5']:
        src = OUTPUT_DIR / f'optimization_{period}.json'
        if src.exists():
            dst = today_dir / f'optimization_{period}.json'
            shutil.copy(src, dst)
            logger.info(f"✓ 已归档: {dst.name}")
    
    logger.info(f"历史归档完成: {today_dir}")
```

**调用位置**: 在 `multi_period_optimizer.py` 主函数末尾调用

---

### 4.3 备选方案：创建独立归档脚本

如果不想修改优化脚本，可创建独立的轻量归档脚本：

**文件**: `versions/v2/scripts/archive_results.py`

```python
#!/usr/bin/env python3
"""
归档优化结果（独立脚本）

替代原 generate_top_stocks.py 的归档功能
"""

import json
import shutil
from pathlib import Path
from datetime import datetime

BASE_DIR = Path(__file__).parent.parent  # versions/v2/
OUTPUT_DIR = BASE_DIR / 'output'

def archive_optimization_results():
    """归档优化结果"""
    history_dir = OUTPUT_DIR / 'history'
    today = datetime.now().strftime('%Y-%m-%d')
    today_dir = history_dir / today
    
    today_dir.mkdir(parents=True, exist_ok=True)
    print(f"历史归档目录: {today_dir}")
    
    # 复制所有 optimization_*.json
    for f in OUTPUT_DIR.glob('optimization_*.json'):
        dst = today_dir / f.name
        shutil.copy(f, dst)
        print(f"✓ 已归档: {f.name}")
    
    print(f"归档完成: {today_dir}")

if __name__ == '__main__':
    archive_optimization_results()
```

---

## 五、风险评估

### 5.1 影响范围

| 影响范围 | 影响程度 | 说明 |
|---------|---------|------|
| web_app.py API 接口 | 中 | 3个接口依赖该数据：`/api/precompute/result`、`/api/portfolio/*` |
| portfolio_tracker.py | 中 | 每日跟踪功能依赖该数据 |
| precompute_optimizer.py | 低 | 仅 `get_top_stocks()` 函数受影响 |
| 历史数据 | 无 | 归档数据格式不变，仅路径调整 |

### 5.2 风险点

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|----------|
| 字段名不匹配 | 低 | 高 | 严格按 `selections` 字段读取，添加格式转换 |
| 文件路径错误 | 低 | 高 | 使用绝对路径，添加文件存在性检查 |
| 数据格式变化 | 中 | 中 | 添加字段兼容性处理，支持 fallback |
| API 响应格式变化 | 低 | 中 | 转换时保持 `stocks` 字段名，保证下游兼容 |

### 5.3 测试计划

#### 单元测试

```bash
# 测试 portfolio_tracker.py 的 load_precompute_result()
cd /home/admin/.openclaw/workspace/yunzhou/factor_ic_analyzer
python3 -c "
from portfolio_tracker import load_precompute_result
result, stocks = load_precompute_result('T1')
print(f'Result: {result is not None}')
print(f'Stocks count: {len(stocks) if stocks else 0}')
"
```

#### API 测试

```bash
# 测试 web_app.py 接口
curl -s http://localhost:5000/api/precompute/result | jq '.data.best_result.stocks | length'
curl -s http://localhost:5000/api/precompute/result | jq '.data.all_periods'
```

#### 集成测试

```bash
# 测试完整流程
cd /home/admin/.openclaw/workspace/yunzhou/factor_ic_analyzer/versions/v2/scripts
python3 multi_period_optimizer.py --quick  # 先运行优化
python3 -c "
from portfolio_tracker import load_precompute_result
result, stocks = load_precompute_result('T1')
print(f'✓ T1: {len(stocks)} stocks')
result, stocks = load_precompute_result('T3')
print(f'✓ T3: {len(stocks)} stocks')
result, stocks = load_precompute_result('T5')
print(f'✓ T5: {len(stocks)} stocks')
"
```

---

## 六、实施步骤

### Step 1: 修改依赖模块（建议顺序）

1. 修改 `precompute_optimizer.py` 的 `load_v2_precompute_result()` 函数
2. 修改 `portfolio_tracker.py` 的 `load_precompute_result()` 函数
3. 修改 `web_app.py` 的股票数据读取逻辑

### Step 2: 添加归档功能

选择方案：
- **推荐**: 在 `multi_period_optimizer.py` 添加 `archive_optimization_results()` 函数
- **备选**: 创建独立脚本 `archive_results.py`

### Step 3: 测试验证

```bash
# 1. 单元测试
python3 test_load_precompute_result.py

# 2. API 测试
curl -s http://localhost:5000/api/precompute/result | jq '.'

# 3. 集成测试
python3 versions/v2/scripts/multi_period_optimizer.py --quick
```

### Step 4: 删除选股脚本

```bash
# 备份
cp versions/v2/scripts/generate_top_stocks.py backups/

# 删除
rm versions/v2/scripts/generate_top_stocks.py

# 删除冗余数据
rm cache/v2/precompute/top_stocks_T*.json
```

### Step 5: 清理冗余文件

```bash
# 删除选股脚本生成的冗余数据
rm -f cache/v2/precompute/top_stocks_T1.json
rm -f cache/v2/precompute/top_stocks_T3.json
rm -f cache/v2/precompute/top_stocks_T5.json
```

---

## 七、回滚方案

### 7.1 快速回滚

如果修改后出现问题，可快速回滚：

```bash
# 恢复选股脚本
cp backups/generate_top_stocks.py versions/v2/scripts/

# 恢复依赖模块代码
git checkout -- web_app.py portfolio_tracker.py precompute_optimizer.py

# 重新生成冗余数据
python3 versions/v2/scripts/generate_top_stocks.py
```

### 7.2 代码回滚（推荐使用 Git）

```bash
# 查看修改
git diff web_app.py portfolio_tracker.py precompute_optimizer.py

# 回滚单个文件
git checkout -- web_app.py

# 回滚所有修改
git checkout -- .
```

---

## 八、变更记录

| 版本 | 日期 | 修改内容 |
|------|------|---------|
| v3.16 | 2026-05-02 | 删除选股脚本，直接读取 optimization_T_*.json |

---

## 九、附录

### A. optimization_T_*.json 完整结构

```json
{
  "success": true,
  "period": "T+1",
  "return_col": "forward_return_1d",
  "weights": { "rsi": -0.05, ... },
  "metrics": {
    "sharpe_ratio": 1.5,
    "max_drawdown": 29.59,
    "win_rate": 52.35,
    "annual_return": 43.0
  },
  "icir": 4.415,
  "tier": "tier1",
  "selections": [
    { "code": "001207", "name": "联科科技", "rank": 1, "total_score": 43.65 },
    ...
  ]
}
```

### B. 字段映射表

| 原字段 (top_stocks_T*.json) | 新字段 (optimization_T_*.json) |
|------------------------------|--------------------------------|
| `stocks` | `selections` |
| `weights_used` | `weights` |
| `summary` | `metrics` |
| `computed_at` | `computed_at` (不变) |
| `period` | `period` (不变) |

### C. 相关文件清单

| 文件 | 状态 | 说明 |
|------|------|------|
| `versions/v2/scripts/generate_top_stocks.py` | 待删除 | 选股脚本（冗余） |
| `cache/v2/precompute/top_stocks_T*.json` | 待删除 | 冗余数据 |
| `versions/v2/output/optimization_T_*.json` | 保留 | 权威数据源 |
| `web_app.py` | 待修改 | 更新读取路径和字段 |
| `portfolio_tracker.py` | 待修改 | 更新读取路径和字段 |
| `precompute_optimizer.py` | 待修改 | 更新读取路径和字段 |

---

## 审核问题处理

| 问题 | 处理方案 |
|------|----------|
| 文件名错误 | precompute_optimizer_multi_period.py |
| computed_at缺失 | 使用os.path.getmtime()作为fallback |
| 回滚风险 | 实施前git stash保存修改 |
| 测试补充 | 增加边界场景和验收标准 |