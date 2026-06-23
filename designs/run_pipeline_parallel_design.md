# run_pipeline.py IC/Backtest 并行改造设计

> 创建：2026-06-23
> 状态：[design] 待审核
> 范围：仅 `run_pipeline.py` 单文件改动
> 触发：用户需求 — IC 脚本越来越多串行耗时太长，依次串行总耗时已达小时级

---

## 1. 需求（用户原话）

1. **默认 2 个脚本并行**，可通过 CLI 参数指定 N 个脚本并行
2. **批内并行批间串行**：N 个脚本执行完才执行下一批
3. **保留**指定从哪个脚本开始执行的能力（`--start-script` 不变）

---

## 2. 现状分析

### 2.1 当前架构（run_pipeline.py 595 行）

- `PIPELINE_SCRIPTS: list[ScriptTask]` 扁平列表（106 个脚本），每个携带 `stage` 字段
- `run_script(task, retry)` 调用 `subprocess.run` 同步执行单脚本（已经流式输出避免 OOM）
- `run_pipeline(start_stage, start_script, skip_stages)` 逐个 `for task in scripts_to_run` 串行执行
- 每个脚本之间 `gc.collect() + time.sleep(3)` 防 OOM
- `MAX_RETRIES=3, RETRY_DELAY=30s, SCRIPT_TIMEOUT=1800s`，部分任务有自定义 `timeout`

### 2.2 Stage 分布

| Stage | 内容 | 脚本数 | 可否并行 |
|-------|------|:---:|---|
| 0 | 数据拉取（fetch_*） | 7 | **不可** — 部分有顺序依赖 + 网络 IO 已限速 |
| 1 | factor_generator | 1 | N/A — 单脚本 |
| 2 | **IC 计算** | **52** | **✅ 可** — 每个脚本独立读 Parquet，无写竞争 |
| 3 | **分层回测** | **52** | **✅ 可** — 同 IC，独立读 Parquet 写各自 result/ |
| 4 | 综合因子 composite_* | 4 | ⚠️ 暂不并行（每个脚本峰值 ~2.6GB，并行易 OOM） |
| 5 | weight_selector | 1 | N/A |
| 6 | stock_selector | 1 | N/A |
| 7 | summary_report | 1 | N/A |

### 2.3 性能基准

- Parquet 迁移后单 IC 脚本：数据加载 1.9s + 计算 ~25s + 收尾 ~5s ≈ 30s
- 串行 52 个 IC ≈ 26 分钟（含 sleep(3)）
- 串行 52 个 backtest ≈ 30+ 分钟
- N=2 并行预算：单脚本峰值 ~2.6GB × 2 ≈ 5.2GB，7.3GB 机器有余量 ✅
- N=3 风险：峰值瞬时 7.8GB → 接近 OOM 阈值 ⚠️（用户负责把控）

---

## 3. 设计决策（每决策列方案 A/B + 出处）

### 决策 1：并行原语 — `ProcessPoolExecutor` vs `multiprocessing.Pool` vs `subprocess + Semaphore`

| 方案 | 优 | 劣 | 出处 |
|------|---|---|------|
| **A. `concurrent.futures.ThreadPoolExecutor` + subprocess.run** | 标准库；`subprocess.run` 本身就是子进程，线程池仅做调度；retry 逻辑可在线程内顺序执行；接口最简单 | 主进程多线程持有 subprocess 句柄（GIL 不影响，因为 subprocess.run 是阻塞 IO） | Python 官方文档 `concurrent.futures` |
| B. `ProcessPoolExecutor` | 真正多进程 | 多此一举 — subprocess 已经是子进程，再套 ProcessPool 增加 fork 开销 | — |
| C. `subprocess.Popen` + 手动 Semaphore | 控制粒度最细 | 手写 Semaphore + poll 循环易出 bug，重试逻辑变复杂 | — |

**选 A（ThreadPoolExecutor）**：subprocess.run 是阻塞 IO 操作，线程池调度它**没有 GIL 问题**，且 `as_completed()` 能精确知道每个 future 何时完成。

### 决策 2：并行单位 — 整个 Pipeline vs 仅 IC/Backtest 阶段

