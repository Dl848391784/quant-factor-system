# summary 模块规范

> 版本: v2.1
> 创建时间: 2026-05-28
> 最后更新: 2026-06-02

## 快速参考

### 模块职责

**summary 模块负责采集其他模块的日志信息，生成统计报告。**

核心功能：
1. 数据汇总：读取各模块 result 目录的输出数据
2. 报告生成：生成因子分析数据汇总报告
3. 因子合并：合并多个因子数据到主数据源

### 目录结构

```
summary/
├── MODULE.md           # 本文件（模块规范）
├── docs/               # 流程文档
│   ├── generate_factor_summary_report_flow.md
│   └── merge_factors_flow.md
├── logs/               # 日志目录（汇总报告生成日志）
├── result/             # 汇总报告输出目录
│   └── factor_summary_report_YYYY-MM-DD.txt
├── test_cases/         # 测试用例
│   ├── test_generate_factor_summary_report.py
│   └── test_merge_factors.py
│
├── generate_factor_summary_report.py  # 因子分析汇总报告生成
└── merge_factors.py                   # 因子数据合并
```

---

## 数据来源规范

### 输入数据路径

**summary 模块读取其他模块的输出数据，不自行计算。**

| 数据类型 | 来源模块 | 数据路径 | 文件格式 |
|---------|---------|---------|---------|
| IC 分析结果 | factor_ic | `factor_ic/result/` | `ic_<因子名>_analysis_result.json` |
| 分层回测结果 | backtest | `backtest/result/` | `<因子名>_layered_backtest.json` |
| 综合因子结果 | comprehensive_factor | `comprehensive_factor/result/` | `composite_<加权方式>_1d.json` |
| 因子数据 | data_fetchers | `data_fetchers/result/` | `factor_ic_data.json.gz` |

### 数据流向

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│  factor_ic  │────▶│  summary    │────▶│   汇总报告  │
│ (IC 结果)   │     │ (数据采集)  │     │ (文本输出)  │
└─────────────┘     └─────────────┘     └─────────────┘
      │                   │
      │                   │
┌─────────────┐     ┌─────────────┐
│  backtest   │────▶│             │
│ (回测结果)  │     │             │
└─────────────┘     └─────────────┘
      │                   
      │                   
