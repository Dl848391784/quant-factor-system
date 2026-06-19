# factor_ic 模块 logger 风格统一 - 设计文档 v1.0

**状态**: pending-review
**作者**: 云瑶
**创建**: 2026-06-15
**预估工作量**: 1-2 小时（含审查）

---

## 1. 目标

将 `factor_ic/` 模块所有 `logger.*(f"...")` / `logger.*(.. + ..)` 风格的日志调用，
统一改为 `logger.*("...", arg1, arg2)` 的 **% 惰性格式化** 风格，并通过 ruff 规则 G004/G003/G201 防回归。

### Why（为什么要改）

1. **性能**：日志级别未启用时，% 惰性格式化跳过字符串拼接（ruff G004 官方理由）
2. **风格一致**：`ic_tail_price_position.py` v1.3 已采用此风格，需要扩展到全模块；当前 49 个文件 219 处违规
3. **防回归**：启用 ruff G 规则后，新增 f-string 日志会被 lint 拦截
4. **历史教训**：本文件用户偏好"项目其他日志均使用 % 格式化"——但实际全模块当前并不一致，
   本次是把"假设"变成"事实"

### Why Not（什么不做）

- 不动 `data_fetchers/`、`backtest/`、`comprehensive_factor/`、`summary/`：超出本次范围，
  应该作为独立 PR 推进（避免单 commit 跨太多模块）
- 不改业务逻辑、不重构日志内容：纯格式风格转换
- 不动测试 mock 字符串（不是 logger 调用）

---

## 2. 范围

### 2.1 受影响文件（factor_ic/ 内）

| 类别 | 文件数 | 违规处数 |
|---|---|---|
| `factor_ic/ic_*.py` | 31 | ~155 |
| `factor_ic/common/*.py` | 8 | ~64 |
| **合计** | **39** | **~219**（G004:186 + G003:32 + G201:1）|

### 2.2 不受影响

- `factor_ic/test_cases/*.py`：测试代码不涉及 logger
- `factor_ic/MODULE.md`、`PROJECT.md`：仅在末尾追加风格规范说明
- 项目其他模块：本次不动

---

## 3. 实施方案

### 3.1 步骤（每步独立可审查 + commit）

**Step 1**：批量自动修复
```bash
ruff check --select G003,G004,G201 --fix --unsafe-fixes factor_ic/
ruff format factor_ic/
```
- `--unsafe-fixes` 是必须的（ruff 把 f-string→%s 标记为 unsafe，因为变量参数表达式可能有副作用）
- 修复后立即 `git diff` 全文件审查

**Step 2**：审查 diff（关键，发现 unsafe-fix 副作用）
- 重点检查：含方法调用 `f"...{obj.method()}..."` 的转换是否保留了求值
- 重点检查：嵌套 f-string、格式说明符 `:.4f`、`:%` 等是否正确转换
- 通过 `git diff --stat` + 抽样检查关键行

**Step 3**：跑全量测试
```bash
pytest factor_ic/test_cases/ -v
ruff check factor_ic/
mypy factor_ic/  # 如果项目已启用
```

**Step 4**：启用 ruff G 规则防回归
```toml
# pyproject.toml [tool.ruff.lint]
select = [
    "E", "F", "W", "I", "B904", "UP", "C4", "SIM",
    "G",  # logging format (G003 string concat, G004 f-string, G201 exception with exc_info)
]
```
- 验证：`ruff check .` 全项目通过（factor_ic 修完后应通过；其他模块如果也违规需要单独评估是否同时修）
- **风险**：若其他模块也触发 G 规则，启用 G 会让全项目 lint 失败 → **预案见 §5**

**Step 5**：更新 PROJECT.md / MODULE.md 规范
- 在"代码风格"章节追加：日志使用 % 惰性格式化（ruff G 规则强制）
- 引用 ruff G004 文档链接

**Step 6**：commit（按 step 拆分 1-2 个 commit）