| 方案 | 描述 | 出处 |
|------|------|------|
| A. 全 stage 并行 | 所有 stage 内部都并行 | 用户需求字面 |
| **B. 仅 Stage 2/3 并行**，其他保持串行 | Stage 0 有顺序依赖、Stage 1/5/6/7 单脚本、Stage 4 并行风险高 | 用户标题"IC 脚本并行改造"+ 现状分析 §2.2 |

**选 B**：用户标题明确"IC 脚本并行"，需求 1 也是"脚本并行"（不是 stage 并行）。批内并行只在"可并行 stage"内启用，其他 stage 走原串行路径。

### 决策 3：批次切分策略 — 固定 N vs 动态调度

| 方案 | 描述 |
|------|------|
| A. 固定 batch_size=N，分批 `[0:N], [N:2N], ...`，**每批等所有完成再进下一批** | 严格符合用户需求"N 个脚本执行完再执行下一批" |
| B. 流式调度（一个完成就启动下一个，始终保持 N 个并发） | 总耗时更短，但不符合"批间严格屏障" |

**选 A**：用户明确要求"N 个脚本执行完再执行下一批" = 批间屏障。

### 决策 4：失败处理

保持现有语义：单脚本失败不中断 pipeline，记入 `failed_scripts`，最终汇总返回 False。
**并行下的扩展**：同一批中多个失败都记录，**不因一个失败而取消同批其他 future**（用 `wait(..., return_when=ALL_COMPLETED)` 不是 `FIRST_EXCEPTION`）。

### 决策 5：CLI 参数命名

- `--parallel N`（默认 2）：并行度。`N=1` 等同于完全串行（向后兼容路径）
- `--start-script` 保留不变
- `--start-stage` 保留不变
- `--skip-stages` 保留不变

### 决策 6：gc.collect() + sleep(3) 何时执行

- **串行 stage**：每脚本后 `gc.collect() + sleep(3)`（保持现状）
- **并行 stage**：每批 N 个**全部完成后** `gc.collect() + sleep(3)`（一次，而非 N 次）

理由：sleep 防 OOM 的作用是让 OS 回收子进程内存。并行批结束时所有 N 个子进程已 exit，sleep 一次足够。

### 决策 7：日志输出

- 并行执行时多脚本日志会交织 — 现状是子进程流式 stdout 直接打到父进程 terminal
- **保持**流式输出（不缓存到内存，避免 OOM），但在每个脚本输出前后加 `[task_name]` 前缀分隔
- 由于子进程的 stdout 是直接继承父进程的，**无法**强制加前缀（除非改成 PIPE 读取再写）。**接受日志交织作为已知折衷**，理由：用户主要看的是各模块独立的 `logs/<script>_YYYY-MM-DD.log` 文件，pipeline stdout 只是粗粒度进度
- 添加 batch 边界标记：`>>> Batch 3/26 启动 (5 tasks): ic_rsi, ic_volume_ratio, ...` 和 `<<< Batch 3/26 完成 (耗时 32.1s, 成功 5/5)`

---

## 4. 实施清单（最小改动）

### 4.1 改动文件

仅 `run_pipeline.py` 1 个文件。**满足任务粒度约束 ≤3 文件 ≤200 行**。

### 4.2 新增 / 修改

| 位置 | 改动 | 行数估算 |
|------|------|:---:|
| 文件顶部 import | `from concurrent.futures import ThreadPoolExecutor, as_completed` | +1 |
| 配置常量区 | `DEFAULT_PARALLEL = 2`；`PARALLELIZABLE_STAGES = {2, 3}` | +3 |
| 新函数 `run_script_with_retry(task) -> tuple[ScriptTask, bool]` | 封装"单脚本 + 重试循环"，供并行线程调用 | +25 |
| 新函数 `_run_batch_parallel(tasks, parallel) -> list[tuple[ScriptTask, bool]]` | ThreadPoolExecutor 提交 N 个 task，as_completed 收集结果 | +30 |
| 改 `run_pipeline()` 签名 | 新增 `parallel: int = 1` 参数 | +1 |
| 改 `run_pipeline()` 执行循环 | 按 `stage` 分组扫描；对 `stage ∈ PARALLELIZABLE_STAGES` 走批处理；其他走原 for 循环 | +35 / -15 |
| 改 `main()` argparse | 新增 `--parallel N` | +5 |

