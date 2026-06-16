# Design: FactorSpec required_cols 自动化 + sys.path 收敛

> Bug #3 + Bug #4 整体设计文档
> 状态：**Draft（第 2 轮：方案 3-A + 4-A 已选定，事实数据 + 拆分清单细化中）**
> 作者：云瑶
> 创建日期：2026-06-16
> 关联 Bug：`ic_industry_amplitude_trend_1d.py` 6 项问题清单中的 #3、#4

---

## 1. 背景与问题（事实数据）

### 1.1 Bug #3：FactorSpec required_columns 双重维护

**现状**（grep 实测 2026-06-16）：
- `factor_ic/ic_*.py` 共 **34 个** ic 脚本，全部使用 `register_factor(FactorSpec(required_columns=...))` 显式声明
- 其中 **31 个为复杂因子**（含 `calculation=`），**3 个为简单因子**（无 calculation）：
  - `ic_past_return_1d_1d.py`、`ic_rsi_1d.py`、`ic_volume_ratio_1d.py`
- `data_fetchers/factor_calculator/*.py` 中 **27 个**函数已声明 `func.required_cols = [...]`
- ic 脚本调用的 calculation 函数共 **31 个 unique**，分布：
  - **25 个**来自 calculator 模块（已有 `.required_cols`）
  - **6 个**为脚本内本地 `def calculate_*`（无 `.required_cols`，calculator 不可见）：
    - `calculate_intraday_intensity` → `ic_intraday_intensity_1d.py`
    - `calculate_tail_price_position` → `ic_tail_price_position.py`
    - `calculate_tail_price_slope` → `ic_tail_price_slope_1d.py`
    - `calculate_tail_price_volume_intensity` → `ic_tail_price_volume_intensity.py`
    - `calculate_tail_volume_acceleration` → `ic_tail_volume_acceleration_1d.py`
    - `calculate_tail_volume_shrink` → `ic_tail_volume_shrink_1d.py`

**风险案例**：
- 本次 bug #2 即把产出列 `industry_amplitude_trend` 误写入 `required_columns`，但 `calculate_industry_amplitude_trend.required_cols = ["date", "asset", "amplitude"]` 早已正确声明 → 双重维护漂移

### 1.2 Bug #4：sys.path.insert 散布在 34 个脚本头部

**现状**（grep 实测）：
- `factor_ic/ic_*.py` **全部 34 个**含 `sys.path.insert(0, str(Path(__file__).parent.parent))`
- 后跟 7-9 行 `from ... import ...  # noqa: E402` 群
- 项目根 `conftest.py` 已有 logger 抑制 fixture，但**无 pythonpath 注入**
- `pyproject.toml` `[tool.pytest.ini_options]` **未配 pythonpath**

**风险**：
- 路径硬编码 + 模块导入与运行时副作用混杂
- 大量 `# noqa: E402` 噪声，模糊真实 E402 违规
- 新增脚本必须复制粘贴头部模板，模板漂移成本

---

## 2. 影响面分析

| 维度 | Bug #3（方案 3-A） | Bug #4（方案 4-A） |
|------|-------------------|-------------------|
| 公共模块改动 | `factor_ic/common/factor_spec.py` | `pyproject.toml` + `conftest.py` |
| 因子脚本数 | 34 个 ic_*.py（25 个 calculator 模块来源 + 6 个脚本本地 + 3 个简单因子） | 34 个 ic_*.py |
| calculator 侧补全 | 0（25 个已全覆盖；6 个本地不需要补） | — |
| ic 脚本侧本地 calc 补全 | 6 个脚本内 calculation 函数补 `.required_cols` 属性 | — |
| 简单因子（无 calculation） | 3 个脚本保留显式 `required_columns=` | — |
| 运行场景兼容 | pytest / `python -m factor_ic.xxx` / pipeline | 同左（`python factor_ic/xxx.py` 裸路径运行需切 -m） |

