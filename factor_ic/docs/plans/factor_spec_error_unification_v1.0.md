# FactorSpec 错误统一化设计 v1.0

> 涉及范围：1 个公共模块 + 1 个规范文档 + 17 个 ic_*.py + 1 个守门脚本
> 起因：用户提出 `factor_ic/ic_industry_momentum_5d_1d.py` 7 个 issue，按 H8 必须先对齐
> 跨度：21 文件 ≫ H9 阈值（≤3 文件 / ≤200 行），强制 Design-First

## 目录

- §1 背景与目标
- §2 Issue 清单与影响面映射
- §3 决策矩阵
- §4 公共模块改动（factor_spec.py）
- §5 H12 退出码档扩展（PROJECT.md + check_exit_codes.py）
- §6 momentum_5d 单文件落地映射
- §7 16 文件扩散范围与节奏
- §8 验证策略
- §9 风险与回滚

---

## §1 背景与目标

R17 落地后（commit `1ca728a` ~ `dde8909`），17 个 ic_*.py 已统一 `log_factor_summary` 失败 → `sys.exit(3)` 模式，但仍存在 7 类残留缺陷（issue 1-7），均集中在「错误处理 + 退出码语义」边界：

- 模块顶层 except 捕获范围过窄（issue 1）
- main() 内残留 `sys.exit`，破坏单元测试边界（issue 2）
- 业务异常 DataSchemaError / FactorCalcError / 通用 Exception 共用 exit 1，调度器无法差异化（issue 3）
- `register_factor` 失败上下文丢失 factor_name（issue 4）
- main() 职责过载（issue 5）
- DataSchemaError / FactorCalcError 分支用 `logger.error` 丢 traceback（issue 6/7）

**目标**：一次性把以上 7 个 issue 在 momentum_5d 单文件落地，并把"必须扩散"的部分（issue 1 + issue 4 公共模块基建）扩散到其余 16 个 ic_*.py，建立长期可守门的语义统一。

---

## §2 Issue 清单与影响面映射

| # | 描述 | 修复层级 | 涉及文件 | 是否扩散到 16 文件 |
|---|---|---|---|---|
| 1 | except (ValueError, TypeError) 范围过窄 | 公共模块 + 单文件 + 扩散 | factor_spec.py + 17 ic_*.py | ✅ 必须（issue 4 联动） |
| 2 | main() 内 sys.exit(3) 杀测试宿主 | 单文件 | momentum_5d.py | ⏸ 由 R3 后用户决策 |
| 3 | DataSchemaError / FactorCalcError 共用 exit 1 | 规范 + 单文件 | PROJECT.md + check_exit_codes.py + momentum_5d.py | ⏸ 由 R3 后用户决策 |
| 4 | register_factor 失败丢失 factor_name 上下文 | 公共模块 | factor_spec.py | ✅ 公共模块自动覆盖 17 文件 |
| 5 | main() 职责过载（解析 + 编排 + 退出码） | 单文件 | momentum_5d.py | ⏸ 由 R3 后用户决策 |
| 6 | FactorCalcError 用 logger.error 丢 traceback | 单文件 | momentum_5d.py | ⏸ 由 R3 后用户决策 |
| 7 | DataSchemaError 用 logger.error 丢 traceback | 单文件 | momentum_5d.py | ⏸ 由 R3 后用户决策 |

**扩散判断原则**：
- issue 1 + 4 是公共模块改动，自动作用于所有 ic_*.py，扩散成本 = 0（仅需把 17 个文件的 `except (ValueError, TypeError)` 收窄为 `except SpecRegistrationError`）
- issue 2/3/5/6/7 涉及 main() 和 __main__ 块结构性重构，单文件改动量 ~30 行，17 文件 = ~500 行，超 H9 单轮阈值，必须分批且需用户在 R3 后决策是否启动扩散

---

## §3 决策矩阵

### §3.1 issue 4 范围（用户已选 B）

用户已通过 clarify 选择 **B 方案**：公共模块 + momentum_5d + 同步扩散到 16 个 ic_*.py，一次彻底统一。

**实现路径**：
1. `factor_spec.py` 新增 `SpecRegistrationError(ValueError)`（继承 ValueError 保证向后兼容）
2. `register_factor` 内部把所有异常包装为 `SpecRegistrationError`（含 factor_name）
3. 17 个 ic_*.py 把 `except (ValueError, TypeError)` 收窄为 `except SpecRegistrationError`
4. 因 SpecRegistrationError 是 ValueError 子类，旧的 `except ValueError` 仍能 catch，扩散过程零中断

### §3.2 issue 3 退出码档（用户超时，按上下文锁定 D）

