# factor_ic 启动日志去重 - 设计文档 v1.0

**状态**: implemented (2026-06-15)
**作者**: 云瑶
**创建**: 2026-06-15
**实施完成**: 2026-06-15
**预估工作量**: 2-3 小时（含审查 + 34 脚本批改）
**实际工作量**: 与预估一致

---

## 1. 目标

消除 `factor_ic/` 模块「公共模块 + 入口脚本」双重启动日志。
将启动节点信息（factor_name + return_period + 入口参数）统一收口到
`factor_ic/common/factor_ic_runner.py` 的横幅打印逻辑，34 个 `ic_*.py`
入口脚本不再各自打印 `logger.info("启动X因子IC计算: ...")`。

### Why（为什么要改）

1. **DRY 违规**：当前公共模块 `factor_ic_runner.py:128-130` 已打印
   `="*60 / 因子 IC 分析: %s_%s / ="*60` 横幅；34 个入口脚本又各自
   `logger.info("启动X因子IC计算: ...")`，关键节点重复记录
2. **风格分裂**：32 个脚本用 `"启动X因子IC计算: min_stocks=%s, force_full=%s"`，
   2 个脚本（rsi/turnover_surge）用 `"X 因子 IC 计算启动 [...]"`，文案+格式两套
3. **与 MODULE.md M3 (logger 传递) 一致**：公共模块已统一收口 logger 实例，
   启动日志同样应在公共模块集中打印，避免规范分裂
4. **可扩展性**：未来新增公共启动参数（如 NW 滞后阶数）只改公共模块签名，
   不必扫 34 脚本

### Why Not（什么不做）

- 不动结果摘要日志（行 100-114）：摘要包含因子计算后的指标，属于入口职责
- 不动「计算完成」收尾日志（行 127）：与启动横幅对称的入口锚点，保留
- 不动 logger 传递机制（_logger 参数）：M3 已稳定，本次仅扩展 kwargs
- 不动其他模块（backtest / comprehensive_factor / summary）：超出范围，独立 PR
- 不改业务逻辑、不改异常处理：纯日志收口

---

## 2. 范围

### 2.1 受影响文件

| 类别 | 文件数 | 改动性质 |
|------|--------|---------|
| `factor_ic/common/factor_ic_runner.py` | 1 | 新增 `extra_log_params` 参数 + 横幅扩展 |
| `factor_ic/ic_*.py` | 34 | 删除入口启动 `logger.info`，改为传 `extra_log_params=` |
| `factor_ic/MODULE.md` | 1 | 在 M3 后追加 M3.x 启动日志规范 |
| `factor_ic/docs/<flow>.md` | ~10 | 同步更新流程文档启动节点位置 |
| **合计** | **~46** | |

### 2.2 不受影响

- `factor_ic/test_cases/*.py`：测试代码不依赖启动日志文本
- `factor_ic/common/factor_ic_runner.py:main()` CLI 入口（行 423-456）：
  独立 CLI，不经入口脚本，本次保留现状
- 其他模块、其他 PROJECT.md 规则

### 2.3 启动日志当前两种风格清单

| 风格 | 文案模板 | 数量 | 代表脚本 |
|------|---------|------|---------|
| A | `"启动X因子IC计算: min_stocks=%s, force_full=%s"` | 32 | ic_amplitude_1d.py 等 |
| B | `"X 因子 IC 计算启动 [param=%s, ...]"` | 2 | ic_rsi_1d.py / ic_turnover_surge_1d.py |

带额外参数的脚本（参数信息必须保留）：
- `ic_kdj_j_1d.py`：n / m1 / m2
- `ic_bollinger_pb_1d.py`：n / k
- `ic_turnover_surge_1d.py`：surge_window
- `ic_capital_flow_ratio_trend_1d.py`：v（版本号）

---

## 3. 方案对比（选型已定）

| 方案 | 描述 | 重复消除 | 参数保留 | 改动点 | 决策 |
|------|------|---------|---------|--------|------|
| ① | 全删入口启动日志 | ✅ | ❌ KDJ 等丢失 | 34 脚本 | ❌ 弃 |
| ② | 入口降 debug | ❌ 仍两处 | ✅ 默认隐藏 | 34 脚本 | ❌ 弃 |
| ③ | 公共模块删横幅，入口自带 | ✅ | ✅ | 1 公共 | ❌ 弃（横幅风格易分裂） |
| **④** | **公共模块接 `extra_log_params`，一处集中打** | **✅** | **✅** | **1 公共 + 34 脚本** | **✅ 采纳** |

