# ic_turnover_surge_1d.py 优化计划

> 生成时间: 2026-05-20 17:30 (北京时间)
> 执行者: 云瑶
> 审阅版本: v1.0

---

## 审计发现的问题

### 问题 1: 异常处理类型不一致（代码 Bug）

**位置**: 第 422-423 行

**当前实现**:
```python
except Exception as e:
    raise RuntimeError(f"数据加载失败: {e}")
```

**问题根因**:
- ValueError（数据验证错误：股票数不足）被包装为 RuntimeError（基础设施错误）
- 调用方无法用 `except ValueError` 捕获数据验证错误
- 无法区分"文件不存在"和"股票数不足"

**修复方案**: 区分异常类型处理
```python
except FileNotFoundError as e:
    # 基础设施错误：包装为 RuntimeError
    raise RuntimeError(f"缓存文件不存在: {e}") from e
except ValueError as e:
    # 数据验证错误：直接 raise，保留原始类型
    raise  # 不包装
except Exception as e:
    # 未预期异常：包装为 RuntimeError
    raise RuntimeError(f"数据加载失败: {e}") from e
```

---

### 问题 2: sample_stats 缺少 avg_stocks_period 字段（规范遗漏）

**位置**: 第 365-369 行

**当前实现**:
```python
'sample_stats': {
    'total_days': raw_metadata.get('total_days', 0) if raw_metadata else 0,
    'valid_days': result['n_days'],
    'avg_stocks_per_day': int(factor_data.groupby('date').size().mean())
}
```

**问题根因**:
- 缺少 avg_stocks_period 子字段（口径范围说明）
- 用户不知道 avg_stocks_per_day 反映哪个时间段
- 违反 MODULE.md 输出结构统一性规范

**修复方案**: 添加口径字段
```python
'sample_stats': {
    'total_days': raw_metadata.get('total_days', 0) if raw_metadata else 0,
    'valid_days': result['n_days'],
    'avg_stocks_per_day': int(factor_data.groupby('date').size().mean()),
    'avg_stocks_period': {
        'start': period_start,
        'end': period_end,
        'description': '平均每日有效股票数统计范围'
    }
}
```

---

### 问题 3: 异常处理缺少 FileNotFoundError 分支（代码 Bug）

**位置**: 第 89-92 行

**当前实现**:
```python
for path, name in [(turnover_path, '换手率'), (factor_path, '因子'), (return_path, '收益')]:
    if not path.exists():
        raise FileNotFoundError(f"{name}缓存不存在: {path}")
```

**问题根因**:
- FileNotFoundError 直接抛出，没有包装为 RuntimeError
- 与后续异常处理风格不一致

**修复方案**: 保持一致性（FileNotFoundError 不需要包装，但注释需要说明）
```python
for path, name in [(turnover_path, '换手率'), (factor_path, '因子'), (return_path, '收益')]:
    if not path.exists():
        # 数据验证错误：裸 raise 保留原始类型
        # 原因：FileNotFoundError 表示缓存缺失，是可预期错误，原始类型更易诊断
        raise FileNotFoundError(f"{name}缓存不存在: {path}")
```

---

### 问题 4: 增量模式 fallback 处理需要注释改进（规范遗漏）

**位置**: 第 556-572 行

**当前实现**:
```python
elif mode == 'incremental':
    # 缺失数据，执行增量更新
    # 注意：换手率突增因子需要窗口计算（5日换手率均值），增量计算需要额外历史数据
    # 为简化实现，暂使用全量计算替代增量计算
    print(f"\n[增量模式] 缺失 {len(missing_dates)} 天数据")
    print("  注意：换手率突增因子需要5日窗口计算，增量模式暂用全量计算替代")
```

**问题根因**:
- 注释不够清晰，缺少设计意图说明
- 为何"暂用全量计算替代"？是因为技术限制还是业务决策？

**修复方案**: 改进注释，说明设计意图
```python
elif mode == 'incremental':
    # 增量模式 fallback：换手率突增因子依赖5日窗口计算
    # 设计决策：为简化实现，暂用全量计算替代增量计算
    # 技术原因：增量计算需要额外历史数据（前5日换手率），实现复杂度高
    # 未来改进：实现真正的增量计算（仅计算缺失日期 + 窗口数据）
    print(f"\n[增量模式] 缺失 {len(missing_dates)} 天数据")
    print("  注意：换手率突增因子需要5日窗口计算，增量模式暂用全量计算替代")
```

---

### 问题 5: 控制流标记变量不存在（检查项）

**位置**: 第 532-584 行

**分析**:
- 已使用显式控制流架构（每个分支都有明确的 return）
- 不存在 should_full_recalculate 等标记变量
- 控制流清晰，无死代码

**结论**: 此项无问题，符合规范。

---

### 问题 6: 跨脚本输出结构一致性验证（检查项）

**位置**: 输出结构

**当前实现**: ic_metrics 包含 5 字段（ic_mean, ic_std, icir, p_value, p_value_display）

**需要验证**: 与其他因子脚本输出结构是否一致

**验证方法**: 运行脚本后对比 JSON 输出

---

## 优化步骤（分步执行）

按照 superpowers-workflow 分步执行策略：

### Step 1: 修复异常处理类型（问题 1）
- 修改第 414-424 行异常处理
- 区分 FileNotFoundError、ValueError、Exception 三种类型
- 验证语法正确性

### Step 2: 添加 avg_stocks_period 字段（问题 2）
- 修改第 365-369 行 sample_stats 结构
- 添加 avg_stocks_period 子字段
- 更新空数据返回路径（第 282-285 行、第 316-320 行）
- 验证语法正确性

### Step 3: 改进异常处理注释（问题 3）
- 修改第 89-92 行注释
- 说明为何保留 FileNotFoundError 原始类型

### Step 4: 改进增量模式注释（问题 4）
- 修改第 556-572 行注释
- 说明设计意图和技术原因

### Step 5: 更新流程文档
- 更新版本号（v1.3 → v1.4）
- 更新生成时间、实测数据时间
- 添加更新内容说明

### Step 6: 运行验证
- 运行脚本验证数据输出
- 检查输出结构是否符合规范
- 对比其他因子脚本输出结构

### Step 7: Git 提交
- 提交代码修改
- 提交流程文档更新

---

## 预期产出

1. **代码修改**: ic_turnover_surge_1d.py（4处修改）
2. **流程文档更新**: ic_turnover_surge_1d_flow.md（版本 v1.4）
3. **验证结果**: 脚本正常运行，输出结构符合规范

---

*文档结束*