---
name: factor-summary-reporting
description: Summary 报告数据完整性、基础数据源新鲜度、run_pipeline 产物审计、跨节一致性核对。
version: 1.0
---

# factor-summary-reporting

> 自包含方法论要点。触发后按本文件诊断。

## Trigger
- `run_pipeline` 后 `summary/result/factor_summary_report_*.txt` 异常/缺失/误报
- 某 fetch 产物没出现在报告第零部分【基础数据源】
- 修 `summary/report/freshness_check.py::DATA_CHECK_SOURCES`
- 核对基础数据源新鲜度（factor_ic_data / factor_data / turnover / tail_trading / market_cap）
- 新增 `fetch_*.py` 后检查是否注册到 `DATA_CHECK_SOURCES`（新 fetcher 不会自动出现在第零部分）
- "run_pipeline 跑到哪一步 / 是否后台执行 / 从 stage N 起后台启动"
- "§9 §10 空白" -> weight_method 切换断层（加载 `/factor-ic-analyzer-workflow` §4）
- "开盘怎么卖 / §10 操作" -> 加载 `/intraday-strategy-design`

## Mandatory project gate
1. 读 CLAUDE.md（已含精华指针 §1.5）
2. 查 `.codegraph/codegraph.db`（`codegraph callers <symbol>`，db 用 `nodes` 表 + `kind` 字段；新鲜度查 `SELECT datetime(MAX(indexed_at)/1000,'unixepoch','+8 hours') FROM files;`）
3. 2+ 文件改动先写 `designs/<topic>_design.md`

## Core model：第零部分 vs 报告正文
- **第零部分【基础数据源】** 来自 `freshness_check.py::DATA_CHECK_SOURCES` + `check_data_freshness()`
- **正文** IC/回测/综合因子来自 `factor_ic/result/`、`backtest/result/`、`comprehensive_factor/result/` 衍生产物
- 某因子出现在正文 ≠ 其上游原始数据源已配置进第零部分

## Known issues 路由（命中按要点诊断）
| # | Issue | 要点 |
|---|---|---|
| 1 | 重复 IC 结果文件致因子定义缺失 | 双 `get_ic_output_path()` 命名不一致 |
| 4 | 权重查找双键不匹配 | 静态权重键=列名，动态键=因子名；查找处加回退 `weights.get(col, weights.get(name, 0))` |
| 5 | 覆盖率计算 Bug | 同 #4 双键根因 |
| 12 | 振幅过滤静默跳过 | filter 依赖列(amplitude)未加载；**过滤器依赖列必须显式加载** |
| 16 | backtest 文件名正则不匹配 | 因子名应从 JSON 内部字段读，不从文件名提取 |
| 21 | **⚠️ UNFIXED**：`forward_return_1d` T+1 错位 | `pl_ratio_db.py:148-160` + `generate_factor_summary_report.py:670-676` 从 `trade_date` 行读，取到 T+1->T+2 收益。S13 +28% 实际 -24.9%。验证：取一只股用 close 手算 `(close[D+1]-close[D])/close[D]` 对比存储值 |
| 22 | 期望日期基准错位 | `actual` 新于 `expected`（超前）被判延迟；`segment_win_rates` 落后 2-3 交易日是 T+1 闭环物理必然 |

## Audit workflow：跨节一致性核对（迭代审查）
用户要"请再次看一下报告"时，每轮完整读 + 逐节交叉核对直到零问题（3-5 轮）：
- §1(IC 表) = §2(回测表) 因子数相同
- §3 相关性矩阵 = §4 筛选 = §8 选股 选中因子相同
- §5 `format_weights` = §4/§6 `:.1f` 同因子同权重
- §5 权重和 ≈ 100%
- 剔除运算符 `|ICIR|=X<X` 非 `X=X`（除非真相等）
- 叙述声称"接近1.0"的维度实际得分 ≥ 0.9
- `excluded_by_amplitude==0` 时查 Top N 有无一字板（amplitude=0%）
- 维度感知：跨维度高相关标"保留"，同维度为空（已去重）
- 选股过滤不可交易但 IC/回测不过滤 = 方法论不一致（涨停买不进排除，跌停可买不排除）
- §9 与 §10 同分段体系标签一致（统一 S 系列）

## 技巧
- **JSON 产物直接补丁**（pipeline 重跑过慢时）：`composite_*_1d.json` 和报告 txt 在 `.gitignore`。修显示文本可直接 python 补丁 JSON 后只重跑报告生成(<1s)；**影响数值计算必须重跑 pipeline**
- **大 JSON 流式**：`factor_ic_data` 不可 `json.load` 全量（OOM exit 137）。用 `load_factor_values(factor_cols=[...])` 流式（峰值 ~175MB）

## 验证命令
```bash
pytest summary/test_cases/test_generate_factor_summary_report.py -q
ruff check --fix summary/report/ && ruff format summary/report/ && ruff check summary/report/
```

## Documentation sync
改 `DATA_CHECK_SOURCES` 必同步：`summary/MODULE.md` 基础数据源表 + `summary/docs/generate_factor_summary_report_flow.md` + 涉及 2+ 文件则 `designs/<topic>_design.md`。

## 不要做的事
- ❌ 用户报 silent fallback 立刻怀疑 join 语义（**先查数据源完整性**）
- ❌ 把诊断案例塞进 SKILL.md（在 design.md / 代码注释里）
