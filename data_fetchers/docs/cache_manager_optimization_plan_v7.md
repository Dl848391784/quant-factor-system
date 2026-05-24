# cache_manager.py 第十轮优化计划

> 创建时间: 2026-05-24 23:00 北京时间
> 审查范围: cache_manager.py + 流程文档 + 测试用例 + MODULE.md
> 审查依据: PROJECT.md、MODULE.md、superpowers-workflow Spec Compliance 检查清单

---

## 一、审查发现

### 1.1 测试用例版本滞后（高优先级）

**问题描述：**
- 测试用例版本停在 v1.4（第七轮），对应 TC022-TC024
- MODULE.md 显示优化已进行到第九轮（v2.10），创建了 logger_config.py
- 第八轮（测试代码日志规范化）和第九轮（创建 logger_config.py）没有对应测试用例版本记录

**影响：**
- 用户追问"六轮优化后忘记同步测试用例"
- 测试用例版本与代码版本不一致，无法追溯完整演进历史

**修复方案：**
- 测试用例新增 v1.5（第八轮）和 v1.6（第九轮）版本历史记录
- 新增 TC025：setup_logger 函数测试（第九轮）

---

### 1.2 流程文档时间标注错误（高优先级）

**问题描述：**
- 流程文档版本历史显示 v1.8 时间为 "2026-05-24 20:35"
- MODULE.md 版本历史显示 v2.10（第九轮）时间为 "2026-05-24 20:35"
- 但第八轮（v2.9）时间是 "2026-05-24 22:40"，时间顺序矛盾

**影响：**
- 遵循用户偏好"流程文档时间标注必须同步更新"
- 时间标注不一致导致追溯困难

**修复方案：**
- 流程文档 v1.8 时间标注改为 "2026-05-24 22:50"（第九轮实际时间）
- MODULE.md v2.10 时间标注改为 "2026-05-24 22:50"

---

### 1.3 logger_config.py 缺少测试用例（中优先级）

**问题描述：**
- 第九轮创建了 logger_config.py（setup_logger 函数）
- __init__.py 导出了 setup_logger
- 但测试用例没有新增 setup_logger 相关测试

**影响：**
- setup_logger 是公共 API，必须有测试覆盖
- 缺少测试无法验证日志格式、日志文件路径、日志级别

**修复方案：**
- 新增 TC025：setup_logger 日志配置测试
- 测试内容：
  - 日志文件路径验证（logs/<script_name>_YYYY-MM-DD.log）
  - 日志格式验证（%(asctime)s | %(levelname)-8s | %(name)s | %(message)s）
  - 日志级别验证（INFO/DEBUG）
  - 防止重复添加 Handler

---

### 1.4 测试用例汇总表冗余（低优先级）

**问题描述：**
- 第617-640行有测试汇总表（v1.3）
- 第741-768行有测试汇总表（v1.4）
- 两个表格内容相同，冗余

**修复方案：**
- 删除第一个汇总表（第617-640行）
- 保留最后一个汇总表（第741-768行），添加 v1.5/v1.6 内容

---

### 1.5 流程文档架构图不完整（低优先级）

**问题描述：**
- 流程文档架构图只显示 cache_manager.py 内部结构
- 没有显示 logger_config.py 与 cache_manager.py 的关系
- __main__ 测试代码使用了 logger_config.py 的 setup_logger

**修复方案：**
- 架构图新增 logger_config.py 模块
- 显示 __main__ → setup_logger → cache_manager 的调用关系

---

## 二、优化方案

### 2.1 测试用例版本同步

**变更文件：**
- data_fetchers/test_cases/cache_manager_test_cases.md

**具体操作：**
1. 版本历史新增 v1.5（第八轮）："测试代码日志规范化"
2. 版本历史新增 v1.6（第九轮）："创建 logger_config.py，复用 setup_logger"
3. 新增 TC025：setup_logger 测试用例
4. 删除冗余汇总表（第617-640行）
5. 更新最终汇总表，新增 TC025

---

### 2.2 流程文档时间标注修复

**变更文件：**
- data_fetchers/docs/cache_manager_flow.md
- data_fetchers/MODULE.md

**具体操作：**
1. cache_manager_flow.md v1.8 时间改为 "2026-05-24 22:50"
2. MODULE.md v2.10 时间改为 "2026-05-24 22:50"

---

### 2.3 流程文档架构图补充

**变更文件：**
- data_fetchers/docs/cache_manager_flow.md

**具体操作：**
1. 架构图新增 logger_config.py 模块
2. 显示 __main__ 测试调用关系

---

## 三、执行步骤

### Step 1: 更新测试用例版本历史

**变更文件：**
- cache_manager_test_cases.md

**变更内容：**
```markdown
|| v1.5 | 2026-05-24 22:40 | 第八轮优化：测试代码日志规范化（print → logger） ||
|| v1.6 | 2026-05-24 22:50 | 第九轮优化：创建 logger_config.py，复用 setup_logger（DRY 原则） ||
```

---

### Step 2: 新增 TC025 测试用例

**变更文件：**
- cache_manager_test_cases.md

**测试目标：** 验证 setup_logger 配置日志记录器。

**测试步骤：**
1. 调用 setup_logger 创建 logger
2. 验证日志文件路径
3. 验证日志格式
4. 验证日志级别

---

### Step 3: 删除冗余汇总表

**变更文件：**
- cache_manager_test_cases.md

**具体操作：**
- 删除第617-640行的汇总表

---

### Step 4: 更新流程文档时间标注

**变更文件：**
- cache_manager_flow.md
- MODULE.md

---

### Step 5: 更新流程文档架构图

**变更文件：**
- cache_manager_flow.md

---

### Step 6: Git 提交

**提交信息：**
```
优化 cache_manager.py 第十轮：测试用例版本同步 + 时间标注修复 + logger_config 测试用例

- 测试用例版本历史新增 v1.5/v1.6（第八轮和第九轮）
- 新增 TC025：setup_logger 测试用例
- 删除冗余测试汇总表
- 流程文档时间标注修复（v1.8 时间改为 22:50）
- MODULE.md 时间标注修复（v2.10 时间改为 22:50）
- 流程文档架构图补充 logger_config.py
```

---

## 四、预期收益

| 收益项 | 量化指标 |
|--------|---------|
| 测试用例版本同步 | 版本历史完整（v1.0 → v1.6） |
| 时间标注一致性 | 所有文档时间标注一致 |
| 测试覆盖率提升 | setup_logger 有测试覆盖 |
| 文档精简 | 删除冗余汇总表，减少 23 行 |

---

## 五、合规性检查

- [x] 符合 superpowers-workflow Spec Compliance 检查清单
- [x] 符合 PROJECT.md 流程文档时间标注规范
- [x] 符合 PROJECT.md 测试用例同步规范
- [x] 符合 MODULE.md 版本历史规范