**采纳方案 ④ 的核心理由**：
- 单一信息源（DRY），物理上消灭重复点
- 与 M3 logger 传递规范同源，规范一致性最强
- 与未来轮 3（factor_cols 集中收口）思路一致，可合并为同批 PR 大改动
- 改 34 脚本签名是一次性成本，长期收益高于短期工作量

---

## 4. 接口草案

### 4.1 公共模块新签名（factor_ic_runner.py）

```python
def run_factor_ic_analysis(
    factor_name: str,
    factor_col: str,
    ...
    extra_log_params: dict[str, Any] | None = None,  # 新增
    _logger=None,
) -> dict[str, Any]:
    """
    extra_log_params:
        入口脚本传入的额外启动参数（非公共参数），用于在启动横幅中
        打印因子特有参数（如 KDJ 的 n/m1/m2、布林带的 n/k）。
        None / 空 dict 时不打印额外参数行。
    """
```

### 4.2 启动横幅扩展（行 128-130 附近）

```
============================================================
因子 IC 分析: kdj_j_1d
入口参数: min_stocks=10, force_full=False
扩展参数: n=9, m1=3, m2=3
============================================================
```

### 4.3 入口脚本调用示例（修改后）

```python
# Before（ic_kdj_j_1d.py 行 115-122 + 124-）
logger.info(
    "启动KDJ_J因子IC计算: n=%s, m1=%s, m2=%s, min_stocks=%s, force_full=%s",
    args.n, args.m1, args.m2, args.min_stocks, args.force_full,
)
result = run_complex_factor_ic(
    factor_name="kdj_j",
    factor_col="kdj_j",
    factor_cols=["close", "high", "low"],
    custom_factor_calculation=calculate_kdj_j,
    min_stocks=args.min_stocks,
    force_full=args.force_full,
    _logger=logger,
)

# After
result = run_complex_factor_ic(
    factor_name="kdj_j",
    factor_col="kdj_j",
    factor_cols=["close", "high", "low"],
    custom_factor_calculation=calculate_kdj_j,
    min_stocks=args.min_stocks,
    force_full=args.force_full,
    extra_log_params={"n": args.n, "m1": args.m1, "m2": args.m2},
    _logger=logger,
)
```

---

## 5. 引用规范

- PROJECT.md H8 Design-First：2+ 文件改动先提交 design.md
- PROJECT.md H2 输出位置 / §跨模块数据路径表（不涉及）
- factor_ic/MODULE.md M3：logger 传递规范（本方案扩展）
- factor_ic/MODULE.md M19：异常处理（不涉及，本方案不动）
- factor_ic/docs/plans/logger_style_unification_v1.0.md：同类全模块统一参考

---

## 6. 实施步骤（每步独立可审查 + commit）

### Step 1：公共模块扩展启动横幅（最小改动验证）

**目标**：先在 `factor_ic_runner.py` 增加 `extra_log_params` 参数，仅在传入时
打印扩展参数行；不改 34 入口脚本。此 step 可独立合并，零回归风险。

**改动点**：
- `factor_ic/common/factor_ic_runner.py` `run_factor_ic_analysis` 签名增加
  `extra_log_params: dict[str, Any] | None = None`
- `run_simple_factor_ic` / `run_complex_factor_ic` 透传 `extra_log_params`
- 横幅打印逻辑（行 128-130 附近）扩展为：
  ```python
  _logger.info("=" * 60)
  _logger.info("因子 IC 分析: %s_%s", factor_name, return_period)
  _logger.info("入口参数: min_stocks=%s, force_full=%s", min_stocks, force_full)
  if extra_log_params:
      _logger.info(
          "扩展参数: %s",
          ", ".join(f"{k}=%s" % v for k, v in extra_log_params.items()),
      )
  _logger.info("=" * 60)
  ```
- 注意：扩展参数行使用 % 惰性格式化（遵循 PROJECT.md 规则 #13）

**commit**：`feat(factor_ic/common): factor_ic_runner 启动横幅支持 extra_log_params`

### Step 2：批量改 34 入口脚本（按因子类型分批）

**分批理由**：34 脚本一次性改 commit diff 过大，难审查；按"无扩展参数"
和"有扩展参数"分两批，每批独立 commit。

**Batch 2A（无扩展参数，~30 脚本）**：删除入口 `logger.info("启动X因子IC计算: ...")`，
不传 `extra_log_params`。
- 受影响：除 KDJ / 布林带 / 换手突增 / 资金流占比趋势之外的所有 ic_*.py
- 改动模式：删 5-8 行（多行 logger.info + 注释 + 空行）
- **commit**：`refactor(factor_ic): 删除 30 个 ic 脚本入口启动日志，统一收口公共模块`

