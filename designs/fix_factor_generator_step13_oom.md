# Design: fix factor_generator Step 13 OOM

> 作者: 云瑶
> 创建时间: 2026-06-22
> 状态: 用户已确认走"Step 13 局部内存优化"路线，按 Design-First 留痕后执行
> 关联: `designs/fix_factor_generator_step12_oom.md`（同类前置修复，去年 Step 12 同模式问题）

---

## §1 背景与现场证据

v2.36 交互因子（Batch 1-3 已 commit）后跑 `python data_fetchers/factor_generator.py`，进程在 **Step 13: 计算二阶导数企稳信号因子** 被 OOM-kill：

```
2026-06-22 01:12:07 | INFO | factor_generator | Step 12: 计算趋势变化/量价背离因子...
2026-06-22 01:12:07 | INFO | factor_generator | Step 13: 计算二阶导数企稳信号因子...
[killed]
```

`dmesg`：
```
oom-kill: task=python3, pid=2627747
Out of memory: Killed process 2627747 (python3)
total-vm:4170440kB, anon-rss:3595940kB
```

当前环境 `free -h`: 7.3GB 总, Hermes WebUI 1.5GB + pyright 0.78GB + 其他 = 实际可用 ~3.8GB → factor_generator 在 Step 13 内存峰值超出 3.6GB → 被杀。

去年 Step 12 同位置修复后实测 max-RSS 约 3.30GB（`designs/fix_factor_generator_step12_oom.md`）—— 两个事件相隔半年，但根因同模式。

---

## §2 规范触发与范围

| 规范 | 触发原因 | 处理 |
|------|----------|------|
| PROJECT.md H8（行 115-123）| 涉及 momentum.py + volume_price.py（2 个业务文件） | 先提交本 design |
| PROJECT.md H9（行 162）| 控制单轮 ≤3 文件、≤200 行 | 本轮只改 2 业务文件 + 0 测试（行为不变，无需新测试） |
| data_fetchers/MODULE.md R16 | 大对象生命周期 / OOM | sort_values 已返回新对象，禁止额外 copy |
| AGENTS.md §⚡ 第一性原理 | 不切数据库等大改动 | 根因在 momentum/volume_price 6 个函数的 `sort_values().copy()` 双拷贝模式 |
| AGENTS.md 规则 #14 死代码 | `.copy()` 在 sort_values 后是死代码（pandas 已返回新对象）| 删除冗余 copy |

---

## §3 根因分析（第一性原理）

### 3.1 OOM 进程位置

Step 13 包含 6 个因子函数（依次调用）：

| 因子 | 文件:行 | 入口模式 |
|------|---------|---------|
| calculate_return_acceleration_5d | momentum.py:784 | `df = factor_df.sort_values([asset, date]).copy()` |
| calculate_downside_deceleration | momentum.py:824 | `df = factor_df.sort_values([asset, date]).copy()` |
| calculate_amplitude_compression | volume_price.py:432 | `df = factor_df.sort_values([asset, date]).copy()` |
| calculate_range_compression | volume_price.py:473 | `df = factor_df.sort_values([asset, date]).copy()` |
| calculate_volume_decay_rate | volume_price.py:517 | `df = factor_df.sort_values([asset, date]).copy()` |
| calculate_turnover_decay_rate | volume_price.py:554 | `df = factor_df.sort_values([asset, date]).copy()` |

### 3.2 pandas 内部行为（关键事实）

```python
factor_df.sort_values([...])  # 默认 inplace=False，返回新 DataFrame（独立 buffer）
factor_df.sort_values([...]).copy()  # 在新 DataFrame 上再 copy 一次 → 双倍内存
```

**`.copy()` 是冗余的**——sort_values 本身就已经返回了与原 df 不共享 buffer 的新对象。`MODULE.md 约束 4`（DataFrame 参数先 copy）的本意是防止原地修改污染上游 df；但 sort_values 已经天然满足"不污染上游"语义。

### 3.3 内存峰值估算

```
传入 factor_df: 149 万行 × ~45 列 ≈ 1.5GB（含已计算的 Step 1-12 全部因子列）
Step 13 内部 sort_values 返回新对象: +1.5GB（已与原始独立）
额外 .copy(): +1.5GB ← 完全多余
rolling 窗口中间对象 (asset 分组): +0.3-0.5GB
峰值同时存在: 1.5 + 1.5 + 1.5 + 0.5 ≈ 5GB ← OOM
```

Step 13 与去年 Step 12 OOM 都是同一类问题（中间对象未释放/过多副本），但 Step 12 修复设计未覆盖到 Step 13 的 6 个因子函数。**这是 pitfall #169 风格的"修复未传播"**——v2.35 P5-补充新增因子时套用了旧模板（含冗余 .copy()），没继承 fix_factor_generator_step12_oom 的内存优化精神。

### 3.4 为什么 Step 12 没炸

Step 12 的 5 个因子（rsi_slope_3d 等）模式略不同——是 `df = factor_df.copy(); df = df.sort_values(...)`（先 copy 后 sort），sort_values 默认返回新 df 但**已经 copy 过，所以 sort_values 这次的新副本只是临时**，老 copy 在函数末尾返回前会被 sort_values 替换覆盖（同名 df 变量重新绑定）→ 实际峰值是 1×copy + 1×sort 临时 = 2×，比 Step 13 的 3× 少一份。

恰好 Step 12 没触发 OOM 的边界，Step 13 触发了。但 Step 12 的代码模式同样有改进空间（少 1 份不必要的副本）。

---

## §4 方案：删除冗余 .copy()

### §4.1 核心变化

