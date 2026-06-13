# Design：因子名→列名 映射统一来源（方案 B）

> 遵循 AGENTS.md Design-First 流程（涉及 ≥2 文件改动）
> 创建日期：2026-06-13
> 作者：云瑶
> 状态：待审

---

## 1. 背景与目标

### 1.1 痛点

`run_pipeline.py` 在 2026-06-13 已补齐 11 个 IC + 15 个分层回测注册（v1.7），但 Stage 4（综合因子）和 Stage 7（汇总报告）下游存在 **4 处独立维护的 `FACTOR_NAME_TO_COL_MAP`/`FACTOR_COL_TO_NAME_MAP`**，各自版本不同步：

| 文件 | 位置 | 形式 | 当前覆盖 | 缺口 |
|------|------|------|---------|------|
| `comprehensive_factor/common/factor_selector.py` | L67-108（模块级） | dict | 30/34 | 缺 4：amplitude_delta、past_return_1d、return_3d、turnover_surge_delta |
| `comprehensive_factor/common/weight_engine.py` | L34-56（**类内部**字段） | dict | 12/34（含 4 错条目） | 缺 19 + 错 4：kdj_j_9 / bollinger_pb_20 / turnover_surge_5（带后缀但实际数据列名不带）/ main_inflow_ratio_1d（数据源不存在） |
| `comprehensive_factor/common/composite_runner.py` | L253/274（反射 `select_factors.__globals__`） | 间接引用 factor_selector | 跟随 factor_selector | 反射语义模糊 |
| `summary/generate_factor_summary_report.py` | L114（COL_TO_NAME 旧表）+ L129（NAME_TO_COL） | 两份 dict | NAME_TO_COL 23/34、COL_TO_NAME 10/34 | NAME_TO_COL 缺 11、COL_TO_NAME 缺 24（导致相关性矩阵漏算 24 因子） |

**直接后果**：新增因子在 Stage 4 权重计算被静默跳过、Stage 7 相关性矩阵漏 24 个因子——直接命中用户敏感约束"因子被静默跳过"。

### 1.2 目标

1. **单一映射来源**：所有 `name ↔ col` 映射集中在 `factor_definitions.py`，新增因子改 1 处即可
2. **数据源对齐**：以 `data_fetchers/result/factor_ic_data.json.gz` 实际列名为权威，不再保留历史错列名
3. **零行为变更**：仅迁移映射来源，不改业务逻辑（IC 计算/权重选择/筛选阈值）；现有正则后缀回退保留作兜底
4. **可验证**：新增 `tests/test_factor_definitions.py` 断言全 34 因子都有 `name → col` 映射

### 1.3 非目标

- ❌ 不改 `FACTOR_DEFINITIONS`（语义定义字典）已有内容
- ❌ 不重构 weight_engine 的正则后缀回退逻辑（保留兜底）
- ❌ 不改 Stage 1/2/3 注册（已在 run_pipeline v1.7 完成）

---

## 2. 方案设计

### 2.1 单一映射来源（factor_definitions.py v1.5）

在现有 v1.4 基础上**新增** 2 个常量 + 2 个辅助函数，**不修改** `FACTOR_DEFINITIONS`：

```python
# 新增：因子名 → 数据列名（权威来源 = factor_ic_data.json.gz 实际列名）
FACTOR_NAME_TO_COL_MAP: dict[str, str] = {
    # 基础因子（数据源带后缀的仅 2 个）
    "rsi": "rsi_6",
    "volume_ratio": "volume_ratio_5",
    # 其余 32 个因子：name == col（不带后缀）
    "kdj_j": "kdj_j",
    "bollinger_pb": "bollinger_pb",
    ...
}

# 新增：反向映射（自动生成，避免手工同步）
FACTOR_COL_TO_NAME_MAP: dict[str, str] = {v: k for k, v in FACTOR_NAME_TO_COL_MAP.items()}

def get_factor_col(factor_name: str, default: str | None = None) -> str:
    """因子名 → 列名；未注册时回退因子名本身（与现有兼容逻辑一致）"""
    return FACTOR_NAME_TO_COL_MAP.get(factor_name, default if default is not None else factor_name)

def get_factor_name(col: str, default: str | None = None) -> str:
    """列名 → 因子名；未注册时回退列名本身"""
    return FACTOR_COL_TO_NAME_MAP.get(col, default if default is not None else col)
```

