# factor_cols 字面量常量化 - 设计文档 v1.0

**状态**: draft
**作者**: 云瑶
**创建**: 2026-06-15
**前置**: 轮 1(启动日志去重)+ 轮 2(告警文案统一)已完成

---

## 1. 目标

消除 `factor_ic/ic_*.py` 中 38 处 `factor_cols` 字符串字面量(34 个脚本),
实现:

1. **L1 编译期**: `factor_cols` 值来自命名常量/数据结构,mypy/IDE 可补全,ruff 可检拼写
2. **L2 注册期**: 因子声明含 `required_columns` 元组,导入时自动校验格式
3. **L3 运行时**: 数据加载后缺列 → 立即 `DataSchemaError`(已有 `KeyError`,升级为专用异常含因子名上下文)
4. **排序归一化**: 同一列组合只允许一种排序(消除 4 种漂移写法)

---

## 2. 现状分析

### 2.1 字面量分布(38 处 / 34 脚本)

| 模式 | 命中 | 示例 |
|------|------|------|
| join key `[date, asset]` | 10 | capital_flow_*, tail_volume_acceleration |
| OHLCV 子集 | 12 | `[high, low, close]` `[close]` `[open, close, high, low]` |
| 跨脚本因子链 `[date, asset, X]` | 6 | `[date, asset, amplitude]` `[date, asset, tail_price_position]` |
| 杂项 | 10 | `[close, return_5d]` `[close, turnover_rate]` `[open, close, turnover_surge]` |

### 2.2 排序漂移(同一组合多种写法)

| 列集合 | 排序变体 |
|--------|---------|
| date+asset+close | `[date, asset, close]`(4处) / `[close, asset, date]`(2处) |
| open+close+asset+date | `[open, close, asset, date]`(3处) |
| high+low+close | `[high, low, close]`(2处) |
| date+asset+volume | `[date, asset, volume]`(4处) |

### 2.3 已有防御

| 层 | 位置 | 机制 | 缺陷 |
|---|---|---|---|
| L3 运行时 | data_loader.py L263-266 | `missing_factor_cols` → `KeyError(缺失列 + 可用列)` | 无因子名上下文;列名来自字面量 |
| L2 注册期 | factor_ic_runner.py L149-159 | `factor_col not in factor_cols` 自动追加 | 只检查 factor_col,不检查 factor_cols 完整性 |
| L1 编译期 | — | — | 无(字符串字面量 ruff/mypy 不检) |

### 2.4 生产者 schema(已有)

`data_fetchers/factor_generator.py`:
- `_BASE_COLS`(L278-289): `date, asset, open, close, high, low, rsi_6, volume_ratio_5, turnover_rate, volume`
- `_EXTENDED_FACTOR_COLS`(L239-271): 30 个扩展因子列
- `_OUTPUT_COLS`(L293): 上述之和 + `_RETURN_COLS`
- `generate_all_factors()` metadata 输出含 `factor_columns` 字段

**问题**: `_OUTPUT_COLS` 是私有常量(`_`前缀),factor_ic 模块无法导入(M4 跨目录禁止),且 metadata 写入 json.gz 内,读取消耗大(408MB)。

---

## 3. 方案

### 3.1 核心架构:FactorSpec 声明式注册 + 消费者 schema 查询

