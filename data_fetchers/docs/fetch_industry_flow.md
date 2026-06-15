# fetch_industry 流程文档

> 版本: v3.13
> 创建时间: 2026-05-27 14:20 北京时间
> 更新时间: 2026-06-15（v3.13 误导性日志消除与 docstring 契约补充：_write_backup_cache 调用移出 try/except、SW docstring 补包装语义、衔接日志措辞修正）

---

## 整体架构

```
┌──────────────────────────────────────────────────────────────────────────┐
│                    fetch_industry.py 架构 (v3.0)                        │
├──────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  ┌──────────────┐      ┌─────────────┐      ┌─────────────┐              │
│  │ EM API       │─────▶│ 板块名称映射 │─────▶│ 数据验证    │              │
│  │ (东方财富)   │      │ (_SW_TO_EM) │      │ (列名校验)  │              │
│  └──────────────┘      └─────────────┘      └─────────────┘              │
│         │                     │                    │                      │
│         │  [EM 失败时降级]     │                    │                      │
│         ▼                     ▼                    ▼                      │
│  ┌──────────────┐                                                        │
│  │ SW API       │                                                        │
│  │ (申万行业)   │─────▶ SW_INDUSTRY_CODE_MAP ────▶ 数据验证              │
│  └──────────────┘                                                        │
│         │                                                                │
│         ▼                                                                │
│  ┌─────────────────────────────────────────────────────────────────────┐│
│  │                        缓存机制（7天有效期）                          ││
│  │  result/stock_industry.json ← 行业数据（一级分类，供其他模块使用）    ││
│  │  meta.source: em_category / sw_category / local_backup              ││
│  └─────────────────────────────────────────────────────────────────────┘│
│                                                                          │
│  ┌─────────────────────────────────────────────────────────────────────┐│
│  │                   线程安全模块级缓存（DCL+哨兵对象）                   ││
│  │  _industry_cache + _cache_lock + _UNSET（区分空dict与未初始化）       ││
│  └─────────────────────────────────────────────────────────────────────┘│
│                                                                          │
└──────────────────────────────────────────────────────────────────────────┘
```

---

## 数据流图

### 主流程：load_stock_industry()

```
                    用户调用 load_stock_industry()
                              │
                              ▼
                    ┌─────────────────────┐
                    │ 缓存文件是否存在？   │
                    └─────────────────────┘
                              │
              ┌───────────────┼───────────────┐
              │ YES           │               │ NO
              ▼               │               ▼
    ┌─────────────────┐       │      ┌─────────────────┐
    │ 加载缓存文件    │       │      │ refresh_cache() │
    └─────────────────┘       │      └─────────────────┘
              │               │               │
              ▼               │               ▼
    ┌─────────────────┐       │      ┌─────────────────┐
    │ 数据完整性检查   │       │      │ EM→SW 降级链    │
    │ (industries类型) │       │      └─────────────────┘
    └─────────────────┘       │               │
              │               │               ├────────────┐
              ▼               │               │ SUCCESS    │ FAIL
    ┌─────────────────┐       │               ▼            ▼
    │ 缓存是否过期？   │       │      ┌───────────┐  ┌──────────────┐
    │ (>7天)          │       │      │ 写入缓存   │  │ load_backup()│
    └─────────────────┘       │      └───────────┘  └──────────────┘
              │               │               │            │
    ┌─────────┼─────────┐     │               ▼            ▼
    │ FRESH   │ EXPIRED │     │         返回数据      推断行业
    ▼         ▼         │                          │
返回缓存  refresh_cache()│                          ▼
              │         │                   ┌──────────────┐
              ▼         │                   │ 名称关键词推断│
    ┌─────────────────┐ │                   └──────────────┘
    │ 尝试刷新        │ │                          │
    └─────────────────┘ │                          ▼
              │         │                   ┌──────────────┐
    ┌─────────┼─────────┤                   │ 写入备用缓存  │
    │ SUCCESS │ FAIL    │                   └──────────────┘
    ▼         ▼         │                          │
返回新数据 降级旧缓存    │                          ▼
              │         │                   返回备用数据
              └─────────┘
```

### refresh_industry_cache() 内部降级链（v3.0 新架构）