`__all__` 同步追加 4 项；版本升 v1.5；版本历史增条目。

### 2.2 数据源真值清单（34 因子，权威）

**带后缀的列（仅 2 个）**：
- `rsi` → `rsi_6`
- `volume_ratio` → `volume_ratio_5`

**name == col 的列（32 个）**：
amplitude、amplitude_delta、bollinger_pb、capital_flow_intensity、capital_flow_ratio_trend、industry_amplitude_trend、industry_earnings_growth、industry_momentum_5d、industry_pe_trend、industry_roe_trend、industry_turnover_trend、intraday_intensity、kdj_j、ma5_deviation、momentum_strength、near_high_ratio_5、overnight_ret、past_return_1d、positive_day_ratio_5、price_position、return_3d、return_5d、tail_price_position、tail_price_position_delta、tail_price_slope、tail_price_volume_intensity、tail_volume_acceleration、tail_volume_shrink、tail_volume_shrink_delta、turnover_surge、turnover_surge_delta、volume_price_strength

**校验依据**：上一轮通过 `gzip` 解压 `data_fetchers/result/factor_ic_data.json.gz` 头 200KB 提取实际列名得到。`return_3d` 在头 200KB 未出现但 `factor_ic/result/ic_return_3d_1d_analysis_result.json` 存在，按 IC 脚本可正常计算视为有效列。

### 2.3 历史错条目处理（Q1 默认建议已确认）

`weight_engine.py` 4 个错条目的处理：

| 历史条目 | 数据源真实列名 | 处置 |
|----------|---------------|------|
| `kdj_j → kdj_j_9` | `kdj_j` | 修正为 `kdj_j → kdj_j` |
| `bollinger_pb → bollinger_pb_20` | `bollinger_pb` | 修正为 `bollinger_pb → bollinger_pb` |
| `turnover_surge → turnover_surge_5` | `turnover_surge` | 修正为 `turnover_surge → turnover_surge` |
| `main_inflow_ratio → main_inflow_ratio_1d` | （数据源无） | **删除**（死条目） |

**风险评估**：weight_engine `_get_factor_name_from_col` 正则 `(.+)_(?:\d+[a-z]?|\d+)$` 对 `kdj_j_9`/`bollinger_pb_20`/`turnover_surge_5` 之前是"碰巧救场"——历史 IC 结果文件名是 `ic_kdj_j_1d_analysis_result.json`（**因子名 kdj_j**，不是 `kdj_j_9`），weights 字典实际收到的列名也是 `kdj_j`（数据列名）。错条目实际从未被命中，删除/修正是安全操作。

### 2.4 反射改显式 import（Q2 默认建议已确认）

`composite_runner.py:253-274` 当前通过 `select_factors.__globals__.get("FACTOR_NAME_TO_COL_MAP")` 反射拿映射，迁移后改为：

```python
from factor_definitions import FACTOR_NAME_TO_COL_MAP, FACTOR_COL_TO_NAME_MAP
```

显式依赖更清晰；删除反射 fallback `.get(..., {})`（找不到映射应是配置错误，不该静默退化为空）。

---

## 3. 文件改动清单（4+1 处）

### 3.1 `factor_definitions.py`（v1.4 → v1.5）【新增映射常量】

| 改动点 | 内容 |
|--------|------|
| 文件头 docstring 版本历史 | 追加 v1.5 (2026-06-13) 条目，说明新增 NAME_TO_COL/COL_TO_NAME 映射 |
| `__all__` | 追加 `FACTOR_NAME_TO_COL_MAP`、`FACTOR_COL_TO_NAME_MAP`、`get_factor_col`、`get_factor_name` |
| `__version__` | `"1.4"` → `"1.5"` |
| 新增常量 | `FACTOR_NAME_TO_COL_MAP`（34 项，按章节归类，与 `FACTOR_DEFINITIONS` 章节对齐）+ `FACTOR_COL_TO_NAME_MAP`（推导） |
| 新增函数 | `get_factor_col(factor_name, default=None)`、`get_factor_name(col, default=None)` |