```
data_fetchers/factor_generator.py
  │ 已有: _OUTPUT_COLS 元组
  └─ 新增: generate_all_factors() 写 factor_ic_data_columns.json (列名清单,~1KB)
     位置: data_fetchers/result/factor_ic_data_columns.json
     格式: {"base_cols": [...], "extended_factor_cols": [...], "return_cols": [...],
            "all_cols": [...], "generated_at": "2026-06-15T..."}

factor_ic/common/data_columns.py  ← 新增
  ├─ 标准列组常量: JOIN_KEYS / OHLC / OHLCV / PRICE_VOLUME 等
  ├─ load_available_columns() → dict[str, list[str]]  (读 columns.json)
  └─ validate_required_columns(required, available) → DataSchemaError

factor_ic/common/factor_spec.py  ← 新增
  ├─ @dataclass(frozen=True) FactorSpec:
  │     factor_name: str
  │     factor_col: str
  │     required_columns: tuple[str, ...]  # 替代 factor_cols
  │     calculation: Callable | None       # 替代 custom_factor_calculation
  │     calc_params_fn: Callable | None    # 替代 custom_factor_calculation_params
  │     extra_log_params_fn: Callable | None  # 替代 extra_log_params
  ├─ FACTOR_REGISTRY: dict[str, FactorSpec]  # 注册表
  └─ register_factor(spec) → spec  (导入时注册 + 格式校验)

factor_ic/common/factor_ic_runner.py
  ├─ 新增: run_factor_ic(spec: FactorSpec, ...) → dict
  │     从 spec 提取 factor_name/factor_col/required_columns/calculation/calc_params
  │     调用 validate_required_columns() 后走原有流程
  └─ 保留: run_simple_factor_ic / run_complex_factor_ic (旧接口,兼容期)

factor_ic/ic_amplitude_delta_1d.py
  from factor_ic.common.factor_spec import FactorSpec, register_factor
  from factor_ic.common.data_columns import JOIN_KEYS

  SPEC = register_factor(FactorSpec(
      factor_name="amplitude_delta",
      factor_col="amplitude_delta",
      required_columns=JOIN_KEYS + ("amplitude",),
      calculation=calculate_amplitude_delta,
      calc_params_fn=lambda args: {"n": args.n},
      extra_log_params_fn=lambda args: {"n": args.n},
  ))

  def main():
      args = parser.parse_args()
      # 启动横幅由公共模块 factor_ic_runner 统一打印
      result = run_factor_ic(spec=SPEC, min_stocks=args.min_stocks, force_full=args.force_full, _logger=logger)
```

### 3.2 三层防御

| 层 | 机制 | 检出时机 | 示例 |
|---|---|---|---|
| **L1 编译期** | `FactorSpec` frozen dataclass + `required_columns: tuple[str, ...]` | mypy 类型检查 / IDE 补全 | `requried_columns` 拼写错 → mypy 报错 |
| **L2 注册期** | `register_factor()` 校验:非空 / 无重复 / 全小写 / factor_col 在 required_columns 中 | 模块导入时 | `("date", "ASSET")` → ValueError |
| **L3 运行时** | `validate_required_columns(df.columns, spec.required_columns)` | 数据加载后、IC 计算前 | 上游改名 → DataSchemaError(`因子 amplitude_delta 缺失列: ['amplitude'], 可用列: [...]`) |

### 3.3 DataSchemaError(新异常类)

```python
class DataSchemaError(Exception):
    """因子数据 schema 校验失败。含因子名 + 缺失列 + 可用列,便于运维定位。"""
    def __init__(self, factor_name: str, missing: list[str], available: list[str]):
        self.factor_name = factor_name
        self.missing_columns = missing
        self.available_columns = available
        super().__init__(
            f"因子 {factor_name} 数据 schema 校验失败: 缺失列 {missing}, "
            f"可用列(前20): {available[:20]}"
        )
```

**与现有 KeyError 的关系**: DataSchemaError 继承 Exception 而非 KeyError。data_loader.py 内部的 KeyError 保持不变(它们是通用列检查,不感知因子名)。FactorSpec 层的 DataSchemaError 是**更高层、更精确**的错误,在 data_loader 之前或之后触发均可。

### 3.4 标准列组常量

```python
# factor_ic/common/data_columns.py

# 索引列(每个因子必须包含)
JOIN_KEYS: tuple[str, ...] = ("date", "asset")

# 行情列组(按字母序排列,消除排序漂移)
OHLC: tuple[str, ...] = ("close", "high", "low", "open")
OHLCV: tuple[str, ...] = ("close", "high", "low", "open", "volume")
PRICE_VOLUME: tuple[str, ...] = ("close", "turnover_rate", "volume")
```