**总改动 ≈ +100 行 / -15 行，净 +85 行**，远低于 200 行上限 ✅

### 4.3 核心代码草稿

```python
DEFAULT_PARALLEL = 2
PARALLELIZABLE_STAGES = {2, 3}  # IC + 分层回测


def run_script_with_retry(task: ScriptTask) -> tuple[ScriptTask, bool]:
    """单脚本 + 重试循环（封装供线程池调用，包含原 for retry in range 逻辑）"""
    for retry in range(MAX_RETRIES + 1):
        if run_script(task, retry):
            return task, True
        if retry < MAX_RETRIES:
            print(f"[{task.name}] 等待 {RETRY_DELAY}s 后重试...")
            time.sleep(RETRY_DELAY)
    print(f"[{task.name}] 重试次数用尽，标记为失败")
    return task, False


def _run_batch_parallel(
    tasks: list[ScriptTask], parallel: int
) -> list[tuple[ScriptTask, bool]]:
    """并行执行一批 tasks，全部完成才返回"""
    results: list[tuple[ScriptTask, bool]] = []
    with ThreadPoolExecutor(max_workers=parallel) as pool:
        futures = {pool.submit(run_script_with_retry, t): t for t in tasks}
        for fut in as_completed(futures):
            results.append(fut.result())
    return results


# run_pipeline() 执行循环改造（保持 scripts_to_run 过滤逻辑不变）：
i = 0
while i < len(scripts_to_run):
    task = scripts_to_run[i]
    if task.stage in PARALLELIZABLE_STAGES and parallel > 1:
        # 收集同 stage 连续段
        j = i
        while j < len(scripts_to_run) and scripts_to_run[j].stage == task.stage:
            j += 1
        stage_tasks = scripts_to_run[i:j]
        # 按 batch_size=parallel 分批
        for batch_start in range(0, len(stage_tasks), parallel):
            batch = stage_tasks[batch_start : batch_start + parallel]
            batch_no = batch_start // parallel + 1
            total_batches = (len(stage_tasks) + parallel - 1) // parallel
            print(f"\n>>> Stage {task.stage} Batch {batch_no}/{total_batches} "
                  f"启动 ({len(batch)} tasks): {', '.join(t.name for t in batch)}")
            t0 = time.time()
            batch_results = _run_batch_parallel(batch, parallel)
            elapsed = time.time() - t0
            ok = sum(1 for _, s in batch_results if s)
            print(f"<<< Stage {task.stage} Batch {batch_no}/{total_batches} "
                  f"完成 (耗时 {elapsed:.1f}s, 成功 {ok}/{len(batch)})")
            # 收集 success/failure
            for tk, success in batch_results:
                if success:
                    success_count += 1
                else:
                    failed_scripts.append((tk, -1))
            gc.collect()
            time.sleep(3)
        i = j  # 跳过整段
    else:
        # 原串行路径
        ...  # 保持现状
        i += 1
```

---

## 5. 测试计划

### 5.1 dry-run 验证（不实际跑脚本）

**问题**：本项目无 mock subprocess 的测试基础设施。

**方案**：写一个 `test_run_pipeline_batching.py`，**不调用 run_script**，而是单独测试新引入的批次切分逻辑：
- 提取批次切分为纯函数 `_plan_batches(scripts, parallel, parallelizable_stages) -> list[list[ScriptTask] | ScriptTask]`
- 测试 `parallel=1` 退化为全串行（单元素 batch list）
- 测试 `parallel=2` 时 stage=2 的 52 个脚本被切成 26 批 × 2
- 测试 `parallel=5` 余数处理（最后一批 < N）
- 测试 stage 0/1 始终串行
- 测试 `--start-script` 跨入 parallelizable stage 的中间时正确处理（从某个 IC 开始仍按剩余脚本分批）

### 5.2 手动 e2e 验证（小规模真跑）

跑一次 `python run_pipeline.py --skip-stages 0 1 4 5 6 7 --start-script ic_amplitude --parallel 2`，确认：
- IC 阶段从 ic_amplitude 开始，按 2 并行
- 不跑 backtest 之后阶段（因为已 skip）
- 内存峰值 < 6GB（用 `/usr/bin/time -v` 测）