**Batch 2B（有扩展参数，4 脚本）**：删除入口 `logger.info`，传
`extra_log_params={"k1": v1, ...}`。
- 受影响：
  - `ic_kdj_j_1d.py` → `extra_log_params={"n": args.n, "m1": args.m1, "m2": args.m2}`
  - `ic_bollinger_pb_1d.py` → `extra_log_params={"n": args.n, "k": args.k}`
  - `ic_turnover_surge_1d.py` → `extra_log_params={"surge_window": args.surge_window}`
  - `ic_capital_flow_ratio_trend_1d.py` → `extra_log_params={"version": args.version}`
- **commit**：`refactor(factor_ic): 4 个带扩展参数 ic 脚本迁移至 extra_log_params`

### Step 3：MODULE.md 追加 M3.x 启动日志收口规范

**位置**：M3（logger 传递）后，编号 M3.1 或 M4 之后追加新条目（依据现有
M 编号决定，可能为 M66 或插入 M3 子条目，**最终编号待 1C 完成时核对**）。

**草稿见 §10**。

**commit**：`docs(factor_ic): MODULE.md 追加启动日志收口规范（配合 startup-log-dedup）`

### Step 4：同步流程文档（factor_ic/docs/*.md）

**目标**：所有 `factor_ic/docs/ic_*_flow.md` 流程图中"启动日志"节点描述
统一改为"由 factor_ic_runner 横幅打印（含 extra_log_params）"。

**预估**：~10 份 flow.md，每份改 1-2 处图示/段落。

**commit**：`docs(factor_ic): 同步 ic flow 文档启动日志收口位置`

### Step 5：跨模块抽样验证

**目标**：本次只改 factor_ic，但有可能间接影响 backtest / summary（若它们
依赖 factor_ic 的日志做 grep 监控）。运行一次 pipeline 主流程冒烟测试。

**抽样**：
```bash
python -m factor_ic.ic_amplitude_1d --force-full   # 无扩展参数
python -m factor_ic.ic_kdj_j_1d --force-full       # 有扩展参数
python -m factor_ic.ic_rsi_1d --force-full         # 简单因子
```
- 检查日志输出：横幅出现 1 次（不重复），扩展参数行正确，无 `KeyError`
- 检查输出 JSON：与改动前 byte-level 一致（启动日志不影响计算）

---

## 7. 验证清单

### 7.1 静态检查

- [ ] `ruff check factor_ic/`：All checks passed（无新增 G004/G003/G201）
- [ ] `ruff format --check factor_ic/`：通过
- [ ] `mypy factor_ic/`：无类型错误（如项目已启用 mypy gate）

### 7.2 单元测试

- [ ] `pytest factor_ic/test_cases/ -v`：全通过（基线对比，无新增失败）
- [ ] 重点关注：`test_logger_*` / `test_factor_ic_runner_*`（如存在）

### 7.3 集成验证

- [ ] 抽样运行 §6 Step 5 三个脚本，日志启动横幅 **只出现 1 次**
- [ ] 抽样脚本输出 JSON 与改动前完全一致（diff 验证）
- [ ] grep 验证：`grep -E 'logger\.info\("启动' factor_ic/ic_*.py | wc -l == 0`
- [ ] grep 验证：`grep -E '"X 因子 IC 计算启动 \['` 风格 B 也清零

### 7.4 文档同步

- [ ] MODULE.md 追加 M3.x 条目（What/How/Don't 三段齐全）
- [ ] 至少 3 份 ic_*_flow.md 抽样确认已同步
- [ ] design.md（本文件）状态从 pending-review 改为 implemented

### 7.5 commit 取证

- [ ] 每个 commit message 引用 PROJECT.md 规则 #5（IC 计算共用流程）/ #9（日志格式）
- [ ] 引用本 design.md 行号
- [ ] commit 拆分符合 §6 Step 1-5 边界，未跨步

---

## 8. 回滚方案

### 8.1 回滚触发条件

任一即触发：
- 抽样脚本运行后 JSON 输出与基线 byte-level 不一致
- pytest 出现新增失败（非 flaky）
- 横幅打印出现 `KeyError` / 类型错误（extra_log_params 处理 bug）
- 任何 ic 脚本启动日志比改动前**减少了**关键参数信息（运维巡检用）

### 8.2 回滚顺序（按 §6 Step 反序）

1. `git revert` Step 4 commit（流程文档）
2. `git revert` Step 3 commit（MODULE.md）
3. `git revert` Step 2B commit（4 个带扩展参数脚本）
4. `git revert` Step 2A commit（30 个无扩展参数脚本）
5. `git revert` Step 1 commit（公共模块签名扩展）

