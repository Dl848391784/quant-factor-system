# fetch_industry.py 优化实现计划

> **For Hermes:** 使用 subagent-driven-development skill 按任务执行此计划。

**Goal:** 将 fetch_industry.py 重构为使用公共模块、符合 PROJECT.md 和 MODULE.md 规范、创建配套文档和测试用例。

**Architecture:** 
- 使用 common/logger_config.py 的 setup_logger 替换 logging.basicConfig
- 使用 common/cache_manager.py 的原子写入替换手写实现
- 使用 common/paths.py 的路径函数替换硬编码路径
- 创建流程文档 docs/fetch_industry_flow.md
- 创建 pytest 测试文件 test_cases/test_fetch_industry.py

**Tech Stack:** Python 3.11+, pytest,公共模块（logger_config, cache_manager, paths）

---

## 问题诊断

根据 PROJECT.md 和 MODULE.md 规范审查 fetch_industry.py（531行），发现以下问题：

| # | 问题类型 | 违反规范 | 描述 | 影响 |
|---|---------|---------|------|------|
| 1 | 公共模块复用违规 | MODULE.md 约束 #4 | 第512-517行使用 logging.basicConfig而非 setup_logger | 日志不统一 |
| 2 | 公共模块复用违规 | MODULE.md 约束 #4 | 第268-279行手写原子写入，未用 cache_manager | 重复代码 |
| 3 | 公共模块复用违规 | MODULE.md 约束 #4 | 第375-384行手写原子写入，未用 cache_manager | 重复代码 |
| 4 | 路径硬编码 | MODULE.md 约束 #62 | 第46-54行硬编码 BASE_DIR/RESULT_DIR/CACHE_DIR | 跨模块耦合 |
| 5 | 流程文档缺失 | PROJECT.md 脚本配套文件规范 | 缺少 docs/fetch_industry_flow.md | 文档不完整 |
| 6 | 测试用例缺失 | PROJECT.md 测试代码规范 | 缺少 test_cases/test_fetch_industry.py（pytest 文件） | 测试不规范 |
| 7 | __main__ 测试代码 | PROJECT.md 测试代码规范 | 第512-532行 __main__ 块测试代码，非 pytest | 无法集成 CI |

---

## 实现任务

### Task 1: 添加路径函数导出到 __init__.py

**Objective:** 将 get_module_result_dir 添加到公共模块导出列表，供 fetch_industry.py 使用。

**Files:**
- Modify: `data_fetchers/common/__init__.py:27-35`（paths 导入块）
- Modify: `data_fetchers/common/__init__.py:95-103`（__all__ 导出列表）

**Step 1: 添加导入**

在第33行后添加：

```python
from .paths import (
    get_project_root,
    get_cache_dir,
    get_factor_data_dir,
    get_stock_list_file,
    get_logs_dir,
    get_module_logs_dir,      # 新增
    get_module_result_dir,    # 新增
    Paths,
    paths,
)
```

**Step 2: 添加导出**

在第103行后添加：

```python
__all__ = [
    # paths
    'get_project_root',
    'get_cache_dir',
    'get_factor_data_dir',
    'get_stock_list_file',
    'get_logs_dir',
    'get_module_logs_dir',      # 新增
    'get_module_result_dir',    # 新增
    'Paths',
    'paths',
    ...
]
```

**Step 3: 验证导入**

Run: `python -c "from data_fetchers.common import get_module_result_dir; print(get_module_result_dir())"`
Expected: `/home/admin/projects/factor_ic_analyzer/data_fetchers/result`

**Step 4: Commit**

```bash
git add data_fetchers/common/__init__.py
git commit -m "feat: 导出 get_module_result_dir 和 get_module_logs_dir 路径函数"
```

---

### Task 2: 使用公共模块的 setup_logger

**Objective:** 替换第512-517行的 logging.basicConfig 为公共模块的 setup_logger。

**Files:**
- Modify: `data_fetchers/fetch_industry.py:33-43`（导入块）
- Modify: `data_fetchers/fetch_industry.py:512-532`（__main__ 块）

**Step 1: 添加公共模块导入**