### 3.2 `comprehensive_factor/common/factor_selector.py`【删本地 map，改 import】

| 改动点 | 内容 |
|--------|------|
| L67-108（本地 `FACTOR_NAME_TO_COL_MAP` 定义） | **删除**整段，改为 `from factor_definitions import FACTOR_NAME_TO_COL_MAP`（顶部 import 区） |
| L60-66 docstring 注释 | 保留首行说明，移除"v1.2 → v1.3 扩展"细节注释（迁入 factor_definitions） |
| L776-780 `if factor_name in FACTOR_NAME_TO_COL_MAP` 兼容回退逻辑 | **保留**（统一映射来源后语义不变） |
| 文件 docstring 版本历史 | 追加 v1.X (2026-06-13)：迁移映射来源至 factor_definitions |

### 3.3 `comprehensive_factor/common/weight_engine.py`【删类内 map，改 import】

| 改动点 | 内容 |
|--------|------|
| L34-56（类内 `FACTOR_NAME_TO_COL_MAP` + L57 `COL_TO_FACTOR_NAME_MAP`） | **删除**类内字段，类顶部加注释说明使用 `factor_definitions` 模块级常量 |
| 顶部 imports | 加 `from factor_definitions import FACTOR_NAME_TO_COL_MAP, FACTOR_COL_TO_NAME_MAP as COL_TO_FACTOR_NAME_MAP`（保留旧别名） |
| `_FACTOR_SUFFIX_PATTERN` + `_get_factor_name_from_col` | **保留**（正则后缀回退兜底） |
| 4 个错条目（kdj_j_9 / bollinger_pb_20 / turnover_surge_5 / main_inflow_ratio_1d） | **不再出现**（统一映射后自动消失） |
| 文件 docstring 版本历史 | 追加：迁移映射来源 + 修正历史 4 个错条目 |

### 3.4 `comprehensive_factor/common/composite_runner.py`【反射改显式 import】

| 改动点 | 内容 |
|--------|------|
| L252-289 反射调用 `select_factors.__globals__.get("FACTOR_NAME_TO_COL_MAP", {})` | 改为 `from factor_definitions import FACTOR_NAME_TO_COL_MAP, FACTOR_COL_TO_NAME_MAP`，3 处反射调用直接使用模块级常量 |
| L274 `col_to_name_map = {v: k for k, v in ...}` 推导 | 改为 `col_to_name_map = FACTOR_COL_TO_NAME_MAP` |
| 文件 docstring 版本历史 | 追加：删除反射依赖，改显式 import |

### 3.5 `summary/generate_factor_summary_report.py`【两份 map 都改 import】

| 改动点 | 内容 |
|--------|------|
| L114-124 `FACTOR_COL_TO_NAME_MAP`（旧 10 条） | **删除**，改为 `from factor_definitions import FACTOR_COL_TO_NAME_MAP`（已有 `from factor_definitions import FACTOR_DEFINITIONS` 在 L75，扩为多项 import） |
| L128-161 `FACTOR_NAME_TO_COL_MAP`（23 条） | **删除**，改为 `from factor_definitions import FACTOR_NAME_TO_COL_MAP` |
| L162 `COL_TO_FACTOR_NAME_MAP` 推导 | **删除**（已统一到 FACTOR_COL_TO_NAME_MAP） |
| L719/721/746/791/1265/1289/1973 使用点 | **不变**（变量名保持），其中 L746 `factor_cols = list(FACTOR_COL_TO_NAME_MAP.keys())` 自动从 10 → 34，**修复 24 个因子相关性矩阵漏算问题** |
| 文件 docstring 版本历史（v2.18 → v2.19） | 追加：统一映射来源 + 修复相关性矩阵漏算 |

### 3.6 测试新增/扩展 `tests/test_factor_definitions.py`

| 改动点 | 内容 |
|--------|------|
| 新增测试 `test_factor_name_to_col_map_complete` | 断言 34 个因子全部有 `name → col` 映射 |
| 新增测试 `test_factor_col_to_name_map_inverse` | 断言 `COL_TO_NAME_MAP` 与 `NAME_TO_COL_MAP` 互逆 |
| 新增测试 `test_no_legacy_wrong_entries` | 断言 `kdj_j_9`/`bollinger_pb_20`/`turnover_surge_5`/`main_inflow_ratio_1d` 不在映射 values 中 |
| 新增测试 `test_data_source_columns_alignment` | 断言所有 col 值都能在 `factor_ic_data.json.gz` 列名集合中找到（或在已知豁免清单内，如 `return_3d`） |
| 新增测试 `test_get_factor_col_fallback` | 断言未注册因子名回退到自身 |