┌─────────────┐     
│comprehensive│────▶
│  _factor    │     
└─────────────┘     
```

### 模块依赖（v2.1 新增）

**generate_factor_summary_report.py 依赖根目录 factor_definitions 模块获取因子定义信息。**

```python
# 导入方式
from factor_definitions import FACTOR_DEFINITIONS, get_factor_definition
```

依赖原因：
- 因子定义（计算公式、业务含义）是项目级公共信息
- 新增因子时只需在 factor_definitions.py 添加定义，无需修改 summary 模块
- 符合 PROJECT.md "跨模块数据契约"定位

---

## 数据完整性检查规范（v1.9 新增）

### 检查时机

**generate_report() 函数开始时执行数据完整性检查，在加载 IC/回测数据之前。**

检查目的：
- 确保所有数据源已更新至最新交易日（T-1）
- 提前发现数据缺失或延迟问题
- 在报告第零部分展示检查结果

### 基础数据源检查

**check_data_freshness(date, logger) 检查基础数据源新鲜度和完成度。**

检查配置 DATA_CHECK_SOURCES：

| 数据源 | 路径 | 日期字段 | 格式 |
|-------|------|---------|------|
| factor_ic_data | factor_ic_data.json.gz | dates[-1] | line_json |
| factor_data | factor_data.json.gz | meta.date_range.end | full_json |
| turnover_data | turnover_rate_data.json.gz | meta.date_range.end | full_json |

**数据完成度检查（v2.0 新增）：**

基础数据源不仅要检查最新日期是否存在，还要统计最新日期的股票数占比：

```
完成度 = 最新日期股票数 / 总股票数
```

例如：总股票数 3000 支，最新日期只有 300 支股票数据 → 完成度 10% → 状态为 △不完整

| 完成度阈值 | 状态判定 | 符号 |
|-----------|---------|------|
| ≥ 95% | ok | ✓正常 |
| 70% ~ 95% | warning | △不完整 |
| < 70% | error | ✗严重缺失 |

检查方法：
1. 从 factor_ic_data.json.gz 读取最新日期（dates[-1]）
2. 统计该日期下的股票数（读取该日期对应的数据行）
3. 对比 expected_stocks（从 factor_data.json.gz meta.total_stocks 获取，约 3000）
4. 计算完成度百分比

### 衍生数据检查

**check_derived_data_freshness(date, logger) 检查衍生数据存在性和数据完整性。**

检查内容：

| 数据类型 | 检查方式 | 状态判定 |
|---------|---------|---------|
| IC 结果 | 文件存在 + dates[-1] 匹配 + 数据非空 | ok/warning/error |
| 回测结果 | 文件存在 + 数量统计 + 数据非空 | ok/error |
| 综合因子结果 | 文件存在 + 数量统计 + 数据非空 | ok/error |

**数据存在性检查（v2.0 新增）：**

衍生数据不仅要检查文件是否生成，还要验证文件中数据是否存在：

| 数据类型 | 检查字段 | 非空标准 |
|---------|---------|---------|
| IC 结果 | dates, ic_values | len(dates) > 0, len(ic_values) > 0 |
| 回测结果 | layers, long_short | len(layers) > 0, long_short 非空 |
| 综合因子结果 | weights, factor_list | len(weights) > 0, len(factor_list) > 0 |

若文件存在但数据为空 → 状态为 ✗数据空

### 状态判定标准

| 状态 | 条件 | 符号 |
|------|------|------|
| ok | actual_date == expected_date + 完成度 ≥ 95% + 数据非空 | ✓正常 |
| warning | actual_date != expected_date 或 完成度 70%~95% | △延迟/△不完整 |
| error | 文件不存在 | ✗缺失 |
| error | 文件损坏或格式错误 | ✗读取失败 |
| error | 无法解析日期字段 | ✗无日期 |
| error | 数据为空（dates/ic_values 等长度为 0） | ✗数据空 |
| error | 完成度 < 70% | ✗严重缺失 |

### 报告展示

**_generate_data_check_section(data_results, derived_results) 生成报告第零部分。**

输出格式：
```
零、数据完整性检查
----------------------------------------------------------------------
期望数据日期: 2026-06-01 (T-1)

【基础数据源】
数据源               描述                     最新日期     完成度    状态
----------------------------------------------------------------------
factor_ic_data       主数据源(行情+因子+收益)    2026-06-01   100%     ✓正常
...

【衍生数据】
数据源               描述                     文件数量     数据状态    状态
----------------------------------------------------------------------
ic_results           IC分析结果                    10     数据完整    ✓正常(10因子)
...