在第43行后添加：

```python
# 公共模块导入（遵循 MODULE.md 约束 #4）
from data_fetchers.common import setup_logger
```

**Step 2: 修改 __main__ 块**

替换第512-532行为：

```python
if __name__ == '__main__':
    # 使用公共模块 setup_logger（遵循 PROJECT.md 日志规范）
    logger = setup_logger('fetch_industry')
    
    logger.info(f"[测试] 开始获取行业数据 (v{_OUTPUT_VERSION})...")
    industry_map = refresh_industry_cache()
    logger.info(f"行业数据: {len(industry_map)} 只股票")
    
    # 打印示例
    for code, info in list(industry_map.items())[:5]:
        logger.info(f"  {code}: {info['name']} -> {info['industry']}")
    
    # 测试行业分布统计
    test_codes = ['000001', '603693', '001258', '000002', '600519']
    logger.info("测试行业分布:")
    for code in test_codes:
        industry = get_stock_industry(code)
        logger.info(f"  {code}: {industry}")
```

**Step 3: 验证日志输出**

Run: `python data_fetchers/fetch_industry.py`
Expected: 日志输出到 `data_fetchers/logs/fetch_industry_YYYY-MM-DD.log`

**Step 4: Commit**

```bash
git add data_fetchers/fetch_industry.py
git commit -m "refactor: 使用公共模块 setup_logger 替换 logging.basicConfig"
```

---

### Task 3: 使用公共模块的路径函数

**Objective:** 替换硬编码的 BASE_DIR、RESULT_DIR、CACHE_DIR 为公共模块路径函数。

**Files:**
- Modify: `data_fetchers/fetch_industry.py:33-43`（导入块）
- Modify: `data_fetchers/fetch_industry.py:45-54`（路径常量定义）

**Step 1: 添加路径函数导入**

在第43行后添加：

```python
# 公共模块导入（遵循 MODULE.md 约束 #4）
from data_fetchers.common import setup_logger, get_module_result_dir, get_stock_list_file
```

**Step 2: 替换路径常量定义**

替换第45-54行为：

```python
# 使用公共模块路径函数（遵循 MODULE.md 约束 #62）
RESULT_DIR = get_module_result_dir()
STOCK_LIST_BACKUP_PATH = get_stock_list_file()

# 行业数据缓存路径（输出到 result 目录，MODULE.md 约束 #2）
INDUSTRY_CACHE_PATH = RESULT_DIR / 'stock_industry.json'
```

**Step 3: 删除 BASE_DIR 和 CACHE_DIR**

删除第46-48行的 BASE_DIR 和 CACHE_DIR 定义（不再需要）。

**Step 4: 验证路径正确**

Run: `python -c "from data_fetchers.fetch_industry import RESULT_DIR; print(RESULT_DIR)"`
Expected: `/home/admin/projects/factor_ic_analyzer/data_fetchers/result`

**Step 5: Commit**

```bash
git add data_fetchers/fetch_industry.py
git commit -m "refactor: 使用公共模块路径函数替换硬编码路径"
```

---

### Task 4: 使用公共模块的原子写入 - 主缓存

**Objective:** 替换第268-279行的手写原子写入为公共模块的 write_json_cache。

**Files:**
- Modify: `data_fetchers/fetch_industry.py:33-43`（导入块）
- Modify: `data_fetchers/fetch_industry.py:253-280`（refresh_industry_cache 函数）

**Step 1: 添加缓存函数导入**

在第43行后添加：

```python
from data_fetchers.common import write_json_cache
```

**Step 2: 替换原子写入逻辑**

替换第265-280行为：

```python
    # 确保输出目录存在（MODULE.md 约束 #2：输出到 result 目录）
    RESULT_DIR.mkdir(parents=True, exist_ok=True)
    
    # 使用公共模块原子写入（遵循 MODULE.md 约束 #4）
    write_json_cache(INDUSTRY_CACHE_PATH, cache_data, indent=2)
    logger.info(f"[行业数据] 缓存已更新: {INDUSTRY_CACHE_PATH} (v{_OUTPUT_VERSION})")
    
    return industry_map
```

