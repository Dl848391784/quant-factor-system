# Factor IC Analyzer — 代码规范与项目文档

> 本文档对 AI 智能体与人类开发者均适用。每条编码规则采用统一框架:**What / Why / How / Don't / When / Verify**。
>
> **harness 中立约定**:本规范不绑定任何特定智能体平台,描述的"读取、写入、调用工具"均为通用语义,不依赖具体 harness 的专属功能。

---

## 目录

### 代码规则 (20 条)
- **A. 导入与模块结构**
  - [R1. `__main__` 块用法](#r1-__main__-块用法)
  - [R2. 条件导入合并](#r2-条件导入合并)
- **B. 常量管理**
  - [R3. 常量显式定义,禁切片索引](#r3-常量显式定义禁切片索引)
  - [R4. 模块级常量用 tuple](#r4-模块级常量用-tuple)
  - [R5. 常量引用关系](#r5-常量引用关系)
  - [R6. 可变对象返回副本](#r6-可变对象返回副本)
  - [R7. 常量注释放定义处](#r7-常量注释放定义处)
  - [R8. pandas 列选择 list 转换](#r8-pandas-列选择-list-转换)
- **C. 异常与错误处理**
  - [R9. docstring Raises 与实际一致](#r9-docstring-raises-与实际一致)
  - [R10. 异常日志含类型名](#r10-异常日志含类型名)
  - [R11. 错误信息含上下文](#r11-错误信息含上下文)
  - [R12. 兜底块异常信息完整](#r12-兜底块异常信息完整)
- **D. 文件 IO**
  - [R13. 原子文件写入完整流程](#r13-原子文件写入完整流程)
  - [R14. 临时文件清理用 missing_ok](#r14-临时文件清理用-missing_ok)
- **E. 计算与内存**
  - [R15. 百分比计算显式除零保护](#r15-百分比计算显式除零保护)
  - [R16. 大对象显式 del 释放](#r16-大对象显式-del-释放)
  - [R17. 大规模面板禁用 `groupby.transform`,改用 `_per_asset_transform`](#r17-大规模面板禁用-groupbytransform改用-_per_asset_transform)
- **F. 类型注解与文档**
  - [R18. 泛型类型注解 (3.9+)](#r18-泛型类型注解-39)
  - [R19. 类型注解兼容性 Note](#r19-类型注解兼容性-note)
  - [R20. docstring Example 规范](#r20-docstring-example-规范)
- **G. 框架兼容**
  - [R21. pandas 3.0 用 transform](#r21-pandas-30-用-transform)

### 项目结构与约定
- [paths.py 使用规范](#pathspy-使用规范)
- [输出目录规范](#输出目录规范)
- [模块边界规范](#模块边界规范)

### 模块文档
- [factor_generator.py](#factor_generatorpy)
- [缓存格式](#缓存格式)
- [因子计算参数](#因子计算参数)

### 其他
- [待补充](#待补充)
- [版本历史](#版本历史)

---

## 代码规则

> **规则模板说明**:
> - **What** —— 规则本身,一句话可概括
> - **Why** —— 为什么这么做(背后的原因 / 解决的问题)
> - **How** —— 正例代码
> - **Don't** —— 反例代码
> - **When** —— 适用场景(哪些时候必须遵守)
> - **Verify** —— 如何验证规则遵守(自动化检查 / 人工 review 检查项)

---

### A. 导入与模块结构

#### R1. `__main__` 块用法

**What**:`if __name__ == '__main__'` 块只放 CLI 入口 `sys.exit(main())`,不在其中重新导入本模块自己定义的函数,也不直接写测试代码。

**Why**:
- 在 `__main__` 上下文中,`from xxx_module import func` 会触发该模块以 `xxx_module` 名称二次导入,造成模块被执行两次(循环/重复行为)
- 测试代码混在 `__main__` 块会让 CLI 入口臃肿、不可独立运行
- 测试脚本独立后才能被 CI/CD 调度

**How**:
```python
def main():
    # CLI 逻辑

if __name__ == '__main__':
    import sys
    sys.exit(main())
```

**Don't**:
```python
# ❌ 重新导入自己 → 循环导入
if __name__ == '__main__':
    from data_fetchers.factor_generator import generate_all_factors
    metadata = generate_all_factors(logger=test_logger)

# ❌ 测试代码塞在 __main__ 块
if __name__ == '__main__':
    test_logger = setup_logger(...)
    metadata = generate_all_factors(logger=test_logger)
    # ... 60 行测试代码 ...
```

**When**:所有有 `__main__` 块的脚本(CLI 入口模块、有自测试块的模块)。

**Verify**:
- 人工 review:`__main__` 块行数应 ≤ 5 行
- 测试代码必须存在于 `<模块>/test_cases/test_xxx.py`

---

#### R2. 条件导入合并

**What**:文件中所有 `if __name__ == '__main__' / else:` 条件导入块必须合并到文件顶部一处;底部 CLI `__main__` 块不重复导入已在顶部导入过的模块。

**Why**:
- PEP 8 要求 import 在文件顶部;条件导入散落在文件中间违反规范
- 顶部已导入的模块在同一执行路径内可见,底部重复导入是冗余
- 修改导入时只需改一处,减少漂移

**How**:
```python
# 文件顶部:所有条件导入合并
if __name__ == '__main__':
    import sys
    sys.path.insert(0, str(project_root))
    from xxx import func_a
    from xxx import func_b
else:
    from .xxx import func_a
    from .xxx import func_b

# ... 中间是定义 ...

# 文件底部:CLI 入口,不重复 import sys
if __name__ == '__main__':
    sys.exit(main())
```

**Don't**:
```python
# ❌ 条件导入散在文件中间
if __name__ == '__main__':
    from xxx import func_a
else:
    from .xxx import func_a

# ... 几十行代码后 ...

if __name__ == '__main__':
    from xxx import func_b  # 违反 PEP 8
else:
    from .xxx import func_b
```

**When**:任何用 `if __name__ == '__main__'` 做相对/绝对导入切换的模块。

**Verify**:
- ruff `E402` (module level import not at top of file)
- 人工 review:全文件 `grep -c "^if __name__"` 应 ≤ 2 (顶部条件导入 + 底部 CLI)

---

### B. 常量管理

#### R3. 常量显式定义,禁切片索引

**What**:常量必须显式定义为模块级私有变量 (`_PREFIX`),禁止用切片索引 (`output_cols[8:]`) 从其他列表派生,也禁止用局部变量做无意义的别名 (`output_cols = _OUTPUT_COLS`)。

**Why**:
- 切片索引依赖列表顺序,列顺序一变就索引错位,排错困难
- 无意义别名增加复杂度、维护时需改多处
- 显式命名让常量语义自描述

**How**:
```python
# ✅ 显式命名
_EXTENDED_FACTOR_COLS = ('bollinger_pb', 'kdj_j', 'turnover_surge')
metadata['factor_columns'] = list(_EXTENDED_FACTOR_COLS)

# ✅ 直接用常量,不要别名
missing_cols = [c for c in _OUTPUT_COLS if c not in df.columns]
```

**Don't**:
```python
# ❌ 切片索引 → 脆弱
output_cols = ['date', 'asset', 'open', 'close', 'high', 'low', 'rsi_6', 'volume_ratio_5', ...]
metadata['factor_columns'] = output_cols[8:]  # 依赖顺序

# ❌ 无意义别名
output_cols = _OUTPUT_COLS  # 别名,纯冗余
missing_cols = [c for c in output_cols if c not in df.columns]
```

**When**:任何模块级列名/字段名/键名常量;只要被使用 2 次以上就该提常量。

**Verify**:
- 人工 review:`grep -E "[a-z_]+\[[0-9]+:\]" *.py` 看是否有切片派生常量
- ruff 没有原生规则,建议自定义 AST 检查

---

#### R4. 模块级常量用 tuple

**What**:模块级常量列表必须用 `tuple` 而非 `list`,且加泛型类型注解 `tuple[str, ...]` (Python 3.9+)。

**Why**:
- `tuple` 是不可变对象,防止任何位置意外 `.append()`/`.remove()` 修改模块状态
- 泛型注解让类型检查器能推断元素类型
- 修改受控:必须重新赋值整个常量,review 时容易发现

**How**:
```python
# ✅ tuple + 泛型注解
_EXTENDED_FACTOR_COLS: tuple[str, ...] = ('bollinger_pb', 'kdj_j', 'turnover_surge')
_BASE_COLS: tuple[str, ...] = ('date', 'asset', 'open', 'close', 'high', 'low')
_OUTPUT_COLS: tuple[str, ...] = _BASE_COLS + _EXTENDED_FACTOR_COLS  # tuple 相加仍是 tuple
```

**Don't**:
```python
# ❌ list 可变,可能被意外修改
_EXTENDED_FACTOR_COLS = ['bollinger_pb', 'kdj_j', 'turnover_surge']
_EXTENDED_FACTOR_COLS.append('new')  # 模块状态被修改,影响全局

# ❌ 注解只写 tuple,无元素类型
_EXTENDED_FACTOR_COLS: tuple = ('bollinger_pb', 'kdj_j', 'turnover_surge')
```

**When**:所有模块级 (顶层) 的列名/字段名/字符串列表常量。

**Verify**:
- 人工 review:模块级 `_PREFIX = [...]` 应改为 `_PREFIX: tuple[str, ...] = (...)`
- mypy / pyright 可捕获 `tuple[str, ...]` 元素类型违例

---

#### R5. 常量引用关系

**What**:多个相关常量必须建立引用关系 (一处定义、其他处引用),禁止各自重复硬编码同一份内容。

**Why**:
- 重复硬编码 → 新增/修改时必须同步改多处,极易遗漏
- 引用关系让"唯一来源"清晰,改一处全更新

**How**:
```python
# ✅ 引用链清晰
_EXTENDED_FACTOR_COLS: tuple[str, ...] = ('bollinger_pb', 'kdj_j', 'turnover_surge')
_BASE_COLS: tuple[str, ...] = ('date', 'asset', 'open', 'close', 'high', 'low', 'rsi_6', 'volume_ratio_5')
_OUTPUT_COLS: tuple[str, ...] = _BASE_COLS + _EXTENDED_FACTOR_COLS

metadata['factor_columns'] = list(_EXTENDED_FACTOR_COLS)  # 引用,不重复硬编码
```

**Don't**:
```python
# ❌ 各自硬编码同一份内容
_EXTENDED_FACTOR_COLS = ('bollinger_pb', 'kdj_j', 'turnover_surge')
output_cols = ['date', 'asset', ..., 'bollinger_pb', 'kdj_j', 'turnover_surge']  # 硬编码
metadata['factor_columns'] = ['bollinger_pb', 'kdj_j', 'turnover_surge']         # 再次硬编码
```

**When**:任何"扩展集合 + 基础集合 → 总集合"的派生场景;新增因子/字段时尤其要检查。

**Verify**:
- 人工 review:`grep` 同一份字面量列表是否出现多次,出现 2 次以上即违规

---

#### R6. 可变对象返回副本

**What**:返回模块级可变对象 (即使源是 tuple,转 list 后) 必须返回副本,不返回原引用。

**Why**:
- 模块级常量是单例,直接返回引用让调用方能修改你的内部状态
- 副本隔离让调用方做什么都不影响模块本身
- 即使源是 tuple,转 list 时也是新 list,无引用问题;但如果源就是 list,必须 `.copy()` 或 `list(src)`

**How**:
```python
# ✅ tuple 源 → list() 转换天然产生新对象
metadata['factor_columns'] = list(_EXTENDED_FACTOR_COLS)

# ✅ list 源 → 显式 .copy()
metadata['factor_columns'] = _EXTENDED_FACTOR_COLS_LIST.copy()
```

**Don't**:
```python
# ❌ 返回 list 引用
_EXTENDED_FACTOR_COLS = ['bollinger_pb', 'kdj_j', 'turnover_surge']
metadata['factor_columns'] = _EXTENDED_FACTOR_COLS  # 调用方 .append() 会污染模块常量
```

**When**:任何函数/方法返回模块级 list / dict / set 时;遵守 R4 用 tuple 后,只需 `list(tuple)` 转换。

**Verify**:
- 人工 review:函数 `return _MODULE_VAR` 形式即违规 (除非 _MODULE_VAR 是 tuple/frozenset 等不可变对象)

---

#### R7. 常量注释放定义处

**What**:常量的结构说明 (如各索引位置含义、字段语义) 必须放在定义处;使用处只允许简短一行说明。

**Why**:
- 注释和定义分离 → 修改常量时容易漏改注释,产生说谎注释
- 维护者去使用处才能看懂常量结构 → 增加阅读跳转成本

**How**:
```python
# ✅ 注释在定义处
_OUTPUT_COLS: tuple[str, ...] = _BASE_COLS + _EXTENDED_FACTOR_COLS
# 结构说明:
# _OUTPUT_COLS[0:2]  = date, asset       (索引字段)
# _OUTPUT_COLS[2:6]  = open, close, high, low (行情数据)
# _OUTPUT_COLS[6:8]  = rsi_6, volume_ratio_5 (基础因子)
# _OUTPUT_COLS[8:]   = 扩展因子(见 _EXTENDED_FACTOR_COLS)

def func():
    output_cols = _OUTPUT_COLS  # 见定义处结构说明
```

**Don't**:
```python
# ❌ 定义处无注释,注释散在使用处
_OUTPUT_COLS: tuple[str, ...] = _BASE_COLS + _EXTENDED_FACTOR_COLS

def func():
    # _OUTPUT_COLS[0:2]  = date, asset
    # _OUTPUT_COLS[2:6]  = open, close, high, low
    output_cols = _OUTPUT_COLS
```

**When**:常量结构复杂 (索引位置有语义、字段分组) 时;简单单一字段常量无需此规则。

**Verify**:人工 review

---

#### R8. pandas 列选择 list 转换

**What**:用 pandas `DataFrame[cols]` 选列时,如果 `cols` 是 tuple,必须用 `list(cols)` 转换后再传入。

**Why**:
- pandas 对 `df[tuple]` 的语义可能是 MultiIndex 查询而非列名列表
- pandas 对 `df[list]` 的语义明确是列名列表
- 迭代场景 (`for c in cols`) 不受影响,tuple 和 list 行为一致

**How**:
```python
# ✅ 列选择:tuple 转 list
_OUTPUT_COLS: tuple[str, ...] = ('date', 'asset', 'open', 'close')
output_df = df[list(_OUTPUT_COLS)].copy()

# ✅ 迭代:tuple 直接用
for col in _OUTPUT_COLS:
    if col not in df.columns:
        ...
```

**Don't**:
```python
# ❌ 直接传 tuple → 兼容性问题
output_df = df[_OUTPUT_COLS].copy()  # 可能被解释为 MultiIndex
```

**When**:常量定义用 tuple (R4) 后,凡是用作 pandas 列选择的场景。

**Verify**:
- 人工 review:`grep -E "df\[_[A-Z_]+\]" *.py` 找 `df[_CONSTANT]`,确认 _CONSTANT 是 list 而非 tuple

---

### C. 异常与错误处理

#### R9. docstring Raises 与实际一致

**What**:docstring `Raises:` 章节只列出调用方实际能收到的异常 —— 已在函数内部 `except ... raise XxxError from e` 转换过的异常不要列;函数实现里不会主动 raise 的异常也不要列。

**Why**:
- 列出已被内部捕获转换的异常 → 误导调用方写不可能命中的 `except`
- 列出未实现场景的异常 → 调用方按文档加防御,但其实根本不会触发

**How**:
```python
def generate_all_factors(...):
    """
    Raises:
        FileNotFoundError: 输入数据文件不存在
        ValueError: 数据格式不正确 (含 JSON 解析失败,已内部转换)
        RuntimeError: 文件系统错误

    Note:
        - JSONDecodeError 已在内部捕获并转为 ValueError,调用方收到 ValueError
    """
    try:
        data = json.load(f)
    except json.JSONDecodeError as e:
        raise ValueError(...) from e  # 转换 → 调用方收到 ValueError
```

**Don't**:
```python
def generate_all_factors(...):
    """
    Raises:
        json.JSONDecodeError: JSON 解析失败  # ❌ 已被转换,调用方永远收不到
        ValueError: 数据格式 / 或输入数据为空  # ❌ "输入数据为空"代码无对应检查
    """
```

**When**:任何带 docstring `Raises:` 的函数。新增/删除 raise 语句时必须同步更新 Raises。

**Verify**:
- 人工 review:对每条 Raises 项,搜索函数体内是否真的有对应 raise / 是否被内部转换
- 自动化:可写脚本扫描 `raise X` vs docstring `X:` 一致性(待实施)

---

#### R10. 异常日志含类型名

**What**:`logger.error/warning/exception` 记录异常时必须包含 `type(e).__name__`。

**Why**:
- 只有 `str(e)` 时不知道是 ValueError 还是 RuntimeError,排错时要再回去看堆栈
- 异常类型名是定位问题最快的线索

**How**:
```python
except Exception as e:
    logger.error("执行失败 [%s]: %s", type(e).__name__, str(e))
```

**Don't**:
```python
except Exception as e:
    logger.error("执行失败: %s", str(e))  # 缺少类型名
```

**When**:所有 `except` 块的日志记录。`logger.exception()` 自带堆栈可豁免,但加上类型名仍推荐。

**Verify**:
- ruff/自定义 AST 检查:扫 `logger\.(error|warning|critical).*str\(e\)` 但缺 `type(e).__name__` 的行

---

#### R11. 错误信息含上下文

**What**:`raise` 的错误信息必须包含上下文提示 —— 当前值、期望值、可能的修复方向。

**Why**:
- 模糊的错误信息让调用方排错路径长 (需翻源码 → 翻文档 → 复现)
- 上下文丰富的错误信息直接给出修复方向,显著降低排错时间

**How**:
```python
if missing_cols:
    raise KeyError(
        f"输出列不存在: {missing_cols}, "
        f"请检查因子计算函数的输出列名是否与 _EXTENDED_FACTOR_COLS 一致"
    )
```

**Don't**:
```python
if missing_cols:
    raise KeyError(f"输出列不存在: {missing_cols}")  # 缺上下文,不知道为什么不存在
```

**When**:所有主动 raise 的异常 (R12 兜底块例外,见下)。

**Verify**:人工 review:每条 raise 至少包含 (1) 出错的具体值 (2) 可能的原因或修复方向

---

#### R12. 兜底块异常信息完整

**What**:兜底 `except Exception as e` 块的错误信息必须包含 `type(e).__name__` 和 `str(e)`。

**Why**:
- 兜底块意味着"未预料的异常",信息越完整越有助于事后定位
- 与 R10 (日志) 配套:抛出和日志都要类型 + 详情

**How**:
```python
except Exception as e:
    raise RuntimeError(
        f"未知错误: {path}, {type(e).__name__}: {e}"
    ) from e
```

**Don't**:
```python
except Exception as e:
    raise RuntimeError(f"未知错误: {path}") from e  # 缺少类型和详情
```

**When**:所有兜底 `except Exception` 块。窄异常 (如 `except FileNotFoundError`) 不受此约束 (类型已显式)。

**Verify**:人工 review:`grep -n "except Exception" *.py` 后逐个看 raise 信息

---

### D. 文件 IO

#### R13. 原子文件写入完整流程

**What**:写入文件时遵循"两阶段、分职责、失败可清理"的完整流程:
1. **阶段一**:单独的 try 块,只做 `parent.mkdir(parents=True, exist_ok=True)`
2. **阶段二**:mkdir 成功后才定义 `temp_path`,单独的 try 块,做 写临时文件 + `os.replace(temp, final)`,失败时 `temp_path.unlink(missing_ok=True)`

**Why**:
- mkdir 和写入混在一个 try → 异常信息无法区分是目录创建失败还是写入失败
- temp_path 定义在 mkdir 之前 → mkdir 失败时 `temp_path.unlink()` 的路径可能根本不该存在 (语义混乱)
- 不调 mkdir 直接写 → 父目录不存在时 FileNotFoundError
- 不用 temp + os.replace → 写到一半进程崩溃时留下半成品

**How**:
```python
# 阶段一:mkdir 单独 try
try:
    output_path.parent.mkdir(parents=True, exist_ok=True)
except OSError as e:
    raise RuntimeError(f"创建输出目录失败: {output_path.parent}, {type(e).__name__}: {e}") from e

# 阶段二:mkdir 成功后才定义 temp_path,单独 try
temp_path = output_path.parent / (output_path.name + '.tmp')
try:
    with gzip.open(temp_path, 'wt') as f:
        json.dump(data, f)
    os.replace(temp_path, output_path)  # 原子替换
except OSError as e:
    temp_path.unlink(missing_ok=True)  # 清理,见 R14
    raise RuntimeError(f"文件系统错误: {output_path}, {type(e).__name__}: {e}") from e
```

**Don't**:
```python
# ❌ mkdir 在 try 块外 → 异常无法统一处理
output_path.parent.mkdir(parents=True, exist_ok=True)
temp_path = output_path.parent / (output_path.name + '.tmp')
try:
    with open(temp_path, 'w') as f:
        json.dump(data, f)
except OSError as e:
    pass  # mkdir 异常根本不会进这里

# ❌ mkdir 和写入混在一个 try → 异常信息无法区分职责
temp_path = output_path.parent / (output_path.name + '.tmp')  # mkdir 未执行就定义
try:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(temp_path, 'wt') as f:
        json.dump(data, f)
except OSError as e:
    temp_path.unlink(missing_ok=True)  # 不知道是 mkdir 还是写入失败
```

**When**:所有持久化文件写入 (输出产物、缓存、报告)。临时/调试输出 (走 stderr) 不受约束。

**Verify**:
- 人工 review checklist:
  - [ ] mkdir 有独立 try 块
  - [ ] temp_path 在 mkdir 之后定义
  - [ ] 用了 `os.replace` 而非直接 `open(final_path)`
  - [ ] 写入失败时 unlink 临时文件

---

#### R14. 临时文件清理用 missing_ok

**What**:删除可能不存在的临时文件用 `path.unlink(missing_ok=True)`,不要 `if path.exists(): path.unlink()`。

**Why**:
- `exists() + unlink()` 有 TOCTOU (Time-of-check-to-time-of-use) 竞争窗口:检查后、删除前,文件可能被其他进程删掉,导致 FileNotFoundError
- `missing_ok=True` 是原子操作,无竞争窗口

**How**:
```python
temp_path.unlink(missing_ok=True)  # 原子,文件不存在不报错
```

**Don't**:
```python
if temp_path.exists():
    temp_path.unlink()  # 竞争窗口:exists() 后文件可能被其他进程删除
```

**When**:所有清理可能不存在的临时文件场景 (异常处理中的清理、重试前的清理)。

**Verify**:
- 人工 review:`grep -E "\.exists\(\).*unlink|exists\(\):\s*$" *.py`
- Python 版本要求:3.8+

---

### E. 计算与内存

#### R15. 百分比计算显式除零保护

**What**:任何 `count / total * 100` 形式的百分比计算必须封装在模块级私有函数 `_calc_pct` 中,显式检查 `total <= 0`。

**Why**:
- 空数据时 `total = 0` 直接抛 `ZeroDivisionError`
- 内嵌的辅助函数 (函数内 def) 闭包作用域混乱,且不可复用
- 提为模块级私有函数 → 单独可测、复用清晰

**How**:
```python
# 模块级私有
def _calc_pct(valid_count: int, total_count: int) -> float:
    """计算百分比,total 为 0 时返回 0.0"""
    if total_count <= 0:
        return 0.0
    return round(valid_count / total_count * 100, 2)

# 调用方
logger.info("有效记录: %d (%.2f%%)", valid, _calc_pct(valid, total))
```

**Don't**:
```python
# ❌ 函数内嵌套定义 → 作用域混乱、不可复用
def generate_all_factors(...):
    # ... 几十行 ...
    def calc_pct(valid_count):
        return round(valid_count / total * 100, 2) if total > 0 else 0.0  # 闭包了 total
```

**When**:任何百分比/比例计算 (有效率、缺失率、命中率等)。

**Verify**:
- 人工 review:`grep -E "/\s*[a-z_]+_count.*\*\s*100|/ total.*\* 100" *.py` 找未保护的百分比计算

---

#### R16. 大对象显式 del 释放

**What**:大 DataFrame / 大字典 / 中间数据在用完后必须立即 `del`,不要等函数自然结束才释放。

**Why**:
- 函数执行期间大对象一直占内存,峰值可能爆掉
- merge / 中间列处理后,源 DataFrame 通常不再需要
- 显式 del 让 Python GC 立即回收

**How**:
```python
# ✅ 中间列处理后立即释放
output_df = factor_df[output_cols].copy()
del factor_df  # 包含中间列,已不需要

# ✅ merge 后释放源
factor_df = factor_df.merge(turnover_df[['date', 'asset', 'turnover_rate']], ...)
del turnover_df
```

**Don't**:
```python
# ❌ 源 DataFrame 驻留到函数结束
output_df = factor_df[output_cols].copy()
# factor_df 未释放,继续吃内存

factor_df = factor_df.merge(turnover_df[...], ...)
# turnover_df 也未释放
```

**When**:
- 处理 ≥ 100MB DataFrame 时
- 内存敏感场景 (单机大数据、长时间运行的 worker)
- 不适用于小数据 (< 10MB) 或短生命周期函数

**Verify**:人工 review:对包含 `merge` / `groupby` / `pivot` 的函数,检查中间 DataFrame 是否在用完后 del

---

#### R17. 大规模面板禁用 `groupby.transform`,改用 `_per_asset_transform`

**What**:在大规模面板数据 (>1M 行 × >1k group) 上,`df.groupby(asset)[col].transform(fn)` 必须替换为 `data_fetchers.factor_calculator._per_asset_transform`。

**Why**:
- pandas 的 `groupby.transform` 内部为对齐 group 索引会构建多份中间结构 (group key 重复、临时索引、对齐缓冲),在 1.5M 行 × 1.4k asset 数据上峰值可达 4 GB+
- 实测 `calculate_rsi_df` 旧实现在 RSI 分层回测中触发 OOM (anon-rss 4.21 GB,SIGKILL by oom-killer,2026-06-13)
- `_per_asset_transform` 用 numpy 边界切片逐 asset 调用 fn,内存增量仅 ~36 MB (一份 float64 输出)

**How**:
```python
from data_fetchers.factor_calculator import _per_asset_transform

# ✅ 推荐:helper 假设 asset 已排序,内存友好
factor_df = factor_df.sort_values(["asset", "date"])
result_arr = _per_asset_transform(
    asset_arr=factor_df["asset"].to_numpy(),
    value_arr=factor_df["close"].to_numpy(),
    fn=lambda s: s.rolling(window=20).mean(),
)
factor_df["bollinger_ma"] = result_arr
```

**Don't**:
```python
# ❌ 大面板上的 transform → OOM 风险
factor_df["bollinger_ma"] = factor_df.groupby("asset", group_keys=False)["close"].transform(
    lambda x: x.rolling(window=20).mean()
)
```

**When**:
- 任何 `groupby.transform(rolling/ewm/shift/diff/cumsum)` 调用,数据规模 >100k 行
- 因子计算管线的 panel-level 滚动统计 (Bollinger / KDJ / RSI / Turnover / Momentum 等)
- **不适用**:小数据 (< 10k 行) 或聚合操作 (`groupby.agg/sum/mean`,这类无对齐开销)

**前置约束**:`asset_arr` 必须已按 asset 排序 (同 asset 行连续)。若调用方未排序,需在调用前 `sort_values(["asset", "date"])`,处理后用 `factor_df.loc[original_index]` 恢复原顺序 (参考 `calculate_turnover_surge` 实现)。

**Verify**:
- `pytest data_fetchers/test_cases/test_per_asset_transform.py` 验证 5 处实际重构点 (Bollinger / KDJ / Turnover / Momentum / RSI) 与 `groupby.transform` 位级等价
- `grep -n "groupby.*transform" data_fetchers/factor_calculator.py` 不应再出现 (rolling / ewm 类),保留的只能是聚合用的 `transform("count")` 等
- 实测:`/usr/bin/time -v python -m backtest.layered_backtest_rsi_1d` 的 `Maximum resident set size` 应 < 1.5 GB

**典型案例** (2026-06-13):
- `factor_calculator.py` 5 处 `groupby.transform`(`Bollinger pb` 滚动均值/标准差、`KDJ J` rolling min/max + EWM K/D、`turnover_surge` shift+rolling、`momentum_strength` rolling std)
- RSI 分层回测 OOM (4.16 GB → 901 MB,降 78%) 后系统化重构,通过 `test_per_asset_transform.py` 11 个等价性测试保护
- 新增 helper `_per_asset_transform` (factor_calculator.py:469) 作为统一入口

---

### F. 类型注解与文档

#### R18. 泛型类型注解 (3.9+)

**What**:容器类型注解必须用泛型形式 `tuple[str, ...]` / `list[int]` / `dict[str, float]`,不用裸 `tuple` / `list` / `dict`。

**Why**:
- 裸 `tuple` 不告诉类型检查器元素是什么类型
- 泛型注解让 mypy / pyright 能推断元素类型,提早发现错误

**How**:
```python
_EXTENDED_FACTOR_COLS: tuple[str, ...] = ('bollinger_pb', 'kdj_j', 'turnover_surge')
_PARAMS: dict[str, float] = {'window': 5.0, 'threshold': 2.0}
```

**Don't**:
```python
_EXTENDED_FACTOR_COLS: tuple = ('bollinger_pb', 'kdj_j', 'turnover_surge')  # 元素类型未知
```

**When**:Python 3.9+ 项目所有容器类型注解。Python < 3.9 用 `Tuple[str, ...]` (from typing)。

**Verify**:mypy / pyright 配置 `--strict` 即可捕获

---

#### R19. 类型注解兼容性 Note

**What**:当类型注解为 `int` 但实际接受 `numpy.int64` / `float` 等兼容类型时,在 docstring `Note:` 中显式说明。

**Why**:
- Python 运行时不强制类型检查,注解只是给静态分析用
- 静态分析器看到 `int` 注解时,可能对传入 `numpy.int64` 的调用报警
- Note 说明能让阅读者理解为什么注解和实际接受类型不一致

**How**:
```python
def _calc_pct(count: int, total: int) -> float:
    """
    计算百分比

    Note:
        - 类型注解为 int,但实际接受 int / numpy.int64 / float 等数值类型
        - Python 运行时不强制类型检查,注解仅为静态分析提供参考
    """
```

**Don't**:
```python
def _calc_pct(count: int, total: int) -> float:
    """..."""  # 未说明,静态分析可能误报
```

**When**:函数参数注解为基础类型但实际接受 numpy / pandas 兼容类型时。

**Verify**:人工 review:对接收 DataFrame 列值 / numpy 数组元素的函数,检查 Note 是否说明

---

#### R20. docstring Example 规范

**What**:docstring `Example:` 章节遵循三条:
1. **注释位置**:注释放在 `>>>` 行末,不放在返回值行
2. **依赖标记**:需要外部依赖 (数据文件、网络) 才能运行的示例,显式标注"非运行示例 (XXX 依赖)"
3. **示例值**:不确定的值 (耗时、数据量) 用范围或描述,不用具体数字

**Why**:
- 注释放返回值行会污染 doctest 比对
- 不标记依赖 → doctest 直接失败
- 具体耗时值 (`120.5` 秒) 在不同数据量下差异巨大 (单测可能 < 1ms),会误导

**How**:
```python
"""
Example:
    # 以下为示例用法,非实际运行 (generate_all_factors 需要输入数据文件)
    >>> from data_fetchers.factor_generator import generate_all_factors
    >>> metadata = generate_all_factors()  # 需要 data_fetchers/result/*.json.gz

    >>> metadata['factor_columns']  # 返回列表副本,防止外部修改
    ['bollinger_pb', 'kdj_j', 'turnover_surge']
    >>> isinstance(metadata['elapsed_seconds'], float)  # 范围 0.0 ~ 数百秒,取决于数据量
    True
"""
```

**Don't**:
```python
"""
Example:
    >>> metadata = generate_all_factors()  # ❌ 未标记依赖,doctest 失败
    >>> metadata['factor_columns']
    ['bollinger_pb', 'kdj_j', 'turnover_surge']  # ❌ 注释放返回值行,污染比对
    >>> metadata['elapsed_seconds']
    120.5  # ❌ 具体值 → 单测耗时 < 1ms 时误导
"""
```

**When**:所有带 `Example:` 章节的 docstring。

**Verify**:
- 人工 review checklist:注释在 `>>>` 行末、有依赖时显式标注、不确定值用范围
- `pytest --doctest-modules` 跑通即可验证依赖标记是否到位

---

### G. 框架兼容

#### R21. pandas 3.0 用 transform

**What**:`groupby(...).rolling()` / `groupby(...).expanding()` 类操作必须用 `.transform(lambda x: x.rolling(...).mean())` 包裹,不直接赋值给 DataFrame 列。

**Why**:
- pandas 3.0 中 `groupby(group_keys=False).rolling()` 返回 MultiIndex Series
- 即使指定 `group_keys=False`,索引仍是 MultiIndex,直接赋值给 DataFrame 列报 `TypeError: incompatible index`
- `transform` 返回与原 DataFrame 一致的 RangeIndex,可直接赋值

**How**:
```python
# ✅ 用 transform 包裹
middle = factor_df.groupby('asset', group_keys=False)['close'].transform(
    lambda x: x.rolling(window=n).mean()
)
factor_df['middle'] = middle  # 成功赋值
```

**Don't**:
```python
# ❌ 直接调用 rolling
middle = factor_df.groupby('asset', group_keys=False)['close'].rolling(window=n).mean()
factor_df['middle'] = middle  # TypeError: incompatible index (pandas 3.0)
```

**When**:所有 groupby + 时间窗口聚合操作 (rolling / expanding / ewm),**且数据规模较小** (< 100k 行)。

**与 R17 的关系**:
- R17 (大规模面板禁用 `groupby.transform`) 适用于 >100k 行的因子计算管线 — 优先级**高于** R21
- R21 适用于小数据 + pandas 3.0 兼容性场景 (单元测试、配置类查询、小规模工具脚本)
- 大规模场景:`_per_asset_transform` 同样返回 RangeIndex 兼容的 ndarray,不存在 R21 描述的索引问题

**Verify**:
- 人工 review:`grep -E "groupby.*\)\.rolling" *.py` 找未包 transform 的调用
- pytest 在 pandas 3.0 环境下运行所有相关测试

---

## 项目结构与约定

### paths.py 使用规范

**强制规则**:开发前必须先检查模块的 `common/` 是否已有可复用函数,禁止重复实现。

```
❌ 目录下有 common/ 公共模块,脚本仍手写相同逻辑
❌ 公共模块已封装缓存读写,脚本自行实现 gzip 解压 + JSON 加载
❌ 公共模块已封装 API 调用,脚本自行实现 requests 请求
```

```
✅ 开发前先检查 common/ 是否有可复用函数
✅ 公共模块已封装的逻辑,直接调用,不重复实现
✅ 仅实现数据源特有的逻辑(API 参数、数据转换)
```

---

### 输出目录规范

**所有数据拉取结果输出到 `<模块>/result/`,不输出到脚本同级目录。**

| 数据类型 | 输出目录 | 文件格式 |
|----------|---------|----------|
| 因子数据 | `data_fetchers/result/` | `factor_ic_data.parquet` |
| 换手率数据 | `data_fetchers/result/` | `turnover_rate_data.json.gz` |
| 主力资金流 | `data_fetchers/result/` | `main_inflow_data.json.gz` |
| 市值数据（v1.0+） | `data_fetchers/result/` | `market_cap_data.json.gz` |

**禁止**:
```
❌ 输出到脚本同级目录(散乱,难管理)
❌ 日志输出到项目根目录的 logs/(应输出到模块级 logs/)
❌ 日志文件与脚本同级
```

**目录用途**:
- `<模块>/result/`:数据拉取产物 + 元信息 (拉取时间、数据范围、行数) + 数据质量报告
- `<模块>/logs/`:数据拉取日志 (API 调用记录、错误日志) + 因子生成日志 (计算进度、耗时统计)

---

### 模块边界规范

```
✓ factor_generator.py 独立运行(不依赖 factor_ic、backtest)
✓ 输出到 data_fetchers/result/
✓ 被 factor_ic 模块读取

❌ factor_generator.py 导入 factor_ic.common.*
❌ factor_generator.py 导入 backtest.common.*
```

---

### 配套文件规范

新建脚本时必须同步创建配套文件:

| 文件类型 | 位置 | 命名规则 | 示例 |
|---------|------|---------|------|
| 测试用例 | `<模块>/test_cases/` | `<脚本名>_test_cases.md` | `factor_generator_test_cases.md` |

**新建脚本 checklist**:
```
□ 创建脚本文件 (如 fetch_xxx.py)
□ 同步创建测试用例 (test_cases/fetch_xxx_test_cases.md)
```

---

## 模块文档

### factor_generator.py

**职责**:生成所有因子数据到缓存,提供单一数据源
**位置**:`data_fetchers/factor_generator.py`
**输出**:`data_fetchers/result/factor_ic_data.parquet`

**支持的因子**:

| 因子 | 列名 | 参数 | 数据依赖 |
|------|------|------|---------|
| RSI | rsi_6 | period=6 | close |
| Volume_Ratio | volume_ratio_5 | window=5 | volume |
| Bollinger_PB | bollinger_pb | n=20, k=2.0 | close |
| KDJ_J | kdj_j | n=9, m1=3, m2=3 | close, high, low |
| Turnover_Surge | turnover_surge | window=5 | turnover_rate, close |
| Industry_Momentum_5d | industry_momentum_5d | window=5 | close, stock_industry.json（行业映射） |
| Industry_Turnover_Trend | industry_turnover_trend | — | turnover_rate, stock_industry.json（行业映射） |
| Industry_Amplitude_Trend | industry_amplitude_trend | clip_lower=0.001 | amplitude, stock_industry.json（行业映射） |
| Intraday_Intensity | intraday_intensity | — | open, close, high, low |
| Tail_Price_Position | tail_price_position | — | tail_high, tail_low, prices, daily close/high/low（涨跌停判断） |
| Tail_Price_Slope | tail_price_slope | — | prices（13 根 5 分钟 K 线收盘价）|
| Tail_Price_Volume_Intensity | tail_price_volume_intensity | — | prices, volumes, volume |
| Tail_Volume_Acceleration | tail_volume_acceleration | — | volumes（13 根 5 分钟 K 线成交量）|
| Tail_Volume_Shrink | tail_volume_shrink | — | volumes, volume |

**行业方向性因子说明**（v1.42 2026-06-12 新增）：

**What**：行业层面趋势维度补充因子，衡量行业整体动量/换手率变化/振幅变化。

**How**：
1. `_add_industry_column()` 从 `stock_industry.json` 添加行业列，未知行业赋 '其他'
2. 按 (industry, date) 分组聚合 → 行业均值
3. 比率型/滚动型因子计算 → 同行业个股赋相同值

| 因子 | required_cols | 输出列名 | 公式 |
|------|--------------|---------|------|
| industry_momentum_5d | date, asset, close | industry_momentum_5d | 按(行业,日期)分组→mean(past_return_1d)→5日滚动均值 |
| industry_turnover_trend | date, asset, turnover_rate | industry_turnover_trend | turnover_avg(t)/turnover_avg(t-1)-1，clip(lower=0.001) |
| industry_amplitude_trend | date, asset, amplitude | industry_amplitude_trend | amplitude_avg(t)/amplitude_avg(t-1)-1，clip(lower=0.001) |

**Don't**：行业股票数 < 5 时该日期该行业因子值设 NaN；分母极小时 clip 保护避免极端比值。

**Why**：个股因子只捕捉截面差异，行业因子捕捉板块轮动信号。

**When**：综合因子组合需要行业维度补充时使用。

**Verify**：行业因子计算函数在 `factor_calculator.py` v1.15 中定义；IC 脚本实测 IC 值。

**输出结构**:
```json
{
  "dates": ["2024-04-19", "2024-04-20", ...],
  "data": [
    {
      "date": "2024-04-19",
      "asset": "000001",
      "open": 10.71, "close": 10.69, "high": 10.82, "low": 10.66,
      "rsi_6": 64.42, "volume_ratio_5": 0.74,
      "bollinger_pb": null, "kdj_j": null, "turnover_surge": null
    }
  ]
}
```

**使用方式**:
```bash
# CLI
python data_fetchers/factor_generator.py
```

```python
# Python API
import logging
from data_fetchers.factor_generator import generate_all_factors

# 默认 logger
metadata = generate_all_factors()

# 自定义 logger
logger = logging.getLogger('my_app')
metadata = generate_all_factors(logger=logger)
```

**数据一致性验证 (2026-05-24)**:
factor_generator.py 的因子计算逻辑从 IC 脚本迁移:
- `calculate_bollinger_pb()` ← `ic_bollinger_pb_1d.py`
- `calculate_kdj_j()` ← `ic_kdj_j_1d.py`
- `calculate_turnover_surge()` ← `ic_turnover_surge_1d.py`

验证结果:均值差异 < 0.000001;有效数据数一致;因子计算逻辑完全一致。

**下游模块依赖检查 (2026-06-03)**:

**What**: `factor_generator.py` 的 `_OUTPUT_COLS` 必须完整覆盖下游模块(factor_ic、comprehensive_factor)所需的所有字段,禁止遗漏导致反复调试。

**Why**: 
- 遗漏字段 → factor_ic 脚本报错 → 修复 → 重新运行 factor_generator.py → 反复调试
- 历史教训:volume 字段缺失导致 factor_ic 脚本运行失败,修复了 3 次

**How**:
新增因子或修改 `_OUTPUT_COLS` 时,必须检查:
1. `factor_ic/ic_*.py` 脚本 `factor_cols` 参数所列字段
2. `comprehensive_factor/` 脚本所需字段
3. 确保 `_OUTPUT_COLS` 包含所有下游依赖字段

**Verify**:
- [ ] 新增因子前,先检查 factor_ic 脚本是否依赖此字段
- [ ] 修改 `_OUTPUT_COLS` 后,运行 `python data_fetchers/factor_generator.py` 生成数据
- [ ] 运行 factor_ic 脚本验证数据完整性(无 KeyError)

---

### 缓存格式

**factor_data.json.gz (基础因子)**:
```json
{
  "dates": ["2024-04-19", ...],
  "data": [
    {"date": "2024-04-19", "asset": "000001",
     "open": 10.71, "close": 10.69, "high": 10.82, "low": 10.66,
     "rsi_6": 64.42, "volume_ratio_5": 0.74}
  ]
}
```

**factor_ic_data.parquet (统一数据源)**:包含所有 5 个因子 (见 factor_generator.py 输出结构)

**turnover_rate_data.json.gz**:
```json
{
  "data": [
    {"date": "2024-03-19", "asset": "000001", "turnover_rate": 0.6664}
  ]
}
```

---

### 因子计算参数

**参数默认值**:

| 因子 | 参数 | 默认值 | 说明 |
|------|------|--------|------|
| RSI | period | 6 | RSI 计算周期 |
| Volume_Ratio | window | 5 | 成交量均值窗口 |
| Bollinger_PB | n | 20 | 移动平均周期 |
| Bollinger_PB | k | 2.0 | 标差倍数 |
| KDJ_J | n | 9 | RSV 计算周期 |
| KDJ_J | m1 | 3 | K 值平滑周期 |
| KDJ_J | m2 | 3 | D 值平滑周期 |
| Turnover_Surge | window | 5 | 换手率均值窗口 |
| Industry_Momentum_5d | window | 5 | 行业动量滚动窗口 |
| Industry_Momentum_5d | min_stocks | 5 | 行业最小股票数（不足则NaN） |
| Industry_Turnover_Trend | clip_lower | 0.001 | 分母保护下限 |
| Industry_Turnover_Trend | min_stocks | 5 | 行业最小股票数 |
| Industry_Amplitude_Trend | clip_lower | 0.001 | 分母保护下限 |
| Industry_Amplitude_Trend | min_stocks | 5 | 行业最小股票数 |

**计算规范 (遵循 PROJECT.md)**:
- 函数入口**禁止** `.copy()` 整表拷贝（OOM 根因）；直接在输入 df 上加列，`_run_pipeline_step` 重新赋值后旧引用立即丢弃
- 使用 `transform` 方法避免 pandas 3.0 索引问题 (见 R21)
- 异常检测而非静默修正
- 使用 EPSILON 避免除零 (见 R15)

---

## 待补充

```
□ 各脚本测试用例(test_cases/fetch_xxx_test_cases.md)
□ 日期处理模块(common/date_utils.py,交易日判断、日期范围计算)
□ 数据验证模块(common/data_validator.py,字段完整性检查)
□ 增量更新策略规范
□ 数据质量检查自动化
□ 因子计算性能优化(大数据量测试)
✓ 公共模块实现(paths.py、cache_manager.py、http_client.py、stock_utils.py) - 已完成 2026-05-24
```

---

## 版本历史

### 文档版本

| 版本 | 日期 | 更新内容 |
|------|------|---------|
| v2.1 | 2026-06-13 | 新增 R17（大规模面板禁用 `groupby.transform`,改用 `_per_asset_transform`）;原 R17/R18/R19/R20 编号下移为 R18/R19/R20/R21;源自 RSI 分层回测 OOM 系统化修复 (5 处 transform 重构,11 个等价性测试保护) |
| v2.0 | 2026-06-03 | 大重构:27 条规则去重合并到 20 条,按 7 类别 (A-G) 组织,每条套 What/Why/How/Don't/When/Verify 框架,加目录索引,后半部分项目文档整理 |
| v1.x | 2026-05-25 ~ 2026-05-27 | 增量积累的代码 review 发现 (27 条规则) |

### factor_calculator.py 版本

| 版本 | 时间 | 更新内容 |
|-----|------|---------|
| v1.0 | 2026-05-27 17:00 | 初始创建:导入规范化、logger 参数化、类型注解精确化、__all__ 修复、docstring 补全 (Example 章节);配套 test_cases/test_factor_calculator.py |
| v1.1 | 2026-05-27 19:30 | 第二轮优化:版本历史添加、常量命名私有化 (DEFAULT_* → _DEFAULT_*)、__all__ 移到导入后位置 |
| v1.2 | 2026-05-27 20:00 | 第三轮优化:内部函数 `_calculate_ewm_with_initial` docstring 补全、新增私有常量 (volume_ratio_window、forward_return_shift)、消除硬编码默认值 |
| v1.3 | 2026-05-27 21:00 | 第四轮优化:提取列名常量 (6 输入 + 3 输出)、提取魔法数字常量 (4 个基准值 + 2 个阈值)、消除硬编码字符串和魔法数字 |
| v1.37 | 2026-06-05 | 新增 momentum_strength 因子计算函数 |
| v1.38 | 2026-06-11 | 修复 momentum_strength 极端值：分母下限保护 (clip std≥0.01)，防止均匀涨跌时比值爆炸；std=0 归入 invalid_mask 设 NaN |
| v1.15 | 2026-06-12 | 新增行业方向性因子：calculate_industry_momentum_5d / calculate_industry_turnover_trend / calculate_industry_amplitude_trend；新增 _add_industry_column() 辅助函数；行业映射来自 stock_industry.json |

### fetch_turnover.py 版本

| 版本 | 时间 | 更新内容 |
|-----|------|---------|
| v2.18 | 2026-06-10 | 日志配置修复:替换 logging.basicConfig → setup_logger;新增 _get_logger()、_SCRIPT_NAME/_LOGS_DIR 常量;模块级 logger 写入 data_fetchers/logs/ 目录 |

---

*最后更新: 2026-06-12*