```
refresh_industry_cache()
        │
        ├─ 1. fetch_stock_industry_em()     ← 东方财富板块成分股（主数据源）
        │       │
        │       │ ak.stock_board_industry_cons_em(symbol=板块名)
        │       │ 遍历31个申万一级对应板块，0.3s间隔防反爬
        │       │ 列名校验: ['代码', '名称']
        │       │ 不受 SSL 证书问题影响
        │       │
        │       ├─ [SUCCESS] source = 'em_category'
        │       │   → 写入缓存 → 返回
        │       │
        │       └─ [FAIL] 记录 em_error，继续 ↓
        │
        ├─ 2. fetch_stock_industry_sw()     ← 申万行业分类（备用数据源）
        │       │
        │       │ ak.stock_industry_clf_hist_sw() → 行业代码映射
        │       │ ak.stock_info_a_code_name() → 股票名称
        │       │ SW_INDUSTRY_CODE_MAP → 一级分类映射
        │       │ 受 swsresearch.com SSL 缺失中间证书影响
        │       │
        │       ├─ [SUCCESS] source = 'sw_category'
        │       │   → 写入缓存 → 返回
        │       │
        │       └─ [FAIL] → raise RuntimeError(EM + SW 均失败)
        │
        └─ [RuntimeError] → 调用方(load_stock_industry)降级到本地推断
```

---

## 函数调用关系

```
get_industry_map()                   ← 公共接口（模块级缓存）
    │
    └─ load_stock_industry()         ← 加载行业数据（优先缓存）
        │
        ├─ INDUSTRY_CACHE_PATH.exists()
        │   │
        │   ├─ [YES] json.load() → 数据验证 → 过期检查
        │   │   │
        │   │   ├─ [FRESH] 返回缓存
        │   │   └─ [EXPIRED] refresh_industry_cache()
        │   │       │
        │   │       ├─ [SUCCESS] 返回新数据
        │   │       └─ [FAIL] 降级旧缓存
        │   │
        │   └─ [NO] refresh_industry_cache()
        │
        └─ refresh_industry_cache()  ← 刷新缓存（EM→SW降级链）
            │
            ├─ fetch_stock_industry_em()  ← 东方财富板块成分股（主）
            │   │
            │   ├─ ak.stock_board_industry_cons_em(symbol) × 31 板块
            │   ├─ _SW_TO_EM_MAP           ← 申万一级→EM板块名映射
            │   └─ _EXPECTED_EM_COLS       ← 列名校验 ['代码', '名称']
            │
            ├─ fetch_stock_industry_sw()   ← 申万行业分类（备）
            │   │
            │   ├─ ak.stock_industry_clf_hist_sw()  ← 行业分类历史
            │   ├─ ak.stock_info_a_code_name()      ← 股票名称
            │   └─ SW_INDUSTRY_CODE_MAP             ← 行业代码映射
            │
            ├─ [SUCCESS] write_json_cache() → meta.source标注来源
            │
            └─ [FAIL] → raise RuntimeError → load_local_industry_backup()
                │
                ├─ stock_list.json → infer_industry_from_name()
                │   │
                │   └─ 关键词匹配（模糊推断）
                │
                └─ write_json_cache() [非致命错误]
```

---

## 缓存机制

### 主缓存（akshare数据）

**路径**: `result/stock_industry.json`

**有效期**: 7天

**结构**:
```json
{
  "meta": {
    "version": "3.0",
    "source": "em_category",
    "level": "一级",
    "updated_at": "2026-06-12",
    "total_count": 5585
  },
  "industries": {
    "000001": {
      "name": "平安银行",
      "industry": "银行",
      "industry_code": "em_银行"
    },
    "600000": {
      "name": "浦发银行",
      "industry": "银行",
      "industry_code": "em_银行"
    },
    ...
  }
}
```

**meta.source 取值**:
| 值 | 含义 | 数据源 |
|---|------|--------|
| `em_category` | 东方财富板块成分股 | fetch_stock_industry_em() |
| `sw_category` | 申万行业分类 | fetch_stock_industry_sw() |
| `local_backup` | 本地关键词推断 | load_local_industry_backup() |

**industry_code 格式**:
| 数据源 | 格式 | 示例 |
|--------|------|------|
| EM | `em_{板块名}` | `em_银行` |
| SW | 4位申万代码 | `4801` |
| local | `local` | `local` |

