# ic_turnover_surge_1d.py 优化计划（第二轮）

> 生成时间: 2026-05-21 22:00 (北京时间)
> 版本: v2.0

## 诊断结论

对比参照脚本 ic_rsi_1d.py，发现以下问题：

### 问题清单

| # | 问题类型 | 位置 | 描述 | 优先级 |
|---|---------|------|------|--------|
| 1 | 代码风格 | 第268行 | 注释缩进不一致：`# ========== [4/4] 保存结果 ========== ` 缺少缩进（应与第269行代码一致） | P1 |
| 2 | 规范遗漏 | __main__ | 缺少 RuntimeError 捕获（ic_rsi_1d.py 有 RuntimeError 捕获） | P1 |

### 代码对比

**ic_rsi_1d.py __main__ 异常处理（正确）：**
```python
except RuntimeError as e:
    logger.exception("计算失败")
    sys.exit(1)
except Exception as e:
    logger.exception("未预期的错误")
    sys.exit(1)
```

**ic_turnover_surge_1d.py __main__ 异常处理（缺少 RuntimeError）：**
```python
except FileNotFoundError as e:
    logger.exception("缓存文件不存在...")
except json.JSONDecodeError as e:
    logger.exception("缓存文件损坏...")
except PermissionError as e:
    logger.exception("缓存文件权限错误...")
except Exception as e:  # ← 缺少 RuntimeError 分支
    logger.exception("计算失败...")
```

## 修复步骤（Bite-sized Tasks）

### Step 1: 修复第268行注释缩进
- 时间: 1分钟
- 修改: 添加缩进，使注释与代码块一致

### Step 2: 添加 RuntimeError 捕获
- 时间: 2分钟
- 修改: 在 Exception 之前添加 RuntimeError 分支
- 原因: 主函数抛出 RuntimeError，__main__ 需要捕获

### Step 3: 同步更新流程文档
- 时间: 3分钟
- 文件: docs/ic_turnover_surge_1d_flow.md
- 更新: 版本号 v1.23→v1.24，时间标注，修复内容

### Step 4: Git commit
- 时间: 1分钟

## 规范依据

- PROJECT.md 代码风格规范：注释缩进与代码块一致
- ic_rsi_1d.py 参照脚本：__main__ 异常处理模式