**关键边界**（影响 R3.x 拆分）：
- 方案 3-A 自动派生需要 `calculation` 拥有 `.required_cols` 属性
- 6 个脚本内本地 calculation 函数不在 calculator 模块中 → 必须在脚本内附属 `.required_cols`
- 3 个简单因子无 `calculation` → 保留手动 `required_columns=`，FactorSpec 校验路径不变（factor_spec.py L98-102 仍要求 factor_col ∈ required_columns）

---

## 3. 方案选型（已选定 2026-06-16）

### 3.1 Bug #3：**方案 3-A**（用户已选）

**FactorSpec.required_columns 改为可选 + 自动派生**

```python
@dataclass(frozen=True)
class FactorSpec:
    factor_name: str
    factor_col: str
    required_columns: tuple[str, ...] | None = None  # ← 改为可选
    calculation: Callable | None = None
    ...

    def __post_init__(self):
        # 自动派生：calculation 有 .required_cols 时自动拼装 JOIN_KEYS
        if self.required_columns is None:
            if self.calculation is None or not hasattr(self.calculation, "required_cols"):
                raise ValueError(...)
            derived = JOIN_KEYS + tuple(c for c in self.calculation.required_cols if c not in JOIN_KEYS)
            object.__setattr__(self, "required_columns", derived)
```

**校验语义新增**（注册期 L2）：
- 若同时提供 `required_columns` 和 `calculation.required_cols`，必须一致（防漂移）
- 若 `required_columns` 为 None 且 `calculation` 无 `.required_cols` → ValueError

### 3.2 Bug #4：**方案 4-A**（用户已选）

**pyproject.toml + conftest.py 统一 pythonpath**

```toml
# pyproject.toml
[tool.pytest.ini_options]
pythonpath = ["."]  # 新增
```

```python
# conftest.py（项目根，已有 logger fixture）
import sys
from pathlib import Path
_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
```

各 ic 脚本删除：
- `sys.path.insert(0, str(Path(__file__).parent.parent))`
- 末尾 `# noqa: E402` 群

CLI 运行规范：`python -m factor_ic.ic_xxx_1d --force-full`

---

## 4. 子任务拆分（方案 3-A + 4-A）

### 4.1 默认决策（待 sign-off）

- **是否合并设计**：合并为本份单一 design.md（#3 + #4 强相关：都改 ic 脚本头部，合并避免 30+ 文件改两轮）
- **迁移粒度**：**中等档（5 文件/轮）**——平衡 commit 颗粒度与 review 成本

### 4.2 Bug #3 实施轮次（R3.x）

#### R3.1 — FactorSpec 改造（公共模块）
- **文件**：`factor_ic/common/factor_spec.py`（+30 行）
- **改动**：
  - `required_columns` 改为 `tuple[str, ...] | None = None`
  - 新增 `__post_init__` 自动派生
  - `_validate_spec` 新增"双声明一致性"校验
- **测试**：新增 `factor_ic/common/test_factor_spec.py`
  - case A：`required_columns=None` + calculation 有 `.required_cols` → 自动派生
  - case B：`required_columns=None` + calculation 无 `.required_cols` → ValueError
  - case C：双声明且一致 → 通过
  - case D：双声明且不一致 → ValueError
  - case E：简单因子 `required_columns=...` 显式声明 → 不变
- **验证**：ruff + pytest factor_ic/common/test_factor_spec.py
- **commit**：独立显式路径

#### R3.2 — 脚本本地 calculation 补 `.required_cols`（6 个脚本）
- **文件**（按字母序，5+1 拆 2 轮）：
  - **R3.2a**（5 个）：`ic_intraday_intensity_1d.py`、`ic_tail_price_position.py`、`ic_tail_price_slope_1d.py`、`ic_tail_price_volume_intensity.py`、`ic_tail_volume_acceleration_1d.py`
  - **R3.2b**（1 个）：`ic_tail_volume_shrink_1d.py`
- **改动**：每个脚本在 `def calculate_xxx(...)` 之后追加 `calculate_xxx.required_cols = [...]`
- **验证**：模块导入 + ruff
- **commit**：每轮独立