---

## 4. 验证清单（执行阶段强制）

每步完成后必须验证：

| 步骤 | 命令 | 期望 |
|------|------|------|
| 1 | `ruff check . && ruff format --check .` | 全部通过 |
| 2 | `pytest tests/test_factor_definitions.py -v` | 5 个新增测试全部 PASS |
| 3 | `pytest comprehensive_factor/test_cases/ -v` | 现有测试全部 PASS（行为零变更） |
| 4 | `pytest summary/test_cases/ -v` | 现有测试全部 PASS |
| 5 | `python -c "from factor_definitions import FACTOR_NAME_TO_COL_MAP; assert len(FACTOR_NAME_TO_COL_MAP) == 34; print('OK')"` | OK |
| 6 | grep 检查残留：`grep -rn 'FACTOR_NAME_TO_COL_MAP\s*=\s*{' --include='*.py' .` | 仅 1 处（`factor_definitions.py`） |
| 7 | grep 检查残留：`grep -rn 'kdj_j_9\\|bollinger_pb_20\\|turnover_surge_5\\|main_inflow_ratio_1d' --include='*.py' .` | 0 处（除测试文件中的反向断言） |
| 8 | 端到端 smoke：`python run_pipeline.py --stage 4`（comprehensive_factor）| 无 KeyError，权重表覆盖 34 因子 |
| 9 | 端到端 smoke：`python run_pipeline.py --stage 7`（summary）| 相关性矩阵列数从 10 → 34 |

---

## 5. 执行顺序与回滚方案

### 5.1 执行顺序（最小破坏面）

```
Step 1: factor_definitions.py 新增映射常量 + 函数（仅 add，不破坏既有）
Step 2: tests/test_factor_definitions.py 新增 5 个测试 → pytest PASS
Step 3: factor_selector.py 改 import（删本地 map）→ pytest PASS
Step 4: weight_engine.py 改 import + 删类内字段 → pytest PASS
Step 5: composite_runner.py 反射改显式 import → pytest PASS
Step 6: summary/generate_factor_summary_report.py 改 import（删两份本地 map）→ pytest PASS
Step 7: ruff check + ruff format
Step 8: 端到端 smoke（Stage 4 + Stage 7）
Step 9: git commit（消息引用 PROJECT.md 规则 #1/#11 + 本 design.md 行号）
```

每步独立 commit，便于二分回滚。

### 5.2 回滚方案

| 风险 | 表现 | 回滚 |
|------|------|------|
| 某下游脚本依赖 weight_engine 类内字段（直接访问 `instance.FACTOR_NAME_TO_COL_MAP`） | AttributeError | weight_engine 类顶部加 class-level alias `FACTOR_NAME_TO_COL_MAP = FACTOR_NAME_TO_COL_MAP` 兼容 |
| `FACTOR_COL_TO_NAME_MAP` 由 10 → 34 后，相关性矩阵显示因子超过预期 | 报告变长 | 接受（这正是修复目标） |
| 历史错条目修正后 IC 结果文件名匹配失败 | KeyError | 实测文件名是 `ic_kdj_j_1d_analysis_result.json` 等（无后缀），与新映射一致；正则后缀回退保留兜底 |

任一步 pytest 失败 → `git revert` 该步 commit，回到上一稳定状态分析根因。

---

## 6. 提交清单（Definition of Done）

- [ ] design.md 通过用户审核
- [ ] 6 个文件改动 + 5 个新增测试均完成
- [ ] ruff check / format 通过
- [ ] pytest 全绿（覆盖率 ≥70%）
- [ ] grep 验证 7：无残留错条目
- [ ] grep 验证 6：仅 1 处映射定义
- [ ] 端到端 smoke：Stage 4 + Stage 7 跑通
- [ ] git commit 消息引用 PROJECT.md 规则 + design.md 行号