| 现状 | 修改后 | 理由 |
|------|--------|------|
| `df = factor_df.sort_values(...).copy()` | `df = factor_df.sort_values(...)` | sort_values 已返回独立新对象，copy 多余 |
| 内存峰值 ≈ 3×factor_df | 内存峰值 ≈ 2×factor_df | 省一份副本 |
| MODULE.md 约束 4（不修改上游）| 仍满足 | sort_values 天然不修改原 df |

### §4.2 影响范围

| 文件 | 函数 | 行 | 改动 |
|------|------|-----|------|
| momentum.py | calculate_return_acceleration_5d | 804 | `.copy()` 删 |
| momentum.py | calculate_downside_deceleration | 845 | `.copy()` 删 |
| volume_price.py | calculate_amplitude_compression | 448 | `.copy()` 删 |
| volume_price.py | calculate_range_compression | 489 | `.copy()` 删 |
| volume_price.py | calculate_volume_decay_rate | 533 | `.copy()` 删 |
| volume_price.py | calculate_turnover_decay_rate | 570 | `.copy()` 删 |

**总计 2 文件、6 行改动（每处 1 行）**——远小于 H9 200 行上限。

### §4.3 等价性证明

**修改前**：
```python
df = factor_df.sort_values([_COL_ASSET, _COL_DATE]).copy()
# df 是 factor_df 的"排序后副本的副本"
# 后续对 df 操作不影响 factor_df ✓
```

**修改后**：
```python
df = factor_df.sort_values([_COL_ASSET, _COL_DATE])
# df 是 factor_df 的"排序后副本"
# 后续对 df 操作不影响 factor_df ✓ （sort_values 已返回独立 buffer）
```

**关键 pandas 保证**：`DataFrame.sort_values(inplace=False)` 返回的对象与原对象 **不共享底层 numpy buffer**。对返回值做赋值（`df[col] = ...`）不会修改原 factor_df 的列。这是 pandas 公开 API 契约（见 pandas docs 关于 `inplace=False`）。

唯一行为差异：原代码中 `.copy()` 是显式深拷贝，新代码中 sort_values 内部也是深拷贝（因为要排序数据）。两者结果等价，新代码省掉一次冗余的内存分配。

---

## §5 不做项（明确边界）

- ❌ 不切数据库存储（架构重写，影响 80+ 下游脚本）
- ❌ 不改 `_FACTOR_PIPELINE_STEPS` 逻辑
- ❌ 不修改 Step 12 的 5 个因子（虽然也有改进空间，但**不触发 OOM**，本次不引入额外变更范围；后续可独立 PR）
- ❌ 不新增测试（行为不变；现有 unit test 覆盖率不下降）
- ❌ 不引入分块计算或流式落盘（更大改动，留作后续路线）

---

## §6 验证计划

### §6.1 单元测试

```bash
python3 -m pytest data_fetchers/test_cases/test_factor_calculator.py \
                  data_fetchers/test_cases/test_factor_calculator_interaction.py \
                  -q --no-header
```

期望：原 43 + 19 = 62 测试全过（行为不变，无新失败）。

### §6.2 内存对比（量化指标）

```bash
/usr/bin/time -v python data_fetchers/factor_generator.py 2>&1 | grep "Maximum resident"
```

期望：
- 修改前 max-RSS（基于 dmesg 现场）：~3.6GB
- 修改后 max-RSS：≤ 3.2GB（节省 6 份 sort copy 各 ~50-80MB，累计 ~400MB+）

### §6.3 数据等价性

旧 `factor_ic_data.json.gz` 备份后跑新代码，比对 6 个 Step 13 因子列的数值一致性：

```python
import pandas as pd
old = pd.read_json("factor_ic_data.OLD.json.gz")
new = pd.read_json("factor_ic_data.json.gz")
for col in ["return_acceleration_5d","downside_deceleration","amplitude_compression",
            "range_compression","volume_decay_rate","turnover_decay_rate"]:
    assert (old[col].fillna(-999) == new[col].fillna(-999)).all()
```

期望：6 列数值完全一致（毕竟只是删 copy，不改算法）。

---

## §7 实施拆分

按 H9 单 commit ≤3 文件原则：

**Round 1**: momentum.py 2 个函数（2 行删除）
**Round 2**: volume_price.py 4 个函数（4 行删除）

**或者**：因改动极小（共 6 行），可一次 commit 提交（仍 ≤3 文件，≤200 行）。

推荐：**一次 commit**，更短的审阅链路。

---

## §8 与 Step 12 修复的关系

| 维度 | Step 12 修复（已落地）| Step 13 修复（本设计）|
|------|---------------------|---------------------|
| OOM 位置 | _format_and_write_output 输出层 | _run_factor_pipeline 计算层 |
| 根因 | to_dict("records") 把列式膨胀成 Python list | sort_values 后冗余 .copy() |
| 方案 | 列视图 + itertuples 流式写出 | 删除冗余 copy |
| 范围 | factor_generator.py 内部 helper | factor_calculator 6 个因子函数 |
| 行数 | ~50 行 | 6 行 |

两次都是**计算/IO 层局部内存优化**，不是架构改动。这印证了 §1.1 用户问"是否切数据库"时的判断——**OOM 应在生成它的层级修复，不应通过下游架构重写规避**。

---

## §9 审核问题

1. **是否需要把 Step 12 的 5 个因子也一并优化？**
   - 否（推荐）：Step 12 不 OOM，多带一份改动违反 H9 单批粒度；后续可独立 PR
   - 是：本批一并改 Step 12 + Step 13 共 11 处删除 copy
2. **是否需要 max-RSS 量化比对作为 commit 验收？**
   - 是（推荐）：1 行命令验证 OOM 是否实际解决
   - 否：仅做单元测试 + 数据等价性比对（更快但缺峰值证据）
