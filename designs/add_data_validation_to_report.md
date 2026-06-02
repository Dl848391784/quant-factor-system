# 设计文档：Report 脚本数据校验功能完善

> 创建时间: 2026-06-02
> 状态: 待审核

---

## 背景

用户要求在 Report 脚本第一步增加对拉取数据的校验。

**现状分析**：
- 代码层面：`generate_factor_summary_report.py` 已有 v1.9 数据完整性检查功能
- 文档层面：流程文档 `generate_factor_summary_report_flow.md` 为 v1.4，未同步更新
- 测试层面：pytest 测试文件未覆盖数据完整性检查函数

**问题**：
1. 流程文档未同步代码变更（第零部分：数据完整性检查）
2. 测试用例未覆盖新增的数据校验函数
3. MODULE.md 未记录数据完整性检查功能

---

## 改动文件清单

| 文件 | 操作 | 改动内容 |
|------|------|----------|
| `summary/docs/generate_factor_summary_report_flow.md` | 更新 | 同步 Step 0 数据完整性检查流程 |
| `summary/test_cases/test_generate_factor_summary_report.py` | 更新 | 新增数据校验函数测试用例 |
| `summary/MODULE.md` | 更新 | 新增数据完整性检查规范 |

---

## 详细设计

### 1. 流程文档更新（generate_factor_summary_report_flow.md）

**新增 Step 0: 数据完整性检查**

```markdown
### Step 0: 数据完整性检查（v1.9 新增）

**触发时机：** generate_report() 函数开始时，在加载 IC/回测数据之前

**检查内容：**
- 基础数据源新鲜度（factor_ic_data, factor_data, turnover_data）
- 衍生数据存在性（IC 结果、回测结果、综合因子结果）

**期望标准：** 最新日期 = T-1（前一天）

**状态判定：**
- ✓正常：actual_date == expected_date
- △延迟：actual_date != expected_date（可能非交易日）
- ✗缺失：文件不存在
- ✗读取失败：文件损坏或格式错误
- ✗无日期：无法解析日期字段

**输出位置：** 报告第零部分
```

**更新版本号**：v1.4 → v1.5

### 2. 测试用例新增（test_generate_factor_summary_report.py）

**新增测试函数**：

| 测试函数 | 覆盖场景 |
|---------|----------|
| `test_get_expected_t_minus_1` | 日期计算正确性 |
| `test_check_data_freshness_file_exists` | 文件存在时正常检查 |
| `test_check_data_freshness_file_missing` | 文件不存在时返回 error 状态 |
| `test_check_data_freshness_date_match` | 日期匹配时返回 ok 状态 |
| `test_check_data_freshness_date_mismatch` | 日期不匹配时返回 warning 状态 |
| `test_check_derived_data_freshness` | 衍生数据检查 |
| `test_generate_data_check_section` | 报告第零部分生成 |
| `test_get_nested_field` | 嵌套字段提取 |
| `test_extract_date_from_json_content` | 正则日期提取 |

### 3. MODULE.md 更新

**新增章节：数据完整性检查规范**

```markdown
### 数据完整性检查

**检查时机：** 报告生成开始时（Step 0）

**检查范围：**
- 基础数据源：factor_ic_data.json.gz, factor_data.json.gz, turnover_rate_data.json.gz
- 衍生数据：IC 结果、回测结果、综合因子结果

**期望标准：** 最新日期应更新至 T-1

**报告展示：** 第零部分展示检查结果
```

---

## 执行顺序

```
1. 更新流程文档（generate_factor_summary_report_flow.md）
   - 新增 Step 0 数据完整性检查
   - 更新版本号 v1.4 → v1.5
   - 更新最后更新时间

2. 新增测试用例（test_generate_factor_summary_report.py）
   - 9 个新增测试函数
   - 覆盖数据校验各场景

3. 更新 MODULE.md
   - 新增数据完整性检查章节
   - 更新版本历史 v1.9

4. 运行 pytest 验证
   - pytest summary/test_cases/test_generate_factor_summary_report.py

5. 运行脚本验证
   - python summary/generate_factor_summary_report.py --date 2026-06-02

6. Git commit
```

---

## 验证检查项

```
□ 流程文档包含 Step 0 数据完整性检查
□ 测试覆盖率不低于 60%
□ 所有新增测试用例通过
□ 脚本运行无报错
□ 报告包含第零部分：数据完整性检查
□ MODULE.md 包含数据完整性检查章节
```

---

## 待审核

请确认设计方案是否可行，确认后开始执行。