汇总: ✓ 所有数据源已更新至 T-1
```

---

## 因子数据汇总规范（v2.0 新增）

### 单因子 IC 数据汇总

**_generate_ic_section(ic_results) 必须汇总所有因子，新增因子自动适配。**

要求：
1. **自动发现因子**：从 `factor_ic/result/ic_*_analysis_result.json` 文件列表动态获取因子名
2. **不遗漏因子**：禁止硬编码因子列表，必须从文件列表推断
3. **排序规则**：按 ICIR 降序排列
4. **数量一致性**：报告显示的因子数 = factor_ic/result 目录下的文件数

检查方法：
```bash
# 因子数量一致性检查
factor_count=$(ls factor_ic/result/ic_*_analysis_result.json | wc -l)
grep -c "^因子" summary/result/factor_summary_report_*.txt | expect $factor_count
```

### 单因子分层回测数据汇总

**_generate_backtest_section(ic_results, backtest_results) 必须汇总所有因子。**

要求：
1. **自动发现因子**：从 `backtest/result/*_layered_backtest.json` 文件列表动态获取
2. **不遗漏因子**：禁止硬编码因子列表
3. **排序规则**：按 IC 结果的 ICIR 排序（回测数据跟随 IC 排序）
4. **数量一致性**：报告显示的因子数 = backtest/result 目录下的文件数

### 因子筛选结果展示

**get_factor_selection_info(...) 必须展示所有因子及其筛选状态。**

要求：
1. **展示所有因子**：选中因子 + 剔除因子都要展示，不遗漏
2. **自动适配**：新增因子自动加入筛选结果，无需手动修改代码
3. **剔除原因透明**：每个剔除因子必须展示具体剔除原因（ICIR 不足、高相关、单调性差等）

输出格式：
```
四、因子筛选结果
----------------------------------------------------------------------
auto_select 模式结果:
  - 选中因子: amplitude(ICIR=0.36), turnover_surge(ICIR=0.32)
  - 剔除因子: volume_ratio(高相关), bollinger_pb(单调性差), ...
----------------------------------------------------------------------
筛选后因子列表: ['amplitude', 'turnover_surge']
```

---

## 综合因子权重完整性规范（v2.0 新增）

### 四种权重必须包含

**综合因子四种权重回测数据汇总必须包含以下四种方式：**

| 权重方法 | 文件名 | 必须存在 |
|---------|--------|---------|
| IC 加权 | composite_ic_weight_1d.json | ✓ |
| ICIR 加权 | composite_icir_weight_1d.json | ✓ |
| Rolling ICIR 加权 | composite_rolling_icir_weight_1d.json | ✓ |
| 等权 | composite_equal_weight_1d.json | ✓ |

检查方法：
```bash
ls comprehensive_factor/result/composite_*_1d.json | wc -l | expect 4
```

若缺失任一权重 → 报告显示 ✗权重缺失，并提示缺失的权重方法

### 数据相近提示

**四种权重的回测数据相近时必须提示，可能存在 bug。**

相近判定标准：

| 指标 | 相近阈值 | 提示 |
|------|---------|------|
| 多空年化收益 | 差值 < 0.5% | △收益相近，检查权重计算 |
| 夏普比率 | 差值 < 0.1 | △夏普相近，检查权重计算 |
| 单调性系数 | 差值 < 0.05 | △单调性相近，检查权重计算 |

例外：若选中因子只有 1 个（单因子），则四种权重结果必然相同，相近是合理的，不提示。

提示格式：
```
⚠ 权重方法 IC加权 与 ICIR加权 数据相近（收益差 0.3%），可能存在计算 bug
  若选中因子为单因子，相近是合理的
```

---

## 脚本规范

### 脚本命名规则

| 脚本类型 | 命名规则 | 示例 |
|---------|---------|------|
| 汇总报告生成 | `generate_<功能>_report.py` | `generate_factor_summary_report.py` |
| 数据合并 | `merge_<对象>.py` | `merge_factors.py` |

### generate_factor_summary_report.py

**功能：** 生成因子分析数据汇总报告

**输入：**
- 单因子 IC 分析结果（factor_ic/result/）
- 单因子分层回测结果（backtest/result/）
- 综合因子四种权重回测结果（comprehensive_factor/result/）
- 因子数据文件（data_fetchers/result/factor_ic_data.json.gz）

**输出：**
- 汇总报告（文本格式）
- 默认输出到终端，可通过 --output 参数指定文件路径

**报告内容：**
0. 数据完整性检查（v1.9 新增，检查数据源新鲜度）
1. 单因子 IC 数据汇总表（因子名、IC均值、ICIR、IC标准差、有效天数）
2. 单因子分层回测数据汇总表（因子名、多空年化收益、夏普比率、单调性）
3. 因子相关性矩阵（高相关/中等相关因子对提示）
4. 因子筛选信息（选中/剔除因子及原因）
5. 综合因子四种权重回测对比表
6. 综合因子 vs 单因子对比表

**CLI 参数：**
```bash
python summary/generate_factor_summary_report.py [--date YYYY-MM-DD] [--output report.txt]
```

| 参数 | 说明 | 默认值 |
|------|------|--------|
| --date | 指定日期 | 当天 |
| --output | 指定输出文件路径 | `summary/result/factor_summary_report_YYYY-MM-DD.txt` |

**输出路径规范：**
- 默认输出到 `summary/result/factor_summary_report_<日期>.txt`
- 可通过 `--output` 参数指定自定义路径

### merge_factors.py

**功能：** 合并多个因子数据到主数据源

**输入：**
- 主数据源（data_fetchers/result/factor_ic_data.json.gz）
- 新因子文件（cache/factor_data/factors/*.parquet）

**输出：**
- 合并后数据（data_fetchers/result/factor_ic_data.json.gz）
- 合并后数据 Parquet 格式（data_fetchers/result/factor_ic_data.parquet）
- 元数据文件（data_fetchers/result/factor_ic_data_metadata.json）

**合并流程：**
1. 加载主数据源
2. 加载所有 parquet 因子文件
3. 数据对齐（基于 date + asset）
4. 命名统一（使用 parquet 文件名作为因子名）
5. 生成合并后数据

---

## 日志规范

### 日志目录

**汇总报告生成日志存放在 `summary/logs/` 目录。**

日志文件命名规则：
- `<脚本名>_YYYY-MM-DD.log`
- 例如：`generate_factor_summary_report_2026-05-28.log`

### 日志内容要求

| 步骤 | 必须记录内容 |
|------|-------------|
| 数据加载 | 加载的数据源路径、记录数、列数 |
| 数据处理 | 处理进度、处理结果统计 |
| 报告生成 | 报告各部分生成状态 |
| 异常处理 | 异常类型、异常信息、处理结果 |

---

## 公共模块复用规范

**summary 模块暂无公共模块（common/）。**

如需抽取公共功能，遵循 PROJECT.md 公共模块规范：
- 公共模块放在 `summary/common/` 目录
- 公共函数接收 logger 参数（遵循 factor_ic/MODULE.md 日志传递规范）
- 公共模块仅在本模块内复用，禁止跨模块调用

---

## 输出格式规范

### 汇总报告格式

**报告使用纯文本格式，便于终端阅读。**

报告结构：
```
======================================================================
                    因子分析数据汇总报告 (YYYY-MM-DD)
======================================================================

零、数据完整性检查（v1.9 新增）
----------------------------------------------------------------------
期望数据日期: YYYY-MM-DD (T-1)

【基础数据源】
数据源               描述                     最新日期     状态
----------------------------------------------------------------------
factor_ic_data       主数据源(行情+因子+收益)    YYYY-MM-DD    ✓正常
...

【衍生数据】
数据源               描述                     文件数量     状态
----------------------------------------------------------------------
ic_results           IC分析结果                    N     ✓正常(N因子)
...

汇总: ✓ 所有数据源已更新至 T-1
----------------------------------------------------------------------

一、单因子 IC 数据汇总
----------------------------------------------------------------------
因子               IC均值      ICIR    IC标准差    有效天数
----------------------------------------------------------------------
rsi                -0.045     0.51      0.089       498
...

二、单因子分层回测数据汇总
----------------------------------------------------------------------
...

三、因子相关性矩阵
----------------------------------------------------------------------
...

四、因子筛选信息
----------------------------------------------------------------------
...

五、综合因子四种权重回测对比
----------------------------------------------------------------------
...

六、综合因子 vs 单因子对比
----------------------------------------------------------------------
...
======================================================================
```

### 单调性质量符号

| quality 值 | 显示符号 |
|-----------|---------|
| good | ✓良好 |
| moderate | △一般 |
| poor | ✗较差 |
| unknown | ?未知 |

---

## 测试用例规范

### 测试文件位置

**测试用例存放在 `summary/test_cases/` 目录。**

测试文件命名规则：
- `test_<脚本名>.py`
- 例如：`test_generate_factor_summary_report.py`

### 测试覆盖范围

| 测试类型 | 覆盖内容 |
|---------|---------|
| 输入验证 | 数据文件存在性、数据格式正确性 |
| 输出验证 | 报告格式正确性、字段完整性 |
| 边界条件 | 无数据情况、部分数据缺失 |
| 异常处理 | 文件读取失败、JSON 解析错误 |

---

## 更新记录

1. v1.0（2026-05-28）：
   - 首次创建模块规范
   - 定义目录结构（docs、logs、test_cases）
   - 定义数据来源规范
   - 定义脚本规范（generate_factor_summary_report.py、merge_factors.py）
   - 定义输出格式规范
   - 定义测试用例规范

2. v1.1（2026-05-28）：
   - 新增 result 目录（存放汇总报告）
   - 更新输出路径规范：默认输出到 summary/result/
   - 修改脚本默认输出路径（不再打印到终端）
   - 同步更新 PROJECT.md 目录结构和数据路径表

3. v1.2（2026-05-28）：
   - generate_factor_summary_report.py 代码优化（v1.1 → v1.2）
   - 添加 `__version__` 常量和版本历史
   - 添加导入分组注释（标准库/第三方）
   - 修复 logger 传递缺失（load_composite_results、get_factor_selection_info）
   - 修复函数签名不一致（所有数据加载函数添加 logger 参数）
   - 替换 print → logger（main 函数）
   - 删除硬编码结论注释（违反"因子方向不可预判"规范）
   - 所有 docstring 补充 Args/Returns 说明

4. v1.3（2026-05-28）：
   - generate_factor_summary_report.py 深度审查优化（v1.2 → v1.3）
   - 删除 calculate_factor_correlation 未使用参数 ic_results
   - 补充返回类型注解（get_monotonicity_symbol、get_weight_method_display、format_weights、generate_correlation_section）
   - 创建流程文档 docs/generate_factor_summary_report_flow.md
   - 创建 pytest 测试文件 test_cases/test_generate_factor_summary_report.py（25个测试用例）

5. v1.4（2026-05-28）：
   - generate_factor_summary_report.py 第三轮深度审查（v1.3 → v1.4）
   - 补全异常处理（load_json_file 添加 PermissionError/IsADirectoryError/OSError）
   - 重构重复代码（新增 _extract_corr_pairs 辅助函数，消除高/中等相关因子对提取重复）
   - 删除未使用参数（load_ic_results/load_backtest_results/load_composite_results 移除 date 参数）
   - 添加边界保护（generate_report max() 添加空列表检测）
   - 补全 docstring（merge_factor_data/format_percentage/format_float）
   - 优化性能（get_factor_selection_info 避免重复读取文件，直接使用 composite_results 数据）
   - load_composite_results 新增 factor_list 和 weights 字段

6. v1.5（2026-05-28）：
   - generate_factor_summary_report.py 第四轮深度审查（v1.4 → v1.5）
   - 提取魔法数字为常量（CORR_THRESHOLD_HIGH/MEDIUM/MAX, ICIR_THRESHOLD, RETURN_THRESHOLD, MAX_STOCKS_SAMPLE）
   - 导入 Tuple 类型，修复 _extract_corr_pairs 返回类型注解为 List[Tuple[str, str, float]]
   - 删除未使用变量（load_backtest_results 移除冗余 corr 变量）
   - 添加 load_composite_results 日志计数
   - 简化排序逻辑（backtest_sorted 使用字典映射代替 index() 查找）
   - 函数拆分重构（新增 _generate_ic_section/_generate_backtest_section/_generate_composite_section/_generate_comparison_section）
   - generate_report 从约146行缩减到约60行，职责更清晰

7. v1.6（2026-05-28）：
   - merge_factors.py 研发规范优化（v1.0 → v1.1）
   - 添加 __version__ 常量和版本历史
   - 添加导入分组注释（标准库/第三方）
   - 创建 setup_logger 函数，替换 basicConfig
   - 重构路径配置，使用 PROJECT_ROOT 和 DATA_PATHS
   - 补充函数返回类型注解（load_main_data/load_parquet_factor/merge_factors → Optional[pd.DataFrame]）
   - 补全 docstring（Args/Returns）
   - 添加异常处理（gzip.BadGzipFile/json.JSONDecodeError/OSError）
   - 添加魔法数字注释说明（total_factors = columns - 2）
   - 创建 pytest 测试文件 test_cases/test_merge_factors.py（20个测试用例）

8. v1.7（2026-05-28）：
   - merge_factors.py 第二轮深度审查（v1.1 → v1.2）
   - 精确化异常处理（load_parquet_factor: OSError/EmptyDataError/ValueError）
   - 删除未使用变量（before_rows）
   - 函数拆分重构（新增 detect_value_column/merge_single_factor/save_merged_data）
   - 修复列名推断逻辑风险（新增 FACTOR_VALUE_COLUMNS 优先级列表，排除 REQUIRED_COLUMNS）
   - 添加 argparse 命令行参数支持（--factors/--output/--list-factors/--version）
   - 新增 list_available_factors 函数
   - 创建流程文档 docs/merge_factors_flow.md

9. v1.8（2026-05-28）：
   - merge_factors.py 第三轮深度审查（v1.2 → v1.3）
   - 删除未使用导入（typing.Tuple）
   - 删除未使用常量（OUTPUT_FILES['json']）
   - 修复日志文件名含时间戳问题（固定为 merge_factors.log）
   - 添加合并进度显示（[i/N] 加载/合并因子）
   - 动态生成 metadata source 字段（包含实际合并因子数和名称）
   - 新增数据验证函数 validate_merged_data（检查记录数、必需列、原始列、新增因子）
   - 支持从配置文件读取因子列表（--config 参数，优先级：命令行 > 配置文件 > 默认）
   - 新增 load_config 函数
   - metadata 新增 merged_factors 字段记录实际成功合并的因子

10. v1.9（2026-06-02）：
   - generate_factor_summary_report.py 数据完整性检查（v1.8 → v1.9）
   - 新增 check_data_freshness() 函数检查基础数据源新鲜度
   - 新增 check_derived_data_freshness() 函数检查衍生数据存在性
   - 新增 _get_nested_field() 辅助函数提取嵌套字段
   - 新增 _extract_date_from_json_content() 辅助函数正则日期提取
   - 新增 _generate_data_check_section() 生成报告第零部分
   - 新增 DATA_CHECK_SOURCES 配置表
   - 报告新增第零部分（数据完整性检查）
   - 新增 get_expected_t_minus_1() 计算期望日期
   - 更新流程文档 generate_factor_summary_report_flow.md v1.5
   - 新增测试用例 9 个（数据完整性检查相关）

11. v2.0（2026-06-02）：
   - MODULE.md 规范扩展（v1.9 → v2.0）
   - 新增【基础数据源】数据完成度检查规范（股票数占比，阈值分级）
   - 新增【衍生数据】数据存在性检查规范（dates/ic_values 非空验证）
   - 新增"因子数据汇总规范"章节（单因子 IC/回测自动适配）
   - 新增"综合因子权重完整性规范"章节（四种权重必须包含，相近数据提示）
   - 因子筛选结果展示规范（选中/剔除因子不遗漏，剔除原因透明）
   - 状态判定标准扩展（完成度分级、数据空判定）