**更新策略**:
- 缓存过期（>7天）时尝试刷新
- 刷新失败时**降级使用旧缓存**（而非直接切换备用）
- 写入使用 `write_json_cache()`（原子写入）

### 备用缓存（本地推断）

**路径**: 同 `result/stock_industry.json`（覆盖主缓存）

**触发条件**: EM + SW 均获取失败（refresh_industry_cache 抛 RuntimeError）

**数据源**: `data_fetchers/result/stock_list.json`

**推断方式**: 名称关键词匹配（`infer_industry_from_name()`）

**写入策略**:
- 备用缓存写入失败为**非致命错误**（warning）
- 下次调用会重新读取备用数据源
- 与主缓存写入策略不同（主缓存失败抛异常）

---

## 数据源切换说明（v3.0）

### 为什么切换主数据源

**原问题**: `www.swsresearch.com` 服务器 TLS 配置不完整——只发送了叶子证书，未发送中间证书（GeoTrust G2 TLS CN RSA4096 SHA256 2022 CA1）。Python `requests` 使用 certifi CA 库验证时缺少中间证书导致 SSL 验证失败。

**影响**: SW SSL 失败 → 降级本地关键词推断 → 75.4% 股票归为"其他"

**解决方案**: 主数据源切换为东方财富 `stock_board_industry_cons_em`，不受 SSL 影响。

### 效果对比

| 指标 | v2.x（SW关键词推断） | v3.0（EM板块成分股） |
|------|---------------------|---------------------|
| 总股票数 | ~3019 | 5585 |
| "其他"占比 | 75.4% | 0.0% |
| 行业覆盖 | ~15个关键词类别 | 31个申万一级标准行业 |
| meta.source | local_backup | em_category |

---

## v3.1 SW SSL 修复 + 防覆盖（2026-06-14）

### 背景：2026-06-13 行业数据污染事故

**事件**: 2026-06-12 13:07 EM 拉取成功（5585 只）→ 2026-06-13 03:22 自动刷新时 EM
（IP 被反爬封禁，TLS-then-RST）+ SW（akshare 内部 SSL 失败）双源同时失败 →
`load_local_industry_backup` 触发 → `_write_backup_cache` **静默覆盖**了 6-12 的真实
缓存为 3021 只的关键词推断版本（75.44% "其他"）→ 下游 `industry_pe_trend` 因子全部
按错误行业分组计算，IC=-0.0148。

**根因**:
1. EM 不可达（外部）：阿里云出口 IP 被 `*.push2.eastmoney.com` 反爬封禁
2. SW 不可用（环境）：Python `requests` 默认 `certifi` CA bundle 不含 `GeoTrust G2 TLS CN RSA4096 SHA256 2022 CA1` 中间 CA，但**系统 CA bundle (`/etc/pki/tls/cert.pem`) 完整可用**
3. 设计缺陷（代码）：`_write_backup_cache` 无条件覆盖，没有"宁可保留旧真实数据也不写新假数据"的保护

### 修复 1：SW 数据源恢复（绕开 akshare 内部 SSL 限制）

新增 `_download_sw_industry_xls()`：直接用 `requests.get(verify=系统CA bundle)` 下载
swsresearch.com 的 xls 文件，绕开 akshare 内部 `requests.get(url)`（默认 certifi）。

**关键代码路径**:
```
fetch_stock_industry_sw()
  └─ _download_sw_industry_xls()              # v3.1 新增
       ├─ _get_sw_ca_bundle()                 # 选择系统 CA：/etc/pki/tls/cert.pem 等
       ├─ requests.get(url, verify=ca_bundle, timeout=30)
       └─ pd.read_excel + rename 列名
  └─ ak.stock_info_a_code_name()              # 股票名称（仍走 akshare，3 次重试）
```

**CA bundle 候选优先级**: `/etc/pki/tls/cert.pem`（RHEL/CentOS/AliLinux）→
`/etc/ssl/certs/ca-certificates.crt`（Debian/Ubuntu）→ `/etc/ssl/cert.pem`（macOS/Alpine）→
回退 `True`（让 requests 用 certifi 默认，会失败但不静默）。

