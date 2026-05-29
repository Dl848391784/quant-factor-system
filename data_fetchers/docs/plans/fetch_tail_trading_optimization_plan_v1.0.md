# fetch_tail_trading.py 优化计划

> 版本: v1.0
> 创建时间: 2026-05-29 11:45 北京时间
> 预计执行时间: 15分钟（分3轮执行）

---

## 当前状态分析

### 已合规项（✅）

| 约束 | 说明 | 状态 |
|------|------|------|
| #1 | 脚本命名 `fetch_tail_trading.py` | ✅ |
| #2 | 输出到 `result/` 目录 | ✅ `_RESULT_DIR / 'tail_trading_data.json.gz'` |
| #16 | version 字段提取为常量 | ✅ `_OUTPUT_VERSION = '1.0'` |
| #17 | datetime.now() 只调用一次 | ✅ `_NOW = datetime.now()` 固定时间戳 |
| #51 | 导入在模块顶部 | ✅ 所有导入在文件开头 |
| #77 | logger 参数命名规范 | ✅ 使用 `logger_arg`，内部变量 `_logger` |
| #78 | session 资源管理 | ✅ 使用 `with eastmoney_session() as session` |
| #50 | 异常日志包含类型名 | ✅ `[{type(e).__name__}]: {e}` 格式 |

---

## 需优化项（分3轮执行）

### Round 1: 规范合规修复（5分钟）

#### 1.1 约束 #15: main 函数 docstring 删除 Returns 节

**问题**: 第576行 main 函数 docstring 有 Returns 节，违反约束 #15（None 返回类型的函数不需要 Returns 节）

**当前代码**（第563-580行）:
```python
def main(...) -> bool:
    """
    主函数：拉取尾盘数据
    
    Args:
        ...
        
    Returns:
        是否成功
    """
```

**修复方案**:
```python
def main(...) -> bool:
    """
    主函数：拉取尾盘数据
    
    Args:
        full: 全量模式（拉取历史12天）
        max_stocks: 最大股票数（用于测试，0为不限制）
        logger_arg: 日志 logger（遵循 MODULE.md 约束 #77）
        
    Raises:
        RuntimeError: 数据拉取失败时抛出
        
    Note:
        返回值仅用于 CLI 入口判断执行状态，调用方不应依赖返回值做业务判断
    """
```

**文件位置**: 第563-580行

---

### Round 2: 代码健壮性优化（5分钟）

#### 2.1 魔法数字提取为常量

**问题**: 部分数值硬编码未提取为常量，降低可维护性

**当前代码**（第72-78行）:
```python
TAIL_PERIOD_START = '14:30'
TAIL_PERIOD_END = '15:00'
TAIL_KLINE_COUNT = 7
DEFAULT_HISTORY_DAYS = 12
DEFAULT_REQUEST_DELAY = 0.2
```

**优化方案**: 补充遗漏常量
```python
# 尾盘时段定义（5分钟K线）
TAIL_PERIOD_START = '14:30'  # 尾盘开始时间
TAIL_PERIOD_END = '15:00'    # 尾盘结束时间（收盘）
TAIL_KLINE_COUNT = 7         # 尾盘K线数量（14:30-15:00共7根5分钟K线）

# API 配置
DEFAULT_HISTORY_DAYS = 12    # 默认历史天数（API限制约12天）
DEFAULT_REQUEST_DELAY = 0.2  # 请求间隔（秒）
API_KLT = 5                  # K线类型：5分钟
API_FQT = 1                  # 前复权
API_LMT_FULL = 500           # 全量模式最大条数
API_LMT_INCREMENTAL = 50     # 增量模式最大条数
```

**文件位置**: 第71-79行

---

#### 2.2 异常处理精确化

**问题**: 部分函数捕获 Exception 范围过宽，掩盖具体错误类型

**当前代码**（第321行）:
```python
except Exception as e:
    _logger.error(f"[{code}] API请求失败: [{type(e).__name__}]: {e}")
    return []
```

**优化方案**: 区分异常类型
```python
except requests.RequestException as e:
    _logger.warning(f"[{code}] 网络请求失败: [{type(e).__name__}]: {e}")
    return []
except json.JSONDecodeError as e:
    _logger.warning(f"[{code}] JSON解析失败: [{type(e).__name__}]: {e}")
    return []
except Exception as e:
    _logger.error(f"[{code}] 未预期异常: [{type(e).__name__}]: {e}")
    return []
```

**文件位置**: 第321-323行

---

### Round 3: 文档同步验证（5分钟）

#### 3.1 流程文档检查

**检查项**:
- [ ] `docs/fetch_tail_trading_flow.md` 是否包含所有新增参数说明
- [ ] 版本历史是否同步更新
- [ ] 示例数据是否与实际运行结果一致

#### 3.2 测试文件检查

**检查项**:
- [ ] `test_cases/test_fetch_tail_trading.py` 是否覆盖新增参数
- [ ] 测试用例是否与脚本函数签名一致
- [ ] pytest 是否全部通过

---

## 执行顺序

```
Round 1: 规范合规修复 → 验证导入 → Git commit
Round 2: 代码健壮性优化 → 验证运行 → Git commit
Round 3: 文档同步验证 → 运行测试 → Git commit
```

---

## 验证命令

```bash
# Round 1 验证
python3 -c "from data_fetchers.fetch_tail_trading import main"

# Round 2 验证（测试模式）
cd /home/admin/projects/factor_ic_analyzer/data_fetchers
python3 fetch_tail_trading.py --test --full

# Round 3 验证
cd /home/admin/projects/factor_ic_analyzer
python3 -m pytest data_fetchers/test_cases/test_fetch_tail_trading.py -v
```

---

## 预期成果

1. **规范合规**: 所有 MODULE.md 约束项通过
2. **代码健壮性**: 异常处理精确化，魔法数字提取
3. **文档同步**: 流程文档与测试用例同步更新
4. **Git提交**: 每轮独立 commit，版本号递增

---

*创建时间: 2026-05-29 11:45 北京时间*