#### R3.3 — 复杂因子脚本迁移（25 个 calculator 来源 + 6 个本地 = 31 个）
- **拆分**（5 文件/轮，约 7 轮）：
  - **R3.3a–R3.3g**：每轮 5 个 ic 脚本，删除 `required_columns=` 参数（复杂因子）
- **改动模板**：
  ```python
  # 改前
  required_columns=JOIN_KEYS + ("close", "high", "low"),
  calculation=calculate_kdj_j,
  # 改后
  calculation=calculate_kdj_j,  # required_columns 自动派生
  ```
- **验证**：每轮 `python -c "import factor_ic.ic_xxx_1d"` + ruff + 抽样 pytest
- **commit**：每轮独立

#### R3.4 — 简单因子（3 个）保持不变
- 不在迁移范围（无 `calculation` → 必须保留 `required_columns=`）
- design.md 注明跳过原因，避免后续误删

### 4.3 Bug #4 实施轮次（R4.x）

#### R4.1 — 项目级路径注入（公共配置）
- **文件**：`pyproject.toml` + `conftest.py`
- **改动**：
  - `pyproject.toml [tool.pytest.ini_options]` 加 `pythonpath = ["."]`
  - `conftest.py` 顶部注入 root 到 sys.path
- **验证**：
  - `pytest factor_ic/common/test_public_modules.py`
  - 临时新建无 sys.path 的脚本 import factor_ic 模块成功
- **commit**：独立

#### R4.2 — 单脚本验证
- **文件**：`factor_ic/ic_industry_amplitude_trend_1d.py`（前序 4 项 commit 已修，作为 sample）
- **改动**：删除 `sys.path.insert(...)` + 全部 `# noqa: E402`
- **验证**：
  - `python -m factor_ic.ic_industry_amplitude_trend_1d --help`
  - ruff check（E402 不应再触发）
- **commit**：独立

#### R4.3 — 批量迁移（剩余 33 个脚本）
- **拆分**（5 文件/轮，约 7 轮）：
  - **R4.3a–R4.3g**：每轮 5 个脚本，删除 sys.path.insert + noqa
- **批量脚本**（temporary/ 下临时辅助，commit 时不带入）：
  ```bash
  # 验证脚本（每轮跑一遍）
  for f in <本轮文件清单>; do
      python -c "import importlib; importlib.import_module('factor_ic.$(basename $f .py)')" || exit 1
  done
  ```
- **验证**：每轮 ruff + 模块导入 + 抽样 pytest
- **commit**：每轮独立

#### R4.4 — 文档更新
- 更新 `factor_ic/MODULE.md`：CLI 运行规范改为 `python -m factor_ic.ic_xxx_1d`
- 更新各 flow 文档（如有 `python factor_ic/xxx.py` 提法）
- **commit**：独立

### 4.4 总轮次预估

| 类别 | 轮次 | commit 数 |
|------|------|-----------|
| R3.1 公共模块 | 1 | 1 |
| R3.2 本地 calc 补全 | 2 | 2 |
| R3.3 复杂因子迁移 | 7 | 7 |
| R3.4 简单因子（跳过） | 0 | 0 |
| R4.1 项目级配置 | 1 | 1 |
| R4.2 单脚本验证 | 1 | 1 |
| R4.3 批量迁移 | 7 | 7 |
| R4.4 文档更新 | 1 | 1 |
| **合计** | **20** | **20** |

---

## 5. 验证策略

### 5.1 单元测试（R3.1 必含）
- `factor_ic/common/test_factor_spec.py` 覆盖 5 个 case（A-E，见 §4.2 R3.1）

### 5.2 模块导入验证（每轮必跑）
```bash
# 单脚本
python -c "import factor_ic.ic_xxx_1d"

# 批量（每轮文件清单）
for f in <本轮 5 个文件>; do
    python -c "import factor_ic.$(basename $f .py)" || { echo "FAIL: $f"; exit 1; }
done
```