**设计原则**: 只抽象 **2+ 脚本共用** 的列组。单脚本特有的组合(如 `[close, return_5d]`)直接在 FactorSpec 中写 tuple 字面量,不造无复用价值的常量。

### 3.5 factor_ic_data_columns.json

生产者(factor_generator)在 `generate_all_factors()` 末尾写出列名清单:

```json
{
  "base_cols": ["date", "asset", "open", "close", "high", "low", "rsi_6", "volume_ratio_5", "turnover_rate", "volume"],
  "extended_factor_cols": ["past_return_1d", "bollinger_pb", ...],
  "return_cols": ["forward_return_1d", "forward_return_3d", "forward_return_5d"],
  "all_cols": ["date", "asset", ...],
  "generated_at": "2026-06-15T12:00:00"
}
```

**大小**: ~1KB。**读取频率**: 仅 `validate_required_columns()` 调用时(可缓存)。

**M4 合规**: factor_ic 读 `data_fetchers/result/factor_ic_data_columns.json` 是**读数据产物**,不是 `from data_fetchers import ...`。与 `factor_ic_data.json.gz` 同等地位。

---

## 4. 接口变更

### 4.1 新增文件

| 文件 | 职责 |
|------|------|
| `factor_ic/common/data_columns.py` | 标准列组常量 + schema 查询 + validate_required_columns |
| `factor_ic/common/factor_spec.py` | FactorSpec dataclass + FACTOR_REGISTRY + register_factor |
| `factor_ic/test_cases/test_data_columns.py` | data_columns 单测 |
| `factor_ic/test_cases/test_factor_spec.py` | FactorSpec 注册/校验单测 |

### 4.2 修改文件

| 文件 | 变更 |
|------|------|
| `data_fetchers/factor_generator.py` | `generate_all_factors()` 末尾新增写 `factor_ic_data_columns.json` |
| `factor_ic/common/factor_ic_runner.py` | 新增 `run_factor_ic(spec=SPEC, ...)` 入口(旧接口保留) |
| `factor_ic/common/exceptions.py` | 新增 `DataSchemaError` |
| `factor_ic/MODULE.md` | 新增 M3.3 FactorSpec 声明式注册规范 |
| 34 个 `ic_*.py` | 逐批迁移至 `SPEC = register_factor(FactorSpec(...))` + `run_factor_ic(spec=SPEC, ...)` |

### 4.3 FactorSpec dataclass 定义

```python
@dataclass(frozen=True)
class FactorSpec:
    """因子声明式注册规格。

    Attributes:
        factor_name: 因子名称(如 "amplitude_delta")
        factor_col: 因子列名(如 "amplitude_delta", 即 DataFrame 中的列名)
        required_columns: 需加载的原始因子列(含索引列 date/asset,替代旧 factor_cols 参数)
        calculation: 因子计算函数(None = 简单因子,直接从缓存读取)
        calc_params_fn: 从 CLI args 提取计算参数的函数 → dict
        extra_log_params_fn: 从 CLI args 提取启动横幅扩展参数的函数 → dict
    """
    factor_name: str
    factor_col: str
    required_columns: tuple[str, ...]
    calculation: Callable | None = None
    calc_params_fn: Callable | None = None
    extra_log_params_fn: Callable | None = None
```

### 4.4 register_factor 校验规则

| 规则 | 实现 | 异常 |
|------|------|------|
| `required_columns` 非空 | `if not spec.required_columns` | ValueError |
| `required_columns` 无重复 | `if len(set(...)) != len(...)` | ValueError |
| 全小写 + 下划线 | `all(c.islower() or c == '_' or c == '.' for c in col)` | ValueError |
| `factor_col` 在 `required_columns` 中 | `if spec.factor_col not in spec.required_columns` | ValueError |
| 不可覆盖注册 | `if spec.factor_name in FACTOR_REGISTRY` | ValueError |

### 4.5 run_factor_ic 新入口

