# Design: 报告展示综合因子值 Bottom 30

## 背景

用户诉求: `factor_summary_report` 目前只展示 Stage 1 Top 30 (composite 降序),
缺少 Bottom 30. 用户需要同时看到 composite 最高和最低的股票, 以判断系统选股方向.

## What

在 `factor_summary_report` 的 Stage 1 区域, Top 30 简表后新增 Bottom 30 简表.

## How

### 1. stock_selector.py — 捕获 Bottom 30 快照

在 L1499 `stage1_top_snapshot` 旁新增:

```python
stage1_bottom_snapshot: list[dict[str, Any]] = []
# ...
stage1_bottom_snapshot = [copy.deepcopy(s) for s in stage1_stocks[-config.top_n:]]
```

Bottom 30 的 rank 从 stage1_stocks 原始 rank 保留 (171~200), 不重新编号.

### 2. stock_selector.py — Parquet 归档 stage=4

`write_selection_history` 新增 `stage1_bottom` 参数, 以 `stage=4` 写入 Parquet.
schema 不变 (stage 字段 int8, 已支持 1/2/3/4).

### 3. generate_factor_summary_report.py — 读取 stage=4 并展示

- 读取侧: `load_stock_selection_result` 新增 `stage4_rows` 读取, 返回 `stage1_bottom`
- 展示侧: L2378 Top 30 简表后新增 Bottom 30 简表

### 4. 报告格式

```
【Stage 1: 综合因子值 Top 30 (composite 降序)】
  排名 股票代码       股票名称            综合因子值
--------------------------------------------------
   1 600598     北大荒             1.065
  ...
--------------------------------------------------

【Stage 1: 综合因子值 Bottom 30 (composite 升序)】
  排名 股票代码       股票名称            综合因子值
--------------------------------------------------
 171 603261     ...               -2.341
  ...
--------------------------------------------------
```

## Don't

- 不从 composite daily parquet 直接读取 Bottom 30 (跨模块数据依赖, 违反模块边界)
- 不修改 Parquet schema (stage 字段 int8 已支持 4)

## Why

- Parquet 选股历史是 summary 的标准数据源 (AGENTS.md 跨模块数据路径表)
- stage=4 复用现有 schema, 向后兼容 (旧报告代码 `df[df["stage"]==1]` 不受影响)

## When

- 两阶段选股启用时 (enable_two_stage=True)
- 单阶段模式时 stage1_bottom 为空, 报告跳过 Bottom 30 展示

## 影响范围

- □ 短名单 (30~50) ← 不影响
- □ 最终持仓 (3~5) ← 不影响
- □ Layer 1 候选池 (549) ← 不影响
- 仅展示层增强, 不改变选股逻辑

## 文件改动

| 文件 | 改动 |
|------|------|
| stock_selector.py | 新增 stage1_bottom_snapshot + write_selection_history 参数 |
| generate_factor_summary_report.py | 读取 stage=4 + 展示 Bottom 30 |
