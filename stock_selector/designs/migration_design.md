# stock_selector 目录迁移设计文档

> 迁移日期: 2026-06-26
> 设计依据: AGENTS.md 陷阱 1（路径迁移未同步）

## What

将 `comprehensive_factor/` 下 5 个选股相关脚本迁移到独立的 `stock_selector/` 顶层模块。

## 迁移文件清单

| 原路径 | 新路径 | 大小 |
|--------|--------|------|
| `comprehensive_factor/stock_selector.py` | `stock_selector/selector.py` | 68KB |
| `comprehensive_factor/stock_selector_config.py` | `stock_selector/config.py` | 13KB |
| `comprehensive_factor/stock_selector_history.py` | `stock_selector/history.py` | 14KB |
| `comprehensive_factor/stock_selector_lr.py` | `stock_selector/lr.py` | 30KB |
| `comprehensive_factor/weight_selector.py` | `stock_selector/weight_selector.py` | 27KB |

### 测试文件迁移

| 原路径 | 新路径 |
|--------|--------|
| `comprehensive_factor/test_cases/test_stock_selector.py` | `stock_selector/test_cases/test_stock_selector.py` |
| `comprehensive_factor/test_cases/test_stock_selector_exposure.py` | `stock_selector/test_cases/test_stock_selector_exposure.py` |
| `comprehensive_factor/test_cases/test_stock_selector_filter.py` | `stock_selector/test_cases/test_stock_selector_filter.py` |
| `comprehensive_factor/test_cases/test_two_stage_selector.py` | `stock_selector/test_cases/test_two_stage_selector.py` |
| `comprehensive_factor/test_cases/test_selection_history_parquet.py` | `stock_selector/test_cases/test_selection_history_parquet.py` |
| `comprehensive_factor/test_cases/test_filter_role.py` | `stock_selector/test_cases/test_filter_role.py` |
| `comprehensive_factor/test_cases/test_liquidity_filter.py` | `stock_selector/test_cases/test_liquidity_filter.py` |
| `comprehensive_factor/test_cases/test_weight_selector_p3.py` | `stock_selector/test_cases/test_weight_selector_p3.py` |
| `comprehensive_factor/test_cases/test_direction_unify.py` | `stock_selector/test_cases/test_direction_unify.py` |

### 不迁移的文件

- `comprehensive_factor/decision_card.py` — 决策卡是 comprehensive_factor 的业务逻辑，stock_selector 只是调用方
- `comprehensive_factor/common/*` — 共享基础设施（factor_loader, weight_engine, convert_types）
- `comprehensive_factor/composite_*.py` — 综合因子加权脚本
- `comprehensive_factor/test_cases/test_*.py`（非选股相关测试）

## 新模块结构

```
stock_selector/
├── __init__.py           # re-export（向后兼容）
├── selector.py           # 核心选股逻辑 + CLI（原 stock_selector.py）
├── config.py             # 配置+常量+数据加载（原 stock_selector_config.py）
├── history.py            # Parquet 选股历史写入（原 stock_selector_history.py）
├── lr.py                 # LR 过滤训练/应用（原 stock_selector_lr.py）
├── weight_selector.py    # 权重方式选择（原 weight_selector.py）
├── common/
│   ├── __init__.py
│   └── logger_config.py  # 独立 logger（遵循模块边界规则）
├── designs/
├── logs/
├── result/
└── test_cases/
```

## Import 变更规则

### 模块内部 import（迁移文件之间）

| 原 import | 新 import |
|-----------|-----------|
| `from comprehensive_factor.stock_selector_config import X` | `from stock_selector.config import X` |
| `from comprehensive_factor.stock_selector_history import X` | `from stock_selector.history import X` |
| `from comprehensive_factor.stock_selector_lr import X` | `from stock_selector.lr import X` |
| `from comprehensive_factor.stock_selector import X` (内部) | `from stock_selector.selector import X` |

### 保留的跨模块 import（合法依赖）

- `from comprehensive_factor.common.factor_loader import X` — 因子加载基础设施
- `from comprehensive_factor.common.weight_engine import X` — 权重引擎
- `from comprehensive_factor.common.convert_types import X` — 类型转换
- `from comprehensive_factor.decision_card import X` — 决策卡构建

### Logger 变更

| 原 import | 新 import |
|-----------|-----------|
| `from comprehensive_factor.common.logger_config import get_logger` | `from stock_selector.common.logger_config import get_logger` |

### 外部引用更新

所有 `from comprehensive_factor.stock_selector import X` → `from stock_selector import X`（通过 `__init__.py` re-export）

涉及文件：
1. `summary/report/sections.py`
2. `summary/test_cases/test_generate_factor_summary_report.py`
3. `temporary/backfill_lr_training_data.py`（临时脚本，同步更新）

## import-linter 配置

`stock_selector` 不加入 independence 列表——它对 `comprehensive_factor.common` 有合法的跨模块依赖（factor_loader, weight_engine）。

## paths.py 更新

新增 `STOCK_SELECTOR_RESULT` 路径常量（如果 stock_selector 需要独立输出目录）。

当前 `LR_TRAINING_DATA_DIR` 和选股历史输出仍指向 `comprehensive_factor/result/`，迁移后改为 `stock_selector/result/`。

## 执行轮次

### R1: 基础设施（≤3 文件）
- 创建 `stock_selector/__init__.py`
- 创建 `stock_selector/common/__init__.py` + `logger_config.py`
- 创建 `stock_selector/MODULE.md`

### R2: 迁移 config + history（≤3 文件）
- 迁移 config.py（改 import）
- 迁移 history.py（改 import）
- 验证导入

### R3: 迁移 lr + weight_selector（≤3 文件）
- 迁移 lr.py（改 import）
- 迁移 weight_selector.py（改 import）
- 验证导入

### R4: 迁移 selector.py + __init__.py re-export（≤3 文件）
- 迁移 selector.py（改 import）
- 完善 __init__.py re-export
- 验证导入 + CLI --help

### R5: 迁移测试文件 + 更新外部引用
- 移动 ~9 个测试文件，更新 import
- 更新 summary/report/sections.py、summary 测试文件
- ruff + pytest 全量验证

### R6: 文档同步
- 更新 comprehensive_factor/MODULE.md（删除选股规范）
- 更新 PROJECT.md 跨模块数据路径表
- 更新 paths.py
- 删除原文件
- 最终 pytest + git commit

## 风险

1. **测试 mock 路径**：测试中 `patch("comprehensive_factor.stock_selector.X")` 需全部更新
2. **输出路径**：选股历史 Parquet 输出目录变更需同步所有下游读取方
3. **向后兼容**：`from comprehensive_factor.stock_selector import X` 将不再可用（与上次 report 重构不同，这次是物理迁移）
