# summary 模块规范

> 版本: v1.0
> 创建时间: 2026-05-28
> 最后更新: 2026-05-28

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
| 因子数据缓存 | cache | `cache/factor_data/` | `factor_data.json.gz` |

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
1. 单因子 IC 数据汇总表（因子名、IC均值、ICIR、IC标准差、有效天数）
2. 单因子分层回测数据汇总表（因子名、多空年化收益、夏普比率、单调性）
3. 因子相关性矩阵（高相关/中等相关因子对提示）
4. 综合因子四种权重回测对比表
5. 因子筛选信息（选中/剔除因子及原因）

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
- 主数据源（cache/factor_data/factor_data.json.gz）
- 新因子文件（cache/factor_data/factors/*.parquet）

**输出：**
- 合并后数据（cache/factor_data/factor_data_merged.json.gz）
- 合并后数据 Parquet 格式（cache/factor_data/factor_data_merged.parquet）
- 元数据文件（cache/factor_data/factor_data_merged_metadata.json）

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

四、综合因子四种权重回测对比
----------------------------------------------------------------------
...

五、因子筛选信息
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