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
| B1 | `faaa7fe` | 2026-06-16 | ✅ 完成（intraday.py 新建 + 注册，+216 行）|
| B2 | `a969c67` | 2026-06-16 | ✅ 完成（tail.py 骨架 + I/O，+120 行；新旧 _load_tail_trading_data 在 66304×9 数据上 df.equals=True）|
| B3 | `b7cee65` | 2026-06-16 | ✅ 完成（5 个 row-level helper，+229 行；26 个边界用例 vs 原版全等）|
| B4 | `bb0732b` | 2026-06-16 | ✅ 完成（calculate_tail_factors 公共 API，+142 行；真实数据 3000 行 5 列 vs _calculate_tail_factors 全等）|
| B5 | `80be47f` | 2026-06-16 | ✅ 完成（factor_generator.py 切换+删除，1392→946 行，+6 / -448）|
| B6 | _本轮_ | 2026-06-16 | ✅ 完成（MODULE.md 因子表 +6 行，design.md 状态闭环）|

## 7. 收口验证

- [x] `ruff check` / `ruff format` 全套通过
- [x] `from data_fetchers import factor_generator` 包导入 OK
- [x] `python data_fetchers/factor_generator.py --help` 脚本入口 OK
- [x] `pytest --collect-only` 通过
- [x] B5 真实数据等价性已验证（B4 commit 上 2997 有效值 5 列全等）

## 8. 后续建议（不在 B 步范围）

- `data_fetchers/docs/factor_generator_flow.md` 当前仅描述到 Step 1-8 / Bollinger/KDJ/Turnover_Surge 因子（pre-existing 过时，未在本轮收口；建议在 D 步（generate_all_factors 表驱动重构）时一并修订到 Step 1-11+ 全因子）
- factor_generator.py 当前 946 行——D / E / F 步可继续瘦身：
  * D: generate_all_factors 表驱动（预计 -200 行）
  * E: metadata 派生（预计 -50 行）
  * F: I/O helper 抽提（预计 -80 行）
  * 合计目标 ~580 行