```python
def run_factor_ic(
    spec: FactorSpec,
    *,
    return_period: str = "1d",
    min_stocks: int = 10,
    force_full: bool = False,
    args: Any | None = None,  # CLI args,供 calc_params_fn / extra_log_params_fn 提取
    _logger=None,
    **kwargs,
) -> dict[str, Any]:
    """FactorSpec 驱动的 IC 分析入口。"""
    # 提取参数
    custom_factor_calculation = spec.calculation
    custom_factor_calculation_params = spec.calc_params_fn(args) if spec.calc_params_fn and args else None
    extra_log_params = spec.extra_log_params_fn(args) if spec.extra_log_params_fn and args else None

    return run_factor_ic_analysis(
        factor_name=spec.factor_name,
        factor_col=spec.factor_col,
        factor_cols=list(spec.required_columns),
        return_period=return_period,
        min_stocks=min_stocks,
        force_full=force_full,
        custom_factor_calculation=custom_factor_calculation,
        custom_factor_calculation_params=custom_factor_calculation_params,
        extra_log_params=extra_log_params,
        _logger=_logger,
        **kwargs,
    )
```

**旧接口兼容**: `run_simple_factor_ic` / `run_complex_factor_ic` 不删除,标记 `# deprecated: use run_factor_ic(spec=SPEC, ...)` ,保留 2 个版本后再移除。

---

## 5. 实施步骤

### R3.1: 核心定义 + 单测(3-4h)

| Step | 内容 | 文件 |
|------|------|------|
| 1 | `DataSchemaError` 加入 exceptions.py | factor_ic/common/exceptions.py |
| 2 | `data_columns.py`: 标准列组常量 + validate_required_columns | factor_ic/common/data_columns.py |
| 3 | `factor_spec.py`: FactorSpec + register_factor + FACTOR_REGISTRY | factor_ic/common/factor_spec.py |
| 4 | 单测 | test_data_columns.py + test_factor_spec.py |
| 5 | ruff + pytest + commit | — |

### R3.2: 生产者 schema 清单(2-3h)

| Step | 内容 | 文件 |
|------|------|------|
| 1 | `generate_all_factors()` 末尾写 factor_ic_data_columns.json | data_fetchers/factor_generator.py |
| 2 | `data_columns.py` 新增 `load_available_columns()` | factor_ic/common/data_columns.py |
| 3 | 单测 + commit | — |

### R3.3: runner 新入口 + 集成(3-4h)

| Step | 内容 | 文件 |
|------|------|------|
| 1 | `run_factor_ic(spec=SPEC, ...)` 新入口 | factor_ic/common/factor_ic_runner.py |
| 2 | 旧接口标记 deprecated | factor_ic/common/factor_ic_runner.py |
| 3 | 集成 DataSchemaError 到数据加载路径 | factor_ic/common/data_loader.py |
| 4 | 单测 + commit | — |

### R3.4: 34 脚本迁移(拆 4 批,6-8h)

