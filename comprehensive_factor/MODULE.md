# comprehensive_factor 模块规范

> 本文档定义 comprehensive_factor/ 目录下综合因子计算脚本的开发规范。
> 创建时间: 2026-05-24
> 版本: v1.1（新增完整流程说明）

---

## 综合因子构建完整流程

```
┌─────────────────────────────────────────────────────────────────────┐
│                    Step 1: 单一因子分析                              │
├─────────────────────────────────────────────────────────────────────┤
│  ├─ Percentile 分层回测 → 多空年化收益、夏普比率、单调性              │
│  └─ 计算 IC 序列 → IC均值、ICIR、每日IC值                            │
└─────────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────────┐
│                    Step 2: 因子筛选                                  │
├─────────────────────────────────────────────────────────────────────┤
│  ├─ 计算所有因子两两相关性矩阵                                        │
│  ├─ 无效因子（IC不显著、单调性差）→ 直接丢弃                          │
│  ├─ 高相关组（|corr|>0.7）→ 只保留最强的                             │
│  └─ 保留下来的因子 → 两两低相关                                       │
└─────────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────────┐
│                    Step 3: 标准化                                    │
├─────────────────────────────────────────────────────────────────────┤
│  每日截面标准化：factor_std = (factor - μ) / σ                       │
└─────────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────────┐
│                    Step 4: 加权计算综合因子                           │
├─────────────────────────────────────────────────────────────────────┤
│  ├─ 等权（equal_weight）                                             │
│  ├─ ICIR加权（icir_weight）                                          │
│  ├─ IC加权（ic_weight）                                              │
│  └─ 滚动ICIR加权（rolling_icir_weight）                              │
│  → 得到 4 个综合因子                                                 │
└─────────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────────┐
│                    Step 5: 综合因子分层回测                          │
├─────────────────────────────────────────────────────────────────────┤
│  对 4 个综合因子分别做分层回测 → 选择最优方案                         │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 概述

comprehensive_factor 模块负责将多个单因子按加权方式组合成综合因子，并调用 backtest 模块进行分层回测。

**模块定位：**
- 输入：factor_ic 的 IC 结果 + 单因子值（从 cache 或 backtest 结果）
- 处理：加权计算综合因子值
- 输出：综合因子分层回测结果

---

## Step 2: 因子筛选（自动化）

> 2026-05-24 新增自动化逻辑，详见 `common/factor_selector.py`

### 无效因子判定标准

| 指标 | 阈值 | 判断逻辑 | 理由 |
|-----|------|---------|------|
| |ic_mean| | < 0.03 | 无效 | IC均值太低无预测能力 |
| p_value | > 0.05 | 无效 | 统计不显著 |
| |icir| | < 0.15 | 无效 | 稳定性差（波动大） |
| |monotonicity_corr| | < 0.4 | 无效 | 分层收益不单调 |
| long_short_return_annual | < 3% | 无效 | 经济意义弱（扣除成本后负收益） |

**判定规则：** 任一指标不满足即判定为无效因子。

**阈值依据：**
- |ic_mean| ≥ 0.03：业界公认的最低有效阈值
- p_value ≤ 0.05：统计显著性标准（95%置信）
- |icir| ≥ 0.15：IC均值/IC标准差 ≥ 0.03/0.2，最低稳定水平
- |monotonicity_corr| ≥ 0.4：一般单调性标准（0.5为强单调）
- long_short_return ≥ 3%：扣除双边成本（各1%）后仍正收益

### 高相关组筛选标准

| 指标 | 阈值 | 处理方式 | 理由 |
|-----|------|---------|------|
| |corr| | > 0.7 | 组内保留 |ICIR| 最高的 | 高相关因子冗余，信息重叠 |

**筛选算法：**
1. 使用连通分量算法识别高相关因子组
2. 组内比较 |ICIR|，保留最高的因子
3. 其他因子标记为"高相关冗余"并丢弃

### 使用方式

**手动配置（默认）：**
```python
# 脚本中直接指定因子列表
factor_list = ['rsi', 'volume_ratio']
factor_cols = ['rsi_6', 'volume_ratio_5']
```

**自动筛选（推荐）：**
```python
# 启用自动筛选
result = run_composite_backtest(
    weight_method='icir_weight',
    auto_select=True,  # 启用自动筛选
    thresholds={        # 可自定义阈值（可选）
        'ic_mean_abs_min': 0.03,
        'monotonicity_corr_abs_min': 0.4,
        ...
    }
)
```

### 筛选输出示例

```json
{
  "selected": ["volume_ratio", "rsi"],
  "valid_count": 4,
  "total_count": 5,
  "invalid": {
    "kdj_j": ["|ic_mean|=0.015<0.03", "|icir|=0.092<0.15"]
  },
  "high_corr_dropped": {
    "turnover_surge": "与volume_ratio高相关(0.99)，ICIR较低"
  }
}
```

---

## 脚本命名

**格式：** `composite_<加权方式>_<收益周期>.py`

**加权方式标识：**

| 加权方式 | 标识 | 说明 |
|---------|------|------|
| 等权 | equal_weight | 所有因子权重相等 |
| ICIR加权 | icir_weight | 权重 = ICIR / sum(ICIR) |
| 滚动ICIR加权 | rolling_icir_weight | 滚动窗口（如60日）ICIR加权 |
| IC加权 | ic_weight | 权重 = IC均值 / sum(IC均值) |

**示例：**
- `composite_equal_weight_1d.py` — 等权综合因子
- `composite_icir_weight_1d.py` — ICIR加权综合因子
- `composite_rolling_icir_weight_1d.py` — 滚动ICIR加权
- `composite_ic_weight_1d.py` — IC加权综合因子

**命名规则来源：** 与 factor_ic、backtest 模块命名规则保持一致。

---

## 加权方式规范

### 1. 等权（Equal Weight）

```python
weight = 1 / n_factors  # 每个因子权重相等
composite_factor = sum(w_i * factor_i)  # 加权求和
```

**适用场景：** 因子数量较少，无先验IC信息时默认方案。

### 2. ICIR加权（静态）

```python
weight_i = ICIR_i / sum(ICIR_j)  # ICIR越高权重越大
composite_factor = sum(w_i * factor_i)
```

**数据来源：** `factor_ic/result/*.json` 的 `icir` 字段

**适用场景：** 已知历史ICIR，全样本静态加权。

**权重公式：**
$$w_i = \frac{ICIR_i}{\sum_j ICIR_j}$$

### 3. 滚动ICIR加权（动态）

```python
# 每日计算滚动窗口（如60日）内的ICIR
rolling_icir_t = calc_rolling_icir(ic_series, window=60)
weight_i_t = rolling_icir_i_t / sum(rolling_icir_j_t)
composite_factor_t = sum(w_i_t * factor_i_t)
```

**数据来源：** factor_ic 的每日IC序列（需从 `result/*_daily.json.gz` 加载）

**适用场景：** 因子有效性随时间变化，动态调整权重。

**滚动窗口参数：**
- 默认窗口：60日（可配置）
- 最小窗口：20日（数据不足时回退到静态ICIR）

### 4. IC加权（静态）

```python
weight_i = ic_mean_i / sum(ic_mean_j)  # IC均值越高权重越大
composite_factor = sum(w_i * factor_i)
```

**数据来源：** `factor_ic/result/*.json` 的 `ic_mean` 字段

**适用场景：** 简化版ICIR加权，忽略波动性。

---

## 因子标准化规范

**加权前必须标准化因子值：**

```python
# 每日对每个因子做截面标准化
factor_standardized = (factor - factor.mean()) / factor.std()
```

**原因：**
- 不同因子值范围不同（RSI: 0-100, Volume_Ratio: 0.1-5）
- 未标准化会导致高值因子主导组合

**标准化时机：** 加权计算前，在 `composite_runner` 中统一处理。

---

## 因子相关性过滤规范

**组合因子前必须检查相关性：**

| 组合 | 相关系数 | 建议 |
|------|---------|------|
| Volume_Ratio vs Turnover_Surge | 0.99 | 只选其一（等价） |
| RSI vs Bollinger_PB | 0.94 | 只选其一（等价） |
| Volume_Ratio vs RSI | 0.30 | ✓ 可组合（低相关） |
| Volume_Ratio vs Bollinger_PB | 0.27 | ✓ 可组合（低相关） |

**预设低相关组合：**
- 流动性因子（Volume_Ratio） + 技术指标因子（RSI 或 Bollinger_PB，选其一）

**高相关因子处理规则：**
```python
if corr > 0.7:
    # 选择ICIR更高的因子保留
    keep_factor = factor_with_max_icir([factor_a, factor_b])
```

---

## 公共入口防御性编程规范（v1.1 新增）

> 本节定义 composite_runner.py 公共入口的防御性校验规范，避免隐含假设导致的静默崩溃。

### 必需列校验规范

**问题类型：** factor_df 列名依赖隐含假设，未做校验导致 KeyError 延迟暴露。

**规范要求：**
```python
# 在访问 DataFrame 列前，必须校验列存在性
required_cols = ['date', 'asset']
for col in required_cols:
    if col not in factor_df.columns:
        raise ValueError(
            f"factor_df 缺少必需列 '{col}'，当前列: {list(factor_df.columns)}"
        )

# 因子列校验（factor_cols 参数传入）
for col in factor_cols:
    if col not in factor_df.columns:
        raise ValueError(
            f"factor_df 缺少因子列 '{col}'，当前列: {list(factor_df.columns)}"
        )
```

**校验时机：**
- 加载因子数据后，立即校验必需列（date/asset）
- 计算综合因子后，校验因子列存在性
- 保存输出前，校验输出必需列

**错误信息要求：**
- 必须包含缺失列名
- 必须包含当前列列表（便于调试）
- 错误信息友好，避免 KeyError 静默崩溃

### 返回值解包校验规范

**问题类型：** 函数返回值解包可能出错，用 `_` 丢弃返回值但未校验数量和类型。

**规范要求：**
```python
# 不要直接解包，先校验返回值
result = load_factor_return_data(cache_dir=cache_dir, logger=logger)

# 校验返回值数量和类型
if result is None:
    raise ValueError("函数返回 None，期望 (factor_df, return_df)")

if not isinstance(result, tuple) or len(result) != 2:
    raise ValueError(
        f"返回值数量错误，期望 2 个，实际: {len(result) if isinstance(result, tuple) else '非tuple'}"
    )

# 安全解包
_, return_df = result

# 校验解包后的值
if return_df is None:
    raise ValueError("return_df 为 None，数据加载失败")

if 'forward_return_1d' not in return_df.columns:
    raise ValueError(
        f"return_df 缺少 'forward_return_1d' 列，当前列: {list(return_df.columns)}"
    )
```

**适用场景：**
- load_factor_return_data() 返回值解包
- 其他跨模块调用函数返回值解包

**防御性校验层级：**
1. 返回值本身校验（None 检查）
2. 返回值类型和数量校验（tuple + len）
3. 解包后值校验（DataFrame 列校验）

### 父类 validate() 方法调用规范

**问题类型：** CompositeLayerConfig 继承 LayerConfigBase，调用 super().validate() 时需确认父类方法存在。

**规范要求：**
```python
# 父类 LayerConfigBase 已定义 validate() 方法（backtest/common/layered_backtest_runner.py 第 100-123 行）
# 子类 validate() 必须调用父类校验（确保基础校验不遗漏）

def validate(self) -> None:
    """校验配置完整性"""
    super().validate()  # 调用父类校验（n_layers、factor_direction、layer 编号校验）
    
    # 子类特有校验
    if not self.factor_list:
        raise ValueError("factor_list 不能为空")
    
    if len(self.factor_list) != len(self.factor_cols):
        raise ValueError("factor_list 与 factor_cols 数量不一致")
```

**父类校验内容（LayerConfigBase.validate）：**
- n_layers ≥ 2
- factor_direction ∈ ['positive', 'negative']
- long_layers/short_layers 非空
- layer 编号在 [1, n_layers] 范围内

---

## 因子名到列名映射规范（v1.1 新增）

> 本节定义 factor_list（因子逻辑名）与 factor_cols（数据列名）的映射规范，避免 auto_select 逻辑遗漏。

### 映射必要性

**问题类型：** factor_list 是因子逻辑名（如 'rsi'），factor_cols 是缓存数据列名（如 'rsi_6'），直接等号赋值会导致 load_factor_values 找不到对应列。

**映射来源：**
- factor_ic 脚本命名：`ic_<因子名>_<周期>.py`（如 `ic_rsi_1d.py`）
- 缓存数据列名：因子名 + 参数（如 `rsi_6`，6 为 RSI 周期参数）
- 命名差异：逻辑名不带参数，列名带参数

### 映射表定义位置

**定义位置：** `comprehensive_factor/common/factor_selector.py` 的 `FACTOR_NAME_TO_COL_MAP`

**当前硬编码映射（临时方案）：**
```python
FACTOR_NAME_TO_COL_MAP = {
    'rsi': 'rsi_6',
    'volume_ratio': 'volume_ratio_5',
    'kdj_j': 'kdj_j_9',
    'bollinger_pb': 'bollinger_pb_20',
    'turnover_surge': 'turnover_surge_5',
    'main_inflow_ratio': 'main_inflow_ratio_1d'
}
```

**后续改进方向：**
- 从配置文件读取（如 `config/factor_mapping.yaml`）
- 支持动态参数（如 `rsi_{window}`）
- 支持因子版本管理（如 `rsi_v2_6`）

### select_factors 返回结构（v1.1 更新）

**新增字段：**
```json
{
  "selected": ["volume_ratio", "rsi"],
  "factor_cols": ["volume_ratio_5", "rsi_6"],  // 新增：映射后的列名列表
  "unmapped_factors": [],  // 新增：未找到映射的因子列表
  "valid_count": 2,
  "total_count": 5,
  ...
}
```

**未映射因子处理：**
- 未找到映射时，使用因子名作为列名（兼容处理）
- 记录到 `unmapped_factors` 列表，并输出警告日志
- 调用方应检查 `unmapped_factors`，决定是否终止流程

---

## 动态权重保存规范（v1.1 新增）

> 本节定义动态权重（rolling_icir_weight）的保存规范，避免语义误导。

### 问题类型

**问题：** RollingICIRWeightMethod 每日动态计算权重，无法用固定字典表达。如果保存 `get_weights()` 返回的等权默认值，会产生误导。

**静态权重 vs 动态权重：**

| 加权方式 | 权重类型 | get_weights() 返回 | 正确保存方式 |
|---------|---------|-------------------|-------------|
| equal_weight | 静态 | 固定等权字典 | 直接保存 |
| icir_weight | 静态 | 固定 ICIR 比例字典 | 直接保存 |
| ic_weight | 静态 | 固定 IC 比例字典 | 直接保存 |
| rolling_icir_weight | **动态** | 等权默认（误导） | 标记为动态权重，不保存静态值 |

### 动态权重保存格式

**正确做法：**
```python
if weight_method == 'rolling_icir_weight':
    # 标记为动态权重，不保存静态值
    weights = {
        '_dynamic': True,
        '_method': 'rolling_icir_weight',
        '_window': 60
    }
else:
    # 静态权重直接保存
    weights = weight_engine.get_weights(factor_cols, ic_results)
```

**输出示例：**
```json
{
  "weights": {
    "_dynamic": true,
    "_method": "rolling_icir_weight",
    "_window": 60
  }
}
```

**语义说明：**
- `_dynamic: true` 表示权重每日动态计算
- `_method` 记录加权方式
- `_window` 记录滚动窗口参数
- 用户需从 daily 输出中提取每日权重（因子计算时已嵌入）

---

## NaN 相关性处理规范（v1.1 新增）

> 本节定义因子相关性 NaN 的显式处理规范，避免静默跳过异常情况。

### 问题类型

**问题：** 缺失值过多导致相关系数为 NaN，`abs(NaN) > 0.7` 返回 False（IEEE754），静默跳过异常情况。

**NaN 来源：**
- 因子缺失值过多（覆盖率低于阈值）
- 截面标准化后全部为 NaN（无有效数据）
- 计算异常（零方差导致 corr 无法计算）

### 显式处理规范

**校验代码：**
```python
if pd.isna(corr_val):
    nan_corr_pairs.append({
        'factor_a': factor_cols[i],
        'factor_b': factor_cols[j],
        'reason': 'NaN（缺失值过多导致相关性无法计算）'
    })
    logger.warning(
        "相关性 NaN 警告: %s vs %s，缺失值过多导致相关性无法计算",
        factor_cols[i], factor_cols[j]
    )
    continue  # 跳过 NaN，不判断高相关性
```

**输出新增字段：**
```json
{
  "high_corr_pairs": [{"factor_a": "rsi", "factor_b": "bollinger_pb", "corr": 0.94}],
  "nan_corr_pairs": [{"factor_a": "kdj_j", "factor_b": "main_inflow", "reason": "NaN（缺失值过多）"}]
}
```

**处理建议：**
- NaN 相关性因子应检查数据覆盖率
- 覆盖率低于阈值（如 60%）的因子应标记为无效
- 因子筛选时应提前排除数据缺失严重的因子

---

## 模块级代码规范（v1.2 新增）

> 本节定义模块级代码（import 时执行的代码）的规范，避免副作用风险。

### sys.path.insert 规范

**问题类型：** 模块级 sys.path.insert 在每次 import 时都会执行，多次 import 可能导致路径重复污染。

**错误写法：**
```python
# ❌ 每次 import 都会执行，可能导致重复插入
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
```

**正确写法：**
```python
# ✓ 添加重复插入检查，避免多次 import 时路径重复污染
_project_root = str(Path(__file__).parent.parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)
```

**适用场景：**
- 跨模块导入（如 comprehensive_factor 导入 backtest 模块）
- 项目根目录添加到 sys.path

**注意事项：**
- sys.path.insert 位置 0 会优先搜索，影响 import 顺序
- 重复插入同一路径不会报错，但会污染 sys.path
- 检查方式：`if path_str not in sys.path:`

---

## 函数入口类型统一规范（v1.2 新增）

> 本节定义函数入口参数类型统一转换规范，避免内部冗余转换。

### output_dir 类型转换规范

**问题类型：** 参数签名声明 str，但内部多处调用 Path() 转换，冗余且不一致。

**错误写法：**
```python
def run_composite_backtest(
    output_dir: Optional[str] = None  # 签名声明 str
):
    ...
    Path(output_dir).mkdir(...)       # 多次转换
    output_file = Path(output_dir) / 'xxx.json'  # 再次转换
    daily_file = Path(output_dir) / 'xxx.gz'     # 又一次转换
```

**正确写法：**
```python
def run_composite_backtest(
    output_dir: Union[str, Path, None] = None  # 签名支持两种类型
):
    # 入口统一转换，后续无需再调用 Path()
    if output_dir is not None:
        output_dir = Path(output_dir)
    
    ...
    output_dir.mkdir(...)             # 直接调用 Path 方法
    output_file = output_dir / 'xxx.json'       # 直接使用 / 运算符
    daily_file = output_dir / 'xxx.gz'          # 无需冗余转换
```

**类型签名建议：**
- 支持 str 或 Path：`Union[str, Path, None]`
- 入口统一转换为 Path：便于后续直接调用 Path 方法
- 文档说明：在 docstring 中注明"支持 str 或 Path，入口统一转换"

**适用参数：**
- `output_dir`：输出目录路径
- `cache_dir`：缓存目录路径
- `ic_result_dir`：IC结果目录路径
- 其他路径参数均可采用此模式

---

## composite_factor NaN 检查规范（v1.2 新增）

> 本节定义综合因子全 NaN 的检查规范，避免分层回测静默失效。

### 问题类型

**问题：** 所有因子值缺失时，composite_factor 全为 NaN，后续分层回测无法进行（无法计算 percentile）。

**NaN 来源：**
- 所有因子值缺失（factor_cols 配置错误或数据缺失）
- 标准化后全为 NaN（原始数据覆盖率过低）
- 加权计算异常（weight_engine.calculate 返回全 NaN）

### 检查规范

**校验代码：**
```python
# 添加综合因子到 factor_df
factor_df['composite_factor'] = composite_factor

# 检查 composite_factor 全为 NaN 的情况
valid_composite_count = factor_df['composite_factor'].notna().sum()
if valid_composite_count == 0:
    raise ValueError(
        "composite_factor 全为 NaN，无法进行分层回测\n"
        "可能原因：\n"
        "  1. 所有因子值缺失（检查 factor_cols 是否正确）\n"
        "  2. 标准化后全为 NaN（检查原始数据覆盖率）\n"
        "  3. 加权计算异常（检查 weight_engine.calculate()）"
    )
```

**错误信息要求：**
- 明确说明"无法进行分层回测"
- 提供可能原因列表（便于排查）
- 包含建议检查点

**检查时机：**
- 在添加 composite_factor 到 factor_df 后立即检查
- 在调用分层回测引擎前

---

## CLI 异常退出码规范（v1.2 新增）

> 本节定义 CLI 异常处理退出码规范，确保 shell 能正确识别执行状态。

### 问题类型

**问题：** raise 重新抛出异常后，进程退出码取决于调用方（shell 可能返回非零，但不确定），应显式设置。

**错误写法：**
```python
try:
    result = run_composite_backtest(...)
    logger.info("回测完成")
except Exception as e:
    logger.error("回测执行异常: %s", e)
    raise  # 退出码不确定
```

**正确写法：**
```python
try:
    result = run_composite_backtest(...)
    logger.info("回测完成，退出码 0")
    sys.exit(0)  # 显式设置成功退出码
except Exception as e:
    logger.error("回测执行异常: %s", e)
    logger.error("退出码 1（异常终止）")
    sys.exit(1)  # 显式设置失败退出码
```

**退出码语义：**
- 0：成功完成
- 1：异常终止（通用错误）
- 2：参数错误（可选）
- 其他：特定错误码（按需定义）

**适用场景：**
- CLI 脚本入口（create_cli_entrypoint 返回的 main 函数）
- 被 shell 调用的脚本（如 cron job）

**shell 退出码检查示例：**
```bash
python composite_icir_weight_1d.py
if [ $? -eq 0 ]; then
    echo "执行成功"
else
    echo "执行失败，退出码: $?"
fi
```

---

## 校验前置规范（v1.3 新增）

> 本节定义列校验的执行时机规范，避免校验位置错误导致无效计算。

### 问题类型

**问题：** 列校验放在 composite_factor 计算之后，如果列不存在，calculate 已经执行但结果无效，浪费计算资源。应校验前置，放在 standardize 之后、calculate 之前。

### 校验时机规范

**校验顺序：**
```
加载因子数据 → 标准化因子 → 【列校验】 → 计算相关性 → 计算综合因子 → ...
```

**校验层级：**
1. 必需列校验：`['date', 'asset']`
2. 因子列校验：`factor_cols`（用户传入）
3. 标准化因子列校验：`*_std`（standardize_factors 生成）

**校验代码位置：**
```python
# 4. 标准化因子
factor_df = standardize_factors(factor_df, factor_cols, logger)

# 校验前置：在 calculate 之前校验
required_cols = ['date', 'asset']
for col in required_cols:
    if col not in factor_df.columns:
        raise ValueError(f"factor_df 缺少必需列 '{col}'")

# 校验因子列存在性
for col in factor_cols:
    if col not in factor_df.columns:
        raise ValueError(f"factor_df 缺少因子列 '{col}'")

# 校验标准化因子列存在性（standardize_factors 生成 *_std 列）
std_cols = [f'{col}_std' for col in factor_cols]
for col in std_cols:
    if col not in factor_df.columns:
        raise ValueError(f"factor_df 缺少标准化因子列 '{col}'")

# 5. 计算因子相关性（校验通过后才执行）
...
```

**校验前置的意义：**
- 避免无效计算：列不存在时立即报错，不执行 calculate
- 快速失败：尽早暴露问题，减少调试时间
- 资源节约：避免浪费计算资源

---

## DataFrame 空值检查规范（v1.3 新增）

> 本节定义 DataFrame 空值检查规范，包括 None 和空 DataFrame 两种情况。

### 问题类型

**问题：** 只检查 None 和列存在性，未检查空 DataFrame（有列名但无数据）。空 DataFrame 会导致回测引擎静默产生空结果。

### 空值类型对比

| 类型 | 检查方式 | 说明 |
|------|---------|------|
| None | `df is None` | 数据加载失败 |
| 空DataFrame | `len(df) == 0` | 有列名但无数据（静默问题） |
| 缺失列 | `col not in df.columns` | 列不存在 |

### 检查规范

**完整检查代码：**
```python
_, return_df = factor_return_result

# 1. None 检查
if return_df is None:
    raise ValueError("return_df 为 None，收益数据加载失败")

# 2. 空 DataFrame 检查
if len(return_df) == 0:
    raise ValueError(
        "return_df 为空 DataFrame（有列名但无数据），无法进行分层回测\n"
        "可能原因：\n"
        "  1. 缓存数据文件为空\n"
        "  2. 数据加载异常"
    )

# 3. 列存在性检查
if 'forward_return_1d' not in return_df.columns:
    raise ValueError("return_df 缺少 'forward_return_1d' 列")
```

**错误信息要求：**
- 区分三种空值类型
- 提供可能原因列表
- 包含当前列列表（便于调试）

---

## 权重元信息分离规范（v1.3 新增）

> 本节定义权重元信息与权重数据的分离规范，避免序列化风险。

### 问题类型

**问题：** 动态权重字典混入非权重字段（如 `_dynamic`），后续序列化存在风险。

**错误写法：**
```python
weights = {'_dynamic': True, '_method': 'rolling_icir_weight', '_window': 60}
# 问题：'_dynamic' 等字段不是因子权重，混入权重字典语义不清
```

**正确写法：**
```python
# 权重数据（动态权重时为空字典）
weights = {}

# 权重元信息（与权重数据分离）
weight_meta = {
    'is_dynamic': True,
    'method': 'rolling_icir_weight',
    'window': 60,
    'note': '权重每日动态计算，不保存静态值'
}
```

### 输出结构规范

**输出字段：**
```json
{
  "weights": {"rsi": 0.4, "volume_ratio": 0.6},  // 权重数据（动态权重时为空）
  "weight_meta": {                               // 权重元信息（分离）
    "is_dynamic": false,
    "method": "icir_weight"
  }
}
```

**语义说明：**
- `weights`：因子权重数据（因子名 → 权重值）
- `weight_meta`：权重元信息（is_dynamic、method、window等）

**序列化优势：**
- 字典字段语义清晰
- 无需特殊处理 `_` 前缀字段
- 易于下游解析和使用

---

## CLI 异常堆栈保留规范（v1.3 新增）

> 本节定义 CLI 异常处理堆栈信息保留规范，便于排查问题。

### 问题类型

**问题：** `logger.error("异常: %s", e)` 只打印异常消息，丢失堆栈信息，难以排查根因。

### 堆栈保留方式

**方式1：traceback.format_exc()**
```python
import traceback

try:
    result = run_composite_backtest(...)
except Exception as e:
    logger.error("回测执行异常: %s", e)
    logger.error("异常堆栈:\n%s", traceback.format_exc())  # 打印完整堆栈
    sys.exit(1)
```

**方式2：logger.exception()**
```python
try:
    result = run_composite_backtest(...)
except Exception as e:
    logger.exception("回测执行异常: %s", e)  # 自动打印堆栈
    sys.exit(1)
```

**推荐方式：** 方式1（traceback.format_exc()），可控制堆栈打印位置和格式。

**堆栈信息用途：**
- 定位异常发生位置（文件、行号）
- 分析调用链（函数调用顺序）
- 查看异常上下文（局部变量值）

---

## 标准化列名接口约定规范（v1.5 新增）

> 本节定义 standardize_factors 函数与 WeightEngine 接口的列名转换约定，避免维护者误判为 bug。

### 问题类型

**问题：** standardize_factors 新增 `_std` 后缀的标准化列，但 WeightEngine.calculate() 接收原始列名 factor_cols，易被误判为"列名不匹配 bug"。

### 接口约定说明

**实际上这不是 bug，而是设计约定：**

1. **standardize_factors 接口约定：**
   - 输入列名：原始因子列名（如 `'rsi_6'`, `'volume_ratio_5'`）
   - 输出列名：新增 `_std` 后缀（如 `'rsi_6_std'`, `'volume_ratio_5_std'`）
   - 返回 DataFrame：保留原始列 + 新增标准化列

2. **WeightEngine.calculate() 接口约定：**
   - 参数 `factor_cols`：接收原始列名（不是 `_std` 列）
   - 内部自动转换：`std_cols = [f'{col}_std' for col in factor_cols]`
   - 使用标准化列计算：`factor_df[std_cols]`

**接口设计原因：**
- 用户视角：传入因子名（`factor_cols=['rsi_6']`），无需关心标准化细节
- 内部视角：自动转换列名，使用标准化值计算
- 分离关注点：标准化是内部实现，接口简洁清晰

**代码示例（weight_engine.py）：**
```python
class EqualWeightMethod(WeightMethodBase):
    def calculate(self, factor_df, factor_cols, ...):
        # 内部自动转换为 _std 列
        std_cols = [f'{col}_std' for col in factor_cols]
        
        # 使用标准化列计算
        composite = factor_df[std_cols[0]] * weight
        ...
```

**维护提醒：**
- 不要修改 WeightEngine.calculate() 接口，传入原始列名是正确的
- 不要在调用方预先转换列名，WeightEngine 内部已处理
- 查看函数注释了解接口约定（factor_loader.py:241-257）

---

## 标准化 NaN 处理规范（v1.5 新增）

> 本节定义截面标准化时 NaN 值的处理规范，避免单样本场景下的错误行为。

### 问题类型

**问题：** `lambda x: (x - x.mean()) / x.std() if x.std() > 0 else 0` 在单样本场景下：
1. `x.std(ddof=1)` 单样本返回 NaN（不是 0）
2. 条件 `x.std() > 0` 对 NaN 返回 False
3. 整组被置为 0（包括原本 NaN 的行）
4. 后置 `.loc` 还原 NaN，逻辑冗余且易出错

### NaN 处理规范

**正确行为：**

1. **原始 NaN 保持 NaN**：原因子值为 NaN 时，标准化后仍为 NaN
2. **单样本标准化为 NaN**：某日只有单只股票有有效值时，标准化结果为 NaN（样本标准差无法计算）
3. **有效值不足警告**：count <= 1 时记录警告日志，便于排查数据质量问题

**修复代码：**
```python
# 计算每日截面统计
daily_stats = factor_df.groupby('date')[col].agg(['mean', 'std', 'count'])

# 检查有效值数量不足的情况
low_count_mask = daily_stats['count'] <= 1
low_count_dates = list(daily_stats.index[low_count_mask])
if low_count_dates:
    logger.warning(
        "因子 %s 在 %d 个日期有效值数量 <=1，标准化结果将为 NaN: %s",
        col, len(low_count_dates), low_count_dates[:5]
    )

# 使用 transform 计算标准化值
# 注意：x.std(ddof=1) 单样本时返回 NaN，是正确行为
factor_df[std_col] = factor_df.groupby('date')[col].transform(
    lambda x: (x - x.mean()) / x.std() if x.std() > 0 else np.nan
)

# NaN 处理：原因子值为 NaN 时标准化后仍为 NaN
factor_df.loc[factor_df[col].isna(), std_col] = np.nan
```

**行为对比：**

| 场景 | 原代码行为 | 修复后行为 |
|------|-----------|-----------|
| 单样本有效值 | 整组置为 0 | 返回 NaN（正确） |
| 原始 NaN | 后置还原 | 直接保持 NaN |
| 有效值不足 | 静默错误 | 记录警告日志 |

**修复意义：**
- 单样本场景返回 NaN 符合统计学原理（样本标准差未定义）
- 警告日志帮助发现数据质量问题（如某日只有 1 只股票交易）
- 避免无效标准化值被错误使用

---

## 函数前置条件校验规范（v1.6 新增）

> 本节定义函数前置条件校验规范，避免依赖隐式假设导致的 KeyError。

### 问题类型

**问题：** calc_factor_correlation 依赖 _std 列，但未校验前置条件。如果调用方没先调用 standardize_factors，会抛出不明确的 KeyError。

### 校验规范

**前置条件校验代码：**
```python
def calc_factor_correlation(factor_df, factor_cols, logger):
    std_cols = [f'{col}_std' for col in factor_cols]
    
    # 前置校验：_std 列必须存在
    for std_col in std_cols:
        if std_col not in factor_df.columns:
            raise ValueError(
                f"factor_df 缺少标准化因子列 '{std_col}'\n"
                "可能原因：\n"
                "  1. 调用方未先调用 standardize_factors()\n"
                "  2. standardize_factors 参数 factor_cols 与 calc_factor_correlation 不一致\n"
                "调用顺序：load_factor_values → standardize_factors → calc_factor_correlation"
            )
    
    # 计算相关性
    ...
```

**校验原则：**
- 依赖其他函数生成的列时，必须校验存在性
- 错误信息包含可能原因列表 + 正确调用顺序
- 避免隐式假设（"调用方一定会先调用 X"）

---

## 数据类型校验规范（v1.6 新增）

> 本节定义 DataFrame 关键列的数据类型校验规范。

### 问题类型

**问题：** load_factor_values 未校验 date、asset 列类型，类型不一致可能导致 groupby、merge 等操作异常。

### 类型校验规范

**关键列类型要求：**
| 列名 | 期望类型 | 异常后果 |
|------|---------|---------|
| date | str | groupby('date') 失败 |
| asset | str | merge on='asset' 失败 |

**校验代码：**
```python
def load_factor_values(...):
    factor_df = pd.DataFrame(factor_data['data'])
    
    # 校验列类型
    if len(factor_df) > 0:
        first_date = factor_df['date'].iloc[0]
        if not isinstance(first_date, str):
            raise TypeError(
                f"date 列应为 str，实际为 {type(first_date).__name__}\n"
                f"首行值: {first_date}\n"
                "可能原因：JSON 文件中 date 字段为数字而非字符串"
            )
        
        first_asset = factor_df['asset'].iloc[0]
        if not isinstance(first_asset, str):
            raise TypeError(...)
    
    return factor_df
```

**校验时机：** 数据加载后、返回前。

---

## 缺失因子返回规范（v1.6 新增）

> 本节定义函数返回缺失因子列表的规范，避免调用方不知道哪些因子缺失。

### 问题类型

**问题1：** load_ic_results 静默跳过缺失因子，调用方不知道哪些因子缺失，后续 WeightEngine 可能 KeyError。

**问题2：** load_ic_daily 静默跳过缺失因子，滚动ICIR 计算时部分因子缺失。

### 返回值规范

**返回 Tuple[结果, 缺失列表]：**
```python
def load_ic_results(factor_names, ...) -> Tuple[Dict[str, Dict], List[str]]:
    ic_results = {}
    missing_factors = []
    
    for factor_name in factor_names:
        if not ic_file.exists():
            missing_factors.append(factor_name)
            continue
        
        ic_results[factor_name] = ...
    
    return ic_results, missing_factors
```

**调用方处理：**
```python
ic_results, missing_ic_factors = load_ic_results(...)
if missing_ic_factors:
    logger.warning("部分因子 IC 结果缺失，权重计算将回退等权: %s", missing_ic_factors)
```

**设计原则：**
- 返回缺失列表，让调用方决定如何处理（警告/报错/回退）
- 不静默跳过，避免下游 KeyError

---

## 数据一致性强校验规范（v1.6 新增）

> 本节定义数据一致性校验规范，避免静默截断导致的错位数据。

### 问题类型

**问题：** load_ic_daily 日期与 IC 值数量不一致时静默截断，可能导致错位数据对齐到错误日期。

### 校验规范

**强校验（抛出错误而非截断）：**
```python
if len(dates) != len(ic_values):
    raise ValueError(
        f"日期与IC值数量不一致: dates={len(dates)}, ic_values={len(ic_values)}\n"
        "可能原因：\n"
        "  1. IC 计算过程中部分日期缺失数据\n"
        "  2. JSON 文件写入异常\n"
        "建议：重新运行 IC 分析脚本生成完整的 IC 结果文件"
    )
```

**设计原则：**
- 数据一致性问题是严重错误，不应静默截断
- 截断可能导致错位数据，产生错误的计算结果
- 强校验帮助发现上游数据生成问题

---

## 死代码移除规范（v1.6 新增）

> 本节定义死代码识别和移除规范。

### 问题类型

**问题：** load_ic_daily 生成 ic_sign 列，但后续 WeightEngine 未使用（搜索验证），且 v 可能是 None 导致 TypeError。

### 死代码识别方法

**识别步骤：**
1. 搜索列名使用：`grep "ic_sign"` → 无下游使用
2. 检查计算逻辑：`v > 0` 时 v 可能是 None
3. 确认移除不影响功能

**移除代码：**
```python
# 原代码（死代码 + TypeError 风险）
daily_df = pd.DataFrame({
    'date': dates,
    'ic': ic_values,
    'ic_sign': [1 if v > 0 else -1 if v < 0 else 0 for v in ic_values]  # 死代码
})

# 修复后
ic_values_cleaned = [v if v is not None else np.nan for v in ic_values]
daily_df = pd.DataFrame({
    'date': dates,
    'ic': ic_values_cleaned  # 移除 ic_sign
})
```

**移除原则：**
- 未被下游使用的列 = 死代码，应移除
- 计算逻辑有健壮性问题时，移除而非修复（如果功能不需要）
- 函数注释说明移除原因，避免后续重复添加

---

## 字段回退验证规范（v1.6 新增）

> 本节定义 JSON 字段回退时的验证规范。

### 问题类型

**问题：** load_ic_results 从 ic_metrics 回退到 summary，但 summary 结构可能与 ic_metrics 不一致，缺少必需字段。

### 回退验证规范

**必需字段定义：**
```python
REQUIRED_IC_FIELDS = ['ic_mean', 'icir']  # 静态权重计算必需
```

**回退时验证：**
```python
if 'ic_metrics' in ic_data:
    extracted_data = ic_data['ic_metrics']
elif 'summary' in ic_data:
    extracted_data = ic_data['summary']
    # 检查必需字段是否存在
    missing_fields = [f for f in REQUIRED_IC_FIELDS if f not in extracted_data]
    if missing_fields:
        logger.warning("summary 字段缺失必需字段: %s", missing_fields)
```

**验证原则：**
- 回退字段结构可能不同，必须验证必需字段
- 缺失必需字段时记录警告（不跳过，让下游处理回退）

**遵循 PROJECT.md 模块边界规范：只复用 comprehensive_factor/common/ 下的模块。**

### 必须复用的公共模块

| 功能 | 公共模块路径 | 说明 |
|------|-------------|------|
| 因子数据加载 | `comprehensive_factor.common.factor_loader` | 从factor_ic/backtest结果加载因子值 |
| 加权计算 | `comprehensive_factor.common.weight_engine` | 等权/ICIR/滚动ICIR/IC加权引擎 |
| 公共入口 | `comprehensive_factor.common.composite_runner` | 调用backtest分层回测 |
| 日志配置 | `comprehensive_factor.common.logger_config` | get_logger函数 |
| 类型转换 | `comprehensive_factor.common.convert_types` | numpy/pandas → Python原生类型 |

### 禁止手写的逻辑

| 逻辑 | 正确方式 | 错误方式 |
|------|---------|---------|
| 因子加载 | `load_factor_values()` | 手写 gzip.open + json.load |
| IC结果加载 | `load_ic_results()` | 手写 json.load |
| 加权计算 | `WeightEngine.calculate()` | 手写权重循环 |
| 分层回测 | `run_composite_backtest()` | 手写分层逻辑 |

---

## 输出目录规范

**综合因子结果输出位置：** `comprehensive_factor/result/`

**输出文件命名：** `<脚本名>.json`

**输出结构：**

```json
{
  "meta": {
    "weight_method": "icir_weight",
    "return_period": "1d",
    "factor_list": ["rsi", "volume_ratio_5"],
    "weights": {
      "rsi": 0.35,
      "volume_ratio_5": 0.65
    },
    "ic_results": {
      "rsi": {"ic_mean": -0.032, "icir": -0.45},
      "volume_ratio_5": {"ic_mean": -0.058, "icir": -1.97}
    },
    "correlation_matrix": {
      "rsi_vs_volume_ratio_5": 0.30
    },
    "n_factors": 2,
    "composite_factor_range": [-2.5, 2.8]
  },
  "backtest_result": {
    // 复用 backtest 输出结构
    "meta": {...},
    "layer_stats": [...],
    "long_short": {...},
    "monotonicity": {...},
    "trading_cost_analysis": {...}
  },
  "config": {
    "n_layers": 5,
    "factor_direction": "negative",
    "long_layers": [1, 2],
    "short_layers": [4, 5],
    "trade_cost_rate": 0.003
  },
  "created_at": "2026-05-24T..."
}
```

---

## 日志规范

**遵循 PROJECT.md 项目级日志规范。**

核心要点：
- 使用 Python 标准库 `logging` 模块
- 导入方式：`from comprehensive_factor.common.logger_config import get_logger`
- 日志路径：`comprehensive_factor/logs/*.log`

---

## Config 配置规范

**综合因子分层回测 Config 类：**

```python
from dataclasses import dataclass, field
from typing import List, Dict

@dataclass
class CompositeLayerConfig:
    """综合因子分层配置
    
    综合因子默认为反向因子（低值预期高收益），
    因为低相关性组合中流动性因子（缩量）+ 技术指标（超卖）都指向反向逻辑。
    """
    n_layers: int = 5
    factor_direction: str = 'negative'  # 综合因子默认反向
    long_layers: List[int] = field(default_factory=lambda: [1, 2])
    short_layers: List[int] = field(default_factory=lambda: [4, 5])
    trade_cost_rate: float = 0.003
    min_stocks_per_layer: int = 10
    
    # 因子组合参数
    factor_list: List[str] = field(default_factory=lambda: ['rsi', 'volume_ratio_5'])
    rolling_window: int = 60  # 滚动ICIR窗口（仅rolling_icir使用）
    
    def validate(self) -> None:
        """校验配置完整性"""
        if self.n_layers < 2:
            raise ValueError(f"n_layers 至少需要 2 层，当前: {self.n_layers}")
        if not self.factor_list:
            raise ValueError("factor_list 不能为空")
```

---

## 新加权方式扩展规范

**添加新加权方式时：**

```
□ 在 weight_engine.py 新增加权方法类（继承 WeightMethodBase）
□ 在 MODULE.md 加权方式章节新增说明
□ 新建脚本 composite_<新方式>_1d.py
□ 新建测试用例 test_cases/<新方式>_test_cases.py
□ 运行脚本验证
□ 更新 MODULE.md 版本号
```

---

## 因子数据来源规范

**因子值加载路径：**

| 数据类型 | 来源路径 | 加载方式 |
|---------|---------|---------|
| 因子原始值 | `cache/factor_data/factor_data.json.gz` | `factor_loader.load_factor_values()` |
| IC统计结果 | `factor_ic/result/*.json` | `factor_loader.load_ic_results()` |
| IC每日序列 | `factor_ic/result/*_daily.json.gz` | `factor_loader.load_ic_daily()` |

---

## 调用 backtest 规范

**综合因子计算完成后，调用 backtest 分层回测：**

```python
from backtest.common.layered_backtest_runner import run_layered_backtest

# 将综合因子添加到 factor_df
factor_df['composite_factor'] = composite_factor_values

# 调用分层回测
result = run_layered_backtest(
    factor_name=f'{weight_method}_composite',
    factor_col='composite_factor',
    config=config,
    cache_dir=cache_dir,
    output_dir=output_dir,
    logger=logger
)
```

**注意：** 不重新加载 backtest 的公共模块，直接调用 `run_layered_backtest` 函数。

---

## 版本历史

| 版本 | 日期 | 变更内容 |
|------|------|---------|
| v1.0 | 2026-05-24 | 初始设计：目录结构、脚本命名、加权方式、公共模块、输出规范 |
| v1.1 | 2026-05-24 | 新增公共入口防御性编程规范（必需列校验、返回值解包校验、父类 validate 调用规范） |
| v1.2 | 2026-05-24 | 新增因子名到列名映射规范、动态权重保存规范、NaN相关性处理规范 |
| v1.3 | 2026-05-24 | 新增模块级代码规范、函数入口类型统一规范、composite_factor NaN检查规范、CLI异常退出码规范 |
| v1.4 | 2026-05-24 | 新增校验前置规范、DataFrame空值检查规范、权重元信息分离规范、CLI异常堆栈保留规范 |
| v1.5 | 2026-05-24 | 新增标准化列名接口约定规范、标准化NaN处理规范（单样本场景返回NaN而非0） |
| v1.6 | 2026-05-24 | 新增函数前置条件校验、数据类型校验、缺失因子返回、数据一致性强校验、死代码移除、字段回退验证规范 |
| v1.7 | 2026-05-24 | 新增Union-Find算法、正则因子名解析、关键指标缺失判定、筛选完整性标记、ICIR缺失处理规范 |

---

## Union-Find 算法规范（v1.7 新增）

> 本节定义高相关因子组识别的 Union-Find（并查集）算法规范。

### 问题类型

**问题：** identify_high_corr_groups 使用遍历 pair 合并到第一个找到的组，会漏掉跨组合并。
例：A-B、B-C、C-D 高相关时，可能产生 [A,B,C] 和 [D] 两个独立组，而非 [A,B,C,D]。

### Union-Find 算法规范

**算法步骤：**
1. 初始化每个因子为独立集合（parent[name] = name）
2. 遍历高相关 pair，union 两个因子
3. 最终按 root 分组输出

**代码示例：**
```python
# Union-Find 数据结构
parent = {name: name for name in factor_names}

def find(x: str) -> str:
    """查找根节点（带路径压缩）"""
    if parent[x] != x:
        parent[x] = find(parent[x])  # 路径压缩
    return parent[x]

def union(x: str, y: str) -> None:
    """合并两个集合"""
    root_x = find(x)
    root_y = find(y)
    if root_x != root_y:
        parent[root_x] = root_y  # 合并

# 遍历高相关 pair，union
for (name_i, name_j, _) in high_corr_pairs:
    union(name_i, name_j)

# 按 root 分组
groups_dict = {}
for name in factor_names:
    root = find(name)
    if root not in groups_dict:
        groups_dict[root] = []
    groups_dict[root].append(name)

# 只返回有多个因子的组
groups = [group for group in groups_dict.values() if len(group) > 1]
```

**算法保证：**
- 所有高相关因子合并到同一连通分量
- 路径压缩优化查找效率

---

## 正则因子名解析规范（v1.7 新增）

> 本节定义文件名因子名解析的正则规范。

### 问题类型

**问题：** 使用多次 replace 解析因子名，非标准文件名（如 `ic_rsi_1d_special_analysis_result.json`）会解析错误。

### 正则解析规范

**正则模式：**
```python
import re

# IC 结果文件：ic_<因子名>_<收益周期>_analysis_result.json
ic_pattern = re.compile(rf'^ic_(.+?)_{return_period}_analysis_result$')

# 回测文件：<因子名>_layered_backtest.json
backtest_pattern = re.compile(r'^(.+?)_layered_backtest$')

# 使用正则提取
match = ic_pattern.match(ic_file.stem)
if match:
    factor_name = match.group(1)
else:
    # 回退：使用原逻辑（兼容非标准文件名）
    factor_name = ic_file.stem.replace(...)
    logger.warning("文件名格式非标准: %s", ic_file.name)
```

**正则模式说明：**
- `.+?` 非贪婪匹配因子名（支持含 `_` 的因子名，如 `volume_ratio`）
- 回退逻辑兼容非标准文件名，但记录警告

---

## 关键指标缺失判定规范（v1.7 新增）

> 本节定义因子有效性判定时关键指标缺失的处理规范。

### 问题类型

**问题：** validate_factor 中 ic_mean/icir 缺失时静默跳过检查，空字典因子被判为有效。

### 缺失判定规范

**关键指标（必需）：**
- `ic_mean`：静态权重计算必需
- `icir`：静态权重计算必需

**缺失时判定：**
```python
# 1. IC 均值检查
ic_mean = ic_metrics.get('ic_mean', None)

if ic_mean is None:
    reasons.append("ic_mean 缺失（数据不完整）")
elif abs(ic_mean) < thresholds['ic_mean_abs_min']:
    reasons.append(f"|ic_mean|={abs(ic_mean):.3f}<{thresholds['ic_mean_abs_min']}")

# 3. ICIR 检查
icir = ic_metrics.get('icir', None)

if icir is None:
    reasons.append("icir 缺失（数据不完整）")
elif abs(icir) < thresholds['icir_abs_min']:
    reasons.append(f"|icir|={abs(icir):.3f}<{thresholds['icir_abs_min']}")
```

**判定原则：**
- 关键指标缺失 → 因子无效（数据不完整）
- 可选指标缺失 → 跳过检查（不影响判定）
- 区分缺失和未达标（reason 信息不同）

---

## 筛选完整性标记规范（v1.7 新增）

> 本节定义筛选结果返回结构中的完整性标记规范。

### 问题类型

**问题：** select_factors 中 corr_matrix 为 None 跳过高相关筛选，但返回结构无标记，调用方无法判断筛选是否完整。

### 完整性标记规范

**返回结构：**
```python
result = {
    'selected': selected_factors,
    'valid_count': len(valid_factors),
    'invalid': invalid_factors,
    ...
    'selection_complete': True/False,  # 筛选是否完整
    'selection_warnings': [...]        # 筛选过程中的警告
}
```

**标记说明：**
- `selection_complete=True`：完整筛选（包括高相关筛选）
- `selection_complete=False`：跳过高相关筛选（corr_matrix 缺失或无有效因子）
- `selection_warnings`：警告信息列表

**调用方处理：**
```python
result = select_factors(...)

if not result['selection_complete']:
    logger.warning("筛选不完整: %s", result['selection_warnings'])
    # 决策：是否补充相关性矩阵重新筛选
```

---

## ICIR 缺失处理规范（v1.7 新增）

> 本节定义高相关组选择时 ICIR 缺失的处理规范。

### 问题类型

**问题：** select_best_from_groups 中 icir 缺失时默认为 0，icir 缺失的因子可能因 "ICIR=0" 被选中，而实际 ICIR 较高的因子被丢弃。

### 缺失处理规范

**处理逻辑：**
```python
icir_values = {}
missing_icir_factors = []

for factor_name in group:
    icir = ic_metrics.get('icir', None)  # 不默认为 0
    
    if icir is None:
        missing_icir_factors.append(factor_name)
        icir_values[factor_name] = None  # 明确标记缺失
    else:
        icir_values[factor_name] = abs(icir)

# 只比较有 ICIR 的因子
valid_icir_values = {k: v for k, v in icir_values.items() if v is not None}

if not valid_icir_values:
    # 所有因子 ICIR 缺失，保留第一个（无法比较）
    best_factor = group[0]
    logger.warning("高相关组 %s 所有因子 icir 缺失，无法比较", group)
else:
    # 找出 ICIR 最高的因子
    best_factor = max(valid_icir_values.keys(), key=lambda k: valid_icir_values[k])
```

**处理原则：**
- ICIR 缺失的因子不参与比较（不默认为 0）
- 所有因子 ICIR 缺失时保留第一个（无法比较）
- 区分 ICIR 缺失和 ICIR 较低（丢弃原因不同）

---

## Union-Find 迭代实现规范（v1.8 新增）

> 本节定义 Union-Find 算法的迭代实现规范，避免大规模因子库栈溢出。

### 问题类型

**问题：** Union-Find 使用递归实现 find(x)，大规模因子库（10000+）可能栈溢出。

### 迭代实现规范

**代码示例：**
```python
def find(x: str) -> str:
    """查找根节点（迭代实现 + 路径压缩）"""
    # 迭代查找根节点
    root = x
    while parent[root] != root:
        root = parent[root]
    
    # 路径压缩：将路径上所有节点直接指向根
    current = x
    while parent[current] != root:
        next_node = parent[current]
        parent[current] = root
        current = next_node
    
    return root
```

**优势：**
- 避免递归栈溢出（10000+ 因子安全）
- 保持路径压缩优化（查找效率接近 O(1))

---

## 正则跳过非标准文件规范（v1.8 新增）

> 本节定义文件名解析失败时的跳过处理规范。

### 问题类型

**问题：** 正则不匹配时使用回退逻辑（多次 replace），可能复现已修复的解析 bug。

### 跳过处理规范

**处理逻辑：**
```python
match = ic_pattern.match(ic_file.stem)
if match:
    factor_name = match.group(1)
else:
    # 正则不匹配时跳过文件，而非使用可能有问题的回退逻辑
    logger.warning(
        "文件名格式非标准，跳过: %s（期望格式: ic_<因子名>_%s_analysis_result.json）",
        ic_file.name, return_period
    )
    continue  # 跳过非标准文件
```

**处理原则：**
- 正则不匹配 → 跳过文件（不降级处理）
- 明确告知期望格式（便于排查）
- 单文件问题不影响整体加载

---

## logger 参数传递规范（v1.8 新增）

> 本节定义函数签名新增 logger 参数时的调用方更新规范。

### 问题类型

**问题：** validate_factor 签名新增 logger 参数，但 filter_invalid_factors 调用时未传入。

### 传递规范

**修复代码：**
```python
# filter_invalid_factors 中调用 validate_factor
for factor_name, factor_data in all_factors.items():
    # 传入 logger 参数，以便 validate_factor 记录日志
    is_valid, reasons = validate_factor(
        factor_name, factor_data, thresholds, logger
    )
```

**规范原则：**
- 签名新增 logger 参数 → 所有调用方必须传入
- 子函数需要日志 → 传递父函数的 logger（追溯调用方）

---

## 文件读取异常处理规范（v1.8 新增）

> 本节定义多文件加载时的异常处理规范，单文件损坏不影响整体。

### 问题类型

**问题：** load_all_factor_results 文件读取无异常处理，单文件损坏导致整体失败。

### 异常处理规范

**代码示例：**
```python
for ic_file in ic_result_dir.glob(...):
    match = ic_pattern.match(ic_file.stem)
    if not match:
        continue
    
    # 异常处理：单文件损坏不影响整体加载
    try:
        with open(ic_file, 'r', encoding='utf-8') as f:
            ic_data = json.load(f)
        
        all_factors[factor_name] = {...}
    except (json.JSONDecodeError, UnicodeDecodeError, IOError) as e:
        # JSON 格式错误、编码错误、磁盘问题
        logger.error(
            "文件加载失败，跳过: %s，错误类型: %s，错误信息: %s",
            ic_file.name, type(e).__name__, str(e)
        )
        continue  # 跳过损坏文件，继续加载其他文件
```

**捕获异常类型：**
- `json.JSONDecodeError`: JSON 格式错误
- `UnicodeDecodeError`: 编码错误
- `IOError`: 磁盘问题（文件不存在、权限错误）

**处理原则：**
- 单文件损坏 → 跳过该文件，记录错误
- 其他文件 → 正常加载
- 异常信息 → 包含文件名、错误类型、错误详情

---

## 因子名匹配校验规范（v1.8 新增）

> 本节定义因子名与相关性矩阵索引的匹配校验规范。

### 问题类型

**问题：** identify_high_corr_groups 只在遍历时检查单因子，入口无校验。

### 入口校验规范

**代码示例：**
```python
factor_names = list(valid_factors.keys())

# 入口校验因子名与相关性矩阵索引的匹配性
missing_in_index = [name for name in factor_names if name not in corr_matrix.index]
missing_in_columns = [name for name in factor_names if name not in corr_matrix.columns]

if missing_in_index or missing_in_columns:
    logger.warning(
        "因子名与相关性矩阵索引不匹配: "
        "缺失于 index=%s, 缺失于 columns=%s，将跳过这些因子",
        missing_in_index[:5], missing_in_columns[:5]
    )
    # 过滤掉不在矩阵中的因子
    factor_names = [name for name in factor_names 
                    if name in corr_matrix.index and name in corr_matrix.columns]
    
    if len(factor_names) == 0:
        logger.error("所有因子都不在相关性矩阵中，返回空组")
        return []
```

**校验原则：**
- 入口校验 → 发现问题立即处理
- 跳过不匹配因子 → 继续处理其他因子
- 全部不匹配 → 返回空组，记录错误

---

## set 替代 list 性能规范（v1.8 新增）

> 本节定义使用 set 替代 list 提升性能的规范。

### 问题类型

**问题：** select_best_from_groups 使用 list.remove() + in 检查，嵌套循环 O(n²) 复杂度。

### 性能优化规范

**代码示例：**
```python
# 使用 set 替代 list，避免 O(n²) 复杂度
# list.remove() + in 检查 都是 O(n)，嵌套循环总体 O(n²)
# set.discard() + in 检查 都是 O(1)，总体 O(n)
selected_factors_set = set(valid_factors.keys())  # 初始为所有有效因子

for group in high_corr_groups:
    for factor_name in group:
        if factor_name != best_factor:
            if factor_name in selected_factors_set:  # O(1)
                selected_factors_set.discard(factor_name)  # O(1)

# 返回 list 格式（兼容调用方）
return list(selected_factors_set), dropped_factors
```

**性能对比：**
| 操作 | list | set |
|------|------|-----|
| in 检查 | O(n) | O(1) |
| remove/discard | O(n) | O(1) |
| 嵌套循环总体 | O(n²) | O(n) |

**适用场景：**
- 嵌套循环中需要频繁删除 + 检查
- 因子数量可能增长到 100+| 版本 | 日期 | 变更内容 |
|------|------|----------|
| v1.0 | 2026-05-24 | 初始设计：目录结构、脚本命名、加权方式、公共模块、输出规范 |
| v1.1 | 2026-05-24 | 新增公共入口防御性编程规范（必需列校验、返回值解包校验、父类 validate 调用规范） |
| v1.2 | 2026-05-24 | 新增因子名到列名映射规范、动态权重保存规范、NaN相关性处理规范 |
| v1.3 | 2026-05-24 | 新增模块级代码规范、函数入口类型统一规范、composite_factor NaN检查规范、CLI异常退出码规范 |
| v1.4 | 2026-05-24 | 新增校验前置规范、DataFrame空值检查规范、权重元信息分离规范、CLI异常堆栈保留规范 |
| v1.5 | 2026-05-24 | 新增标准化列名接口约定规范、标准化NaN处理规范（单样本场景返回NaN而非0） |
| v1.6 | 2026-05-24 | 新增函数前置条件校验、数据类型校验、缺失因子返回、数据一致性强校验、死代码移除、字段回退验证规范 |
| v1.7 | 2026-05-24 | 新增Union-Find算法、正则因子名解析、关键指标缺失判定、筛选完整性标记、ICIR缺失处理规范 |
| v1.8 | 2026-05-24 | 新增Union-Find迭代实现、正则跳过非标准文件、logger参数传递、文件读取异常处理、因子名匹配校验、set替代list性能规范 |
| v1.9 | 2026-05-24 | 新增import位置规范、thresholds入口统一处理、logger参数使用规范 |

---

## import 位置规范（v1.9 新增）

> 本节定义 import 语句的位置规范，遵循 PEP 8 标准。

### 问题类型

**问题：** import re 放在函数体内部而非模块顶层，违反 PEP 8。

### import 位置规范

**规范要求（PEP 8）：**
- 所有 import 语句应放在模块顶层
- import 顺序：标准库 → 第三方库 → 本地库
- 每组之间空一行

**正确示例：**
```python
import json
import logging
import re  # 修复：移至模块顶层（PEP 8 规范）
import pandas as pd
import numpy as np
from pathlib import Path
from typing import Dict, List, Tuple, Optional

from comprehensive_factor.common.logger_config import get_logger
```

**错误示例：**
```python
def load_all_factor_results(...):
    logger.info("加载 IC 结果: %s", ic_result_dir)
    import re  # 错误：在函数体内部导入
    
    ic_pattern = re.compile(...)
```

**例外情况：**
- 条件导入（可选依赖）
- 避免循环导入（极少数情况）

---

## thresholds 入口统一处理规范（v1.9 新增）

> 本节定义可选参数 thresholds 的入口统一处理规范。

### 问题类型

**问题：** select_factors 中 thresholds.get(...) 在 thresholds 为 None 时需要分散处理多处。

### 入口统一处理规范

**处理逻辑：**
```python
def select_factors(..., thresholds: Optional[Dict] = None, ...):
    if logger is None:
        logger = get_logger(__name__)
    
    # 修复：入口统一处理 thresholds 为 None 的情况
    if thresholds is None:
        thresholds = DEFAULT_THRESHOLDS
    
    # 后续代码直接使用 thresholds，无需反复判断 None
    high_corr_groups = identify_high_corr_groups(
        threshold=thresholds['high_corr_threshold'],  # 直接使用
        ...
    )
```

**优势：**
- 入口统一处理 → 后续代码简洁
- 避免分散的 `if thresholds else ...` 判断
- 降低维护成本（修改一处而非多处）

---

## logger 参数使用规范（v1.9 新增）

> 本节定义 logger 参数接收后的使用规范，避免死代码。

### 问题类型

**问题：** validate_factor 中 logger 参数接收并初始化，但函数体内无日志调用，是死代码。

### logger 使用规范

**使用原则：**
- logger 参数接收 → 必须在关键分支使用
- debug 日志 → 记录检查过程（便于排查）
- warning/error 日志 → 记录异常情况

**正确示例：**
```python
def validate_factor(..., logger: Optional[logging.Logger] = None):
    if logger is None:
        logger = get_logger(__name__)
    
    # 修复：关键指标缺失时记录日志
    if ic_mean is None:
        reasons.append("ic_mean 缺失（数据不完整）")
        logger.debug("因子 %s: ic_mean 缺失", factor_name)
    elif abs(ic_mean) < thresholds['ic_mean_abs_min']:
        reasons.append(f"|ic_mean|={abs(ic_mean):.3f}<...")
        logger.debug("因子 %s: |ic_mean|=%.3f 不达标", factor_name, abs(ic_mean))
```

**日志级别选择：**
| 情况 | 级别 |
|------|------|
| 正常检查过程 | debug |
| 指标缺失 | debug |
| 指标不达标 | debug |
| 因子无效 | warning（调用方处理） |

**死代码判断：**
- logger 参数接收 + 初始化 → 但无调用 → 死代码
- 死代码 → 删除参数 或 添加调用

---

## 滚动 ICIR 时间轴计算规范（v1.10 新增）

> 本节定义滚动 ICIR 的正确计算方式，避免按 asset 分组的逻辑错误。

### 问题类型

**问题：** RollingICIRWeightMethod 按 asset 分组计算滚动 ICIR，逻辑根本性错误。

### 错误实现

```python
# 错误：按 asset 分组后在股票截面上滚动
factor_df.groupby('asset')[ic_col].transform(
    lambda x: x.rolling(window).mean() / x.rolling(window).std()
)
```

**错误原因：**
- IC 是每日截面相关性（因子值与未来收益的相关性）
- 同一日期所有股票的 IC 值相同
- 按 asset 分组是多余的（所有股票 IC 序列相同）
- 滚动计算应在时间轴上进行

### 正确实现

```python
# 正确：直接在时间轴上滚动
# IC 时间序列：每日截面 IC 值组成的时间序列
ic_series = ic_df.set_index('date')['ic'].sort_index()

# 时间轴滚动计算
rolling_mean = ic_series.rolling(window=self.window, min_periods=self.window // 3).mean()
rolling_std = ic_series.rolling(window=self.window, min_periods=self.window // 3).std()
rolling_icir = rolling_mean / rolling_std.replace(0, np.nan)
```

**正确逻辑：**
- IC 时间序列：每日截面 IC 值 → 一条时间序列
- 滚动 ICIR：在时间轴上计算（mean/std）
- 映射到 factor_df：同一天所有股票共享同一个滚动 ICIR

---

## 因子名反向映射规范（v1.10 新增）

> 本节定义因子列名到 IC 结果因子名的反向映射规范。

### 问题类型

**问题：** ICIRWeightMethod 和 ICWeightMethod 硬编码 `_5`、`_6` 后缀移除。

### 错误实现

```python
# 错误：硬编码特定后缀
factor_name = col.replace('_5', '').replace('_6', '')
```

**问题：**
- 不支持其他后缀（`_20`, `_1d`, `_9`）
- 新增因子需要修改代码

### 正确实现

```python
# 正确：使用反向映射 + 正则回退
class WeightMethodBase(ABC):
    FACTOR_NAME_TO_COL_MAP = {
        'rsi': 'rsi_6',
        'volume_ratio': 'volume_ratio_5',
        ...
    }
    COL_TO_FACTOR_NAME_MAP = {v: k for k, v in FACTOR_NAME_TO_COL_MAP.items()}
    
    def _get_factor_name_from_col(self, col: str) -> str:
        # 优先使用反向映射
        if col in self.COL_TO_FACTOR_NAME_MAP:
            return self.COL_TO_FACTOR_NAME_MAP[col]
        
        # 回退：正则移除数字后缀
        match = re.match(r'(.+?)_\d+[a-z]?$', col)  # 支持 _5, _6, _1d 等
        if match:
            return match.group(1)
        
        # 最终回退：原列名
        return col
```

**优势：**
- 精确匹配优先（反向映射）
- 正则支持任意数字后缀
- 新增因子只需更新映射表

---

## factor_cols 空值校验规范（v1.10 新增）

> 本节定义 factor_cols 空值校验规范，避免 IndexError。

### 问题类型

**问题：** EqualWeightMethod.calculate 在 factor_cols 为空时触发 IndexError（`std_cols[0]`）。

### 校验规范

```python
# 基类公共方法
def _validate_factor_cols(self, factor_cols: List[str], logger: logging.Logger) -> None:
    if not factor_cols or len(factor_cols) == 0:
        raise ValueError("因子列 factor_cols 为空，无法计算加权")

# 子类调用
def calculate(self, factor_df, factor_cols, ...):
    self._validate_factor_cols(factor_cols, self.logger)
    ...
```

**校验位置：**
- calculate 方法入口
- get_weights 方法入口
- WeightEngine.calculate 入口

---

## 除零保护规范（v1.10 新增）

> 本节定义权重计算中的除零保护规范。

### 问题类型

**问题：** ICIRWeightMethod 和 ICWeightMethod 的 total_icir/total_ic 为 0 时产生 ZeroDivisionError。

### 除零保护规范

```python
# 除零保护
total_icir = sum(icir_values.values())
if total_icir == 0:
    logger.warning("所有因子 ICIR 绝对值均为 0，回退等权")
    n_factors = len(factor_cols)
    return {col: 1.0 / n_factors for col in factor_cols}

weights = {col: icir_values[col] / total_icir for col in factor_cols}
```

**触发条件：**
- 所有因子 ICIR 缺失（被置为 1.0）→ 不触发（total > 0）
- 所有因子 ICIR 绝对值均为 0 → 触发除零

**处理方式：**
- 检测 total == 0
- 回退等权
- 记录警告日志

---

## 无效参数警告规范（v1.10 新增）

> 本节定义无效参数的警告提示规范。

### 问题类型

**问题：** WeightEngine 中 window 参数仅对 rolling_icir_weight 有效，其他方式静默忽略。

### 警告规范

```python
class WeightEngine:
    WINDOW_VALID_METHODS = ['rolling_icir_weight']
    
    def __init__(self, weight_method, window=60, ...):
        # 修复：window 参数仅对 rolling_icir_weight 有效
        if window != 60 and weight_method not in self.WINDOW_VALID_METHODS:
            logger.warning(
                "window=%d 参数对 %s 加权方式无效，仅 rolling_icir_weight 支持窗口参数",
                window, weight_method
            )
```

**警告条件：**
- window != 60（非默认值）
- weight_method 不在 WINDOW_VALID_METHODS 中

**处理方式：**
- 记录警告日志
- 继续执行（不中断）
- 调用方知情

---

## 向量化加权实现规范（v1.10 新增）

> 本节定义向量化加权实现规范，替代循环实现。

### 问题类型

**问题：** 三个静态加权类的 calculate 方法存在重复的循环加权代码。

### 向量化实现

```python
# 基类公共方法
def _apply_weights(
    self,
    factor_df: pd.DataFrame,
    factor_cols: List[str],
    weights: Dict[str, float],
    logger: logging.Logger,
    method_name: str = "加权"
) -> pd.Series:
    # 向量化加权求和（而非循环）
    std_cols = [f'{col}_std' for col in factor_cols]
    weight_values = np.array([weights[col] for col in factor_cols])
    std_df = factor_df[std_cols]
    
    # DataFrame * 权重向量，然后按列求和
    composite = std_df.multiply(weight_values, axis=1).sum(axis=1)
    
    return composite
```

**性能对比：**
| 实现 | 方式 | 性能 |
|------|------|------|
| 循环 | `composite + factor_df[col] * weight` | O(n) 次循环 |
| 向量化 | `DataFrame.multiply().sum()` | 单次矩阵运算 |

**适用场景：**
- 静态权重（权重不随时间变化）
- 每日动态权重（滚动 ICIR）需单独处理

---

| 版本 | 日期 | 变更内容 |
|------|------|----------|
| v1.0 | 2026-05-24 | 初始设计：目录结构、脚本命名、加权方式、公共模块、输出规范 |
| v1.1 | 2026-05-24 | 新增公共入口防御性编程规范（必需列校验、返回值解包校验、父类 validate 调用规范） |
| v1.2 | 2026-05-24 | 新增因子名到列名映射规范、动态权重保存规范、NaN相关性处理规范 |
| v1.3 | 2026-05-24 | 新增模块级代码规范、函数入口类型统一规范、composite_factor NaN检查规范、CLI异常退出码规范 |
| v1.4 | 2026-05-24 | 新增校验前置规范、DataFrame空值检查规范、权重元信息分离规范、CLI异常堆栈保留规范 |
| v1.5 | 2026-05-24 | 新增标准化列名接口约定规范、标准化NaN处理规范（单样本场景返回NaN而非0） |
| v1.6 | 2026-05-24 | 新增函数前置条件校验、数据类型校验、缺失因子返回、数据一致性强校验、死代码移除、字段回退验证规范 |
| v1.7 | 2026-05-24 | 新增Union-Find算法、正则因子名解析、关键指标缺失判定、筛选完整性标记、ICIR缺失处理规范 |
| v1.8 | 2026-05-24 | 新增Union-Find迭代实现、正则跳过非标准文件、logger参数传递、文件读取异常处理、因子名匹配校验、set替代list性能规范 |
| v1.9 | 2026-05-24 | 新增import位置规范、thresholds入口统一处理、logger参数使用规范 |
| v1.10 | 2026-05-24 | 新增滚动ICIR时间轴计算、因子名反向映射、factor_cols空值校验、除零保护、无效参数警告、向量化加权实现规范 |
| v1.11 | 2026-05-24 | 新增lambda延迟绑定修复、NaN动态权重归一化、正则预编译规范 |

---

## lambda 延迟绑定问题规范（v1.11 新增）

> 本节定义 lambda 延迟绑定问题的修复规范，避免循环变量捕获问题。

### 问题类型

**问题：** RollingICIRWeightMethod 中 lambda 捕获循环变量，导致所有因子映射到同一序列。

### 错误实现

```python
# 错误：lambda 延迟绑定
for col in factor_cols:
    rolling_icir_series = rolling_icir_dict[col]
    factor_df[f'{col}_rolling_icir'] = factor_df['date_sorted'].map(
        lambda d: rolling_icir_series.get(pd.Timestamp(d), np.nan)
    )
```

**问题分析：**
- Python lambda 捕获变量是延迟绑定的（闭包引用）
- 循环中 `rolling_icir_series` 被多次赋值
- `map` 是惰性的（返回 map 对象，未立即执行）
- 循环结束后，所有 lambda 中的 `rolling_icir_series` 指向最后一个因子的序列

**结果：** 所有因子列映射到同一个 IC 序列（最后一个因子）

### 正确实现

```python
# 正确：直接使用 pandas.Series.map（无 lambda）
for col in factor_cols:
    if col in rolling_icir_dict and len(rolling_icir_dict[col]) > 0:
        rolling_icir_series = rolling_icir_dict[col]
        # Series.map(Series) 会用 date_sorted 的值在 rolling_icir_series 索引中查找
        factor_df[f'{col}_rolling_icir'] = factor_df['date_sorted'].map(rolling_icir_series)
```

**优势：**
- 无 lambda，无延迟绑定问题
- pandas.Series.map(Series) 直接索引查找
- 更简洁且更高效

### 其他解决方案

```python
# 方案2：使用默认参数固定当前值（不推荐）
lambda d, series=rolling_icir_series: series.get(pd.Timestamp(d), np.nan)
```

---

## NaN 动态权重归一化规范（v1.11 新增）

> 本节定义加权计算中的 NaN 处理规范，避免权重稀释问题。

### 问题类型

**问题：** _apply_weights 中 sum(axis=1) 将 NaN 位置计为 0，导致综合因子偏低。

### 错误实现

```python
# 错误：sum(axis=1) 默认 skipna=True，NaN 计为 0
composite = std_df.multiply(weight_values, axis=1).sum(axis=1)
```

**问题分析：**
- 3个因子，权重各 1/3
- 因子1缺失（NaN），因子2、3有效
- 原实现：综合因子 = 0 + factor2*1/3 + factor3*1/3 = factor2*1/3 + factor3*1/3
- 权重之和 = 1/3 + 1/3 = 2/3 < 1（权重被稀释）

**结果：** 缺失因子值时综合因子偏低（权重不归一）

### 正确实现

```python
# 正确：动态权重归一化
# 识别有效值（非 NaN）位置
valid_mask = ~std_df.isna()

# 计算每行的有效权重之和
valid_weight_sum = (valid_mask.multiply(weight_values, axis=1)).sum(axis=1)

# 加权后归一化
weighted_df = std_df.multiply(weight_values, axis=1)
composite = weighted_df.divide(valid_weight_sum.replace(0, np.nan), axis=0).sum(axis=1, skipna=False)

# 全 NaN 行保持 NaN
composite = composite.where(valid_weight_sum > 0, np.nan)
```

**处理逻辑：**
- 因子1缺失 → 有效权重 = factor2权重 + factor3权重
- 归一化：每个有效因子权重 / 有效权重之和
- 结果：权重之和始终为 1（无稀释）

---

## 正则预编译规范（v1.11 新增）

> 本节定义正则表达式预编译规范，避免重复编译开销。

### 问题类型

**问题：** _get_factor_name_from_col 中正则每次调用都重新编译。

### 错误实现

```python
def _get_factor_name_from_col(self, col: str) -> str:
    import re  # 错误：import 在方法体内部
    match = re.match(r'(.+?)_\d+[a-z]?$', col)  # 错误：每次调用都编译
```

**问题：**
- import 在方法体内部（违反 PEP 8）
- 正则每次调用都编译（性能开销）

### 正确实现

```python
import re  # 正确：import 在文件顶部

class WeightMethodBase(ABC):
    # 正确：正则预编译为类属性（一次编译，多次使用）
    _FACTOR_SUFFIX_PATTERN = re.compile(r'(.+?)_\d+[a-z]?$')
    
    def _get_factor_name_from_col(self, col: str) -> str:
        match = self._FACTOR_SUFFIX_PATTERN.match(col)  # 直接使用预编译正则
```

**优势：**
- import 在文件顶部（PEP 8 规范）
- 正则预编译为类属性（一次编译）
- 每次调用直接使用预编译正则（无编译开销）

---