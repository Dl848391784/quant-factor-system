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
| F1 | — | — | 待执行（本 commit）|
| F2 | — | — | 下一轮（write helper，预算 -50）|

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
