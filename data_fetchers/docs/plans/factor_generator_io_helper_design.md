# factor_generator I/O helper 抽取 design

> 范围：F 步（原计划 -80 行，实际拆为 F1+F2）
> 时间：2026-06-16
> 前置：D 步 4 轮已闭环（commit `d0ee7b4`），factor_generator.py = 1016 行

---

## 1. 背景与决定

E 步原计划「metadata 派生 -50 行」已在 D3 提前消化：metadata 段 66 行 → 4 行 dict comprehension（`valid_records` / `valid_records_percent`），无再压空间。

E 步取消，直接进 F 步。F 步拆为 2 轮：
- **F1（本设计）**：读 helper `_load_json_gz_data`（消化 Step 1/2/3 共 116 行）
- **F2（下一轮）**：写 helper `_write_factor_json_gz`（消化 Step 13 共 87 行）

理由：Step 1/2/3 是 3 份**几乎完全一致**的 25 行 boilerplate（结构平行）；Step 13 含 `_nan_to_null` 闭包 + 流式写入 + 临时文件 + 原子替换，结构与读完全不同。拆 2 轮风险更低，每轮独立可验证。

---

## 2. 现状分析

Step 1/2/3 共同模式（共 116 行 = Step1:29 + Step2:42 + Step3:44，其中加载部分各约 25 行）：

```python
try:
    with gzip.open(<path>, "rt", encoding="utf-8") as f:
        <data_var> = json.load(f)
except FileNotFoundError:
    raise FileNotFoundError(f"<label>数据文件不存在: {<path>}") from None
except gzip.BadGzipFile as e:
    logger.error("gzip 文件损坏: %s, 原因: %s", <path>, str(e))
    raise ValueError(f"gzip 文件损坏: {<path>}") from e
except json.JSONDecodeError as e:
    raise ValueError(f"JSON解析失败: {<path>}, 行 {e.lineno}, 列 {e.colno}, 信息: {e.msg}") from e

# 数据验证：检查 'data' 字段存在
if "data" not in <data_var>:
    raise ValueError(f"<label>数据缺少 'data' 字段: {<path>}")
```

差异仅在：
- `<path>`：3 个数据源路径
- `<label>`：「基础因子 / 换手率 / 收益」中文标签
- `<data_var>`：临时变量名（无意义，helper 内可统一）

**注意**：Step 2/3 在加载后还有 `pd.DataFrame(...)` 转换、`pd.to_datetime(format="mixed")`、merge、缺失检查、`del data_var` 等业务逻辑。helper 只负责**加载到 list/dict 阶段**，业务逻辑保留在调用处。

---

## 3. 设计

### 3.1 helper 签名

```python
def _load_json_gz_data(
    path: Path,
    dataset_label: str,
    logger: logging.Logger,
) -> list[dict[str, Any]]:
    """加载 gzip 压缩的 JSON 数据文件并提取 'data' 字段。

    统一封装 Step 1/2/3 的加载逻辑：gzip 解压 + JSON 解析 + 'data' 字段校验。

    Args:
        path: 数据文件路径
        dataset_label: 数据集中文标签（用于错误消息），例 "基础因子" / "换手率" / "收益"
        logger: 日志器（gzip.BadGzipFile 时 error 日志）

    Returns:
        data: list[dict]，对应 JSON 文件的 "data" 字段值

    Raises:
        FileNotFoundError: 文件不存在
        ValueError: gzip 损坏 / JSON 解析失败 / 缺少 'data' 字段
    """
```

### 3.2 调用点替换

```python
# Step 1
base_data_records = _load_json_gz_data(factor_data_path, "基础因子", logger)
factor_df = pd.DataFrame(base_data_records)
factor_df["date"] = pd.to_datetime(factor_df["date"])
del base_data_records  # 显式释放
# ... 后续业务逻辑不变

# Step 2 / Step 3 同样模式
```

注意：原代码 `del base_data` 释放的是包含 `data` key 的整个 JSON dict，新代码 helper 内部只 return `base_data["data"]`（list），调用处 `del base_data_records` 释放的内存量相同（外层 dict 仅 1 个 key 引用）。

### 3.3 helper 位置