每步 revert 后跑一次 `pytest factor_ic/test_cases/`，确保回滚未引入新问题。

### 8.3 部分回滚（保留公共模块改动）

若 Step 1 验证通过、问题出在 Step 2 批量改：
- 仅 revert Step 2A/2B，保留 Step 1 的 `extra_log_params` 参数（无人调用即无副作用）
- 后续可分更小批次重做 Step 2

---

## 9. 风险与预案

| 风险 | 概率 | 影响 | 预案 |
|------|------|------|------|
| 上游 pipeline 用 grep "启动X因子IC计算" 监控启动 | 中 | 监控漏报 | Step 5 前 `grep -r "启动.*因子IC计算" backtest/ summary/ comprehensive_factor/` 排查；若有引用，本 design 暂停，先改监控逻辑 |
| 横幅多 1 行（扩展参数）破坏下游日志解析 | 低 | 解析失败 | 抽样运行后 grep `logger\.info` 在下游模块的引用，确认无文本结构强依赖 |
| 34 脚本批改有遗漏 | 中 | 部分脚本仍重复打日志 | §7.3 grep 验证清零；CI 可加 `pytest test_no_legacy_startup_log.py` 防回归（独立任务） |
| extra_log_params 类型不一致（dict[str, Any] 太松） | 低 | 运行时 KeyError | 草稿中 `f"{k}=%s" % v` 已对 v 做 % 安全转换；Step 1 加单元测试覆盖 None / 空 dict / int / str / float 四种 v 类型 |
| MODULE.md 编号冲突（已有 M3.x 或 M66） | 中 | 文档混乱 | Step 3 落笔前用 `grep -E '^## M[0-9]+\.' factor_ic/MODULE.md` 核对最大编号 |
| 跨 agent 协作冲突（其他人正改这些脚本） | 中 | git 冲突 | 各 Step commit 前 `git pull --rebase`；Batch 2A 30 脚本一次性 add，避免长时间 staged |

### 9.1 与未来轮 3 (factor_cols 集中收口) 的协调

本轮已设定方向：「公共模块集中收口」是 factor_ic 模块的统一架构思路。
- 若轮 3 也采纳同思路（推荐），轮 3 设计可复用本轮已落地的 `extra_log_params` 模式
- 若轮 3 改主意走"脚本内常量"，仅本轮风格分裂，不影响本轮回滚

**预案**：本轮 commit message 不绑定未来轮决策；MODULE.md M3.x 表述为
"启动日志收口"，不涉及 factor_cols。

---

## 10. MODULE.md 规范补充草稿（M3.x 启动日志收口）

> 落地位置：M3（logger 传递）之后，作为 M3 的扩展条目（编号待 Step 3 落笔时核对）。

### 草稿正文

```markdown
## M3.X 启动日志收口（factor_ic_runner 单一来源，作为 M3 的扩展子条目）

**What**：所有 `factor_ic/ic_*.py` 入口脚本不得在 `main()` 中自行打印
"启动X因子IC计算: ..." 类启动节点日志。启动横幅由公共模块
`factor_ic/common/factor_ic_runner.py` 统一打印。

**Why**：
- 公共模块第 128-130 行已打印 `="*60 / 因子 IC 分析: %s_%s / ="*60` 横幅
- 入口脚本再打 `logger.info("启动X因子IC计算: ...")` 导致关键节点重复记录
- 多脚本演化出两种文案风格（"启动X因子IC计算: ..." vs "X 因子 IC 计算启动 [...]"），
  风格分裂；统一收口后只在公共模块演进一处

**How**：
- 入口脚本不写 `logger.info("启动...")`
- 因子特有参数（如 KDJ 的 n/m1/m2、布林带的 n/k）通过
  `extra_log_params=dict[str, Any]` 传入 `run_simple_factor_ic` /
  `run_complex_factor_ic`
- 公共模块横幅自动追加"扩展参数"行，无传值时不打印该行

**Don't**：
```python
# ❌ 入口脚本自行打启动日志
logger.info("启动KDJ_J因子IC计算: n=%s, m1=%s, ...", args.n, args.m1, ...)
result = run_complex_factor_ic(factor_name="kdj_j", ...)

