# fetch_stock_list 流程文档

> 版本: v2.13
> 创建时间: 2026-05-27 16:20 北京时间
> 更新时间: 2026-05-27 18:30 北京时间

---

## 整体架构

```
┌──────────────────────────────────────────────────────────────────────────┐
│                    fetch_stock_list.py 架构                                │
├──────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  ┌──────────────┐      ┌─────────────┐      ┌─────────────┐              │
│  │ 新浪财经 API │─────▶│ 股票筛选    │─────▶│ 数据验证    │              │
│  │ (主板股票)   │      │ (剔除ST/创业板)│      │ (完整性检查) │              │
│  └──────────────┘      └─────────────┘      └─────────────┘              │
│         │                     │                    │                      │
│         ▼                     ▼                    ▼                      │
│  ┌─────────────────────────────────────────────────────────────────────┐│
│  │                        增量更新机制（双文件）                          ││
│  │  cache/stock_list.json       ← 股票列表数据（供其他模块使用）          ││
│  │  result/stock_list_meta.json ← 元信息（版本号、统计、时间戳）        ││
│  └─────────────────────────────────────────────────────────────────────┘│
│                                                                          │
│  ┌─────────────────────────────────────────────────────────────────────┐│
│  │                   公共模块复用（MODULE.md 约束 #4）                   ││
│  │  - setup_logger（日志配置）                                          ││
│  │  - create_sina_session（HTTP客户端）                                 ││
│  │  - paths 函数（路径管理）                                            ││
│  │  - write_json_cache（原子写入）v2.9新增                              ││
│  └─────────────────────────────────────────────────────────────────────┘│
│                                                                          │
└──────────────────────────────────────────────────────────────────────────┘
```

---

## 数据流图

### 主流程：refresh_stock_cache()

```
                    用户调用 refresh_stock_cache()
                              │
                              ▼
                    ┌─────────────────────┐
                    │ Step 1: 从API获取数据 │
                    │ fetch_stocks_from_sina│
                    └─────────────────────┘
                              │
                              ▼
                    ┌─────────────────────┐
                    │ Step 2: 增量更新缓存 │
                    │   save_cache()      │
                    │  - 新增股票          │
                    │  - 删除退市/ST       │
                    │  - 更新名称          │
                    └─────────────────────┘
                              │
                              ▼
                    ┌─────────────────────┐
                    │ Step 3: 验证完整性   │
                    │   validate_cache()  │
                    └─────────────────────┘
                              │
              ┌───────────────┼───────────────┐
              │               │               │
              ▼               ▼               ▼
         验证通过        验证失败        返回结果
              │               │               │
              ▼               ▼               ▼
         write_json_cache  raise RuntimeError
              │                               │
              ▼                               ▼
         返回成功结果                      异常退出
```

---

## 关键函数说明

### fetch_stocks_from_sina()

**功能**: 从新浪财经API分页获取主板股票列表

**流程**:
1. 使用 `create_sina_session()` 创建HTTP客户端
2. 分页获取沪市A股(sh_a)和深市A股(sz_a)
3. 使用 `is_valid_main_board_stock()` 筛选主板股票
4. 使用 `determine_market()` 判断所属市场
5. 去重 + 按代码排序

**返回**: `(stocks: List[Dict], api_pages: int)`

---

### save_cache()

**功能**: 增量更新股票列表持久化文件

**增量逻辑**:
- **新增**: API有但文件没有 → 添加（标记added_at）
- **删除**: 文件有但API没有 → 删除（退市/ST）
- **更新**: 两边都有 → 同步name字段（最新名称）

**输出文件**:
- `cache/stock_list.json` - 股票列表数据
- `result/stock_list_meta.json` - 元信息

**写入方式**: 使用 `write_json_cache()` 原子写入（v2.9新增）

---

### validate_cache()

**功能**: 验证缓存数据完整性

**检查项**:
1. 数量检查：总股票数 >= MIN_TOTAL_STOCKS (2500)
2. ST股票混入检查：使用前缀匹配（S开头、*ST、ST）
3. 创业板混入检查：30开头
4. 科创板混入检查：688开头
5. 北交所混入检查：8开头、4开头
6. 市场分布检查：沪市 >= 1500，深市 >= 1200
7. 数据格式检查：抽查前10条（code、name、market）