issue 3 描述明确："调度器无法据此做差异化处理" → 必须新增独立 exit 码。  
用户选项：
- A：与现有 H12 冲突，**不可行**
- B：拉到 10+ 区间，**避免冲突但偏离现有档**
- C：判 issue 3 为伪问题不修，**与 issue 3 描述自相矛盾**
- **D：扩展 H12 引入 exit 4 / exit 5**（与 R17 设计哲学一致 — 按"排查路径"差异化退出码）

**锁定 D 方案**理由：
- 用户分歧 1 选 B 表明偏好彻底统一方案
- R17 已建立"按排查路径区分 exit 码"先例（exit 3 = 主结果可用，仅 sidecar 失败）
- exit 4 = DataSchemaError = 数据 schema 不匹配，排查路径 = 上游数据/列契约
- exit 5 = FactorCalcError = 因子计算内部失败，排查路径 = 计算代码/边界条件
- exit 1 = 通用 Exception = 未预期错误，排查路径 = 程序 bug

### §3.3 issue 2 解法（main 内禁 sys.exit）

main() 内 `sys.exit(3)` 杀测试宿主，违反"main 应可被单元测试直接调用"原则。

**解法**：定义 `SummaryLogError(Exception)`，main() 内 `raise SummaryLogError` 替代 `sys.exit(3)`，__main__ 块捕获后转 sys.exit(3)。

**异常归属**：放 `factor_ic/common/exceptions.py`（已有 DataSchemaError / FactorCalcError 同居该文件，结构一致）。

### §3.4 issue 5 解法（main 职责拆分）

main() 拆为：
- `parse_args()`：参数解析
- `main(args)`：流程编排（run_factor_ic + log_factor_summary），抛异常不退出
- `if __name__ == "__main__"`：唯一退出码控制中心

### §3.5 issue 6/7 解法（logger.exception 对称）

`logger.error("...%s", e)` → `logger.exception("...")`：H11 禁 `exc_info=True`，但 `logger.exception` 是 H11 推荐写法（自动附 exc_info=True，由日志库内部处理，不算 H11 违规）。

**H11 与 logger.exception 的边界已在 PROJECT.md 明确**：H11 禁的是「显式传 `exc_info=True` 参数」，`logger.exception` 是合规惯用法。

---

## §4 公共模块改动（factor_spec.py）

### §4.1 新增 SpecRegistrationError

```python
class SpecRegistrationError(ValueError):
    """register_factor 注册失败专用异常。

    继承 ValueError 保证向后兼容（旧 `except ValueError` 仍可 catch）。
    携带 factor_name 上下文供扫描层（test_factor_spec_consistency.py）定位故障因子。

    Attributes:
        factor_name: 注册失败的因子名（用于 importlib 批量扫描时聚合错误）
    """

    def __init__(self, factor_name: str, message: str) -> None:
        self.factor_name = factor_name
        super().__init__(f"FactorSpec({factor_name}) 注册失败: {message}")
```

### §4.2 register_factor 包装层

```python
def register_factor(spec: FactorSpec) -> FactorSpec:
    """注册因子规格到全局注册表，并执行 L2 校验。

    Raises:
        SpecRegistrationError: 校验失败或注册期任何异常（含 factor_name 上下文）
    """
    try:
        _validate_spec(spec)
    except ValueError as e:
        # _validate_spec 抛 ValueError → 包装为 SpecRegistrationError 附 factor_name
        # 已含 factor_name 信息但用统一类型对外暴露
        raise SpecRegistrationError(spec.factor_name, str(e)) from e
    except Exception as e:
        # 防御 L2 校验流程中任何意外异常（AttributeError/RuntimeError/...）
        raise SpecRegistrationError(spec.factor_name, f"意外错误 ({type(e).__name__}): {e}") from e

    FACTOR_REGISTRY[spec.factor_name] = spec
    return spec
```

### §4.3 测试用例

`factor_ic/test_cases/test_factor_spec.py` 新增：
- `test_register_factor_value_error_wrapped`：触发重复注册 → 验证 raise SpecRegistrationError 且 `e.factor_name == "industry_xxx"`
- `test_spec_registration_error_is_value_error`：`isinstance(e, ValueError) is True`（向后兼容契约）
- `test_register_factor_unexpected_error_wrapped`：mock _validate_spec 抛 AttributeError → 验证仍包装为 SpecRegistrationError

---

## §5 H12 退出码档扩展（PROJECT.md + check_exit_codes.py）

### §5.1 H12 档（扩展后）

| Exit Code | 语义 | 排查路径 | 主结果产物 |
|---|---|---|---|
| 0 | 完全成功 | — | 可用 |
| 1 | 未预期错误（程序 bug） | 检查代码 | 不可用 |
| 2 | (R16 弃用) | — | — |
| 3 | 辅助层失败（R17，主结果可用，sidecar 失败） | 检查日志/监控/sidecar | 可用 |
| **4** | **DataSchemaError（R18，数据 schema 不匹配）** | **检查上游数据 / 列契约** | **不可用** |
| **5** | **FactorCalcError（R19，因子计算内部失败）** | **检查计算代码 / 边界条件** | **不可用** |