**Step 3: 验证写入成功**

Run: `python data_fetchers/fetch_industry.py`
Expected: 日志显示"缓存已更新"，文件存在于 `data_fetchers/result/stock_industry.json`

**Step 4: Commit**

```bash
git add data_fetchers/fetch_industry.py
git commit -m "refactor: 使用 write_json_cache 替换手写原子写入（主缓存）"
```

---

### Task 5: 使用公共模块的原子写入 - 备用缓存

**Objective:** 替换第375-384行的手写原子写入为公共模块的 write_json_cache。

**Files:**
- Modify: `data_fetchers/fetch_industry.py:374-385`（_write_backup_cache 函数）

**Step 1: 替换原子写入逻辑**

替换第374-385行为：

```python
    RESULT_DIR.mkdir(parents=True, exist_ok=True)
    
    # 使用公共模块原子写入（遵循 MODULE.md 约束 #4）
    # 备用缓存写入失败为非致命错误（MODULE.md 约束 #72）
    try:
        write_json_cache(INDUSTRY_CACHE_PATH, cache_data, indent=2)
        logger.info(f"[行业数据] 备用缓存已写入: {INDUSTRY_CACHE_PATH}")
    except Exception as e:
        logger.warning(f"[行业数据] 备用缓存写入失败 [{type(e).__name__}]: {e}（非致命，下次将重新读备用数据）")
```

**Step 2: 验证写入成功**

Run: `python data_fetchers/fetch_industry.py`
Expected: 日志显示"备用缓存已写入"或"写入失败（非致命）"

**Step 3: Commit**

```bash
git add data_fetchers/fetch_industry.py
git commit -m "refactor: 使用 write_json_cache 替换手写原子写入（备用缓存）"
```

---

### Task 6: 创建流程文档

**Objective:** 创建 docs/fetch_industry_flow.md，遵循 PROJECT.md 脚本配套文件规范。

**Files:**
- Create: `data_fetchers/docs/fetch_industry_flow.md`

**Step 1: 创建流程文档模板**

```markdown
# fetch_industry 流程文档

> 版本: v1.0
> 生成时间: 2026-05-27
> 作者: 云瑶

## 整体架构

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│   akshare API   │────▶│ fetch_industry.py│────▶│ stock_industry.json│
│  (申万行业分类)  │     │   (数据处理)      │     │  (缓存输出)      │
└─────────────────┘     └──────────────────┘     └─────────────────┘
                                │
                                ▼
                        ┌───────────────┐
                        │ 本地备用数据   │
                        │ (关键词推断)  │
                        └───────────────┘
```

## 详细流程步骤

### Step 1: 检查缓存是否存在

- 检查 `data_fetchers/result/stock_industry.json` 是否存在
- 如果存在，加载缓存数据
- 如果不存在，调用 API 获取

### Step 2: 从 akshare 获取申万行业分类

- 调用 `ak.stock_industry_clf_hist_sw()` 获取行业分类历史数据
- 获取每只股票的最新行业分类（按 start_date 降序）
- 获取股票名称映射 `ak.stock_info_a_code_name()`

### Step 3: 构建行业映射

- 从行业代码提取一级行业（前2位）
- 使用 SW_INDUSTRY_CODE_MAP 映射到行业名称
- 构建输出结构：`{股票代码: {name, industry, industry_code}}`

### Step 4: 写入缓存

- 使用公共模块 `write_json_cache` 原子写入
- 输出到 `data_fetchers/result/stock_industry.json`
- 包含 meta 信息：version、source、level、updated_at、total_count

### Step 5: 备用数据降级

- 如果 akshare API 失败，使用本地备用数据
- 基于 `infer_industry_from_name` 关键词推断行业
- 写入缓存（非致命错误）

## 输出结构

```json
{
  "meta": {
    "version": "2.3",
    "source": "sw_category",
    "level": "一级",
    "updated_at": "2026-05-27",
    "total_count": 5000
  },
  "industries": {
    "000001": {
      "name": "平安银行",
      "industry": "银行",
      "industry_code": "4801"
    },
    ...
  }
}
```

## 关键指标

