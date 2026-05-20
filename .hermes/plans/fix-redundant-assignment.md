# 修复计划：删除冗余赋值 + 补充规范

> 诊断结论：混合问题（代码 bug + 规范遗漏）
> 创建时间：2026-05-19
> 根因：v1.43 添加 update_mode 时遗漏清理旧代码，规范未定义字段集中原则

---

## 任务清单

### Task 1: 删除冗余赋值代码（1分钟）

**目标：** 删除第581-582行的重复赋值和注释

**文件：** `/home/admin/projects/factor_ic_analyzer/factor_ic/ic_rsi_1d.py`

**当前代码（第579-584行）：**
```python
# 保存
print(f"\n保存数据到: {output_file}")
# 添加更新模式标记（遵循 PROJECT.md 返回值标记规范）
merged_data['update_mode'] = 'incremental'
with open(output_file, 'w', encoding='utf-8') as f:
    json.dump(convert_to_native_types(merged_data), f, ensure_ascii=False, indent=2)
```

**修改后：**
```python
# 保存
print(f"\n保存数据到: {output_file}")
with open(output_file, 'w', encoding='utf-8') as f:
    json.dump(convert_to_native_types(merged_data), f, ensure_ascii=False, indent=2)
```

**理由：** update_mode 已在第568行字典构建阶段设置，无需在保存前重复赋值。

---

### Task 2: 补充 PROJECT.md 规范（2分钟）

**目标：** 新增「字典字段集中定义」原则 + 「添加新代码后检查旧代码」原则

**文件：** `/home/admin/projects/factor_ic_analyzer/PROJECT.md`

**插入位置：** 在「增量 IC 计算算法一致性规范」章节后

**新增内容：**
```markdown
---

### 字典构建规范

**核心原则：** 字典字段应在构建阶段集中定义，避免分散赋值。

**问题背景：**

分散赋值导致：
1. 字段来源分散，难以追踪完整结构
2. 后续赋值可能意外覆盖已设置的字段
3. 重复赋值是无效操作，浪费代码行

**错误示例：**

```python
# ❌ 禁止：字典构建后分散赋值
merged_data = {
    'factor_name': 'rsi_1d',
    'dates': all_dates
}
merged_data['update_mode'] = 'incremental'  # 分散赋值
merged_data['update_mode'] = 'incremental'  # 重复赋值（无效操作）
```

**正确实现：**

```python
# ✓ 正确：字典构建阶段集中定义所有字段
merged_data = {
    'factor_name': 'rsi_1d',
    'dates': all_dates,
    'update_mode': 'incremental',  # 集中定义
    'incremental_events': {...}
}
# 后续不再对 merged_data 赋值字段
```

**为何必须集中定义：**

```
1. 字典结构一目了然，便于理解输出结构
2. 避免"添加"注释与"覆盖"行为语义矛盾
3. 防止后续维护引入重复赋值
4. 符合"单一职责"原则（构建阶段负责定义，保存阶段负责写入）
```

---

### 代码维护同步检查规范

**核心原则：** 添加新代码后，必须检查旧代码是否冗余。

**问题背景：**

迭代开发中，新需求可能替代旧实现：
1. 旧代码未被清理，成为冗余代码
2. 冗余代码可能是无效操作（如重复赋值）
3. 注释与行为不符（如注释说"添加"但实际是"覆盖"）

**检查时机：**

| 场景 | 必须检查 |
|------|---------|
| 添加新字段定义 | 检查是否有旧赋值代码需删除 |
| 重构函数逻辑 | 检查是否有旧逻辑代码需删除 |
| 迁移到公共模块 | 检查调用方是否有旧实现需删除 |
| 版本规范升级 | 检查现有代码是否与新规范冲突 |

**检查方法：**

```bash
# 添加新字段后，grep 搜索旧赋值
grep -n "merged_data\['update_mode'\]" ic_rsi_1d.py

# 发现多处赋值 → 确认是否冗余 → 删除旧代码
```

**禁止行为：**

```
1. 添加新代码后不检查旧代码
2. 保留"以防万一"的冗余代码
3. 注释与行为语义矛盾（"添加" vs "覆盖"）
```
```

---

### Task 3: 同步更新流程文档（1分钟）

**目标：** 版本递增 + 时间标注 + 更新内容

**文件：** `/home/admin/projects/factor_ic_analyzer/factor_ic/docs/ic_rsi_1d_flow.md`

**修改内容：**

1. **版本号递增：** v1.48 → v1.49

2. **生成时间更新：** 当前时间

3. **更新内容追加：**
```markdown
> 47. [v1.49] 删除第582行冗余赋值：update_mode 已在第568行字典构建阶段设置
> 48. [v1.49] 补充 PROJECT.md 「字典构建规范」：字段应集中定义，避免分散赋值
> 49. [v1.49] 补充 PROJECT.md 「代码维护同步检查规范」：添加新代码后必须检查旧代码是否冗余
```

---

## 执行顺序

```
Task 1 → Task 2 → Task 3 → 验证
```

---

## 验证方式

1. 运行 `python factor_ic/ic_rsi_1d.py` 验证脚本正常执行
2. 检查 update_mode 字段仍正确输出
3. grep 确认无重复赋值

---

## 修改文件清单

| 文件 | 操作 |
|------|------|
| `factor_ic/ic_rsi_1d.py` | 删除第581-582行冗余代码 |
| `PROJECT.md` | 新增「字典构建规范」+「代码维护同步检查规范」章节 |
| `factor_ic/docs/ic_rsi_1d_flow.md` | 版本递增、时间标注、更新内容追加 |