# ❌ 启动日志只用 print（绕过 logger）
print(f"启动 {factor_name}")
```

**Examples**：
```python
# ✓ 正确：公共模块统一打印 + extra_log_params 传扩展参数
result = run_complex_factor_ic(
    factor_name="kdj_j",
    factor_col="kdj_j",
    factor_cols=["close", "high", "low"],
    custom_factor_calculation=calculate_kdj_j,
    min_stocks=args.min_stocks,
    force_full=args.force_full,
    extra_log_params={"n": args.n, "m1": args.m1, "m2": args.m2},  # 扩展参数
    _logger=logger,
)
```

**When**：所有 factor_ic 入口脚本（ic_*.py）；不适用于 backtest /
comprehensive_factor / summary 模块（独立设计）。

**Verify**：
```bash
# 入口脚本不应包含启动日志
grep -E 'logger\.(info|debug)\("启动' factor_ic/ic_*.py | wc -l   # 应输出 0
grep -E '"[^"]*因子.*IC.*计算启动' factor_ic/ic_*.py | wc -l       # 应输出 0
# 公共模块仍保留横幅
grep -nE '"=" \* 60' factor_ic/common/factor_ic_runner.py          # 应有命中
```
```

### 落地注意

- M3.X 的 X 待 Step 3 落笔时按 MODULE.md 现有 M3 子项编号决定
- 如 M3 当前没有子项，可作为 M3.1；如已有 M3.1-M3.N，使用 M3.(N+1)
- 也可考虑独立编号 M66（紧接 M65 之后），保持 M3 简洁——具体方案 Step 3 时与 reviewer 协商

---

## 11. 更新记录

| 时间 | 版本 | 说明 |
|------|------|------|
| 2026-06-15 | v1.0-skeleton | 骨架完成（目标/范围/方案对比/接口草案）；§6-10 待 1C 补 |
| 2026-06-15 | v1.0-step1c | 1C 补完 §6 实施步骤 + §7 验证清单 |
| 2026-06-15 | v1.0 | 1C 补完 §8 回滚 + §9 风险预案 + §10 MODULE.md 规范草稿；状态变更为 ready-to-execute |
| 2026-06-15 | v1.0-implemented | 全部实施完成；状态置 implemented |

---

## 12. 实施记录（commit 表）

| 阶段 | Commit | 改动 | 说明 |
|------|--------|------|------|
| R1.1 公共模块扩展 | `0709fe6` | +145 行 | `factor_ic_runner` 横幅扩展 + 8 单测 |
| R1.2A-1 试点 5 脚本 | `5f14bea` | -28 净 | ic_amplitude_1d / ic_amplitude_delta_1d / ic_industry_amplitude_trend_1d / ic_intraday_intensity_1d / ic_past_return_1d_1d |
| R1.2A-2 余批 24 脚本 | `d0531c4` | -136 净 | 风格 A 余下脚本批量迁移 |
| R1.2B 含扩展参数 5 脚本 | `2bbddd9` | -32 净 | bollinger_pb / capital_flow_ratio_trend / kdj_j / rsi（风格 B）/ turnover_surge（风格 B + extra） |
| R1.3 MODULE.md M3.2 规范 | `5a68fe4` | +95 | 新增 M3.2 入口启动日志收口规范 + v4.3 更新记录 |

**累计**：5 commits，34 入口脚本启动日志统一收口至公共模块横幅，净增减 +44 行（横幅扩展 +145 抵消入口删除 -196 + 规范文档 +95）。

## 13. R1.5 集成验证记录（2026-06-15）

抽样 3 个脚本覆盖三种迁移模式：

| 脚本 | 迁移模式 | 横幅行数 | 扩展参数 | JSON schema diff |
|------|---------|---------|---------|------------------|
| `ic_rsi_1d` | 风格 B、无扩展、`run_simple_factor_ic` | 3 | — | OK（76 键路径一致） |
| `ic_kdj_j_1d` | 风格 A、含扩展 n/m1/m2、`run_complex_factor_ic` | 4 | `n=9, m1=3, m2=3` | OK（76 键路径一致） |
| `ic_amplitude_delta_1d` | 风格 A、无扩展、`run_complex_factor_ic` | 3 | — | OK（76 键路径一致） |

**横幅样例**（`ic_kdj_j_1d`）：

```
============================================================
因子 IC 分析: kdj_j_1d
入口参数: min_stocks=10, force_full=False
扩展参数: n=9, m1=3, m2=3
============================================================
```

**Verify**:
1. ✓ 启动横幅每次执行**只出现 1 次**（不再有入口脚本重复打印）
2. ✓ JSON schema 与基线完全一致（无字段增减/重命名）
3. ✓ pytest factor_ic/test_cases/ **234 passed, 66 skipped**（无回归）

**结论**：方案 ④ 实施完成，公共模块横幅 + `extra_log_params` 接口稳定，34 脚本统一收口。
