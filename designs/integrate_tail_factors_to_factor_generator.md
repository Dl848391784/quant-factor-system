# 设计文档：尾盘因子整合到 factor_generator.py

> 创建时间: 2026-06-02
> 状态: 待审核

---

## 背景

**问题**：Stage 4（综合因子）执行失败，原因是 `factor_ic_data.json.gz` 缺少尾盘因子列：
- `tail_price_position`
- `tail_price_slope`
- `tail_price_volume_intensity`

**根因**：
- `factor_generator.py` 的 `_EXTENDED_FACTOR_COLS` 不包含尾盘因子
- 尾盘因子在 `factor_ic/ic_tail_price_*.py` 独立脚本计算，未写入统一数据源

---

## 规范依据

| 规范 | 内容 | 适用场景 |
|------|------|---------|
| **PROJECT.md H1** | 模块边界：factor_ic 只能复用 factor_ic/common/ | data_fetchers 不能依赖 factor_ic 模块 |
| **MODULE.md 约束 #30** | 新增输出字段完整链路检查清单（3处同步） | 因子生成入口需同步修改 |
| **数据架构规范**（memory） | factor_ic_data.json.gz 是统一数据源 | 尾盘因子需写入统一数据源 |
| **Design-First 流程**（PROJECT.md） | 2+ 文件改动需先提交 design.md | 本次涉及 2+ 文件 |

---

## 技术方案

### 方案选择

**采用方案**：迁移计算函数到 `factor_generator.py`

**不支持方案**（违反规范）：
- ❌ factor_generator.py 直接导入 `factor_ic.common.tail_data_loader` → 违反 H1 模块边界
- ❌ 尾盘因子只在 factor_ic 脚本计算 → 违反数据架构规范（统一数据源）

### 修改文件清单

| 序号 | 文件 | 修改内容 |
|------|------|---------|
| 1 | `data_fetchers/factor_generator.py` | 新增尾盘因子计算函数 + 更新 `_EXTENDED_FACTOR_COLS` |
| 2 | `data_fetchers/schemas/factor_ic_data.schema.json` | 新增尾盘因子字段定义 |
| 3 | `data_fetchers/MODULE.md` | 更新版本历史 |
| 4 | `factor_ic/ic_tail_price_*.py`（可选） | 改为导入 factor_generator 的函数 |

---

## 详细设计

### 1. factor_generator.py 修改

**新增函数**（从 factor_ic/ic_tail_price_*.py 迁移）：

```python
# 新增：加载尾盘数据函数
def _load_tail_trading_data() -> pd.DataFrame:
    """加载尾盘5分钟K线数据"""
    # 从 tail_trading_data.json.gz 加载
    # 路径：DATA_FETCHERS_RESULT / "tail_trading_data.json.gz"

# 新增：尾盘因子计算函数
def _calculate_tail_price_position(df: pd.DataFrame) -> pd.DataFrame:
    """计算尾盘价格位置因子"""
    # 公式： (收盘价 - tail_low) / (tail_high - tail_low)

def _calculate_tail_price_slope(df: pd.DataFrame) -> pd.DataFrame:
    """计算尾盘趋势斜率因子"""
    # 公式： 线性回归斜率 / 均价

def _calculate_tail_price_volume_intensity(df: pd.DataFrame) -> pd.DataFrame:
    """计算尾盘量价强度因子"""
    # 公式： 尾盘涨跌幅 × 尾盘量比
```

**修改 `_EXTENDED_FACTOR_COLS`**（第129行）：

```python
# 当前：
_EXTENDED_FACTOR_COLS: tuple[str, ...] = ('bollinger_pb', 'kdj_j', 'turnover_surge', 'amplitude', 'price_position')

# 修改后：
_EXTENDED_FACTOR_COLS: tuple[str, ...] = (
    'bollinger_pb', 'kdj_j', 'turnover_surge', 'amplitude', 'price_position',
    'tail_price_position', 'tail_price_slope', 'tail_price_volume_intensity'
)
```

**修改 `generate_all_factors()`**：

```python
# 新增尾盘数据合并步骤
# 在现有因子计算后，调用尾盘因子计算函数
```

### 2. factor_ic_data.schema.json 修改

新增字段定义：

```json
{
  "tail_price_position": {"type": "number", "description": "尾盘价格位置因子"},
  "tail_price_slope": {"type": "number", "description": "尾盘趋势斜率因子"},
  "tail_price_volume_intensity": {"type": "number", "description": "尾盘量价强度因子"}
}
```

### 3. MODULE.md 更新

新增版本历史条目。

---

## 执行流程

```
1. 修改 factor_generator.py（迁移函数 + 更新常量）
2. 修改 factor_ic_data.schema.json（新增字段）
3. ruff check + ruff format
4. pytest 验证测试通过
5. 运行 factor_generator.py 验证数据生成
6. 更新 MODULE.md 版本历史
7. Git commit
```

---

## 验证清单

| 验证项 | 检查命令 |
|--------|---------|
| 因子列定义 | `grep -n "_EXTENDED_FACTOR_COLS" factor_generator.py` |
| schema 字段 | `grep -n "tail_price" schemas/factor_ic_data.schema.json` |
| 数据输出 | `zcat factor_ic_data.json.gz | head -20 | grep tail_price` |
| pytest 测试 | `pytest data_fetchers/test_cases/ -v` |

---

## 风险评估

| 风险 | 影响 | 缓解措施 |
|------|------|---------|
| 尾盘数据文件不存在 | 因子值为 NaN | `_load_tail_trading_data()` 异常处理，返回空 DataFrame |
| 数据合并失败 | 因子列缺失 | 日志记录 + 返回原 DataFrame |
| 内存增加 | ~50MB（尾盘数据） | 已有 4.4GB 可用内存，足够 |

---

## 用户审核确认

请确认方案可行，确认后开始执行。