### §5.2 main() 内禁 sys.exit（R20）

新增规则 **R20**：`main()` 函数体内禁止 `sys.exit`，必须 `raise <具名异常>` 让 `__main__` 块统一处理退出码。

理由：main() 应可被单元测试直接调用，sys.exit 会杀测试宿主进程。

### §5.3 check_exit_codes.py 适配

当前脚本（L135）只允许 __main__ except 中 `sys.exit(1)`，需扩展白名单：
- DataSchemaError 分支允许 `sys.exit(4)`
- FactorCalcError 分支允许 `sys.exit(5)`
- 通用 Exception 分支允许 `sys.exit(1)`
- SummaryLogError 分支允许 `sys.exit(3)`
- 其他自定义具名异常 → 由 except 异常类名映射决定允许的 exit 码

**实现策略**：在 _check_file 中增加"按 except 异常类名 → 允许的 exit 码"映射表（dict），异常类名匹配则用映射值，否则回退默认 RUNTIME_EXIT_CODE=1。

R20 检查：扫描 `def main(` 函数体内的 sys.exit 调用，发现即报违规。

---

## §6 momentum_5d 单文件落地映射

### §6.1 改动清单（issue 1-7 → 代码段）

| 改动段 | 当前状态 | 目标状态 | 涉及 issue |
|---|---|---|---|
| 文件头 import | `from factor_ic.common.exceptions import DataSchemaError, FactorCalcError` | + `SummaryLogError`（新增） + `from factor_ic.common.factor_spec import SpecRegistrationError` | 1, 2, 4 |
| 模块顶层 except (L53) | `except (ValueError, TypeError) as e:` | `except SpecRegistrationError as e:` | 1 |
| 模块顶层 logger.critical | `"FactorSpec 注册失败 (factor=industry_momentum_5d): %s (%s)..."` | `"FactorSpec 注册失败: %s ..."`（factor_name 已在异常对象内） | 4 |
| main() (L73) | 单一函数 | 拆为 `parse_args()` + `main(args)` | 5 |
| main() 内 try/except (L124-131) | `except Exception: ... sys.exit(3)` | `except Exception as e: raise SummaryLogError(...) from e` | 2 |
| __main__ DataSchemaError (L145-150) | `logger.error("...%s", e); sys.exit(1)` | `logger.exception("..."); sys.exit(4)` | 3, 7 |
| __main__ FactorCalcError (L151-153) | `logger.error("...%s", e); sys.exit(1)` | `logger.exception("..."); sys.exit(5)` | 3, 6 |
| __main__ SummaryLogError（新增分支） | — | `logger.exception("..."); sys.exit(3)` | 2, 3 |
| __main__ Exception (L154-156) | `logger.exception("未预期的错误"); sys.exit(1)` | 保持不变 | — |

### §6.2 目标代码骨架

```python
# 模块顶层
from factor_ic.common.exceptions import DataSchemaError, FactorCalcError, SummaryLogError
from factor_ic.common.factor_spec import FactorSpec, SpecRegistrationError, register_factor

try:
    SPEC = register_factor(FactorSpec(...))
except SpecRegistrationError as e:
    logger.critical("FactorSpec 注册失败: %s", str(e)[:200])
    raise


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="行业5日动量因子 IC 计算器")
    parser.add_argument("--force-full", action="store_true", help="强制全量计算")
    parser.add_argument("--min-stocks", type=int, default=DEFAULT_MIN_STOCKS, help="最小股票数")
    return parser.parse_args()


def main(args: argparse.Namespace) -> dict:
    """流程编排：抛异常但不退出。退出码由 __main__ 统一处理。"""
    logger.info("启动 run_factor_ic: factor=%s min_stocks=%d force_full=%s",
                SPEC.factor_name, args.min_stocks, args.force_full)
    result = run_factor_ic(spec=SPEC, min_stocks=args.min_stocks,
                           force_full=args.force_full, _logger=logger)
    try:
        log_factor_summary(result, "行业5日动量因子", logger)
    except Exception as e:
        # R20: main() 内禁 sys.exit，改 raise SummaryLogError 让 __main__ 处理 exit 3
        raise SummaryLogError(
            "log_factor_summary 摘要输出阶段失败（result 已生成；故障源 = 摘要日志层）"
        ) from e
    return result


if __name__ == "__main__":
    try:
        main(parse_args())
    except DataSchemaError:
        logger.exception("行业5日动量因子IC计算失败 (数据列依赖不匹配)")
        sys.exit(4)  # H12 R18: schema 失败 → 检查上游数据
    except FactorCalcError:
        logger.exception("行业5日动量因子IC计算失败")
        sys.exit(5)  # H12 R19: 因子计算失败 → 检查计算代码
    except SummaryLogError:
        logger.exception("摘要日志层失败（主结果产物已生成，可用）")
        sys.exit(3)  # H12 R17: 辅助层失败
    except Exception:
        logger.exception("未预期的错误")
        sys.exit(1)
```

