# 5日累计涨幅因子分层回测流程文档

> 版本: v1.0  
> 作者: 云瑶  
> 创建日期: 2026-06-01  

---

## 概述

本文档记录 `layered_backtest_return_5d_1d.py` 的分层回测流程。

---

## 整体架构

```
layered_backtest_return_5d_1d.py（~80行）
├── Return5dLayerConfig（分层配置类）
│   ├── factor_name = 'return_5d'
│   ├── ic_meta（IC 分析结果）
│   ├── n_layers = 5
│   ├── layer_names（语义描述）
│   └── factor_direction = 'negative'
└── factor_cli_main（公共入口）
    ├── 参数解析
    ├── 因子计算（calculate_return_5d）
    ├── 分层回测
    └── 结果保存
```

---

## 详细流程步骤

### Step 1: 配置定义

```python
@dataclass
class Return5dLayerConfig(LayerConfigBase):
    factor_name: ClassVar[str] = 'return_5d'
    ic_meta: ClassVar[Dict[str, Any]] = {
        'ic_mean': -0.0591,
        'direction': 'negative',
    }
    n_layers: int = 5
    factor_direction: Literal['positive', 'negative'] = 'negative'
```

**关键点**：
- factor_name 作为 ClassVar（单一来源）
- ic_meta 集中 IC 信息
- n_layers 显式声明避免隐式耦合
- factor_direction 由 IC 均值决定（负相关）

### Step 2: CLI 入口

```python
if __name__ == '__main__':
    factor_cli_main(
        factor_name=Return5dLayerConfig.factor_name,
        config_cls=Return5dLayerConfig,
        factor_calculator=calculate_return_5d,
    )
```

**关键点**：
- 使用公共入口 factor_cli_main
- 引用 config.factor_name（单一来源）
- 无 sys.path 操作

### Step 3: 因子计算

调用 `data_fetchers/factor_calculator.py::calculate_return_5d()`

```python
return_5d = close[t] / close[t-5] - 1
```

### Step 4: 分层回测

由公共模块 `layered_backtest_runner.py` 执行：
- percentile 分层（5层，每层20%）
- 反向因子：低值层做多，高值层做空

---

## 输出结构

### 文件路径

```
backtest/result/return_5d_layered_backtest.json
backtest/result/return_5d_layered_backtest_daily.json.gz
```

### JSON 结构

```json
{
  "meta": {
    "factor_name": "return_5d",
    "factor_direction": "negative",
    "n_layers": 5,
    "layer_names": {...}
  },
  "layer_stats": {...},
  "monotonicity": {...},
  "long_short": {...}
}
```

---

## 关键指标

| 指标 | 说明 |
|------|------|
| IC 均值 | -0.0591（负相关，动量反转） |
| 因子方向 | negative（低值层做多） |
| 分层模式 | percentile（MODULE.md 强制规范） |
| 分层数量 | 5 层（显式声明） |

---

## 配套文件

| 文件 | 说明 |
|------|------|
| `layered_backtest_return_5d_1d.py` | 主脚本 |
| `docs/layered_backtest_return_5d_1d_flow.md` | 流程文档 |
| `test_cases/return_5d_layered_backtest_test_cases.md` | 测试用例文档 |
| `test_cases/test_layered_backtest_return_5d_1d.py` | pytest 测试文件 |

---

## 版本历史

| 版本 | 日期 | 更新内容 |
|------|------|----------|
| v1.0 | 2026-06-01 | 初始版本（Round 1：架构修复+配套文档创建） |

---

## 参考

- PROJECT.md: 项目级规范
- MODULE.md: backtest 模块规范
- `layered_backtest_overnight_ret_1d.py`: 参考脚本（最佳实践）