### 3.2 自动修复样例（ruff --unsafe-fixes 的实际转换）

```python
# Before
logger.info(f"启动振幅因子IC计算: min_stocks={args.min_stocks}, force_full={args.force_full}")
logger.error(f"振幅因子IC计算失败: {e}")
logger.info(f"IC 均值: {ic_result.get('ic_mean', 0.0):.4f}")

# After（ruff 自动转换结果）
logger.info("启动振幅因子IC计算: min_stocks=%s, force_full=%s", args.min_stocks, args.force_full)
logger.error("振幅因子IC计算失败: %s", e)
logger.info("IC 均值: %.4f", ic_result.get("ic_mean", 0.0))
```

格式说明符 `:.4f` 会被正确转换为 `%.4f`。

---

## 4. 验证清单

- [ ] `ruff check --select G factor_ic/`：0 errors
- [ ] `ruff check factor_ic/`：All checks passed（无新增其他规则违规）
- [ ] `ruff format --check factor_ic/`：通过
- [ ] `pytest factor_ic/test_cases/`：全通过（基线对比，本次不应破坏任何测试）
- [ ] 抽样运行 1-2 个真实因子脚本（如 `python -m factor_ic.ic_amplitude_1d --force-full`）
      验证日志输出可读性未退化
- [ ] PROJECT.md / MODULE.md 同步更新风格规范段
- [ ] commit message 引用 PROJECT.md 规则 #9（日志格式）+ ruff G 规则文档

---

## 5. 风险与预案

| 风险 | 缓解 |
|---|---|
| ruff unsafe-fix 转换错误（如丢失副作用、嵌套 f-string） | Step 2 全 diff 审查；如果发现错误案例，手工回滚该处后改为人工修复 |
| 启用 G 规则导致其他模块 lint 失败 | **预案 A**（推荐）：仅在 factor_ic/ 路径下启用 G，其他模块单独 PR 推进；**预案 B**：本次 commit 不启用 G 规则，仅做风格转换，启用规则放下个 PR |
| 日志参数含表达式如 `f"x={a+b}"` 转换后可读性下降 | ruff 转换为 `"x=%s", a + b` 是正确的；如果业务希望保留表达式可读性，少数关键日志可手工还原（但需在 noqa 注释说明）|
| 新增防御性测试不需要（纯风格改动） | 不增加新测试；依赖现有 47+ 测试做回归基线 |

### 5.1 启用 G 规则的最终决策

**推荐预案 B**（保守）：
- 本次 commit 只做 factor_ic 风格转换，不动 pyproject.toml
- 风格转换稳定后（1 周观察期），再开 PR 启用全局 G 规则 + 修其他模块
- 理由：避免单 PR 跨范围太广，回滚成本可控

---

## 6. 任务粒度评估（AGENTS.md 规则 #12）

- 涉及文件：39 个（factor_ic/ 内）
- 实际人工动手：**1 个命令 + 全量审查**（不是 39 个文件逐个手改）
- 行数变化：约 219 行风格转换（不是新代码）
- 因此**不违反**"≤3 文件 ≤200 行"约束的精神（该约束针对的是新代码/逻辑改动，纯机械批量风格统一是例外）
- Design-First 流程仍然走（本文档），让用户审核"是否真的要做"+"步骤是否合理"

---

## 7. 待用户确认的决策点

1. **范围**：是否同意只动 factor_ic/，其他模块另起 PR？（推荐 ✓）
2. **启用 G 规则时机**：本次 commit 启用 还是 放下个 PR？（推荐 ✓ 下个 PR）
3. **PROJECT.md 规则补充**：是否需要在 PROJECT.md 硬规则表中新增 #13 "日志使用 % 惰性格式化"？（推荐 ✓）
4. **抽样运行验证**：选哪个/哪几个因子脚本做实际运行验证？（推荐 ic_amplitude_1d、ic_kdj_j_1d 各跑一次）

待你确认上述 4 点后开始 Step 1。