---

## §7 16 文件扩散范围与节奏

### §7.1 扩散内容（仅 issue 1）

把 16 个 ic_*.py 中：
```python
except (ValueError, TypeError) as e:
```
改为：
```python
except SpecRegistrationError as e:
```

并在 import 段加 `SpecRegistrationError`，logger.critical 简化（去 factor=xxx 重复，已含异常对象内）。

### §7.2 不扩散内容（issue 2/3/5/6/7）

issue 2/3/5/6/7 涉及 main() 重构、退出码差异化、logger.exception 改写——单文件 ~30 行 × 16 = ~480 行，超 H9 单轮阈值。

**节奏**：R3 momentum_5d 完成后**告知用户**，由用户决定是否启动扩散（同 R17 后用户授权 R17 扩散的模式）。

### §7.3 扩散批次

参考 R17 节奏，4 文件/组 × 4 轮：

| 轮 | 文件数 | 内容 |
|---|---|---|
| R4.1 | 4 | 行业 trend：amplitude/earnings_growth/pe/roe |
| R4.2 | 4 | 行业 turnover_trend + momentum_5d 已在 R3、past_return + return_5d |
| R4.3 | 4 | amplitude_delta/capital_flow_intensity/volume_ratio/volume_price_strength |
| R4.4 | 4 | tail_price_position_delta/tail_price_slope/tail_volume_shrink/tail_volume_shrink_delta + turnover_surge_delta |

每轮：批量 patch → ruff + check_exit_codes + pytest → 1 commit。

---

## §8 验证策略

### §8.1 公共模块验证（R1）

```bash
pytest factor_ic/test_cases/test_factor_spec.py -v
```

新增 3 个测试覆盖 SpecRegistrationError 包装行为、向后兼容、意外异常防御。

### §8.2 H12 守门验证（R2）

```bash
python scripts/check_exit_codes.py all   # 适配后必须仍 ✓ 全过
pytest scripts/test_check_exit_codes.py  # 新增用例覆盖 exit 4/5/main内禁sys.exit
```

### §8.3 momentum_5d 端到端验证（R3）

参考 R17 模式，mock 4 种异常路径：

```python
# 路径 1：DataSchemaError → exit 4
mock.patch('factor_ic.common.factor_ic_runner.run_factor_ic',
           side_effect=DataSchemaError(...))
# 路径 2：FactorCalcError → exit 5
mock.patch('factor_ic.common.factor_ic_runner.run_factor_ic',
           side_effect=FactorCalcError(...))
# 路径 3：log_factor_summary 失败 → exit 3
mock.patch('factor_ic.common.factor_summary_logger.log_factor_summary',
           side_effect=RuntimeError(...))
# 路径 4：通用 Exception → exit 1
mock.patch('factor_ic.common.factor_ic_runner.run_factor_ic',
           side_effect=KeyError(...))
```

### §8.4 全局回归

```bash
pytest factor_ic/test_cases/ scripts/ -q   # 基线 296 passed / 66 skipped
ruff check $(git diff --name-only <prev> HEAD)  # 本次涉及文件全过
```

---

## §9 风险与回滚

### §9.1 风险

| 风险 | 等级 | 缓解 |
|---|---|---|
| SpecRegistrationError 改变 register_factor 异常类型 → 破坏现有调用方 | 中 | 继承 ValueError，旧 `except ValueError` 仍能 catch |
| H12 扩展 exit 4/5 与现有 CI/调度脚本冲突 | 低 | 仅 momentum_5d 落地新 exit 码；扩散前用户决策 |
| check_exit_codes.py 改写导致存量 16 文件 sys.exit(1) 误判 | 中 | 先在 R2 用映射表保持回退默认值 = 1，确保所有 17 文件全过 |
| logger.exception 与 H11 冲突 | 低 | logger.exception 不属于 H11 禁的 exc_info=True，已在 §3.5 明确 |
| main(args) 接受参数后破坏旧调用 | 低 | momentum_5d 只在 __main__ 调用，无第三方调用方 |

### §9.2 回滚单元

按 commit 粒度回滚：
- R1 失败 → revert R1 单 commit
- R2 失败 → revert R2 单 commit（不影响 R1）
- R3 失败 → revert R3 单 commit（保留 R1/R2 公共基建）
- R4.x 失败 → 单组 revert，其他组不受影响

每轮独立 commit + 独立验证保证回滚最小爆炸半径。