| 指标 | 预期值 | 说明 |
|-----|-------|------|
| 数据来源 | akshare申万 | 主数据源 |
| 行业分类 | 申万2021一级 | 31个行业 |
| 缓存有效期 | 7天 | 过期重新获取 |
| 备用数据准确性 | < akshare | 关键词推断 |

## 版本历史

1. v1.0 (2026-05-27): 初始版本 - 使用公共模块、创建流程文档
```

**Step 2: 验证文档存在**

Run: `ls -la data_fetchers/docs/fetch_industry_flow.md`
Expected: 文件存在，大小约 2KB

**Step 3: Commit**

```bash
git add data_fetchers/docs/fetch_industry_flow.md
git commit -m "docs: 创建 fetch_industry 流程文档"
```

---

### Task 7: 创建 pytest 测试文件

**Objective:** 创建 test_cases/test_fetch_industry.py，遵循 PROJECT.md 测试代码规范。

**Files:**
- Create: `data_fetchers/test_cases/test_fetch_industry.py`

**Step 1: 创建测试文件模板**

```python
#!/usr/bin/env python3
"""
fetch_industry.py 测试用例

遵循 PROJECT.md 测试代码规范：pytest 可执行文件
"""

import pytest
import json
import tempfile
from pathlib import Path
from datetime import datetime

# 导入被测试模块
from data_fetchers.fetch_industry import (
    infer_industry_from_name,
    get_industry_distribution,
    SW_INDUSTRY_CODE_MAP,
)


class TestInferIndustryFromName:
    """测试行业推断函数"""
    
    def test_bank_keyword(self):
        """测试银行关键词"""
        assert infer_industry_from_name('平安银行') == '银行'
        assert infer_industry_from_name('浦发银行') == '银行'
    
    def test_security_keyword(self):
        """测试证券关键词"""
        assert infer_industry_from_name('中信证券') == '证券'
        assert infer_industry_from_name('国泰君安') == '证券'
    
    def test_real_estate_keyword(self):
        """测试房地产关键词"""
        assert infer_industry_from_name('万科') == '房地产'
        assert infer_industry_from_name('保利地产') == '房地产'
    
    def test_unknown_name(self):
        """测试未知名称"""
        assert infer_industry_from_name('某某公司') == '其他'


class TestSWIndustryCodeMap:
    """测试申万行业代码映射"""
    
    def test_official_codes_exist(self):
        """测试官方一级代码存在"""
        official_codes = ['11', '21', '23', '24', '25', '26', '27', '31', '32', '34', '35', '36', '41', '42', '43', '44', '45', '46', '48', '49', '62', '63', '64', '65', '71', '72', '73', '74', '75', '76', '77']
        for code in official_codes:
            assert code in SW_INDUSTRY_CODE_MAP
            assert SW_INDUSTRY_CODE_MAP[code] != '其他'
    
    def test_nonexistent_codes_map_to_other(self):
        """测试不存在的一级代码映射到'其他'"""
        nonexistent_codes = ['22', '28', '33', '37', '47', '51', '61']
        for code in nonexistent_codes:
            assert SW_INDUSTRY_CODE_MAP[code] == '其他'