### 5.3 回归测试

`run_pipeline.py --parallel 1` 应与重构前行为完全一致（同样的失败重试、同样的 sleep、同样的失败汇总）。

---

## 6. 风险与回滚

| 风险 | 缓解 |
|------|------|
| 并行 IC 同时读 Parquet 触发 pyarrow 多线程冲突 | pyarrow 是线程安全的；每个 subprocess 是独立进程，无共享状态 |
| 并行后内存峰值翻 N 倍触发 OOM | 默认 N=2 < 7.3GB / 2.6GB = 2.8；N=3 用户自负 |
| 日志交织难调试 | 用户主要看 `<module>/logs/<script>_YYYY-MM-DD.log`，pipeline stdout 只是粗粒度进度 |
| 重试时序问题（并行批内某脚本进入 30s sleep 阻塞整批） | 接受 — 重试本就是恢复机制，批内只要有一个失败重试，整批耗时拉长在所难免；不引入额外复杂度 |

**回滚**：`--parallel 1` 即恢复原串行行为（向后兼容路径），无需 revert commit。

---

## 7. 提交计划

按 superpowers-workflow 第一性原理 + AGENTS.md 多 agent 提交规则：

1. **本 design.md 先提交**（独立 commit）
2. **代码改动 + 测试单元 commit**（仅 `run_pipeline.py` + 新增 `test_run_pipeline_batching.py`）
3. **文档同步 commit**（PROJECT.md / `Run Pipeline 执行排查流程` 章节）

每步都 `ruff check + format` + 显式路径 `git commit <paths> -m` + `git show --stat HEAD` 验证。

---

## 9. 实测后调整记录（2026-06-23 Execute 阶段后回填）

### 9.1 实测数据

| 测试 | 结果 |
|------|------|
| ic_rsi_1d 单跑（`/usr/bin/time -v`） | 28.14s / 峰值 **2.46 GB** RSS |
| ic_rsi + ic_amplitude **串行** | 总 57.9s / 峰值 2.53 GB / 2 全成功 |
| ic_rsi + ic_amplitude **并行 N=2** | 总 32.7s（**1.77x 加速**）/ ic_amplitude **OOM Killed (exit -9)** |
| dmesg OOM 证据 | `oom-kill: constraint=CONSTRAINT_NONE, global_oom, task=python, total-vm: 4376340kB` |

### 9.2 设计假设偏差

| 项 | 设计假设 | 实测 |
|----|---------|------|
| 单脚本峰值 | 2.6 GB | ic_rsi 2.46 GB ✓ / **ic_amplitude >4 GB ✗** |
| N=2 总占用 | 5.2 GB | **>8 GB**（含中性化 OLS 峰值 + join 中间表）|
| 7.3 GB 机器余量 | 2.1 GB | 实际可用 ~3.7 GB（系统占 3.6 GB），N=2 仍 OOM |

**根因**：`ic_amplitude_1d` 含交叉因子计算（amplitude × volume_ratio 等），中性化阶段 join + OLS 残差矩阵峰值远超 ic_rsi 类纯单因子脚本。设计阶段用 ic_amplitude_1d 做基准（2.6 GB）是**加载完成后的稳态值，不是峰值**。

### 9.3 决策调整

**`DEFAULT_PARALLEL = 2` → `DEFAULT_PARALLEL = 1`**

理由：
- 第一性原理：单脚本峰值不可预测（不同 IC 脚本中性化复杂度差异大），默认 N=1 是安全契约
- 用户语义："默认两个并行"是表达"可选项"，OOM 风险不应作为默认承担
- 兼容性：用户显式 `--parallel 2` 仍可启用，高配机器（>16GB 可用）受益

代码改动：`run_pipeline.py` 行 165 单行常量；批次切分、批间屏障、并行原语等核心逻辑**无需改动**。

### 9.4 未来若想稳定启用 N>1

需先治本（任一即可）：
1. **降低 IC 脚本峰值**：chunked OLS（按日期分块）/ float32 / 中性化前提前 dropna
2. **扩 swap**：`fallocate -l 8G /swapfile` 让 OS 处理瞬时尖峰（牺牲性能）
3. **升级机器**：>16GB 内存，3.7GB 余量变 12GB+，N=2 安全