| 批 | 脚本数 | 分类 | 说明 |
|---|---|---|---|
| Batch 1 | 5 | 试点(含本会话原始 issue #5 脚本) | ic_amplitude_delta_1d / ic_amplitude_1d / ic_kdj_j_1d / ic_bollinger_pb_1d / ic_rsi_1d |
| Batch 2 | 10 | 简单因子(run_simple,无计算函数) | ic_return_3d / ic_return_5d / ic_overnight_ret 等 |
| Batch 3 | 10 | 复杂因子(run_complex,含计算函数) | ic_tail_* / ic_industry_* 等 |
| Batch 4 | 9 | 剩余 + delta 因子 | ic_tail_*_delta / ic_turnover_surge_delta 等 |

每批:迁移 → ruff → pytest → import smoke → commit

### R3.5: 规范 + 文档 + 全量验证(3-4h)

| Step | 内容 |
|------|------|
| 1 | MODULE.md 新增 M3.3 FactorSpec 声明式注册规范 |
| 2 | 流程文档同步(如有) |
| 3 | design.md 状态置 implemented |
| 4 | 全量验证: ruff + pytest + 抽样运行 + schema 校验 |

---

## 6. 验证清单

- [ ] `grep -rn 'factor_cols\s*=\s*\[' factor_ic/ic_*.py | wc -l` = 0 (38→0)
- [ ] `grep -rn 'register_factor' factor_ic/ic_*.py | wc -l` = 34 (每脚本 1 处)
- [ ] `pytest factor_ic/test_cases/test_factor_spec.py` 全过
- [ ] `pytest factor_ic/test_cases/test_data_columns.py` 全过
- [ ] `pytest factor_ic/test_cases/` 无回归(基线 234 passed)
- [ ] 抽样运行 3 脚本:JSON schema 与基线一致
- [ ] `factor_ic_data_columns.json` 存在且列数 = `_OUTPUT_COLS` 长度
- [ ] 故意改 `required_columns` 为不存在的列名 → DataSchemaError 含因子名 + 可用列

---

## 7. 回滚策略

每轮独立 commit,回滚粒度 = 1 轮。

- R3.1/R3.2: 纯新增文件,回滚 = 删文件
- R3.3: runner 新增入口,旧接口未删,回滚 = 删新函数
- R3.4: 每批独立 commit,回滚 = `git revert <commit>`
- R3.5: 规范文档,回滚 = 删 M3.3 章节

---

## 8. 风险与预案

| 风险 | 概率 | 影响 | 预案 |
|------|------|------|------|
| FactorSpec 冻结后需动态参数 | 中 | 改动 dataclass | `calc_params_fn` 已预留闭包;若不够则改为 `field(init=False)` 按需计算 |
| 跨脚本因子链(amplitude → amplitude_delta)上游改名 | 低 | DataSchemaError | L3 运行时校验会立即暴露;维护时改 `required_columns` 即可 |
| columns.json 与实际数据不同步(手动删除数据后未重跑 generator) | 低 | 校验假阳性 | validate_required_columns() 降级:json 不存在 → 仅 warn,不 block;由 DataSchemaError 的 data_loader 层兜底 |
| 旧接口长期不删 | 低 | 维护成本 | M3.3 规范约定 2 版本后移除;commit 搜索 `deprecated` 标记 |
| 34 脚本批量迁移 patch 风险 | 中 | fuzzy match 失败 | R1.2A-2 经验:≥24 文件用 Path.read_text/write_text 脚本化处理 |

---

## 9. 与现有规范的关系

| 规范 | 关系 |
|------|------|
| M1(模块边界) | `data_columns.py` 读 `factor_ic_data_columns.json`(数据产物),不违反 M4 |
| M2(公共模块复用) | FactorSpec 是公共模块,34 脚本统一注册 |
| M3(logger 传递) | 不变 |
| M3.1(日志函数 logger 必传) | 不变 |
| M3.2(启动日志收口) | `extra_log_params_fn` 替代直接传 `extra_log_params` 字典,横幅行为不变 |
| M4(跨目录禁止) | 读 json 数据 ≠ import Python 模块,合规 |
| M19-M23(异常处理) | DataSchemaError 继承 Exception,在 M21 主入口 `except Exception` 捕获范围内 |

---

## 10. 不做的事

| 项目 | 原因 |
|------|------|
| 运行时 schema 校验覆盖 data_loader 内部 | data_loader 已有 KeyError 校验,无需重复;DataSchemaError 在更上层(因子维度)提供上下文 |
| 让 `_OUTPUT_COLS` 变公有 | 跨目录(M4),且 `_` 前缀是 factor_generator 的内部实现;columns.json 是更好的公开接口 |
| 自动生成 FactorSpec | 34 脚本参数各异(计算函数/CLI 参数),手写声明比代码生成更可维护 |
| 修改 backtest/comprehensive_factor 的 data_loader | 不在本 issue 范围;它们的 `load_factor_return_data` 已有列校验 |
