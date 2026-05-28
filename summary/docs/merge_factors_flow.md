# merge_factors.py 流程文档

> 版本: v1.2
> 创建时间: 2026-05-28
> 最后更新: 2026-05-28
> 脚本版本: merge_factors.py v1.2

---

## 一、功能概述

将多个 parquet 因子文件合并到主数据源 `factor_data.json.gz`，生成合并后的数据文件。

---

## 二、流程图

```
┌─────────────────────────────────────────────────────────────────────┐
│                      merge_factors.py 主流程                          │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐           │
│  │ parse_args() │───▶│ setup_logger │───▶│ merge_factors│           │
│  │ 命令行参数    │    │ 日志配置      │    │ 合并主函数    │           │
│  └──────────────┘    └──────────────┘    └──────────────┘           │
│                                                 │                   │
│                                                 ▼                   │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │                    merge_factors 内部流程                      │  │
│  ├──────────────────────────────────────────────────────────────┤  │
│  │                                                              │  │
│  │  1. load_main_data()                                        │  │
│  │     └─▶ 加载 factor_data.json.gz                             │  │
│  │                                                              │  │
│  │  2. for factor in factor_list:                              │  │
│  │     │                                                       │  │
│  │     │  load_parquet_factor(factor)                          │  │
│  │     │  └─▶ 加载 {factor}.parquet                             │  │
│  │     │                                                       │  │
│  │     ▼                                                       │  │
│  │     merge_single_factor(merged_df, factor_df, factor)       │  │
│  │     │                                                       │  │
│  │     │  detect_value_column()                                │  │
│  │     │  └─▶ 检测因子值列名                                    │  │
│  │     │                                                       │  │
│  │     │  DataFrame.merge(on=['date', 'asset'])                │  │
│  │     │  └─▶ 数据对齐合并                                      │  │
│  │     │                                                       │  │
│  │     └─▶ 统计有效值覆盖率                                     │  │
│  │                                                              │  │
│  │  3. save_merged_data()                                      │  │
│  │     │                                                       │  │
│  │     │  to_parquet() ─▶ factor_data_merged.parquet           │  │
│  │     │                                                       │  │
│  │     └─▶ json.dump() ─▶ factor_data_merged_metadata.json     │  │
│  │                                                              │  │
│  └──────────────────────────────────────────────────────────────┘  │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 三、数据流向

```
输入文件                           输出文件
─────────────────────────────────────────────────────────────
factor_data.json.gz (主数据)       factor_data_merged.parquet
    │                                 │
    │  {date, asset, factor1, ...}    │  {date, asset, factor1, ..., new_factors}
    │                                 │
    └──────────────┬──────────────────┘
                   │
                   ▼
factors/{factor}.parquet           factor_data_merged_metadata.json
    │                                 │
    │  {date, asset, factor_value}    │  {created_at, total_records, factors, ...}
    │                                 │
    └─────────────────────────────────┘
```

---

## 四、命令行参数

| 参数 | 简写 | 说明 | 默认值 |
|------|------|------|--------|
| `--factors` | `-f` | 指定因子列表 | 内置14个因子 |
| `--output` | `-o` | 指定输出目录 | `data_fetchers/result` |
| `--list-factors` | `-l` | 列出可用因子 | - |
| `--version` | `-v` | 显示版本号 | - |

### 使用示例

```bash
# 使用默认因子列表
python summary/merge_factors.py

# 指定因子
python summary/merge_factors.py --factors A_FA_N0112 B_atr_pct

# 列出可用因子
python summary/merge_factors.py --list-factors

# 指定输出目录
python summary/merge_factors.py --output ./output
```

---

## 五、函数职责

| 函数名 | 职责 | 输入 | 输出 |
|--------|------|------|------|
| `setup_logger` | 配置日志记录器 | name | Logger |
| `load_main_data` | 加载主数据源 | logger | DataFrame 或 None |
| `load_parquet_factor` | 加载单个因子文件 | factor_name, logger | DataFrame 或 None |
| `detect_value_column` | 检测因子值列名 | factor_df, factor_name, logger | 列名或 None |
| `merge_single_factor` | 合并单个因子 | merged_df, factor_df, factor_name, logger | DataFrame |
| `save_merged_data` | 保存合并数据 | merged_df, output_dir, logger | bool |
| `merge_factors` | 合并主函数 | logger, factor_list, output_dir | DataFrame 或 None |
| `list_available_factors` | 列出可用因子 | logger | List[str] |
| `parse_args` | 解析命令行参数 | - | Namespace |
| `main` | 主入口 | - | None |

---

## 六、异常处理

| 函数 | 异常类型 | 处理方式 |
|------|---------|---------|
| `load_main_data` | `gzip.BadGzipFile` | 返回 None，记录错误 |
| `load_main_data` | `json.JSONDecodeError` | 返回 None，记录错误 |
| `load_main_data` | `OSError` | 返回 None，记录错误 |
| `load_parquet_factor` | `OSError` | 返回 None，记录错误 |
| `load_parquet_factor` | `pd.errors.EmptyDataError` | 返回 None，记录错误 |
| `load_parquet_factor` | `ValueError` | 返回 None，记录错误 |
| `save_merged_data` | `OSError` | 返回 False，记录错误 |
| `save_merged_data` | `ValueError` | 返回 False，记录错误 |

---

## 七、配置常量

| 常量名 | 值 | 说明 |
|--------|-----|------|
| `PROJECT_ROOT` | `Path(__file__).parent.parent` | 项目根目录 |
| `DATA_PATHS['factor_data']` | `'data_fetchers/result'` | 主数据路径 |
| `DATA_PATHS['factors']` | `'data_fetchers/result/factors'` | 因子文件路径 |
| `REQUIRED_COLUMNS` | `['date', 'asset']` | 数据对齐必需列 |
| `FACTOR_VALUE_COLUMNS` | `['factor_value', 'value', 'val']` | 预期因子值列名 |
| `DEFAULT_FACTORS` | 14个因子名称 | 默认因子列表 |

---

## 八、版本历史

| 版本 | 日期 | 主要变更 |
|------|------|---------|
| v1.0 | - | 基础版本（硬编码路径） |
| v1.1 | 2026-05-28 | 研发规范：版本常量、setup_logger、返回类型注解、异常处理、pytest测试 |
| v1.2 | 2026-05-28 | 第二轮深度审查：精确化异常处理、删除未使用变量、函数拆分、argparse支持、流程文档 |

---

## 九、测试覆盖

测试文件：`summary/test_cases/test_merge_factors.py`

覆盖内容：
- setup_logger 初始化测试
- load_main_data 输入验证测试
- load_parquet_factor 异常处理测试
- merge_factors 边界处理测试
- detect_value_column 列名推断测试
- merge_single_factor 数据合并测试
- save_merged_data 文件保存测试
- 常量定义测试
- 数据完整性验证测试