# Design: tail.py masked-apply 重构修 OOM

> 触发：factor_generator 单进程被 SIGKILL(-9)，dmesg 确认 OOM，崩点定位到
> `data_fetchers/factor_calculator/tail.py:431` 的 `merged_df.apply(axis=1)`。
> 系统 7.3GB / 长驻 ~3.4GB / factor_generator 单进程峰值 3.27GB → OOM。

## §1. 问题根因（事实+证据）

**证据 1（dmesg）**：
```
pid 2407139 killed: anon-rss 3.27GB (单进程，非并发)
```

**证据 2（日志最后行）**：
```
23:39:24 | factor_generator | 尾盘数据合并完成: 66243 / 1493252 条匹配
[然后被 -9，未到 Step 11.5]
```

**证据 3（代码热点）**：tail.py 当前实现
- `merged_df` = 1.49M 行 × ~23 列，含 `prices`/`volumes`/`tail_high`/`tail_low` 4 个 list 列
- 连续 4 个 `merged_df.apply(axis=1)`（行 431/444/448/453）
- left merge 命中率仅 **66243 / 1493252 = 4.4%**
- 95.6% 的 apply 调用是 NaN→NaN 的空转，但每行仍构造 Series（含 list 列），内存放大若干倍

## §2. 修复目标

1. **必要**：消除 OOM，保证 factor_generator 单进程跑得过去
2. **必要**：5 个 tail 因子输出与原实现**字节级一致**（含 NaN 位置、有效值）
3. **次要**：执行时间从 ~分钟级降到秒级（apply 行数 ×0.044）

## §3. 方案：mask 子集 apply + reindex

### §3.1 行为等价性论证（必读）

5 个 `_calc_*` helper 对**所有 NaN/None/非 list 输入都返回 np.nan**：
- `_calc_price_position`（130-189）：`pd.isna(close_price/tail_high/tail_low)` 守卫 → NaN
- `_calc_tail_price_slope`（192-224）：`not isinstance(prices, list)` → NaN
- `_calc_tail_price_volume_intensity`（227-269）：`prices/volumes/total_volume is None` → NaN
- `_calc_tail_volume_acceleration`（272-310）：`volumes is None` / 非 list → NaN
- `_calc_tail_volume_shrink`（313-...）：`volumes/total_volume is None` → NaN

**结论**：未匹配行（`prices` 列为 NaN）的 5 个因子值原本就是 NaN，跳过 apply 直接置 NaN 等价。

特别关注：`_calc_price_position` 有涨跌停分支（`tail_high == tail_low` 但 `daily_high/low/close` 非 NaN）。但触发该分支需要 `tail_high/tail_low` 都非 NaN，即必须 merge 命中。未匹配行 `tail_high/tail_low` 为 NaN，直接走开头守卫返回 NaN，与方案 A 跳过 apply 一致。

### §3.2 改造前后对比

**改造前**（tail.py:419-480）：
```python
merged_df = factor_df.merge(tail_df[merge_cols], on=["date", "asset"], how="left")
# ... 4 个 merged_df.apply(axis=1) ...
result_cols = list(factor_df.columns) + list(_TAIL_FACTOR_COLS)
return merged_df[result_cols]
```

**改造后**：
```python
# 1) 在 factor_df 上预先初始化 5 个因子列为 NaN（保留原行序）
for col in _TAIL_FACTOR_COLS:
    factor_df[col] = np.nan

# 2) 只对有尾盘数据的行做 merge + apply
tail_df_indexed = tail_df.set_index(["date", "asset"])
mask = pd.MultiIndex.from_arrays(
    [factor_df["date"], factor_df["asset"]]
).isin(tail_df_indexed.index)

if mask.any():
    sub = factor_df.loc[mask, ["date", "asset", "volume", "close", "high", "low"]].copy()
    # left join 取 tail 列
    sub = sub.merge(tail_df[merge_cols], on=["date", "asset"], how="left")
    sub["tail_close"] = sub["prices"].apply(_get_close_price)
    sub["tail_price_position"] = sub.apply(lambda row: _calc_price_position(...), axis=1)
    sub["tail_price_slope"] = sub["prices"].apply(_calc_tail_price_slope)
    if "volumes" in sub.columns:
        sub["tail_price_volume_intensity"] = sub.apply(...)
        sub["tail_volume_acceleration"] = sub["volumes"].apply(_calc_tail_volume_acceleration)
        sub["tail_volume_shrink"] = sub.apply(...)
    # 3) 把 sub 的因子列 reindex 回 factor_df（按 [date, asset] 对齐）
    sub_indexed = sub.set_index(["date", "asset"])
    for col in _TAIL_FACTOR_COLS:
        if col in sub_indexed.columns:
            factor_df.loc[mask, col] = factor_df.loc[mask].set_index(
                ["date", "asset"]
            ).index.map(sub_indexed[col]).values

# 4) 释放中间对象（R16）
del tail_df, sub  # noqa
return factor_df
```