**实测**: 2026-06-14 EM 仍封禁 → SW 拉取成功 5872 只股票，"其他" 26.3%（v3.0 是 0.0% 但
基于 EM 的 5585 只，v3.1 SW 数据本身就有约 26% 二级代码不在 SW_INDUSTRY_CODE_MAP 中）。

### 修复 2：防覆盖（避免事故重演）

`_write_backup_cache()` 写入前检查现有缓存：

```
现有缓存 meta.source                  | 行为
═════════════════════════════════════ |═════════════
em_category / sw_category（真实数据） | 拒绝写入，仅返回内存数据
local_backup（旧的关键词推断）        | 允许刷新
不存在 / 损坏 / 读取失败              | 允许写入（首次 / 自我修复）
```

**保护策略**: 宁可让进程返回内存中的本地推断数据，也不持久化覆盖磁盘上已有的真实缓存。
下次 EM 或 SW 恢复时，refresh_industry_cache 会拿到真数据并正常写入（不触发本保护）。

### 修复 3：stock_info_a_code_name 重试

`ak.stock_info_a_code_name()`（深交所 API）偶发 `ConnectionResetError`，加 3 次重试
（间隔 2/4 秒），避免 SW 路径被一次抖动拖死。

### v3.1 流程图变化

```
原 SW 调用: ak.stock_industry_clf_hist_sw()
                │ (内部 requests.get, 默认 certifi → SSL fail)
                ▼
                X SSLError

新 SW 调用: _download_sw_industry_xls()
                ├─ _get_sw_ca_bundle() → /etc/pki/tls/cert.pem
                ├─ requests.get(url, verify=ca_bundle)
                └─ pd.read_excel → DataFrame
                ▼
                ✓ 5872 只数据
```

```
原 backup 写入:                     新 backup 写入 (v3.1):
_write_backup_cache(map)             _write_backup_cache(map)
  └─ write_json_cache               ├─ 检查现有缓存 meta.source
     (无条件覆盖)                    │   ├─ 真实数据源 → return（拒绝）
                                    │   └─ 缺失/损坏/local → 继续
                                    └─ write_json_cache（仅在允许时）
```

---

## 错误处理策略

### 错误分类与处理

| 错误类型 | 处理策略 | 日志级别 | 说明 |
|---------|---------|---------|------|
| EM API 失败 | 降级到 SW | warning | 非致命，切换备用数据源 |
| SW API 失败 | 降级本地推断 | warning | EM + SW 均失败时兜底 |
| 缓存文件损坏 | 删除+重新获取 | warning | 数据完整性检查失败 |
| 缓存过期刷新失败 | 降级旧缓存 | warning | 保留旧数据而非备用 |
| 备用缓存写入失败 | 忽略（warning） | warning | 非致命，下次重试 |
| 主缓存写入失败 | 抛异常 | error | 致命错误，影响后续流程 |
| 列名校验失败 | 抛 KeyError | error | API 返回格式异常 |
| 日期解析失败 | 使用现有缓存 | warning | 格式异常不阻塞 |

### 降级策略优先级

```
1. 主缓存（akshare数据，最新）
   ↓ [过期]
2. 刷新缓存（EM→SW 降级链获取新数据）
   ↓ [EM 失败]
3. SW 数据源（申万行业分类）
   ↓ [SW 也失败]
4. 旧缓存（保留过期数据）
   ↓ [不存在]
5. 备用数据（本地推断，准确性低）
```

**关键决策**:
- 优先使用过期缓存而非备用数据
- EM 优先于 SW（EM 不受 SSL 问题影响）
- 备用数据准确性低于 akshare，仅作兜底

---

## 线程安全设计

### 模块级缓存（DCL双重检查 + 哨兵对象）

```python
_UNSET = object()                # 唯一哨兵对象，区分"未初始化"和"空dict"
_industry_cache = _UNSET         # 初始状态
_cache_lock = threading.Lock()   # 线程锁

def get_industry_map():
    global _industry_cache
    if _industry_cache is _UNSET:         # 第一次检查（无锁）
        with _cache_lock:               # 加锁
            if _industry_cache is _UNSET: # 第二次检查（锁内）
                try:
                    _industry_cache = load_stock_industry()
                except Exception as e:
                    _industry_cache = {}  # 加载失败赋空dict
    return _industry_cache
```