class TestGetIndustryDistribution:
    """测试行业分布统计"""
    
    def test_distribution_calculation(self):
        """测试分布计算"""
        test_codes = ['000001', '603693', '001258']
        distribution = get_industry_distribution(test_codes)
        assert isinstance(distribution, dict)
        assert all(isinstance(v, int) for v in distribution.values())


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
```

**Step 2: 验证测试文件存在**

Run: `ls -la data_fetchers/test_cases/test_fetch_industry.py`
Expected: 文件存在，大小约 1KB

**Step 3: Commit**

```bash
git add data_fetchers/test_cases/test_fetch_industry.py
git commit -m "test: 创建 fetch_industry pytest 测试文件"
```

---

### Task 8: 运行测试验证

**Objective:** 运行 pytest 测试验证所有功能正常。

**Files:**
- Test: `data_fetchers/test_cases/test_fetch_industry.py`

**Step 1: 运行 pytest**

Run: `pytest data_fetchers/test_cases/test_fetch_industry.py -v`
Expected: 所有测试通过（约10个测试用例）

**Step 2: 运行脚本验证**

Run: `python data_fetchers/fetch_industry.py`
Expected: 
- 日志输出到 `data_fetchers/logs/fetch_industry_YYYY-MM-DD.log`
- 缓存文件存在于 `data_fetchers/result/stock_industry.json`

**Step 3: 检查日志格式**

Run: `head -20 data_fetchers/logs/fetch_industry_*.log`
Expected: 格式为 `YYYY-MM-DD HH:MM:SS | INFO     | fetch_industry | [行业数据]...`

---

### Task 9: 更新 MODULE.md 版本历史

**Objective:** 在 MODULE.md 中记录本轮优化内容。

**Files:**
- Modify: `data_fetchers/MODULE.md:148-500`（版本历史章节）

**Step 1: 添加版本历史**

在第500行后添加：

```markdown
30. **fetch_industry.py v2.4 (2026-05-27)** — 第七轮公共模块规范化
    - **公共模块复用修复**：使用 setup_logger 替换 logging.basicConfig
    - **原子写入修复**：使用 write_json_cache 替换手写原子写入（两处）
    - **路径函数复用**：使用 get_module_result_dir、get_stock_list_file 替换硬编码路径
    - **流程文档创建**：docs/fetch_industry_flow.md（整体架构 +5步流程 + 输出结构）
    - **测试用例创建**：test_cases/test_fetch_industry.py（pytest 文件）
    - **__main__ 重构**：使用 setup_logger，移除 logging.basicConfig
    - **MODULE.md 导出补全**：添加 get_module_result_dir、get_module_logs_dir 导出
    - **版本历史补全**：fetch_industry.py 新增 v2.4 版本演进说明
    - **修复原因**：公共模块规范合规化（logger 参数化、原子写入复用、路径函数复用、测试规范化）
```

**Step 2: Commit**

```bash
git add data_fetchers/MODULE.md
git commit -m "docs: 更新 MODULE.md 版本历史（fetch_industry v2.4）"
```

---

### Task 10: Git commit 汇总提交

**Objective:** 创建汇总 commit，包含所有本轮优化改动。

**Files:**
- All modified files

**Step 1: 检查所有改动**

Run: `git status`
Expected: 显示所有改动的文件

**Step 2: 创建汇总 commit**

```bash
git add -A
git commit -m "refactor: fetch_industry.py 公共模块规范化（v2.4）

遵循 superpowers-workflow 4阶段流程优化：
- 使用 setup_logger 替换 logging.basicConfig
- 使用 write_json_cache 替换手写原子写入（两处）
- 使用公共模块路径函数替换硬编码路径
- 创建流程文档 docs/fetch_industry_flow.md
- 创建 pytest 测试文件 test_cases/test_fetch_industry.py
- 更新 MODULE.md 版本历史

符合 PROJECT.md 和 MODULE.md 规范要求。"
```

---

## 验证检查清单

完成后执行以下检查：

```
□ 公共模块导入正确：from data_fetchers.common import setup_logger, write_json_cache, get_module_result_dir
□ 日志输出到正确目录：data_fetchers/logs/fetch_industry_YYYY-MM-DD.log
□ 缓存输出到正确目录：data_fetchers/result/stock_industry.json
□ 流程文档存在：docs/fetch_industry_flow.md
□ 测试文件存在：test_cases/test_fetch_industry.py
□ pytest 测试通过：所有测试用例 PASS
□ MODULE.md 版本历史更新：添加 v2.4 记录
□ Git commit 完成：包含所有改动文件
```

---

## 执行模式

**推荐：使用 subagent-driven-development skill 执行此计划。**

执行流程：
1. 加载 subagent-driven-development skill
2. 为每个 Task 分派独立子 agent（fresh context）
3. Spec Compliance 检查（是否符合计划规范）
4. Code Quality 检查（代码质量）
5. 两阶段评审通过后进入下一 Task

---

*计划创建时间: 2026-05-27*
*预计执行时间: 约30分钟（10个任务，每个2-3分钟）*