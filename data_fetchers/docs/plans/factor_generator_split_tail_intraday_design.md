# factor_generator.py 内联因子搬迁 design

**版本**：v1.0
**日期**：2026-06-16
**作者**：云瑶
**状态**：已确认，执行中

---

## 1. 背景与目标

`factor_generator.py`（v1.42, 1388 行）违反 MODULE.md **约束 #3**：
"重构后统一从 factor_calculator 导入因子计算函数"。

但本文件仍内联保留 6 个因子计算函数（约 430 行）：
- `_calc_intraday_intensity`（日内强度，row-level）
- 尾盘族（5 row-level + 1 编排 + 1 I/O + 1 helper）：
  `_load_tail_trading_data` / `_get_close_price` /
  `_calc_price_position` / `_calc_tail_price_slope` /
  `_calc_tail_price_volume_intensity` / `_calc_tail_volume_acceleration` /
  `_calc_tail_volume_shrink` / `_calculate_tail_factors`

**目标**：迁出到 `factor_calculator/` 子模块，恢复约束 #3 合规。

---

## 2. 范围与决策

| # | 决策 | 选定 |
|---|------|------|
| 1 | 落点策略 | **新建 `intraday.py` + `tail.py`**（不合并进 `volume_price.py`，避免单文件超 600 行） |
| 2 | row-level 私有函数可见性 | **保持 `_calc_*` 下划线私有**，与 `_common._per_asset_transform` 对齐；外部仅调公共 DataFrame 接口 |
| 3 | `calculate_intraday_intensity` 接口 | **DataFrame 接口** `(df, logger_arg=None) -> df`，与 `calculate_amplitude` 等同族对齐 |
| 4 | 调用点风格 | factor_generator.py step 10 / 11 改为 `factor_df = calculate_xxx(factor_df, logger_arg=logger)`，与其他 step 完全同构 |
| 5 | 注册路径 | 沿用现有约定：`_legacy.py` 内 `from .xxx import (...)` re-import + 加入 `__all__`；外部 `from data_fetchers.factor_calculator import calculate_xxx` 不变 |

---

## 3. 6 轮拆分计划

| 轮 | 范围 | 文件改动 | 估算行数 |
|---|------|---------|---------|
| **B1** | 搬 `_calc_intraday_intensity` → `intraday.py` 公共 DataFrame 接口；注册 | 新建 `factor_calculator/intraday.py`；编辑 `_legacy.py` __all__ | +90 / 0 |
| **B2** | tail.py 骨架 + I/O 层（常量 + `_load_tail_trading_data` + `_get_close_price`） | 新建 `factor_calculator/tail.py` | +90 / 0 |
| **B3** | 5 个 row-level 尾盘计算函数 | tail.py 追加 5 个 `_calc_*` | +260 / 0 |
| **B4** | tail 编排 + 注册 | tail.py 追加公共 `calculate_tail_factors`；编辑 `_legacy.py` __all__ | +120 / 0 |
| **B5** | factor_generator.py 切换 + 删除（关键轮） | 改 import → 删 6 个内联函数 + 尾盘常量 → step 10/11 对接 | +20 / -430 |
| **B6** | 文档收口 | MODULE.md 约束 #3 grep / factor_generator_flow.md / 本 design 状态闭环 | +30 / -10 |

**前 4 轮"只增不删"，建立双备份；第 5 轮才切换 + 删除，可单独 revert 回退。**

---

## 4. 兼容性契约

- `factor_generator.py` 对外 API 不变（`generate_all_factors` / `get_module_logger`）
- `factor_calculator` 包对外 API 新增 2 个公共函数：`calculate_intraday_intensity` / `calculate_tail_factors`
- 输出 schema 不变（`_OUTPUT_COLS` 不动），下游 factor_ic / backtest / comprehensive_factor 零修改
- 尾盘数据路径常量 `_TAIL_TRADING_DATA_PATH` 从 factor_generator 迁到 tail.py（私有，无外部引用，已 grep 验证）

---

## 5. 验证策略

每轮强制三段：
1. `ruff check + ruff format` 通过
2. `python -c "from data_fetchers.factor_calculator import <new_func>"` 通过
3. `pytest data_fetchers/test_cases/test_factor_generator.py --collect-only` 通过

B5 后追加：`python data_fetchers/factor_generator.py --help` 必须 OK。

---

## 6. 状态闭环

| 轮 | commit | 时间 | 状态 |
|---|--------|------|------|
| B1 | — | 2026-06-16 | 待执行 |
| B2 | — | — | — |
| B3 | — | — | — |
| B4 | — | — | — |
| B5 | — | — | — |
| B6 | — | — | — |