**哨兵对象优势**（v2.6 引入）:
- 区分"未初始化"（_UNSET）与"加载结果为空dict"两种状态
- 避免空 dict 重复加载
- 加载失败也赋值空 dict，后续不重复

---

## 公共模块复用

### v2.4 改进（遵循 MODULE.md 约束）

| 改进项 | 原实现 | 新实现 | 约束编号 |
|-------|--------|--------|---------|
| 日志初始化 | `logging.basicConfig()` | `setup_logger()` | PROJECT.md 日志规范 |
| 缓存写入 | 手写原子写入（120行） | `write_json_cache()` | MODULE.md 约束 #4 |
| 路径管理 | 硬编码路径（4处） | `get_module_result_dir()` | MODULE.md 约束 #62 |
| 备用数据路径 | 硬编码 `data_fetchers/result/stock_list.json` | `get_stock_list_file()` | MODULE.md 约束 #62 |

### 导入规范

```python
# 公共模块导入（遵循 MODULE.md 约束 #4）
from data_fetchers.common import (
    setup_logger,           # 日志初始化
    get_module_result_dir,  # 输出目录路径
    get_stock_list_file,    # 股票列表路径
    write_json_cache        # 缓存写入
)
```

---

## 约束合规说明

### MODULE.md 约束合规

| 约束编号 | 约束内容 | 合规状态 | 实现位置 |
|---------|---------|---------|---------|
| #2 | 输出到 `result` 目录 | ✅ 合规 | RESULT_DIR = get_module_result_dir() |
| #4 | 强制复用公共模块 | ✅ 合规 | 导入、refresh_industry_cache/backup_cache调用 |
| #16 | 版本号提取为常量 | ✅ 合规 | `_OUTPUT_VERSION = '3.0'` |
| #17 | `datetime.now()` 只调用一次 | ✅ 合规 | 固定时间戳（两处：refresh + backup） |
| #62 | 禁止硬编码路径 | ✅ 合规 | 使用公共模块路径函数 |
| #72 | 备用缓存写入失败非致命 | ✅ 合规 | try-except + warning |

### PROJECT.md 日志规范合规

| 规范内容 | 合规状态 | 实现位置 |
|---------|---------|---------|
| 异常日志包含类型名 | ✅ 合规 | `[{type(e).__name__}]` 格式 |
| 日志追溯调用方 | ✅ 合规 | 公共模块接收 logger 参数 |
| __main__ 块有退出码 | ✅ 合规 | sys.exit(0 if success else 1) |

---

## 数据验证

### akshare API 列名校验

| API | 期望列名 | 校验位置 | 数据源 |
|-----|---------|---------|--------|
| `stock_board_industry_cons_em()` | `代码`, `名称` | fetch_stock_industry_em() | EM（主） |
| `stock_industry_clf_hist_sw()` | `symbol`, `industry_code`, `start_date` | fetch_stock_industry_sw() | SW（备） |
| `stock_info_a_code_name()` | `code`, `name` | fetch_stock_industry_sw() | SW（备） |

**校验逻辑**:
```python
missing_cols = [col for col in _EXPECTED_EM_COLS if col not in df.columns]
if missing_cols:
    raise KeyError(f"东方财富板块缺少必需列: {missing_cols}")
```

### 缓存数据完整性检查

| 检查项 | 检查逻辑 | 失败处理 |
|-------|---------|---------|
| `industries` 类型 | `isinstance(industries, dict)` | 删除缓存+重新获取 |
| 空缓存 | `file_size == 0` | 返回空字典 |

---

## 行业代码映射

### 东方财富板块映射（v3.0 主数据源）

**映射规则**:
- `_SW_TO_EM_MAP`: 申万31个一级名称 → 东方财富板块名称（1:1映射，名称基本一致）
- 遍历31个板块获取成分股，0.3秒间隔防反爬
- 首次归属优先（股票出现在多个板块时取首次）

### 申万2021一级分类（SW 备用数据源）

**映射规则**:
- akshare 返回的 `industry_code` 为4位（如 `4801`）
- 前2位为一级代码（如 `48`）
- 使用 `SW_INDUSTRY_CODE_MAP` 映射到行业名称