---

### is_valid_main_board_stock()

**功能**: 判断是否为有效主板股票

**剔除规则**:
1. 创业板（30开头）
2. 科创板（688开头）
3. 北交所（8开头、4开头）
4. ST类股票（前缀匹配，使用ST_PREFIXES常量）
   - S开头：历史特殊处理股票（SST、S*ST）
   - *ST：退市风险警示（不以S开头）
   - ST：风险警示（不以S开头）
5. 退市股票（名称含"退市"）

**保留规则**:
- 沪市主板（60开头）
- 深市主板（00开头，含003）

---

## 公共模块复用（v2.9新增）

### write_json_cache 替换手写原子写入

**修改位置**: save_cache() 函数（678行、686行）

**修改前**:
```python
_write_json_file(CACHE_FILE, cache_data, _logger)
_write_json_file(RESULT_FILE, result_data, _logger)
```

**修改后**:
```python
write_json_cache(CACHE_FILE, cache_data, json_indent=2, logger=_logger)
write_json_cache(RESULT_FILE, result_data, json_indent=2, logger=_logger)
```

**优势**:
- 复用公共模块原子写入实现（tempfile.NamedTemporaryFile + os.replace）
- 删除冗余函数 `_write_json_file`（减少45行代码）
- 符合 MODULE.md 约束 #4（强制复用公共模块）

---

## 版本历史

| 版本 | 日期 | 改进内容 |
|-----|------|---------|
| v2.13 | 2026-05-27 | 返回数据完整性修复：验证失败时填充统计数据、removed_codes_truncated字段添加、validate_cache格式检查注释补全 |
| v2.12 | 2026-05-27 | CLI与注释规范化：CLI入口退出码修复、is_valid_main_board_stock注释修正、validate_cache ST检查与is_valid_main_board_stock严格一致 |
| v2.11 | 2026-05-27 | 类型系统规范化：load_cache返回类型校验、ST_PREFIXES改为具名常量、refresh_stock_cache总是返回字典、typing模块统一改为内置泛型 |
| v2.10 | 2026-05-27 | 代码质量修复：save_cache退市股票过滤使用removed_codes_full、validate_cache引用ST_PREFIXES常量、is_valid_main_board_stock调整ST检查顺序、重试逻辑添加显式continue |
| v2.9 | 2026-05-27 | 公共模块规范化：write_json_cache替换手写原子写入、删除冗余函数、创建流程文档和pytest测试文件 |
| v2.8 | 2026-05-27 | ST前缀提取为常量ST_PREFIXES、doctest修复 |
| v2.7 | 2026-05-27 | removed_codes截断(最多50个)、updated_count补全 |
| v2.6 | 2026-05-27 | ST顺序修复(S→*ST→ST)、重试逻辑简化 |
| v2.5 | 2026-05-27 | 重试逻辑修复、tempfile.NamedTemporaryFile修复 |
| v2.4 | 2026-05-27 | logger参数遮蔽修复、session资源泄漏修复、ST误判修复 |
| v2.3 | 2026-05-27 | load_cache异常捕获扩大 |
| v2.2 | 2026-05-27 | 导入顺序修正、ensure_dir调用时传递logger |
| v2.1 | 2026-05-27 | requests导入移至顶部、原子写入异常处理、类型注解补全 |
| v2.0 | 2026-05-27 | 公共模块规范化：setup_logger、paths函数、输出到result目录 |

---

## 测试策略

**pytest 测试文件**: `test_cases/test_fetch_stock_list.py`

**测试覆盖**:
1. 股票筛选逻辑：主板判断、创业板剔除、ST剔除
2. 市场判断逻辑：沪市/深市/未知
3. 缓存验证逻辑：数量检查、ST混入检测、创业板混入检测
4. 约束合规检查：版本号常量、公共模块导入
5. 增量更新逻辑：保存缓存、API失败处理
6. 异常处理：缓存不存在、JSON解析失败

---

## 相关文档

- [PROJECT.md](../PROJECT.md) - 项目整体规范
- [MODULE.md](../data_fetchers/MODULE.md) - 模块约束规范
- [cache_manager_flow.md](cache_manager_flow.md) - 缓存管理流程
- [fetch_industry_flow.md](fetch_industry_flow.md) - 行业分类流程