**关键不变量**：
- 输入 `factor_df` 行序保留（不排序、不 reindex）
- 5 个输出列与原实现 NaN 位置 / 有效值字节级一致

### §3.3 内存账本预估

| 项 | 原实现 | 新实现 |
|----|--------|--------|
| `merged_df`（含 list 列，1.49M 行）| ~600MB | 仅 `sub`（66k 行）~30MB |
| `apply(axis=1)` 行 Series 构造 | 1.49M 次 ×含 list | 66k 次 ×含 list |
| 进程峰值 RSS（实测） | 3.27GB（OOM） | 预计 ~1.5GB |

### §3.4 决策矩阵

| 子决策 | 选项 | 选择 | 理由（来源） |
|--------|------|------|------|
| mask 实现 | (a) `notna(prices)` 在 merge 后判断 / (b) `MultiIndex.isin(tail_df.index)` 在 merge 前判断 | **(b)** | (a) 仍需先 merge 出全表 → 没消除内存放大；(b) 在小表索引上判断，不构造大 merged_df。规范默认（节省内存优先）|
| 因子列初始化 | (a) `factor_df[col] = np.nan` 单列赋值 / (b) `assign` 一次性 | **(a)** | (a) 与原 `merged_df[col] = np.nan` else 分支语义对齐；inplace 修改，无中间副本。规范默认 |
| 行序保护 | (a) `loc[mask, col] = ...` inplace / (b) merge 回写 | **(a)** | (a) 不改变 factor_df 行序；调用方依赖原序（factor_generator 后续 step 不重排）。MODULE.md R16 推荐 inplace 释放中间 |
| 是否 `factor_df.copy()` 入口 | (a) 保留 / (b) 去掉 | **(a)** | tail.py 行 401 原本就 copy；MODULE.md "函数入口先 copy" 约定。规范默认 |

## §4. 验证（Review 阶段）

### §4.1 ruff + pytest

- `ruff check data_fetchers/factor_calculator/tail.py` 无新增告警
- `pytest data_fetchers/test_cases/test_factor_calculator_tail.py -v`
- `pytest data_fetchers/test_cases/ -v --cov-fail-under=70`

### §4.2 新增等价性测试 `test_factor_calculator_tail.py`

```python
class TestCalculateTailFactorsEquivalence:
    def test_full_match_equivalence(self, ...):
        """所有行都有尾盘数据时，新旧实现结果完全一致"""

    def test_partial_match_equivalence(self, ...):
        """部分行有尾盘数据时（mask 路径），有匹配行=正常值，无匹配行=NaN"""

    def test_zero_match(self, ...):
        """tail_df 为空时，所有 5 个因子均为 NaN"""

    def test_row_order_preserved(self, ...):
        """factor_df 行序保留，不被 sort 打乱"""

    def test_limit_up_branch(self, ...):
        """涨跌停分支（tail_high==tail_low）：merge 命中行进入 sub 后正确处理"""
```

### §4.3 实测内存峰值

```bash
/usr/bin/time -v python -m data_fetchers.factor_generator 2>&1 | grep "Maximum resident"
# 预期：< 1.8GB（原 3.27GB → 约半）
```

### §4.4 端到端验收

完整跑一次 `python -m data_fetchers.factor_generator`：
- 退出码 0
- `data_fetchers/result/factor_ic_data.json.gz` 生成且大小合理
- 5 个 tail 因子有效行数与上次成功跑（如有）一致

## §5. 风险与回滚

**风险 1**：`MultiIndex.isin` 在 1.49M × 66k 数据规模下是否快
- 缓解：实测；如慢可改 `pd.merge(indicator=True)` 取 `_merge=='both'` 索引

**风险 2**：`tail_df` 含重复 `(date, asset)` 键（理论不应有，但 fetch 阶段可能未保证）
- 缓解：测试中加 `assert tail_df.duplicated(subset=["date","asset"]).sum() == 0`

**回滚**：单文件改动，`git revert` 即可。

## §6. 任务粒度

- 修改文件：2 个（`tail.py` + 新建 `test_factor_calculator_tail.py`）
- 修改行数：tail.py 约 -50/+60 行；测试约 +200 行
- 单 commit
- 引用规范：MODULE.md R16（大对象 del）、AGENTS.md 规则 #14（禁止死代码——不变换原 NaN 路径）

## §7. 不在本次范围

- factor_generator.py 内 step 之间 `factor_df` 持久化（如分块写盘）—— 另一类优化，本次不做
- pyright LSP 内存优化（用户机器层面）

---

请确认方案 A 选项是否符合预期，或需要调整。