**特殊处理**:
- 不存在的一级代码（如 `22`, `28`, `33`）映射到 `'其他'`
- 未匹配的行业代码默认 `'其他'`

**一级代码范围**:
```
11, 21, 23-27, 31-32, 34-36, 41-46, 48-49, 62-65, 71-77
```

---

## 关键词推断逻辑

### infer_industry_from_name()

**模糊匹配规则**:
- 关键词包含检测（非精确匹配）
- 遍历顺序决定优先级
- 具体关键词优先（避免歧义）

**关键词重叠消除**:
- `光伏`/`风电` 只在 `电力` 中
- `新能源` 使用 `锂电`/`电池`/`太阳能`
- 品牌词已移除（"平安"、"中信"不作为行业推断依据）

**示例**:
- `"平安银行"` → `"银行"`（匹配 `"银行"`）
- `"新能源电力"` → `"电力"`（匹配 `"电力"`，电力在字典中先于新能源）

---

## 版本历史

| 版本 | 日期 | 改进内容 |
|-----|------|---------|
| v3.1 | 2026-06-14 | SW SSL 修复 + 防覆盖 + 重试：1) 自实现 _download_sw_industry_xls 用系统 CA bundle 调用 swsresearch.com（绕开 certifi 缺中间 CA），SW 重新作为可用降级；2) _write_backup_cache 加防覆盖检查（meta.source ∈ {em_category, sw_category} 时拒绝写 local_backup），避免 2026-06-13 类型事故；3) ak.stock_info_a_code_name 增加 3 次重试（深交所偶发 ConnectionReset） |
| v3.0 | 2026-06-12 | 数据源切换：主数据源从申万宏源(akshare)切换为东方财富行业板块(akshare stock_board_industry_cons_em)，解决SSL证书验证失败问题；降级链调整为 EM→SW→本地关键词推断；新增fetch_stock_industry_em()函数和_SW_TO_EM_MAP映射常量；meta.source新增'em_category'值 |
| v2.8 | 2026-05-27 | 日志精确化：refresh异常日志、缓存未过期分支日志、main错误级别调整 |
| v2.7 | 2026-05-27 | Bug修复与维护性改进：统一降级日志格式、pd.to_datetime转换、__all__移除路径常量、异常链保留 |
| v2.6 | 2026-05-27 | 防御性改进：哨兵对象_UNSET、移除品牌词"中信"、备用文件不存在警告日志 |
| v2.5 | 2026-05-27 | 维护性改进：关键词优先级注释修正、移除品牌词"平安"、日期格式常量、降级链拆平 |
| v2.4 | 2026-05-27 | 公共模块规范化：setup_logger、write_json_cache、路径函数 |
| v2.3 | 2026-05-27 | datetime.now()只调用一次、类型注解 |
| v2.2 | 2026-05-27 | 缓存数据完整性验证 |
| v2.1 | 2026-05-27 | 日志信息修正、备用缓存策略说明 |
| v2.0 | 2026-05-27 | SW_INDUSTRY_CODE_MAP核对官方标准 |

---

## 测试策略

**pytest 测试文件**: `test_cases/test_fetch_industry.py`

**测试覆盖**（32 项测试）:
1. 行业代码映射（TC001）
2. 关键词推断逻辑（TC002）
3. 缓存机制（TC003）
4. 备用数据降级（TC004）
5. 线程安全（TC005）
6. 公共接口（TC006）
7. 约束合规（TC007）——版本号、公共模块、输出目录、退出码
8. 边界情况（TC008）
9. 东方财富数据源（TC009）——映射完整性、列名校验、降级链EM→SW→RuntimeError
10. SW SSL 修复 + 防覆盖（TC010, v3.1）——CA bundle 选择、_download_sw_industry_xls 验证、_write_backup_cache 拒绝覆盖真实数据

---

## 相关文档

- [PROJECT.md](../PROJECT.md) - 项目整体规范
- [MODULE.md](../data_fetchers/MODULE.md) - 模块约束规范
- [cache_manager_flow.md](cache_manager_flow.md) - 缓存管理流程
- [fetch_stock_list_flow.md](fetch_stock_list_flow.md) - 股票列表流程

---

**文档维护者**: 云舟  
**最后审核**: 2026-06-12