放在 `_drop_industry_column`（行 547）之后，CLI 入口之前。模块级私有 helper 区段。

---

## 4. 不变量保证

| 项 | 重构前 | 重构后 | 验证 |
|----|--------|--------|------|
| 异常类型 | FileNotFoundError / ValueError | 完全一致 | unit smoke |
| 异常消息 | `"基础因子数据文件不存在: ..."` 等 | 字符级一致 | unit smoke |
| logger.error 日志 | gzip 损坏时打印 | 完全一致 | unit smoke |
| `'data' 字段` 校验 | 4 处独立 if | helper 内统一 | unit smoke |
| 内存释放时机 | `del base_data` 等 | `del *_records` 等 | 等价 |
| step 段日志 | `logger.info("Step N: 加载 ... ...")` | 不变（保留在调用处） | 字符级一致 |

---

## 5. 行数预算

| 项 | 增/减 |
|----|------|
| 新增 helper（含 docstring）| +35 |
| Step 1 加载段 25 行 → 4 行 | -21 |
| Step 2 加载段 25 行 → 4 行 | -21 |
| Step 3 加载段 25 行 → 4 行 | -21 |
| **F1 净** | **-28** |

实际略低于原 -55 估算（因 Step 2/3 加载部分非全 25 行）。可接受。

行数目标：1016 → ~988。

---

## 6. 状态闭环

| 轮 | commit | 时间 | 状态 |
|---|--------|------|------|
| F1 | `1f65c8d` | 2026-06-16 | ✅ 已完成（_load_json_gz_data；smoke 5/5 通过；factor_generator.py 1016→1013）|
| F2 | (本 commit) | 2026-06-16 | ✅ 已完成（_write_factor_json_gz；smoke 6/6 通过；factor_generator.py 1013→? ）|

---

## 7. F2 设计补充

### 7.1 现状

Step 13 共 82 行（行 812-893），结构：
- mkdir 父目录 try/except（5 行）
- 流式写入主循环（45 行，含 `_nan_to_null` 闭包 11 行）
- **双 except 块**（OSError 5 行 + Exception 兜底 5 行，二者结构平行：error log + temp_path.unlink + raise RuntimeError）
- 收口日志（2 行）

重复模式：
- `temp_path.unlink(missing_ok=True)` 出现 2 次
- `logger.error("XX保存失败: %s, 原因: %s (%s)", output_path, type(e).__name__, str(e))` 出现 2 次
- `raise RuntimeError(f"XX: {output_path}, {type(e).__name__}: {e}") from e` 出现 2 次

### 7.2 helper 签名

```python
def _write_factor_json_gz(
    output_df: pd.DataFrame,
    output_path: Path,
    logger: logging.Logger,
    *,
    batch_size: int = 50000,
) -> None:
    """流式写出 factor_ic_data.json.gz（gzip + 临时文件 + 原子替换）。

    封装 Step 13 的写出逻辑：mkdir + 流式批写 + NaN→null + 临时文件原子替换。

    Args:
        output_df: 已对齐 _OUTPUT_COLS 的输出 DataFrame
        output_path: 目标输出路径
        logger: 日志器
        batch_size: 流式写入批次大小（默认 50000，约 200MB 内存峰值）

    Raises:
        RuntimeError: mkdir 失败 / 写入文件系统错误 / 未知错误（含原因 + 类型名）
    """
```

`_nan_to_null` 闭包 / `dates_list` 计算 / `total_records` 计算从 helper 内部完成。
调用处仅保留 `total_records = len(output_df)` 用于后续 metadata（避免 helper 返回值复杂化）。

### 7.3 调用点替换

```python
# Step 13: 保存输出
logger.info("Step 13: 保存输出...")
total_records = len(output_df)
_write_factor_json_gz(output_df, output_path, logger)
logger.info("  输出路径: %s", output_path)
logger.info("  输出记录数: %d", total_records)
```

### 7.4 不变量保证

