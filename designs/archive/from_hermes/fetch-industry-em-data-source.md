# Design: 替换行业分类数据源为东方财富

> 日期: 2026-06-12
> 状态: pending-review
> 涉及文件: `data_fetchers/fetch_industry.py` (单文件重构，≤200行改动)

---

## What

将 `fetch_industry.py` 的主数据源从 akshare 申万宏源 (`stock_industry_clf_hist_sw`) 切换为东方财富 (`stock_board_industry_cons_em`)，根本解决 SSL 证书验证失败问题。

## Why

- **根因**: `www.swsresearch.com` 服务器 TLS 配置不完整——只发送叶子证书，未发送中间证书 (GeoTrust G2 TLS CN RSA4096 SHA256 2022 CA1)。Python requests 默认使用 certifi CA 库验证，缺少中间证书导致验证失败。
- **影响**: 每次拉取失败后降级到本地关键词推断，75.4% 股票归为"其他"，行业分类严重失真。
- **东方财富优势**: 无 SSL 问题、数据完整覆盖 5607 只股票（31 个一级行业全覆盖）、无需中间证书补丁。

## How

### 核心改动

1. **新增 `fetch_stock_industry_em()` 函数**: 遍历31个申万一级行业对应的东方财富板块，调用 `stock_board_industry_cons_em` 获取成分股，构建 `{股票代码: {name, industry, industry_code}}` 映射。

2. **保留 `fetch_stock_industry_sw()` 函数**: 作为备用数据源，不删除。但降级优先级调整为：EM主 → SW备 → 本地关键词推断。

3. **新增 `_SW_TO_EM_MAP` 常量**: 申万31个一级行业名称 → 东方财富板块名称映射表（名称基本一致，1:1 映射）。

4. **修改 `refresh_industry_cache()`**: 优先调用 `fetch_stock_industry_em()`，失败时降级到 `fetch_stock_industry_sw()`，再降级到本地备用。

5. **修改缓存 meta 字段**: `source` 增加 `'em_category'` 值，区分东方财富和申万数据源。

6. **修改 `infer_industry_from_name()`**: 保留作为三级降级，注释明确标注为最低准确性。

### 映射表定义

```python
_SW_TO_EM_MAP: dict[str, str] = {
    '农林牧渔': '农林牧渔',
    '基础化工': '基础化工',
    '钢铁': '钢铁',
    '有色金属': '有色金属',
    '汽车': '汽车',
    '家用电器': '家用电器',
    '电子': '电子',
    '商贸零售': '商贸零售',
    '医药生物': '医药生物',
    '食品饮料': '食品饮料',
    '纺织服饰': '纺织服饰',
    '轻工制造': '轻工制造',
    '公用事业': '公用事业',
    '交通运输': '交通运输',
    '房地产': '房地产',
    '建筑材料': '建筑材料',
    '社会服务': '社会服务',
    '综合': '综合',
    '银行': '银行',
    '非银金融': '非银金融',
    '建筑装饰': '建筑装饰',
    '电力设备': '电力设备',
    '机械设备': '机械设备',
    '国防军工': '国防军工',
    '计算机': '计算机',
    '传媒': '传媒',
    '通信': '通信',
    '煤炭': '煤炭',
    '石油石化': '石油石化',
    '环保': '环保',
    '美容护理': '美容护理',
}
```

### 降级链设计

```
EM 东方财富（主） → SW 申万宏源（备） → 本地关键词推断（兜底）
```

### 性能考虑

东方财富需逐板块调用（31次API），约耗时30秒。设 `time.sleep(0.3)` 避免反爬。缓存7天过期，正常运行不频繁调用。

## Don't

- ❌ 不删除 `fetch_stock_industry_sw()` 函数——保留为备用
- ❌ 不删除 `SW_INDUSTRY_CODE_MAP`——SW备用数据仍需要
- ❌ 不修改 `infer_industry_from_name()` 的关键词逻辑——兜底仍有效
- ❌ 不在 `fetch_stock_industry_em()` 中设置 `verify=False`——东方财富无SSL问题
- ❌ 不修改缓存文件名（仍为 `stock_industry.json`）——保持下游兼容

## When

行业数据拉取失败（SSL/网络/API异常）时自动降级。正常情况下直接从东方财富获取。

## Verify

1. 运行 `python data_fetchers/fetch_industry.py` → 应显示 "东方财富获取成功"
2. 检查缓存 `meta.source` = `em_category`
3. 检查行业分布：各行业均有合理数量，"其他"占比应 ≈0%（仅综合类19只）
4. `pytest data_fetchers/test_cases/` → 全部通过
5. `ruff check data_fetchers/fetch_industry.py` → 无错误

---

## 影响范围

| 文件 | 改动类型 | 行数估计 |
|------|---------|---------|
| `data_fetchers/fetch_industry.py` | 新增函数+修改降级链+新增常量 | ~80行新增，~30行修改 |
| `data_fetchers/docs/fetch_industry_flow.md` | 更新流程文档 | ~20行 |
| `data_fetchers/test_cases/test_fetch_industry.py` | 新增EM数据源测试 | ~40行 |

总计 ≤3 文件，≤150 行改动，符合粒度约束。