### 5.3 契约一致性测试（R3.1 集成）
新增测试 `factor_ic/common/test_factor_spec_consistency.py`：
- 遍历 `FACTOR_REGISTRY` 所有已注册因子
- 复杂因子（calculation 非空）：断言 `spec.required_columns` 与 `calculation.required_cols` 推导结果一致
- 防止后续 PR 在双声明场景引入漂移

### 5.4 端到端 pipeline 验证（R3 / R4 各阶段末轮）
```bash
# 全量 IC 计算（无数据缓存时跳过）
python -m factor_ic.ic_industry_amplitude_trend_1d --force-full || true

# 公共模块测试
pytest factor_ic/common/ -x --tb=short
```

### 5.5 ruff 验证（每轮）
- `ruff check factor_ic/`：删除 sys.path 后不应有新 E402
- `ruff format --check factor_ic/`

---

## 6. 风险与回滚

| # | 风险 | 缓解 / 回滚 |
|---|------|-------------|
| R1 | FactorSpec 自动派生覆盖手动声明导致漏列 | §3.1 注册期校验"双声明一致性" + R3.1 case D 单测 |
| R2 | 6 个脚本本地 calc 漏补 `.required_cols` 导致 `__post_init__` 报 ValueError | R3.2 优先于 R3.3 执行；模块导入测试拦截 |
| R3 | `python factor_ic/xxx.py` 裸路径运行场景失败 | R4.4 文档显式声明 `python -m` 规范；conftest.py 兜底注入仅 pytest 生效，CLI 必须 -m |
| R4 | 多 agent 并行迁移冲突 staged 区 | 每轮显式路径 commit + 提交前 `git status --short \| wc -l` 校验 |
| R5 | calculator 模块新增因子但忘加 `.required_cols`（未来漂移） | 在 R3.1 集成测试 §5.3 中加"calculator 函数若被任何 FactorSpec 引用必须有 .required_cols"断言 |

**回滚 SOP**：
- 单轮失败：`git revert <commit>`，单 commit 即单轮粒度
- 整体回滚：`git revert R3.1..HEAD` 按倒序逐个 revert
- 不需要 force-push；无破坏性 schema 变更

---

## 7. 决策状态（2026-06-16）

- [x] **Bug #3**：方案 3-A（用户已选）
- [x] **Bug #4**：方案 4-A（用户已选）
- [ ] **是否合并设计**：默认合并（§4.1 已说明，等用户 sign-off）
- [ ] **迁移粒度**：默认 5 文件/轮中等档（§4.1，等用户 sign-off）

---

## 8. 实施触发条件

design.md 第 2 轮（本轮）通过审核后，按 §4.2 / §4.3 顺序进入实施：

1. R3.1 公共模块（先于一切迁移轮）
2. R3.2 本地 calc 补全（必须先于 R3.3，否则导入失败）
3. R3.3 复杂因子迁移（7 轮）
4. R4.1 项目级配置
5. R4.2 单脚本验证
6. R4.3 批量迁移（7 轮）
7. R4.4 文档更新

每轮模板：
```
诊断（5min） → 修改（10min） → ruff（1min） → pytest 抽样（2min）
→ 模块导入（1min） → git status 校验 → 显式路径 commit
```

---

## 9. 附录：本轮 grep 数据来源

```bash
# ic 脚本总数
ls factor_ic/ic_*.py | wc -l   # → 34

# 简单因子（无 calculation）
grep -L 'calculation=' factor_ic/ic_*.py
# → ic_past_return_1d_1d.py / ic_rsi_1d.py / ic_volume_ratio_1d.py

# calculator 已声明 .required_cols
grep -hP '^\w+\.required_cols\s*=' data_fetchers/factor_calculator/*.py | grep -oP '^\K\w+' | sort -u | wc -l   # → 27

# 脚本内本地 calculation
grep -l "def calculate_intraday_intensity\|def calculate_tail_price_position\|def calculate_tail_price_slope\|def calculate_tail_price_volume_intensity\|def calculate_tail_volume_acceleration\|def calculate_tail_volume_shrink" factor_ic/ic_*.py
# → 6 个文件
```