| 项 | 重构前 | 重构后 | 验证 |
|----|--------|--------|------|
| gzip 流式写入 batch_size | 50000 | 50000（默认参数）| 字符级一致 |
| JSON 头/尾 / 逗号分隔 | `{"dates": ...,"data":[...]}` | 字符级一致 | byte 级 diff |
| NaN/inf → null | _nan_to_null 闭包 | helper 内 module-level fn | 行为一致 |
| dates 排序 | 字符串 sorted | 字符串 sorted | 一致 |
| 临时文件 + os.replace 原子 | temp_path = .tmp 后缀 | 一致 | 一致 |
| OSError 异常消息 | `"文件系统错误: {path}, {type}: {e}"` | 字符级一致 | unit smoke |
| Exception 兜底消息 | `"未知错误保存失败: {path}, {type}: {e}"` | 字符级一致 | unit smoke |
| mkdir 失败消息 | `"创建输出目录失败: {parent}, {type}: {e}"` | 字符级一致 | unit smoke |
| logger.error 调用次数 | 1~2 次（按异常路径）| 一致 | mock 验证 |
| temp_path 失败时清理 | unlink(missing_ok=True) | 一致 | unit smoke |

### 7.5 异常处理简化（关键决定）

**保留双 except 块**而非合并：
- OSError 与 Exception 兜底**消息文案不同**（"文件系统错误" vs "未知错误保存失败"），合并会改变错误消息字符串
- 用 try/finally 管理 temp_path 清理理论可行，但需在 finally 内判断异常类型决定是否 unlink，反而更复杂
- 共同后置动作（unlink + raise）抽 inline helper 可消除 6 行重复，但代价是堆栈层数变深，反而难调试

**结论**：双 except 结构原样保留在 helper 内，只是从 generate_all_factors 移到 helper。这本身就是结构价值——主流程函数从 82 行的低层 I/O 散乱细节中解放。

### 7.6 行数预算

| 项 | 增/减 |
|----|------|
| 新增 `_write_factor_json_gz`（含 docstring + 闭包）| +75 |
| `_nan_to_null` 提到模块级（_calc_pct 后）| +14 |
| Step 13 段 82 行 → 5 行 | -77 |
| **F2 净** | **+12** |

⚠️ 行数实际接近 0 净变。F2 价值在**结构**（generate_all_factors 主体瘦身）：
- 主函数 612-957（345 行）→ 612-880（约 268 行）
- I/O 细节集中到 helper，主流程只剩 Step 编号节奏

### 7.7 验证清单

- [ ] ruff check / format
- [ ] 包导入 + helper 导出
- [ ] pytest --collect-only
- [ ] temporary/f2_write_helper_smoke.py：6 个场景
  - [ ] 正常写出 + gzip 解压 + JSON 解析往返
  - [ ] NaN → null 转换正确
  - [ ] inf / -inf → null 转换正确
  - [ ] 多批次（batch_size=2，> 2 行触发批边界）
  - [ ] OSError → RuntimeError + temp 清理
  - [ ] mkdir 失败 → RuntimeError + 父目录路径
- [ ] D3 mock pipeline smoke 仍通过（如有）

---

## 8. 后续建议

F2 完成后 factor_generator.py 仍约 1025 行。**进一步瘦身收益递减**：
- 剩余可探索：generate_all_factors docstring 精简、metadata 段注释合并到 dict comprehension 上方、`_calc_pct` 是否可 inline
- 但**主流程已表驱动 + helper 化**，进一步行数压缩边际价值低
- 建议 F2 收口后停止 factor_generator.py 瘦身工作，转其他模块（factor_ic / comprehensive_factor）

最终目标修订：原 580 行不现实，实际可达约 1000 行（D+F1+F2 后）。
**真正的成果**不是行数，而是新增因子从「3 处编辑 + 25 行 boilerplate」→「表里 +1 行」。

---

## 7. 验证清单

- [ ] ruff check / format
- [ ] 包导入 + 启动期校验
- [ ] pytest --collect-only
- [ ] temporary/f1_load_helper_smoke.py：4 个场景
  - [ ] 正常加载 gzip JSON
  - [ ] FileNotFoundError 透传 + 消息格式
  - [ ] gzip.BadGzipFile → ValueError + logger.error 调用
  - [ ] JSONDecodeError → ValueError + 行列信息
  - [ ] 缺少 'data' 字段 → ValueError
