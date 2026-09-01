# PROJECT.md - Factor IC Analyzer

量化因子 IC 分析系统项目级规范。

**命名风格说明**：项目对外名称使用 Title Case（Factor IC Analyzer），文件系统路径使用 snake_case（factor_ic_analyzer/），章节标题使用中文不受此约束。两者风格差异为设计意图。

---

## 文档架构与加载关系（CLAUDE.md -> PROJECT.md / MODULE.md）[reference]

> AGENTS.md 已退役（见 `designs/retire_agents_md_gateway_design.md`）。现两层架构：CLAUDE.md 自动加载（瘦路由 + 精华指针）指向 PROJECT.md / MODULE.md 真源全文。

| 文档 | 加载方式 | 内容定位 | 何时读取 |
|------|----------|----------|----------|
| CLAUDE.md | 每会话自动注入上下文 | 路由入口 + 精华指针（§1.5）+ 硬规则编号速查 + skill 路由表 | 每次对话自动加载 |
| PROJECT.md | 按需主动读取 | 详细参考、背景说明、完整规范（本文件） | 下列触发条件 |
| `<模块>/MODULE.md` | 按需主动读取 | 模块内规范 | 改该模块代码前必读 |

**必须主动读取 PROJECT.md 的触发条件（任一命中即触发）：**

| 触发场景 | 判定标准 |
|---------|---------|
| 新增模块 | 在 `factor_ic_analyzer/` 下新建顶级业务目录（与 factor_ic/ 同级） |
| 新增脚本类型 | 在 `scripts/` 下新建 `check_*.py` 或 `validate_*.py` |
| 修改跨模块数据契约 | 修改 `paths.py`、任一 `schemas/*.schema.json`、或被 2+ 模块读取的产物文件名/字段 |
| 涉及数据契约 / 路径 / 输出结构讨论 | 由 AI 根据语义判定（不依赖字面关键词匹配） |
| 涉及 2+ 文件改动 | 需写 design.md（dl-workflow 驱动改动豁免，见 Design-First 流程） |

---

## AI 协作模式 [stable]

**本规范由 AI 智能体执行。本节定义智能体在任务全周期中的行为，避免不同智能体 / 不同会话间行为不一致。**

**harness 中立约定**：本规范不绑定任何特定智能体平台（Claude Code / OpenClaude / Cursor / Cline / 自研框架均可）。本节描述的"加载文件、调用工具、与用户交互"均为通用语义，不依赖具体平台的专属功能（如特定的 hook 系统、内置 skill、自动化记忆等）。若某条流程在特定 harness 下不可直接执行，由智能体在保持等价语义的前提下用平台可用的能力实现。

### 任务启动 checklist（每次新任务必跑）

1. CLAUDE.md 已自动加载（含精华指针 §1.5 + 硬规则速查）；命中触发读 PROJECT.md
2. 判断本任务是否命中"主动读取 PROJECT.md 的触发条件"，命中则读本文件
3. 列出本任务预计触及的 H 规则编号（用于 PR 模板取证）
4. 判断是否触发 Design-First（2+ 文件且非 dl-workflow 驱动改动）→ 若是，先写 design.md 并停下等审核

### 何时必须停下问用户（不要自行决策）

| 场景 | 行为 |
|------|------|
| 任务粒度超 H9 阈值（>3 文件 或 >200 行） | 停下问用户："是否拆分 / 走 Design-First / 申请豁免" |
| 检查脚本不存在或执行失败 | 停下问用户："脚本是否待实施？是否绕过？" |
| 规则之间发生冲突 | 按"规则冲突仲裁"节判断，无法判定则停下问用户 |
| 涉及破坏性操作（删除文件、修改 paths.py、改 schema） | 列出影响范围，等用户确认 |
| 任务描述与现有规范冲突 | 停下问用户："以规范为准还是以本次需求为准" |

### 工具缺失时的兜底

- 若某条 H 规则的检查脚本（如 `scripts/check_*.py`）尚未实现：
  - 不可假装已通过检查
  - 应在 PR 描述中显式标注"H? 检查脚本待实施，本次依赖人工 review"
  - 不可作为取证依据（同 [待实施] 规则）

### 自检流程（提交前）

- 列出本次触及的所有规则编号 → 逐条对照
- 跑一次本地 pre-commit → 若失败，先修复再继续，不可 `--no-verify`
- 在 PR 描述中按"PR 模板必填字段"格式填写规范引用

### Pipeline 长任务执行约定 [stable]

**规则**: pipeline 整体运行（`run_pipeline.py`）或单条时间递减管线是长任务（15-30 分钟），一律走后台执行（`background=true + notify_on_complete=true`），不实施实时监控轮询。

| 正确 | 错误 |
|------|------|
| 启动后台 → 等通知 → 收结果 | 启动前台 → 阻塞等待 → 浪费时间 |
| `process(action='wait')` 偶尔用 | 频繁 `process(action='poll')` 轮询 |
| `--start-stage N` 并说明为何选 N | 盲跑全 Stage 不说明 |

**禁止行为**：
- ❌ 禁止 `| tail` 或 pipe 到其他命令（SIGPIPE 杀进程，exit code=0 误判成功）
- ❌ 禁止用 watch/while 循环轮询进程状态
- ❌ 被问及进度时只读当前日志、报 PID，**禁止 kill 正在运行的 pipeline**

**Why**（历史教训）:
> 2026-06-26 pipeline 输出经 `| tail -20` 导致 SIGPIPE 提前终止进程，但 exit code=0，agent 误判 pipeline 全部成功。见 factor-development skill ref `sigpipe-pipeline-truncation.md`。

---

## 战略目标：量化辅助 + 人工决断 [stable]

**What**: 项目的最终产出是**一个高质量的短名单（30~50 只）**，而非一个机械的"Top N 选股结果"。短名单由量化 pipeline 生成，最终选股（3~5 只）由用户人工决断。

这个约定永久约束所有后续方案、设计、代码改动和报告形态。

**How**:

```mermaid
flowchart LR
    A[量化全市场 5000+ 只] --> B[Layer 1 候选池 549 只]
    B --> C[Stage 1<br>composite 排序]
    C --> D["短名单 30~50 只<br>（量化输出）"]
    D --> E[人工决断<br>看公告/新闻/财报]
    E --> F[持仓 3~5 只]
    style D fill:#4a6fa5,color:#fff
    style E fill:#e87d3e,color:#fff
```

| 环节 | 谁负责 | 产出的形式 |
|------|--------|-----------|
| 全市场筛选 → Layer 1 | 量化 | 5 层分层回测 + IC 评估 |
| Layer 1 → 短名单 30~50 | 量化 | composite_factor 排序 + 风格分散化 |
| **短名单 → 持仓 3~5** | **人** | **看公告/新闻/财报后手动挑选** |
| 最终持仓 3~5 只反馈 | 人 → 量化 | 在 summary 报告中标注"用户选中/未选/表现" |

**Don't**:

- ❌ 不要设计"从 5000 只直接选 3~5 只"的纯量化方案——这没有统计支撑
- ❌ 不要用 N=10 作为"默认 Top N 参数"来评估方案——N=3~5 才是真实约束
- ❌ 不要假设分层回测 Layer 1 的 % 年化收益直接等于 Top 3~5 的期望收益——它们之间隔着"极端尾部信号失效"的断层

**Why**（历史教训）:

> 2026-06-23 用户透露真实资金体量只能买 3~5 只。此前所有方案讨论（R4-α 二段筛选、R3 阈值收紧、Top N 历史回测、路线 A/B/C 组合优化）均默认 N≥10 甚至 N=30+，属于**目标错位**——写再多代码也不会解决"Top 3~5 与分层回测不一致"的问题，因为这个不一致是 N=3~5 下的数学必然，不是工程可修复的。

**第一性原理依据**:

1. **N=3~5 在量化选股理论中没有地位**（Barra/均值方差/Black-Litterman/Stat-Arb 的最小持仓都在 30+），任何试图用纯量化方法从 5000→3~5 的设计都在逆数学
2. **人脑擅长"非结构化信息处理"**（公告语气/新闻情绪/财报中的定性披露），这不因子化，但直接决定股价的短中期走势
3. **量化擅长"降维"**（5000→50），不擅长"精挑"（50→3~5）。降维有统计支撑（IC/分层回测），精挑没有

**When**:

| 触发场景 | 行为 |
|---------|------|
| 设计新的选股/排序/过滤方案 | 必须说明方案影响"短名单（30~50）"还是"最终持仓（3~5）" |
| 修改 stock_selector 的输出 N | 短名单 N=30~50 由量化负责；最终 N=3~5 只做人工决断参考 |
| 评估 backtest 年化收益 | 只做 Layer 1 整体的评估；不做 Top 3~5 的 backtest（样本不足） |
| 讨论"阴跌问题" | 先区分：是短名单 30~50 里阴跌偏多（量化问题）还是最终 3~5 里阴跌（选股问题+量化问题双因） |
| 写 summary 报告 | 短名单部分展示量化结果，最终选股留空标注"待人工决断" |

**Examples**:

```markdown
# ✓ 正确的方案描述
"Stage 1 composite 排序 → 短名单 50 只（量化输出，附带因子暴露雷达图 + 风格标签）"
"最终持仓 3~5 只由用户在短名单内参考公告/新闻精选"

# ✗ 错误的方案描述
"Top 3 选股：...layer backtest 年化 24.3%..."
（用 Layer 1 年化替代表 Top 3 表现 = 欺骗性指标）
```

**Verify**:

- 任何新方案的设计.md 必须显式标注"对短名单（30~50）的影响" vs "对最终持仓（3~5）的影响"
- 项目 CI 不强制"最终 N"按名单运作；不做名义上的冻结，靠规范约定

---

## 数据驱动原则：禁止给系统贴叙事标签 [stable]

**What**: 系统的方向、风格、属性完全由**实证数据**（IC、分层回测、因子方向）客观决定，不由用户或设计者**预设**。任何对系统贴"弱势反转 / 趋势跟随 / 反弹捕获 / 价值挖掘"等**主观叙事标签**的描述都是错误的。

**How**:

| 错误（叙事标签） | 正确（数据描述） |
|------|------|
| "我们做弱势反转策略" | "当前 composite 方向 = negative（ic_mean 多数为负），Layer 1 = composite 最负的 549 只，分层回测年化 +24.3%" |
| "改成趋势跟随策略" | "尝试 factor_direction='positive'，需要重跑分层回测验证 Layer 1（最正）的年化收益是否为正" |
| "选股逻辑应该选反弹股" | "Layer 1 子样本里 5d>3% 反弹率 = 14.0%（实证），高于 / 低于市场基线？" |
| "我们的风格是动量" | "RSI/momentum 因子 IC 为正/负？权重占比多少？这才是系统的真实方向" |

**Don't**:

- ❌ 用"弱势反转""趋势跟随""价值投资""动量"等量化策略叙事标签描述系统
- ❌ 假设用户选定了某种"策略风格"——用户**没有**也**不应该**选定风格
- ❌ 在方案讨论中说"这违反/符合 XX 风格"——风格本身是因变量，方案合理性看实证
- ❌ 在 PR / commit / 报告中给系统贴叙事标签

**Why**（历史教训）:

> 2026-06-23 AI 多次在方案讨论中说"当前是弱势反转策略"，用户纠正："**我从来没说过我们系统是弱势反转风格，是因子跑出来的结果，我不决定系统是什么风格，一切遵照跑出来的真实数据客观决定。**"
>
> 教训：AI 把"因子方向多数为 negative + Layer 1 选 composite 最负"这个**实证现象**反向包装为"用户选择了弱势反转策略"这个**叙事标签**，然后基于这个标签去推方案（如"建议改趋势跟随"），形成**虚构因果链**。

**第一性原理依据**:

1. 量化策略的"风格"是**因子方向 + 加权 + Layer 选择**的**涌现结果**，不是设计输入
2. 因子方向（ic_mean 正负）由市场数据决定，不由设计者决定
3. 任何"建议换风格"的方案，必须基于**重新实证**（重跑 IC + 分层回测），而非基于"风格切换"的叙事

**When**:

| 触发场景 | 行为 |
|---------|------|
| 描述系统当前行为 | **必须**用实证数据（IC 值、Layer 收益、因子方向、反弹率），禁用叙事标签 |
| 提案新方向 | **必须**说"需要重新实证 XX 因子的 IC / 分层回测，验证是否值得做"，禁说"建议改成 XX 策略" |
| 解释 Top N 表现 | **必须**追溯到具体的因子值、composite 排序、子样本统计，禁说"因为我们做的是 XX 风格所以..." |
| 在 design.md 中描述系统 | **必须**用"实证: composite_factor 方向 = negative，Layer 1..5 单调性 ✓"等数据陈述 |

**Examples**:

```markdown
# ✓ 正确的方案陈述
"实证数据：interaction_bollinger 全样本 IC=-0.003（无信号），在 Layer 1 子样本 cond_IC=+0.040（15.4x 放大且符号翻转）。
建议：基于这个数据，stage_2 重排可能有边际改善，但 30 日测试期反弹率仅从 14.0% → 17.2%，不足以支撑'人工决断'目标。"

# ✗ 错误的方案陈述
"当前系统是弱势反转策略，无法识别反弹股，建议改成趋势跟随。"
（贴标签 + 推断因果 + 提建议，全部基于虚构叙事）
```

**Verify**:

- 在 design.md / commit / 报告 / 对话中搜关键词 "策略风格 | 弱势反转 | 趋势跟随 | 反弹捕获 | 价值投资"：除非引用历史错误对照（如本节 Why），否则**全部应替换为实证数据描述**
- AI 在做方向性建议时，必须先展示**实证数据**，再下结论；不允许"概念先行，数据补证"

---

## 实战交易规则：T 日尾盘买入 T+1 日卖出 [stable]

**What**: 项目的实战交易模型是**单日持仓**（1 日持有期）：

```
T-1 日收盘后:   data_fetchers 拉数据
T 日 09:25:    pipeline 计算 composite_factor + 短名单
T 日 14:50+:   用户在尾盘 (~14:55) 买入选中的 3~5 只
T+1 日:        卖出（可能开盘 / 盘中 / 收盘）
```

**这意味着评估指标只能是 1 日收益（`forward_return_1d`），不能用 5d / 10d。**

### 核心数据契约（T+1 日期语义 · 唯一权威定义）

> **本节是全系统最重要的日期语义定义，所有"数据是否最新/是否延迟"的判断都以此为准。**
> 其它文档（CLAUDE.md §1.5 / intraday-strategy-design skill / MEMORY）只放指针，不重复本节内容——避免多份拷贝漂移。

**What**: 各数据文件的 `selection_date` / 日期字段在"报告日 R 清晨生成报告"这一流程下的语义与**应有最新日期**。

**核心等式**（R = 报告日，`prev_td(X)` = X 的上一个交易日，跳过周末，不处理法定节假日）：

```
selection_date = T-1 数据日  = prev_td(R)          # = master parquet 最大日期
trade_date     = T 买入日    = R 若是交易日否则下一交易日
持有收益       = forward_return_1d[trade_date]     # T 收盘 → T+1 收盘
```

**各数据文件应有最新日期**（报告日 R 清晨拉 prev_td(R) 数据计算）：

| 数据文件 | 关键日期字段 | 应有最新日期 | 原因（Why） |
|---|---|---|---|
| `factor_ic_data`（master） | `date` | `prev_td(R)` | T-1 数据已拉取到位 |
| `segment_stock_details.parquet` | `selection_date` | `prev_td(R)` | T 日写入，**不等收益**（`segment_win_db.py:64`） |
| `segment_win_rates.parquet` | `selection_date` | `prev_td(prev_td(R))` | 收益需 **T+1 闭环**才可算胜率：0715推荐→0716尾盘买→0717尾盘卖→0717后才可写 0715 胜率 |
| `ic_results`（衍生） | `date` | `prev_td(prev_td(R))` | IC 需次日收益（`forward_return_1d`），最新只能算到 T-2 |

**实例**（R = 2026-07-18 周六，prev_td = 07-17 周五）：

- master 到 **07-17** ✓ 正常
- segment_stock_details 到 **07-17** ✓ 正常（T 日写入）
- segment_win_rates 到 **07-15** ✓ 正常（0716/0717 推荐收益尚未闭环，**不是延迟**）
- ic_results 到 **07-16** ✓ 正常（需次日收益）

**Don't**:

- ❌ 把 `selection_date` 当成"T 日"再往前推一天算期望——这会让期望比应有值早一天，把"已到位"误判为"延迟"（2026-07-19 freshness「△延迟」误报根因）
- ❌ 把 segment_win_rates 只到 `prev_td(prev_td(R))` 当成延迟——那是 T+1 收益闭环的物理必然
- ❌ 用 `actual != expected` 判延迟却不区分"落后"与"超前"——数据超前于期望不是延迟
- ❌ 在 CLAUDE.md / skill / MEMORY 里重复本表全文——只放指针，改时只改本节

**Why（历史教训）**:

> 2026-07-19 freshness 检查把 5 个基础数据源（实际 07-17）+ ic_results（实际 07-16）全部标「△延迟」。
> 真相：`check_data_freshness(selection_date)` 把 `selection_date`(=07-17, T-1 数据日) 当作"T"再 `prev_td` 一天 → 期望 07-16，
> 比本契约的应有值（07-17）早一天 → 全部误报。agent 当时未对齐本契约，凭代码字面 `!=` 判延迟，得出错误结论。
>
> 同类先例：S13「-24.9%」假结论（实为 +28.0%）——也是未验证 producer 日期语义直接判错位。
>
> 教训：**判任何"日期是否最新/是否延迟"前，必须先对齐本契约的日期语义，不能只看代码字面比较。**

**Verify**: 改契约只改本节；其它处发现契约全文拷贝 = 漂移，应改为指针。判断 freshness 类问题前 grep 本节确认语义。

**How**（落地）:

| 评估指标 | 用途 | 数据列 |
|---------|------|--------|
| **`forward_return_1d`** | ✅ **真实持仓收益**（T → T+1 收盘价收益） | factor_ic_data.parquet 已有 |
| `forward_return_3d` / `5d` / `10d` | 仅用于因子稳定性研究，**不代表实战收益** | factor_ic_data.parquet 已有 |

**Don't**:

- ❌ 用 5d / 10d 收益评估 Top N 实战表现——持仓周期不匹配
- ❌ 用 5d / 10d 反弹率（>3%）作为"短名单质量"的指标——人买入次日就卖出，5 日后的事与本次交易无关
- ❌ 用 Layer 1 分层回测的年化收益直接估计"实战年化"——分层回测内部假设 549 只等权日内调仓，与 N=3~5 集中投注的统计性质完全不同
- ❌ 评估 R3 阴跌过滤时用 "5d return < -10%" 作为门槛——这是**回看 5 日**，与 T+1 卖出场景脱节

**Why**（历史教训）:

> 2026-06-23 在讨论"为什么 Top 10 选股 5d 收益 -5.2%"时，多轮分析、设计、实证全部使用 5d 收益作为评估口径。R4-α 二段筛选实证报告也用 5d 反弹率。
>
> 用户纠正："**我们的系统是 T 日生成 T-1 数据，T 日尾盘买入 T+1 日卖出，这个规则你忘了吧？**"
>
> 重新用 1d 收益评估同一份数据，结论完全变了：
> - Top 10 在最近 30 日的**单日平均收益 = -0.41%**
> - 单日均值为正的天数仅 34.5%
> - 含交易成本后期望值更负
>
> 教训：用错评估口径 = 在错误的指标上做了所有优化决策。R4-α 修复的"5d 平均 -5.2%"本身就是**与持仓周期脱节的指标**，不论是否修复都对实战无意义。

**第一性原理依据**:

1. 评估口径必须与决策口径**严格对齐**（详见数据驱动原则）
2. 持仓 1 日 → 评估窗口 = 1 日 → 用 `forward_return_1d`
3. 因子 IC 评估在多周期下是**合理的**（看因子稳定性），但**选股性能评估**只能用对应持仓周期

**When**:

| 场景 | 评估指标 |
|------|---------|
| 因子 IC / ICIR 计算 | 多周期都跑（1d/3d/5d/10d），看稳定性 |
| 分层回测 | 多周期都跑，看 Layer 单调性在不同周期下的鲁棒性 |
| **短名单质量评估** | **只用 1d**（持仓周期对齐） |
| **Top N 实战表现评估** | **只用 1d**（含交易成本扣减） |
| **stock_selector 优化目标** | **1d 平均收益 - 0.1% 成本** |

**Examples**:

```python
# ✓ 正确的评估指标
top_n_daily_return = top_n_picks['forward_return_1d'].mean()  # T+1 真实收益
top_n_after_cost = top_n_daily_return - 0.001  # 扣 0.1% 双边交易成本

# ✗ 错误的评估指标
top_n_5d_rebound = (top_n_picks['forward_return_5d'] > 0.03).mean()  # 与持仓脱节
# 这只反映"如果持有 5 日有多大概率反弹 >3%"，但实际持仓 1 日就卖出了
```

**Verify**:

- 任何新方案的 design.md / 实证脚本，必须在"评估指标"章节显式声明**用的是 forward_return_1d**
- summary 报告的"短名单/Top N"章节必须展示 **1d 平均收益 - 交易成本**作为预期值
- grep 检查 `forward_return_5d|forward_return_10d` 在 stock_selector / summary 模块的使用，确认不是用于"实战收益估计"

---

## 目录结构 [reference]

```
factor_ic_analyzer/
├── factor_ic/              # IC 计算模块
├── backtest/               # 分层回测模块
├── comprehensive_factor/   # 综合因子模块
├── data_fetchers/          # 数据获取模块
├── summary/                # 数据汇总模块
├── reverse_discovery/      # 逆向因子发现模块（experimental，2026-06-18 新增）
├── web_ui/                 # 前端展示模块（experimental，2026-07-04 新增）—— 复用 summary/report/data_loaders.py
├── scripts/                # 自动化检查脚本
├── tests/integration/      # 跨模块集成测试
├── designs/                # design.md 存放目录
├── pipelines/              # 多管线配置目录（2026-06-26 新增）
│   └── pipelines.yaml      # 管线别名 → filter 定义
├── pipeline_context.py     # 管线上下文（别名解析、配置加载）[2026-06-26 新增]
├── pipeline_data_slicer.py # Stage 1.5 数据切割器 [2026-06-26 新增]
├── paths.py                # 跨模块路径单一来源（含 PIPELINE_ALIAS 动态解析）[2026-06-26 改造]
├── temporary/              # 临时文件目录
├── pyproject.toml          # 项目配置（ruff/pytest/import-linter）
└── PROJECT.md              # 本文件
```

> ⚠️ **多管线目录层级**：各模块的 `result/` 和 `logs/` 下按管线别名分目录，详见"多管线架构"章节。

**业务模块统一约定**：每个业务模块（factor_ic / backtest / comprehensive_factor / data_fetchers / summary / reverse_discovery）必须包含：
- `test_cases/` —— 单元测试
- `schemas/` —— JSON Schema 校验文件
- 产物输出到 `result/`（见 H2）

**⚠️ 前端模块豁免条款**（适用于 `web_ui/`，2026-07-04 起）：
- **定位**：web_ui 是 summary 的"前端分支"——复用 `summary/report/data_loaders.py` 读取数据，用 Jinja2 模板渲染 HTML，与 summary 的 txt 输出共用数据契约
- 无 `schemas/` —— 前端无 JSON Schema 校验概念
- 无 `result/` —— 前端不直接产生 Python 业务产物（产物由 Python 业务模块生成后由前端消费）
- H1（common/ 复用）**不适用** —— web_ui 不定义自己的 common/
- H2（输出位置）**不适用** —— 前端不写业务 result/
- H3（临时文件）**适用** —— 前端调试仍走 `temporary/`
- H7（路径导入）**部分适用** —— 内部 Python 模块用 `from paths import`，**不**直接拼路径
- H11（日志格式）**部分适用** —— Python 端遵守 % 惰性格式化（与 summary 一致）
- **适用**：H8（Design-First）/ H9（任务粒度 ≤3 文件 ≤200 行）/ H10（测试覆盖率）/ H12（退出码语义）/ H13（死代码禁止）
- 数据契约铁律：**禁止 web_ui 直接读 Parquet/JSON**——必须经 `summary/report/data_loaders.py` 加载；summary 改 schema 时 web_ui 自动同步

**⚠️ paths.py 导入路径待确认**：
- 当前 H7 要求 `from paths import`，但 `paths.py` 位于 `factor_ic_analyzer/paths.py`，且 `pyproject.toml` 包名为 `factor_ic_analyzer`。
- `pip install -e .` 之后，顶层 `paths` 模块不在 site-packages 中，正确导入应为 `from factor_ic_analyzer.paths import ...`。
- **请验证**：当前代码库实际能 work 的导入语句是哪一种？确认后更新 H7 与 `scripts/check_path_import.py`。

**安装方式**：`pip install -e .`（需要 pyproject.toml 中的 `[project]` 配置）

**pyproject.toml [project] 最小配置示例**：
```toml
[project]
name = "factor_ic_analyzer"
version = "0.1.0"
dependencies = [
    "pandas>=2.0",
    "numpy>=1.24",
    "pytest>=7.0",
    "pytest-cov>=4.0",
    "ruff>=0.1.0",
    "import-linter>=1.0",
]
```

---

## Design-First 流程 [experimental]

**涉及 2 个以上文件的改动必须先提交 design.md 通过审核才能动手。**

**分流（2026-09-01 用户决议）**：dl-workflow 驱动的改动（`wf/*` 分支）**豁免**本流程——
dl-workflow 的 evidence 链 + 读回裁决 + 机械门已是 Design-First 等价物，且其 design.md
装配已退役（见 `~/.dl-workflow/designs/design-md-assembly-retire-design.md`）。
非工作流改动（手动/临时会话）仍须遵守本流程。

**目的**：避免边写边改、推倒重来。让用户在动笔前对齐方案，减少返工。

```
设计阶段：
□ 在 designs/ 目录创建 design.md（改哪些文件、改哪些接口、加哪些测试）
□ 用户审核通过
□ 才能动手写代码

违反此规则 = 直接退回，不 review。
```

**design.md 文件名映射规则（明确化）**：
- 取 PR 分支名，做以下转换：
  1. 所有 `/` 替换为 `_`
  2. 所有 `-` 替换为 `_`
  3. 转小写
- 示例：
  - `feat/add-cache` → `designs/feat_add_cache.md`
  - `feat/sub/cache-v2` → `designs/feat_sub_cache_v2.md`
  - `Fix-Bug-123` → `designs/fix_bug_123.md`
- PR 描述中显式引用 `designs/<文件名>.md` 也可作为匹配依据（优先级低于分支名映射）

**自动检查**：
- 脚本：`scripts/check_design_first.py`
- 检查逻辑：PR 涉及 2+ 文件改动时，仓库 designs/ 目录下必须存在对应的 design.md 文件
- 豁免：`wf/*` 分支（dl-workflow 驱动）跳过检查（脚本按分支前缀判定）
- ⚠ pre-commit 软提示未实现——`.pre-commit-config.yaml` 无此 hook，当前零强制；最终对应规则匹配在 CI 强制检查
- CI 硬关卡：PR 创建时强制检查（可访问 PR 分支名/描述），缺少匹配的 design.md 则 CI 失败
- CI 调用：`python scripts/check_design_first.py`

---

## 硬规则（违反即拒收）[stable]

**命名空间**：H 前缀 = 硬规则（自动强制执行）

| 规则编号 | 规则 | 目的 | 检查工具 | 执行阶段 |
|---|------|------|----------|----------|
| H1 | 模块边界（强约束）：① 只能复用自己目录的 `common/`；② **禁止修改其他模块目录**（web_ui/ 改 summary/ 等禁止；反之亦然）；③ 跨目录的"数据契约扩展"必须走 Design-First + 各模块 owner 确认 | 防止模块间隐式耦合；重构单模块时不会牵连其他模块；保证各模块责任清晰、可独立 review | import-linter + `scripts/check_cross_module_modify.py`（[待实施]） | pre-commit + CI |
| H1.1 | web_ui 边界（v0.4.7 起）：web_ui 目录的代码**只读**其他模块的 Python 脚本（`from summary.report.data_loaders import ...`），**禁止修改** `summary/`、`factor_ic/`、`backtest/`、`comprehensive_factor/`、`data_fetchers/`、`factor_definitions/`、`paths.py` 等任何 web_ui 目录外的文件 | web_ui 是 summary 的"前端分支"，单向依赖；改 web_ui 时不应"顺手"改后端 | 人工 review + `scripts/check_web_ui_boundary.py`（[待实施]） | pre-commit + CI |
| H2 | 输出位置：`<模块>/result/`（详见下方正反例） | 让产物可被清理/打包脚本统一处理，避免散落根目录 | AST 静态分析（`scripts/check_path_literals.py`） | pre-commit + CI |
| H3 | 临时文件：放 `temporary/` | 避免污染版本控制；统一清理入口 | AST 静态分析（`scripts/check_temp_file_path.py`） | pre-commit + CI |
| H5 | 因子方向：根据实际 IC 确定（不可硬编码方向） | 防止方向写反导致回测结论与实际相反 | pytest 断言 | CI |
| H6 | 异常链：`raise ... from e`（详见下方正反例） | 保留错误来源，调试时能追溯根因 | ruff B904 | pre-commit + CI |
| H7 | 路径导入：`from paths import`（⚠️ 见目录结构节导入说明） | 单一来源原则：路径变更只需改一处 | AST 静态分析（`scripts/check_path_import.py`） | pre-commit + CI |
| H8 | Design-First：2+ 文件需 design.md（dl-workflow 驱动改动[wf/* 分支]豁免） | 大改动先对齐再写，避免推倒重来 | CI `scripts/check_design_first.py` | CI |
| H9 | 任务粒度：≤3 文件 **AND** ≤200 行（两者都需满足，违反任一即超粒度） | 控制单次改动规模，便于 review 和回退；超粒度走 Design-First | pre-commit `scripts/check_task_size.py` | pre-commit |
| H10 | 测试覆盖率：不低于阶段性阈值（当前 60%，目标 70%） | 防止新代码无测试拉低基线 | pytest `--cov-fail-under=60`（当前阶段） | CI |
| H11 | 日志格式：% 惰性格式化（禁止 f-string / + 拼接 / `exc_info=True`） | 性能（高 verbosity 时跳过格式化）+ 风格统一 + 与标准库 logging 结构化处理器（如 JSON）兼容 | ruff G004 / G003 / G201 | pre-commit + CI |
| H12 | 退出码语义：0=成功 / 1=未预期错误（程序 bug） / 2=import-time 配置或注册失败（R16 后已弃用，改 logger.critical+raise）/ 3=辅助层失败（R17，计算成功，但日志摘要 / 监控输出 / sidecar 类组件失败）/ 4=DataSchemaError（R18，数据 schema 不匹配，需检查上游列契约）/ 5=FactorCalcError（R19，因子计算内部失败，需检查计算代码）；附 R20 = `main()` 函数体内禁 sys.exit，必须 raise 让 `__main__` 块统一处理 | CI / shell 脚本能区分 6 种状态：成功 vs 程序 bug（exit 1）vs 代码不能加载（exit 2 弃用）vs 主结果可用但旁路告警（exit 3）vs 数据 schema 失败（exit 4，检查上游）vs 因子计算失败（exit 5，检查代码）；R20 保证 main() 可被单元测试直接调用 | 人工 review + `scripts/check_exit_codes.py` | pre-commit + CI |
| H13 | 死代码禁止：禁止永不触发的防御性兜底分支（如 `if result is None` 守卫面对永不返回 None 的 callee） | 死代码掩盖真实错误来源、误导维护者、增加噪音；必须删除而非保留 | 人工 review + `scripts/check_dead_branches.py`（[待实施]） | pre-commit + CI |
| H15 | codegraph 查证：改已有 `.py` 源码前必须对该 symbol 跑 `codegraph callers`/`impact`/`affected`；跨文件调用/影响面断言必附 codegraph 输出或 `file:line` 证据 | 防止"该查没查"凭片段猜/伪造跨文件调用关系（单文件明面事实 Read 即得不在此列）；根治 spec_bridge 行 89 留的"靠自觉"口子 | PreToolUse `.claude/hooks/codegraph_gate.py` + PostToolUse 留痕 `codegraph_audit.py`（designs/codegraph_enforcement_gate_design.md） | 实时（Edit/Write 前） |

**H2 正反例**：
- ✅ 算输出（必须放 `<模块>/result/`）：分析结果 JSON、回测报告、汇总文件、对外暴露的数据产物
- ❌ 不算输出（不进 `result/`）：
  - 调试日志 → 走 stderr 或 `logger`
  - 中间缓存 → 放 `temporary/`（H3）
  - 测试夹具 → 放对应模块的 `test_cases/`

**H6 正反例**：
```python
# ❌ 反例：丢失根因
try:
    load(path)
except FileNotFoundError:
    raise RuntimeError("加载失败")  # 调试时看不到原始 FileNotFoundError

# ✅ 正例：保留链路
try:
    load(path)
except FileNotFoundError as e:
    raise RuntimeError("加载失败") from e
```

**H11 正反例**：
```python
# ❌ 反例 1：f-string（提前格式化，DEBUG 关闭时仍消耗 CPU）
logger.info(f"加载 {len(rows)} 行数据")
logger.error(f"读取失败 [{path}]: {e}")

# ❌ 反例 2：+ 拼接
logger.info("加载 " + str(len(rows)) + " 行数据")

# ❌ 反例 3：exc_info=True（应用 logger.exception 自动捕获）
logger.error("处理失败", exc_info=True)

# ✅ 正例 1：% 惰性格式化（位置参数，logger 在确认级别启用后才格式化）
logger.info("加载 %s 行数据", len(rows))
logger.error("读取失败 [%s]: %s", path, e)

# ✅ 正例 2：浮点数格式说明符
logger.info("IC 均值: %.4f, ICIR: %.2f", ic_mean, icir)

# ✅ 正例 3：异常自动捕获
try:
    process()
except Exception:
    logger.exception("处理失败")  # 自动附 traceback，等价于 error + exc_info=True

# ⚠️ 字面量 % 需转义为 %%
logger.info("Bollinger %%B 因子计算完成")
```

**H11 Why**：
- **性能**：`logger.debug(f"... {expensive_call()} ...")` 即使 DEBUG 级别关闭也会执行 `expensive_call()`；惰性格式化由 logger 内部判断级别后才格式化，跳过被禁用的级别开销
- **结构化日志**：标准库 logging 把 `msg` 和 `args` 分别保留在 `LogRecord` 上，下游 JSON Handler / 日志聚合系统可基于模板 + 参数做模板分组、参数提取；f-string 让模板和参数永久合并，丢失结构化能力
- **风格统一**：项目已统一为 % 风格（factor_ic/ 39 文件 219 处全清），新代码必须保持一致

**H11 Verify**：
```bash
ruff check --select G factor_ic/
# 期望：All checks passed!
```

**H11 当前覆盖范围**：
- ✅ 已强制：`factor_ic/`（含 31 个 ic_*.py + 8 个 common/*.py）
- ⏳ 迁移中（per-file-ignores 暂放行）：`backtest/`、`comprehensive_factor/`、`data_fetchers/`、`summary/`、`temporary/`、`run_pipeline.py`、`factor_definitions.py`
- 迁移路径：每模块完成后从 `pyproject.toml [tool.ruff.lint.per-file-ignores]` 中移除该模块的放行项

**硬规则补充注释**：
- H1：`factor_ic` 只能复用 `factor_ic/common/`，禁止复用 `backtest/common/` 等
- H7：路径常量清单详见"附录：路径常量清单"
- H8：详见"Design-First 流程"章节
- H9：超粒度时不可强拆为多次 commit 绕过，必须走 Design-First 走审核
- H10：阶段计划与设定依据见"测试覆盖规范"章节
- H11：当前仅 `factor_ic/` 强制；其他模块在 `pyproject.toml [tool.ruff.lint.per-file-ignores]` 中暂放行，迁移完成后逐步移除
- H15：弱门禁边界--挡"零 codegraph 查询就改源码"，不挡"查错 symbol"（靠断言附证据 + commit 取证补缝）；白名单跳过非 .py / test_*.py / 新建文件 / scripts/check_*.py；索引超 72h 只警告不阻断；详见 designs/codegraph_enforcement_gate_design.md

**H12 正反例**：
```python
# ❌ 反例 1：所有失败统一 exit 1（无法区分代码 bug vs 运行时错误）
if __name__ == "__main__":
    try:
        SPEC = register_factor(...)  # import-time 注册失败也是 exit 1
        main()                        # 运行时数据缺失也是 exit 1
    except Exception:
        sys.exit(1)

# ❌ 反例 2：用 exit 0 表示"虽然失败但不影响"（CI 无法感知）
if not data_available:
    logger.warning("数据缺失，跳过")
    sys.exit(0)

# ❌ 反例 3（R16 修正）：模块顶层 except 直接 sys.exit(2)
# 该写法被 importlib.import_module 调用时会杀掉宿主进程（如 pytest 扫描注册）
try:
    SPEC = register_factor(...)
except (ValueError, TypeError):
    sys.exit(2)  # 杀掉 pytest 进程！

# ❌ 反例 4（R17 修正）：辅助层（日志摘要 / 监控）异常被静默吞掉
# 因子计算成功 → result 已生成；摘要层抛异常 → logger 后无 sys.exit
# 后果：进程以 exit 0 退出，CI / 调度器把"摘要层失败"当成"完全成功"，告警丢失
def main():
    result = run_factor_ic(spec=SPEC, ...)
    try:
        log_factor_summary(result, "xxx 因子", logger)
    except Exception:
        logger.exception("摘要输出失败")
        # ❌ 缺少 sys.exit(3)：进程仍以 exit 0 退出，调用方无感知
        # 修复：补 sys.exit(3) 用辅助层退出码语义化告警

# ✅ 正例 1：import-time 配置/注册失败 → logger.critical + raise
# （让调用方决定行为：测试可捕获/skip，CLI 由 Python 默认 traceback+exit 1）
try:
    SPEC: FactorSpec = register_factor(
        factor_name="industry_xxx",
        factor_col="industry_xxx",
        required_columns=["date", "stock_code", "industry"],
        calc_func=calculate_industry_xxx,
    )
except (ValueError, TypeError) as e:
    err_msg = str(e)[:200]  # 截断防止超长异常淹没单行日志
    logger.critical("FactorSpec 注册失败: %s (%s)", err_msg, type(e).__name__)
    raise

# ✅ 正例 2：main() 运行时错误 → exit 1
if __name__ == "__main__":
    try:
        main()
    except (DataSchemaError, FactorCalcError) as e:
        logger.error("...IC 计算失败: %s (%s)", e, type(e).__name__)
        sys.exit(1)
    except Exception:
        logger.exception("未预期的错误")
        sys.exit(1)

# ✅ 正例 3（R17）：辅助层（日志摘要 / 监控 / sidecar）失败 → exit 3
# 主结果（因子计算 result）已成功生成、产物可用，仅旁路输出失败；
# 用 exit 3 与业务失败（exit 1）区分，调度器可降级告警（产物可用，仅 sidecar 待修），
# 不与 import-time 失败（exit 2，停流水线）混淆
def main():
    result = run_factor_ic(spec=SPEC, ...)  # 主结果已生成
    try:
        log_factor_summary(result, "xxx 因子", logger)
    except Exception:
        logger.exception(
            "log_factor_summary 摘要输出阶段失败（result 已成功生成；故障源 = 摘要层）"
        )
        sys.exit(3)  # 辅助层失败专用退出码

# ✅ 正例 4（R18+R19+R20）：业务异常按"排查路径"差异化退出码 + main 内禁 sys.exit
# 调度器据 exit 码精确分流：exit 4 → 检查上游数据 / exit 5 → 检查计算代码 /
# exit 3 → 主结果可用仅降级告警 / exit 1 → 程序 bug（CRITICAL 通知）
def main(args):  # R20 拆分：parse_args 独立，main 只编排，不调 sys.exit
    result = run_factor_ic(spec=SPEC, ...)  # 抛 DataSchemaError / FactorCalcError 不捕获
    try:
        log_factor_summary(result, "xxx 因子", logger)
    except Exception as e:
        # R20: main() 内禁 sys.exit，改 raise SummaryLogError 让 __main__ 统一处理
        raise SummaryLogError("摘要日志层失败（result 已生成）") from e
    return result


if __name__ == "__main__":
    try:
        main(parse_args())
    except DataSchemaError:
        logger.exception("IC 计算失败 (数据列依赖不匹配)")
        sys.exit(4)  # R18: 数据 schema 不匹配 → 检查上游 / 列契约
    except FactorCalcError:
        logger.exception("IC 计算失败")
        sys.exit(5)  # R19: 因子计算内部失败 → 检查计算代码 / 边界条件
    except SummaryLogError:
        logger.exception("摘要日志层失败（主结果产物已生成，可用）")
        sys.exit(3)  # R17: 辅助层失败专用退出码
    except Exception:
        logger.exception("未预期的错误")
        sys.exit(1)  # 程序 bug → CRITICAL 告警
```

**H12 Why**：
- **CI / pipeline 区分能力**：exit 1 = 数据/逻辑层面业务失败（可重试、可降级）；
  exit 3 = 辅助层失败（产物可用，调度器降级告警，不阻塞下游消费方）；
  exit 0 = 完全成功
- **可观测性**：`run_pipeline.py` 等编排脚本可据 stderr+退出码决定后续动作（exit 3
  时下游可正常读 `<模块>/result/`，仅旁路监控产物缺失）
- **测试可隔离性（R16 修正）**：模块顶层 sys.exit 会被 importlib.import_module
  传染杀宿主进程；`factor_ic/common/test_factor_spec_consistency.py` 通过 importlib
  扫描所有 ic_*.py 触发 SPEC 注册，import-time exit 路径与该测试设计不兼容。
  改为 logger.critical + raise 后，测试框架可捕获 ValueError/TypeError 并合规断言/skip
- **辅助层退出码（R17 新增）**：log_factor_summary 等辅助组件抛异常时若仅 logger 不
  sys.exit，进程以 exit 0 退出，CI / 调度器无法感知"摘要层失败但计算成功"这一中间态；
  exit 3 让调度器可降级告警（产物可用，sidecar 待修），与 exit 1（业务失败应停止下游）
  和 exit 2（代码不能加载应停流水线）严格区分
- **业务异常差异化（R18+R19 新增）**：原 `except (DataSchemaError, FactorCalcError)`
  合并 exit 1 让排查路径混淆——DataSchemaError 需检查上游数据列契约（哪个 fetcher 改了
  schema），FactorCalcError 需检查计算代码（边界条件 / 算子内部）。拆为 exit 4 / exit 5 后
  调度器可精确分流：exit 4 触发 "上游数据回溯流水线"，exit 5 触发 "代码 owner 通知 + 单元测试
  扩充"，exit 1 退化为程序 bug（CRITICAL 告警立即响应）。同时 exit 1 语义从"运行时业务错误"
  收窄为"未预期错误（程序 bug）"，与 H12 Verify 的语义对齐
- **main 内禁 sys.exit（R20 新增）**：`main()` 内部直接 `sys.exit(N)` 导致单元测试无法
  调用 main 验证业务逻辑（test 进程会被杀），且退出码逻辑分散在 main + __main__ 两处难维护。
  改为 main 只 raise（含 SummaryLogError 包装辅助层异常），__main__ 块统一 except → sys.exit。
  收益：① main 可被 pytest 直接调用 ② 退出码语义集中维护 ③ 单元测试可断言异常类型而非进程退出码
- **trade-off**：放弃 import-time exit 2 / runtime exit 1 的退出码区分，
  换取 import-time 注册失败的可隔离性（CI 仍可通过 stderr 中的
  `CRITICAL ... FactorSpec 注册失败` 关键字 + traceback 区分错误来源）

**H12 Verify**：
```bash
# 检查 sys.exit 调用点是否符合语义
grep -rn "sys.exit(" factor_ic/ic_*.py
# 期望：
# - 模块顶层 try/except register_factor → logger.critical + raise（不应有 sys.exit）
# - main() 函数体内 → 不应有 sys.exit（R20，必须 raise 让 __main__ 处理）
# - __main__ 块 except DataSchemaError → sys.exit(4)（R18）
# - __main__ 块 except FactorCalcError → sys.exit(5)（R19）
# - __main__ 块 except SummaryLogError → sys.exit(3)（R17）
# - __main__ 块 except Exception → sys.exit(1)

# 自动化检查：
python scripts/check_exit_codes.py all
```

**H12 当前覆盖范围**：
- ✅ 已落地：`factor_ic/ic_industry_amplitude_trend_1d.py` / `ic_industry_earnings_growth_1d.py` / `ic_industry_momentum_5d_1d.py` / `ic_industry_turnover_trend_1d.py`
- ⏳ 待迁移：其他 `factor_ic/ic_*.py` 文件、`backtest/`、`comprehensive_factor/`、`data_fetchers/`、`summary/`
- 自动化：`scripts/check_exit_codes.py` ✅ 已交付（AST 分析，pre-commit + CI 模式，11 个 pytest 全过；R16 升级支持模块顶层"无 sys.exit + 必须 raise"模式校验）

**H13 正反例**：
```python
# ❌ 反例 1：callee 永不返回 None，caller 仍写守卫
result = run_factor_ic(...)  # 实现：失败走 build_error_result(返回 dict) 或 raise DataSchemaError
if result is None:            # 死分支，永不触发
    logger.error("run_factor_ic 返回 None")
    sys.exit(1)

# ❌ 反例 2：assert False 之后的代码
def parse(x):
    assert x > 0
    if x < 0:                 # 不可达
        return None
    return x

# ❌ 反例 3：if False 包裹的"备用方案"
if False:                     # 死代码
    use_legacy_path()
else:
    use_new_path()

# ✅ 正例 1：删除死守卫，让真实错误自然抛出
result = run_factor_ic(...)
log_factor_summary(result, "因子名", logger)  # 失败由上游 raise 触发，由 __main__ except 捕获

# ✅ 正例 2：callee 文档明确可能返回 None → 必须守卫（不是死代码）
config = load_config(path)    # 文档：找不到时返回 None
if config is None:
    logger.error("配置文件不存在: %s", path)
    sys.exit(1)

# ✅ 正例 3：第三方库返回值不确定 → 必须守卫（不是死代码）
response = requests.get(url)
if response.status_code != 200:
    raise RuntimeError(f"HTTP {response.status_code}")
```

**H13 Why**：
- **错误来源可追溯**：死代码兜底会用 generic 错误消息掩盖 callee 真实抛出的 DataSchemaError / FactorCalcError 上下文
- **维护者认知负担**：保留死分支让维护者误以为"该路径可能触发，需要思考"，实际是干扰
- **测试覆盖率假象**：死分支永远不会被测试触发，但工具不会标红，造成"覆盖率高但实际未测"假象
- **历史教训**：本次 R1-R3 把 `if result is None` 当"防御性守卫"保留，被用户纠正"应该彻底删除死代码"；R4-R6 修正

**H13 判定边界**（避免过度删除）：
- ✅ 应删：callee 实现明确"永不返回 None"（dict 失败 + raise 双路径）+ caller 仍写 `if result is None` 守卫
- ✅ 应删：`if False:` / `assert False` 之后的代码 / 不可达的 `else` 分支
- ❌ 不应删：callee 文档明确"可能返回 None"
- ❌ 不应删：callee 是 third-party 库（契约可能变化）
- ❌ 不应删：业务上可能进入但当前测试未覆盖（这是测试覆盖问题，不是死代码）
- 判定方法：必须能给出 callee 的具体行号证据（如 `factor_ic_runner.py:442` 返回 dict / `:461` raise），否则按"不应删"处理

**H13 Verify**：
```bash
# 检查 factor_ic/ic_*.py 是否仍有 None 死守卫
grep -rn "if result is None" factor_ic/ic_*.py
# 期望：零命中

# 检查不可达分支
grep -rn "assert False\|if False:" factor_ic/ comprehensive_factor/ backtest/
# 期望：零命中（除测试用例中的负向测试）
```

**H13 当前覆盖范围**：
- ✅ 已落地：4 个行业 IC 脚本（earnings_growth / momentum_5d / turnover_trend / amplitude_trend）`if result is None` 已删
- ⏳ 待审计：30 个 `factor_ic/ic_*.py` 文件已纳入 `scripts/check_dead_branches.py` allowlist 短路豁免，逐个迁移后从 allowlist 删除
- 自动化：`scripts/check_dead_branches.py` ✅ 已交付（AST + allowlist 渐进迁移，pre-commit + CI 模式，15 个 pytest 全过）

---

## 规则冲突仲裁 [stable]

**当多条规则同时触发且要求冲突时，按以下优先级判定：**

| 冲突场景 | 仲裁规则 |
|---------|---------|
| H 之间冲突 | 编号小的优先（H1 > H2 > ... > H10） |
| H vs S 冲突 | H 优先（硬规则必胜） |
| H9（粒度）vs H8（Design-First） | H8 优先：超粒度任务必须先走 Design-First，写好 design.md 通过审核后，可分批提交（每批仍受 H9 约束） |
| Hotfix 紧急通道 vs 任何 H 规则 | 无紧急通道；hotfix 也走完整流程。若用户明确声明"紧急豁免某条规则"，AI 须在 PR 描述中显著标注豁免项并 @维护者 |
| 规范未覆盖的场景 | AI 停下问用户，不自行决策 |

---

## 建议（软约束）[experimental]

**命名空间**：S 前缀 = 建议（软约束，依赖人工执行）

| 规则编号 | 建议 | 目的 | 当前状态 | 自动化计划 |
|---|------|------|----------|------------|
| S2 | 配套文件同步创建（新增 schema 时同步 test、新增 path 时同步 PROJECT.md） | 防止配套漂移 | 人工审核 | 待 PR 模板 + CI |
| S3 | 日志格式统一 | 便于日志聚合与 grep | 手动检查 | 待自定义 logger_config 模块 + AST 检查脚本 |

---

## 因子开发规范 [stable]

新增因子时必须修改的位置（按顺序执行）：

| 序号 | 文件 | 位置 | 作用 |
|------|------|------|------|
| 1 | `data_fetchers/factor_generator.py` | `_EXTENDED_FACTOR_COLS` | 数据源因子列定义 |
| 2 | `data_fetchers/factor_generator.py` | 因子计算函数 | 计算逻辑，结果存入 `factor_ic_data.parquet`（统一数据源） |
| 3 | `comprehensive_factor/common/factor_selector.py` | `FACTOR_NAME_TO_COL_MAP` | 因子名→列名映射（筛选层） |
| 4 | `comprehensive_factor/common/weight_engine.py` | `FACTOR_NAME_TO_COL_MAP` | 因子名→列名映射（权重层） |
| 5 | `factor_definitions.py`（项目根目录） | `FACTOR_DEFINITIONS` | 因子定义（名称、公式、含义），汇总报告因子说明显示 |
| 6 | `PROJECT.md` | 因子列表章节（本表） | 项目级因子清单 |

**因子分类一览**（按领域维度）：

| 分类 | 因子名 | 列名 | 公式/含义 | IC方向 |
|------|--------|------|----------|--------|
| 基础因子 | rsi | rsi_6 | RSI(6日) | 负向(反转) |
| 基础因子 | volume_ratio | volume_ratio_5 | 量比(5日) | — |
| 扩展因子 | kdj_j | kdj_j | KDJ J值 | — |
| 扩展因子 | bollinger_pb | bollinger_pb | 布林带%B | 负向(反转) |
| 扩展因子 | turnover_surge | turnover_surge | 换手率突增 | 负向(反转) |
| 扩展因子 | amplitude | amplitude | 振幅 | 负向(反转) |
| 尾盘因子 | tail_price_position | tail_price_position | 尾盘价格位置 | — |
| 尾盘因子 | tail_price_slope | tail_price_slope | 尾盘趋势斜率 | — |
| 动量因子 | momentum_strength | momentum_strength | 动量强度 | — |
| 方向性因子 | volume_price_strength | volume_price_strength | 量价齐升强度 | 待定 |
| 方向性因子 | positive_day_ratio_5 | positive_day_ratio_5 | 近5日阳线比例 | 待定 |
| 方向性因子 | ma5_deviation | ma5_deviation | 5日均线偏离度 | 待定 |
| 方向性因子 | near_high_ratio_5 | near_high_ratio_5 | 近5日高低位置 | 待定 |
| **行业方向性因子** | **industry_momentum_5d** | **industry_momentum_5d** | **行业5日动量：按(行业,日期)分组→mean(past_return_1d)→5日滚动均值，实测IC=+0.026** | **正向(行业趋势)** |
| **行业方向性因子** | **industry_turnover_trend** | **industry_turnover_trend** | **行业换手率趋势：turnover_avg(t)/turnover_avg(t-1)-1，clip(lower=0.001)** | **待定** |
| **行业方向性因子** | **industry_amplitude_trend** | **industry_amplitude_trend** | **行业振幅趋势：amplitude_avg(t)/amplitude_avg(t-1)-1，clip(lower=0.001)** | **待定** |

**行业方向性因子说明**（v1.42 2026-06-12 新增）：
- **What**：行业层面趋势维度补充因子，衡量行业整体动量/换手率变化/振幅变化
- **Why**：个股因子只能捕捉截面差异，行业因子捕捉板块轮动信号（如行业整体上涨→行业配置偏向）
- **How**：按(行业,日期)分组聚合→行业均值→比率型/滚动型因子→同行业个股赋相同值
- **Don't**：不可假设行业因子IC方向——实测 industry_momentum_5d IC=+0.026（正向），但 turnover/amplitude_trend 方向待定（遵循 H5）
- **When**：综合因子组合需要行业维度补充时使用
- **Verify**：IC脚本实测IC值、回测分层单调性

**关键依赖**: 新增因子后必须重新运行 `factor_generator.py` 更新 `factor_ic_data.parquet`，否则后续脚本无法读取新因子值。

---

## 策略约束：只做多（Long-Only）[stable]

**What**: 本系统为**只做多（long-only）**量化选股策略，不允许做空。

**How**: 只做多约束影响以下三个环节：
1. **因子筛选（M12）**：门槛指标用 `long_return_annual`（多头年化收益）而非 `long_short_return_annual`（多空收益）；`layer_1_annual > 0` 为不可豁免硬约束（公理1: 只做多收益 = Layer1 买入层收益）
2. **方法评分（weight_selector）**：评分指标不含多空/空头指标（`long_short_return_annual`、`long_short_sharpe`、`long_short_net_daily`、`turnover_short_avg` 已移除），改为 `layer_1_annual` + `layer_1_sharpe`
3. **选股执行（stock_selector）**：企稳确认过滤器排除无企稳信号的股票（公理4推论4: 区分错杀vs基本面恶化）

**Don't**:
- 禁止在筛选/评分中使用多空收益指标（对只做多无意义）
- 禁止将 L1<0 的因子豁免入选（只做多策略持有 L1 = 买入层收益）

**Why**: 只做多策略收益 = Layer1 买入层收益，不能做空 Layer5。多空收益指标衡量的是做多Layer1+做空Layer5的对冲组合，对只做多策略无经济意义。历史教训：原 M12 使用 `long_short_return_annual` 导致高IC但L1负的有毒因子被豁免入选。

**When**: 所有涉及因子筛选、方法评分、选股执行的场景必须遵守。

**Verify**: `grep -r "long_short_return_annual" comprehensive_factor/common/factor_selector.py comprehensive_factor/composite_weight_selector.py` 应零命中

---

## 多管线架构 [experimental]（2026-06-26 新增）

**What**: 多管线架构允许在同一项目内并行运行多条独立的分析链路。每条管线在自己的投资域（数据子集）上独立计算 IC、回测、composite、选股和报告，产出物完全隔离。

### 核心概念

| 概念 | 术语 | 说明 |
|------|------|------|
| 管线 | Pipeline | 一条完整的 IC → backtest → composite → 选股 → 报告 链路 |
| 别名 | alias | 管线的唯一标识，用作目录名和环境变量 `PIPELINE_ALIAS` 的值 |
| 投资域筛选 | filter | pandas query 表达式，定义管线的股票子集（`null` = 全市场） |
| 主数据源 | master | `data_fetchers/result/factor_ic_data.parquet`，所有管线的共享源头 |
| 管线数据 | pipeline data | `data_fetchers/result/<alias>/factor_ic_data.parquet`，slicer 产出 |

### 现有管线

| 别名 | 投资域 | filter | 用途 |
|------|--------|--------|------|
| `default` | 全市场全时段 | `null`（不切割） | 基准对比，现有行为不变 |
| `ob_quality` | 超买股 × 高换手率 | `rsi_6 > 70 and turnover_rate > 5` | 超买股中选 Better 的研究（路径 A） |

### 目录架构

**共享区**（Stage 0-1，不随 pipeline 变化）：

```
data_fetchers/result/
├── factor_ic_data.parquet          # 主数据源（factor_generator 产出，所有 pipeline 共享）
├── turnover_rate_data.json.gz      # 换手率数据（共享）
├── tail_trading_data.json.gz       # 尾盘数据（共享）
├── market_cap_data.json.gz         # 市值数据（共享）
├── stock_list.json                 # 股票列表（共享）
├── default/                        # default pipeline 数据
│   └── factor_ic_data.parquet      # symlink → 主数据源（0 额外存储）
└── ob_quality/                     # ob_quality pipeline 数据
    └── factor_ic_data.parquet      # 切割后子集（~75K 行，约 5%）
```

**隔离区**（Stage 2-7 产出，按 alias 隔离）：

```
factor_ic/
├── result/
│   ├── default/                    # default pipeline 的 IC 结果 (ic_*.json)
│   └── ob_quality/                 # ob_quality pipeline 的 IC 结果
└── logs/
    ├── default/                    # default pipeline 的日志
    └── ob_quality/

backtest/
├── result/
│   ├── default/                    # (*_layered_backtest.json)
│   └── ob_quality/
└── logs/
    ├── default/
    └── ob_quality/

comprehensive_factor/
├── result/
│   ├── default/
│   │   ├── composite_*.json              # 综合因子结果
│   │   ├── composite_*_daily.parquet     # 每日 composite 值
│   │   └── lr_training_data/             # LR 训练数据（Hive 双分区 Parquet）
│   │       ├── weight_method=icir_weight/
│   │       │   └── selection_date=YYYY-MM-DD/part-0.parquet
│   │       └── weight_method=equal_weight/
│   └── ob_quality/
│       └── lr_training_data/             # 独立训练数据
└── logs/
    ├── default/
    └── ob_quality/

stock_selector/
└── logs/                              # 选股日志（实际输出在 comprehensive_factor/result/<alias>/stock_selection_history/）
    ├── default/
    └── ob_quality/

summary/
├── result/
│   ├── default/                        # factor_summary_report_*.txt
│   └── ob_quality/
└── logs/
    ├── default/
    └── ob_quality/
```

### 路径解析机制

所有 Stage 2-7 的路径常量在 `paths.py` 中通过 `PIPELINE_ALIAS` 环境变量动态解析：

```python
# paths.py 核心逻辑
PIPELINE_ALIAS = os.environ.get("PIPELINE_ALIAS", "default")

# 共享区（不随 pipeline 变化）
FACTOR_IC_DATA_MASTER = DATA_FETCHERS_RESULT / "factor_ic_data.parquet"

# 隔离区（随 pipeline 变化）
FACTOR_IC_DATA = DATA_FETCHERS_RESULT / PIPELINE_ALIAS / "factor_ic_data.parquet"
FACTOR_IC_RESULT = PROJECT_ROOT / "factor_ic" / "result" / PIPELINE_ALIAS
BACKTEST_RESULT = PROJECT_ROOT / "backtest" / "result" / PIPELINE_ALIAS
COMPREHENSIVE_FACTOR_RESULT = PROJECT_ROOT / "comprehensive_factor" / "result" / PIPELINE_ALIAS
SUMMARY_RESULT = PROJECT_ROOT / "summary" / "result" / PIPELINE_ALIAS
LR_TRAINING_DATA_DIR = COMPREHENSIVE_FACTOR_RESULT / "lr_training_data"
# 日志同理：<module>/logs/<PIPELINE_ALIAS>/
```

**关键规则**：
- Stage 0-1（data_fetchers/factor_generator）不感知 pipeline，总是写主数据源
- Stage 1.5（pipeline_data_slicer）为每个 pipeline 生成数据子集
- Stage 2-7 的所有脚本通过 `from paths import` 获取路径，自动感知 `PIPELINE_ALIAS`
- `run_pipeline.py` 在启动子进程时通过环境变量 `PIPELINE_ALIAS=<alias>` 注入别名

### 新增 Pipeline 操作流程

**步骤 1：定义管线**

在 `pipelines/pipelines.yaml` 中添加新别名：

```yaml
<alias>:
  filter: "<pandas query 表达式>"
  description: "<管线用途描述>"
```

filter 支持任意 `factor_ic_data.parquet` 中的列，如：
- `rsi_6 > 70` — RSI 超买
- `turnover_rate > 5` — 高换手率
- `market_cap > 10000000000` — 大盘股
- `rsi_6 > 70 and turnover_rate > 3` — 组合条件
- `null` — 全市场（创建 symlink，不复制数据）

**步骤 2：切割数据**

```bash
python3 pipeline_data_slicer.py
```

slicer 读取 `pipelines.yaml`，为每个 pipeline 生成 `data_fetchers/result/<alias>/factor_ic_data.parquet`：
- `filter: null` → 创建 symlink（0 额外存储）
- `filter: 表达式` → pandas query 后写新 parquet

**步骤 3：运行管线**

```bash
# 单个 pipeline（从 Stage 2 开始，跳过数据拉取）
python3 run_pipeline.py --pipeline <alias> --start-stage 2

# 多个 pipeline 顺序执行
python3 run_pipeline.py --pipelines default,<alias> --start-stage 2

# 从数据切割开始（含 Stage 1.5）
python3 run_pipeline.py --pipeline <alias> --start-stage 1.5
```

**步骤 4：验证产出**

```bash
# 确认结果写入正确的 alias 子目录
ls <module>/result/<alias>/

# 确认 default 未被污染
ls <module>/result/default/
```

### 隔离边界

| 数据/产出 | 隔离方式 | 共享还是隔离 |
|-----------|---------|-------------|
| `factor_ic_data.parquet`（主数据源） | `FACTOR_IC_DATA_MASTER` | 共享（Stage 0-1 产出） |
| `factor_ic_data.parquet`（管线数据） | `data_fetchers/result/<alias>/` | 隔离（Stage 1.5 产出） |
| IC 结果 `ic_*.json` | `factor_ic/result/<alias>/` | 隔离 |
| 分层回测 `*_layered_backtest.json` | `backtest/result/<alias>/` | 隔离 |
| 综合因子 `composite_*.json` | `comprehensive_factor/result/<alias>/` | 隔离 |
| 综合因子日值 `composite_*_daily.parquet` | `comprehensive_factor/result/<alias>/` | 隔离 |
| LR 训练数据 `lr_training_data/` | `comprehensive_factor/result/<alias>/lr_training_data/` | 隔离 |
| 选股历史 `stock_selection_history/` | `comprehensive_factor/result/<alias>/stock_selection_history/` | 隔离 |
| 汇总报告 `factor_summary_report_*.txt` | `summary/result/<alias>/` | 隔离 |
| 日志 `*.log` | `<module>/logs/<alias>/` | 隔离 |
| 换手率/尾盘/市值等外部数据 | `data_fetchers/result/` | 共享 |

### Don't

- ❌ 禁止在 Stage 2-7 的代码中硬编码路径（如 `Path(__file__).parent.parent / "result"`），必须 `from paths import`
- ❌ 禁止跨 pipeline 读取数据（default 的脚本不应直接读 ob_quality 的结果）
- ❌ 禁止修改 `FACTOR_IC_DATA_MASTER`（主数据源是所有 pipeline 的共享源头，只有 factor_generator 可写）
- ❌ 禁止在 `paths.py` 之外定义 pipeline 感知路径（所有路径必须通过 `PIPELINE_ALIAS` 解析）

### Why

> 2026-06-26 研究命题："如何在超买股中选得更好"。需要在 RSI>70 子集上重新计算因子方向和权重，但现有架构只有一条 pipeline，无法并行运行第二条而不覆盖现有产出。多管线架构通过 `<alias>` 子目录隔离产出，使多条管线可独立运行、对比分析。

### When

| 触发场景 | 行为 |
|---------|------|
| 需要在特定股票子集上独立计算 IC/composite | 新增 pipeline |
| 需要对比不同投资域的因子表现 | 多 pipeline 对比 |
| 现有 pipeline 的因子方向/权重不适用于子集 | 新增 pipeline 独立训练 |

### Examples

```bash
# 新增高换手率管线
# 1. 在 pipelines.yaml 添加：
#    high_turnover:
#      filter: "turnover_rate > 5"
#      description: "高换手率子集"
# 2. 切割数据
python3 pipeline_data_slicer.py
# 3. 运行管线
python3 run_pipeline.py --pipeline high_turnover --start-stage 2
# 4. 对比
python3 run_pipeline.py --pipelines default,high_turnover --start-stage 2
```

### Verify

```bash
# 验证路径解析
PIPELINE_ALIAS=ob_quality python3 -c "from paths import FACTOR_IC_RESULT; print(FACTOR_IC_RESULT)"
# 期望: .../factor_ic/result/ob_quality

# 验证数据隔离
ls factor_ic/result/default/ | wc -l    # default 的 IC 结果数
ls factor_ic/result/ob_quality/ | wc -l  # ob_quality 的 IC 结果数

# 验证 LR 训练数据隔离
ls comprehensive_factor/result/default/lr_training_data/
ls comprehensive_factor/result/ob_quality/lr_training_data/

# 验证日志隔离
ls factor_ic/logs/default/
ls factor_ic/logs/ob_quality/
```

设计文档：`designs/feat_multi_pipeline_architecture.md`（B 方案，含 A/B 选型对比）

---

## 路线图：待实施 / 预留规则 [reference]

**以下规则当前不在硬规则表中强制执行，不可作为 PR 取证依据。** 待对应工具交付或规则升级后，按 checklist 迁入 H 表。

| 编号 | 规则 | 状态 | 升级条件 |
|------|------|------|---------|
| H4 | 字段非空：None 必须显式设置 + 记录原因 | [预留]（规则定义见 S4） | 校验函数 `validate_and_save_output` 交付后，执行下方"S4 → H4 升级 checklist" |
| H14 | 必测场景：每个场景至少一个可运行的测试函数（pytest --collect-only 可发现） | [待实施]（规则定义已生效，工具未交付） | `scripts/check_required_test_scenarios.py` 交付后启用 CI 强制 |
| S4 | 字段非空：None 必须显式设置 + 记录原因（运行时校验） | [部分生效]：依赖人工 review；待 `validate_and_save_output` 交付后升级为 H4 | 见下方 checklist |

**S4 → H4 升级 checklist（升级时必须同步修改的位置）**：
- [ ] 路线图表移除 H4 / S4 行
- [ ] 硬规则表 H 表新增 H4 行（完整规则文字、目的、检查工具、执行阶段）
- [ ] 若 H4 需补充背景，新增"H4 注释"条目
- [ ] 输出结构校验章节"字段非空校验进度"：`详见路线图 S4` → `详见硬规则 H4`
- [ ] CLAUDE.md §5 硬规则速查同步更新
- [ ] PR 校验脚本 `scripts/validate_pr_reference.py`：将 H4 从"不可引用"列表移到"可引用"列表
- [ ] 校验失败示例：删除 H4 预留示例
- [ ] 在版本历史中记录升级时间与升级 PR

---

## 附录：路径常量清单 [reference]

### 共享区路径常量（Stage 0-1，不随 pipeline 变化）

| 路径常量 | 用途 | pipeline 感知 | "未导入"检查 | "硬编码字面量"检查 |
|---------|------|:---:|---|---|
| FACTOR_IC_DATA_MASTER | 主数据源（factor_generator 产出） | 否（共享） | scripts/check_path_import.py | scripts/check_path_literals.py |
| DATA_FETCHERS_RESULT | data_fetchers 输出目录 | 否（共享） | scripts/check_path_import.py | scripts/check_path_literals.py |
| FINANCIAL_DATA | 财务指标数据 | 否（共享） | scripts/check_path_import.py | scripts/check_path_literals.py |
| FUND_FLOW_DATA | 资金流数据 | 否（共享） | scripts/check_path_import.py | scripts/check_path_literals.py |
| MARKET_CAP_DATA | 市值数据 | 否（共享） | scripts/check_path_import.py | scripts/check_path_literals.py |
| STOCK_LIST_DATA | 股票列表 | 否（共享） | scripts/check_path_import.py | scripts/check_path_literals.py |

### 隔离区路径常量（Stage 2-7，按 PIPELINE_ALIAS 隔离）

| 路径常量 | 用途 | pipeline 感知 | 实际路径（alias=default） | 实际路径（alias=ob_quality） |
|---------|------|:---:|---|---|
| FACTOR_IC_DATA | 管线数据源 | ✅ | `data_fetchers/result/default/factor_ic_data.parquet` | `data_fetchers/result/ob_quality/factor_ic_data.parquet` |
| FACTOR_IC_RESULT | IC 输出目录 | ✅ | `factor_ic/result/default/` | `factor_ic/result/ob_quality/` |
| FACTOR_IC_LOGS | IC 日志目录 | ✅ | `factor_ic/logs/default/` | `factor_ic/logs/ob_quality/` |
| BACKTEST_RESULT | 回测输出目录 | ✅ | `backtest/result/default/` | `backtest/result/ob_quality/` |
| BACKTEST_LOGS | 回测日志目录 | ✅ | `backtest/logs/default/` | `backtest/logs/ob_quality/` |
| COMPREHENSIVE_FACTOR_RESULT | 综合因子输出目录 | ✅ | `comprehensive_factor/result/default/` | `comprehensive_factor/result/ob_quality/` |
| COMPREHENSIVE_FACTOR_LOGS | 综合因子日志目录 | ✅ | `comprehensive_factor/logs/default/` | `comprehensive_factor/logs/ob_quality/` |
| LR_TRAINING_DATA_DIR | LR 训练数据 | ✅ | `comprehensive_factor/result/default/lr_training_data/` | `comprehensive_factor/result/ob_quality/lr_training_data/` |
| SUMMARY_RESULT | 汇总报告输出目录 | ✅ | `summary/result/default/` | `summary/result/ob_quality/` |
| SUMMARY_LOGS | 汇总日志目录 | ✅ | `summary/logs/default/` | `summary/logs/ob_quality/` |
| REVERSE_DISCOVERY_RESULT | 逆向发现输出目录 | ✅ | `reverse_discovery/result/default/` | `reverse_discovery/result/ob_quality/` |
| REVERSE_DISCOVERY_LOGS | 逆向发现日志目录 | ✅ | `reverse_discovery/logs/default/` | `reverse_discovery/logs/ob_quality/` |

> ⚠️ 新增 pipeline 时无需修改 `paths.py`——所有隔离区路径通过 `PIPELINE_ALIAS` 自动解析。只需在 `pipelines/pipelines.yaml` 中添加别名并运行 `pipeline_data_slicer.py`。详见"多管线架构"章节。

---

## 测试位置规范 [experimental]

| 测试类型 | 目录位置 | 用途 | pytest 发现 |
|---------|----------|------|-------------|
| 单元测试 | `<模块>/test_cases/` | 测试单个函数/类 | pytest `<模块>/test_cases/` |
| 集成测试 | `tests/integration/` | 测试跨模块交互 | pytest `tests/integration/` |

**历史教训防御表**（按防御机制分类，避免"测试 / CI 脚本 / 运行时校验"三种东西混杂）：

| 教训 | 防御类型 | 实施位置 | 防御内容 |
|------|---------|---------|---------|
| 路径迁移未同步 | pytest 集成测试 | `tests/integration/test_path_migration.py::test_no_legacy_path_in_loader` | 防止数据迁移后 loader 仍从旧路径读取（关联 H7） |
| 收益数据获取错误 | pytest 集成测试 | `tests/integration/test_return_data_source.py::test_return_data_from_factor_ic_data` | 防止下游从废弃 `return_data.json.gz` 读收益（关联 H7） |
| 字段冗余设计 | CI 脚本扫码 | `scripts/check_deprecated_config.py` | 扫描代码中 `additional_factor_files` 等已废弃配置项，命中即报错 |
| 变更同步遗漏 | CI git diff 校验 | `scripts/check_paths_md_sync.py` | git diff 若改动 `paths.py` 则要求同次 commit 含 PROJECT.md 改动 |
| 向后兼容假设 | 运行时 schema 强制 | 数据加载层 | 强制 schema 校验列存在，缺列直接抛错而非取默认值 |
| 文档层级写错 | CI 脚本扫码 | `scripts/check_doc_layer.py` | 扫描 PROJECT.md 是否出现单模块强制句式（如"factor_ic 必须 ..."、"backtest 不可 ..."），命中即报错；通用引用（目录结构表、路径表）不报错 |

---

## 测试覆盖规范 [experimental]

**两个独立要求，必须同时满足：**

### 1. 覆盖率阈值

- 当前阶段：`--cov-fail-under=60`（CI 硬强制，低于即失败）
- 目标：70%
- **目的**：先用 60% 锁定下限，防止覆盖率下降；待团队补测试自然提升至 70% 后升级阈值
- **设定依据**：基于当前代码库现状测算（基线 60%）
- **阶段计划**：基线 60% → 团队补测试至 ≥70% → 升级 H10 阈值至 70% → 同步修改 `pyproject.toml` 中 `addopts = --cov-fail-under=70`

### 2. 必测场景清单

- **单一来源**：`tests/required_scenarios.yaml`（PROJECT.md 不复制清单，避免双源漂移）
- CI 检查：`scripts/check_required_test_scenarios.py`
- 检查逻辑：扫描 `*/test_cases/test_*.py` 与 `tests/integration/test_*.py`，每个必测场景在全仓库至少有一个匹配函数（pytest --collect-only 可发现）
- **场景类别**（具体函数名见 yaml）：输入边界、输出 schema、异常路径

---

## 输出结构校验 [experimental]

**各模块输出必须通过 JSON Schema 校验。**

| 模块 | 输出文件 | Schema 文件路径 | Schema 约束说明 |
|------|---------|----------------|----------------|
| factor_ic | `ic_<因子>_<周期>_analysis_result.json` | `factor_ic/schemas/ic_analysis_result.schema.json` | 同 schema 多文件，schema 内必须包含 `factor_name` 和 `period` 字段约束 |
| backtest | `<因子>_layered_backtest.json` | `backtest/schemas/layered_backtest_result.schema.json` | 同 schema 多文件，schema 内必须包含 `factor_name` 字段约束 |
| comprehensive_factor | `composite_<加权>_1d.json` | `comprehensive_factor/schemas/composite_factor.schema.json` | 同 schema 多文件，schema 内必须包含 `weighting_method` 字段约束 |
| data_fetchers | `factor_data.json.gz` | `data_fetchers/schemas/factor_data.schema.json` | 单文件单 schema |
| data_fetchers | `turnover_rate_data.json.gz` | `data_fetchers/schemas/turnover_rate_data.schema.json` | 单文件单 schema |
| data_fetchers | `factor_ic_data.parquet` | `data_fetchers/schemas/factor_ic_data.schema.json` | 单文件单 schema（统一数据源） |
| summary | `factor_summary_report_YYYY-MM-DD.txt` | `summary/schemas/summary_report.schema.json` | 单文件单 schema |

**校验工具与调用入口**：
- 工具：`jsonschema` Python 包
- 脚本：`scripts/validate_output_schemas.py`
- 脚本作用范围：（1）校验所有 `*.schema.json` 文件本身符合 JSON Schema meta-schema（CI 可独立运行，无依赖）；（2）若 result/ 目录有产物，则用对应 schema 校验产物（pytest 跑出的测试输出 + 任何 CI 步骤生成的输出）；（3）生产环境的输出由 `validate_and_save_output` 函数在保存时实时校验（详见路线图 S4）
- CI 调用：`python scripts/validate_output_schemas.py`

**字段非空校验进度**：详见路线图 S4。

---

## 版本历史 [reference]

| 版本 | 日期 | 更新内容 | 稳定性标注 |
|---|------|---------|-----------|
| (当前) | 2026-06-30 | **管线收敛**：删 `ob_pool` + `ob_quality_06xx` × 10 + `temp_history*` × 7 共 17 个历史管线，只保留 `default` + `ob_quality`。移除 140 个数据/结果/日志目录。同步更新 `paths.py` docstring、`run_pipeline.py` argparse help、`stock_selector*.py` 注释（本批次"小股票池二次排序"曾误标 `ob_pool`，已改为 `ob_quality`）、`PROJECT.md` 目录示例与路径常量表 | — |
| v3.8 | 2026-06-26 | **多管线架构**：新增 `PIPELINE_ALIAS` 环境变量，`paths.py` 所有 Stage 2-7 路径动态解析到 `<module>/result/<alias>/`。新增 `pipelines/pipelines.yaml`、`pipeline_context.py`、`pipeline_data_slicer.py`（Stage 1.5）。`run_pipeline.py` 支持 `--pipeline`/`--pipelines`/`--start-stage 1.5`，两阶段执行（共享 Stage 0-1.5 + 隔离 Stage 2-7）。6 个 `logger_config.py` + 8 个 `data_loader`/`factor_loader`/`factor_selector`/`composite_runner`/`ic_result_builder`/`layered_backtest_runner`/`constants`/`sections`/`data_loaders`/`generate_factor_summary_report` 适配 pipeline 感知路径。LR 训练数据隔离（`LR_TRAINING_DATA_DIR` 随 alias 解析）。现有管线：`default`（全市场）+ `ob_pool`（RSI>70，200K 行/13.4%，已废弃）。新增"多管线架构"章节（What/How/Don't/Why/When/Examples/Verify）、更新目录结构/路径常量清单/执行顺序日志表 | [experimental] |
| v3.7 | 2026-06-23 | **run_pipeline.py 并行改造**：新增 `--parallel N` 参数，Stage 2 (IC) + Stage 3 (Backtest) 内的脚本按批并行（`ThreadPoolExecutor` 调度 subprocess.run）；批间严格屏障（N 个完成才进下一批，`as_completed` 等所有 future）；其他 stage 始终串行；不跨 stage 边界拼批；失败处理保持原 `failed_scripts` 汇总语义。`PARALLELIZABLE_STAGES = {2, 3}` 显式配置避免 Stage 4 (~2.6GB/脚本) 风险。新增"并行执行模式 [experimental]"章节（What/How/Why/When/Don't/Examples/Verify）。新增 `test_cases/test_run_pipeline_batching.py`（12 用例）覆盖批次切分逻辑。**实测后默认改 N=1（串行）**：N=2 在 7.3GB 机器上触发 OOM Killed（ic_amplitude >4GB / ic_rsi 2.46GB），用户显式 `--parallel 2` 才启用并承担 OOM 风险 | [experimental] |
||| v3.6 | 2026-06-23 | **Parquet 迁移完成**：`factor_ic_data.json.gz` → `factor_ic_data.parquet`，删除所有 ijson fallback / JSON.gz dual-write 路径（净减 ~290 行死代码）。实测数据加载耗时 88s → 1.9s（46x），单脚本峰值内存 OOM → 626MB。Parquet file-level metadata 存 `dates` 数组。§1 数据契约表 + 新鲜度检查脚本（步骤 3）同步更新 | [stable] ||
||| v1.42 | 2026-06-12 | 新增行业方向性因子（industry_momentum_5d / industry_turnover_trend / industry_amplitude_trend）；因子分类一览表；行业方向性因子说明（What/Why/How/Don't/When/Verify） | [experimental] ||
||| v3.5 | 2026-06-16 | "Run Pipeline 执行排查流程" 3 处修订：①步骤 3 新鲜度检查改 ijson 流式扫描（修复 408MB factor_ic_data.json.gz 上 `json.load` OOM kill）；②步骤 3 新增"反向追溯（产物→上游脚本映射）"小节，识别 run_pipeline 单脚本失败不中断导致下游静默用旧数据；③步骤 5 汇总表新增"产物 mtime / 数据 latest_date"列 + 判读规则；④常见异常表新增 OOM kill（退出码 137 / 静默截断）行 | [experimental] ||
||| v3.4 | 2026-06-04 | 扩展"Run Pipeline 执行排查流程"步骤 3：检查所有时间序列数据文件日期新鲜度（factor_ic_data + turnover_rate + tail_trading），明确不需要检查的文件类型 | [stable] ||
|| v3.3 | 2026-06-04 | 补充"Run Pipeline 执行排查流程"中 data_fetchers 数据日期新鲜度检查（步骤 3），关联 Pitfall 162 | [stable] ||
|| v3.2 | 2026-06-04 | 新增"Run Pipeline 执行排查流程"章节：执行顺序与日志位置表、排查步骤（标准化流程）、常见异常快速定位表 | [stable] |
|| v3.1 | 2026-06-03 | 加 AI 协作模式（harness 中立）/ 规则冲突仲裁 / 路线图节；H 规则加目的行；歧义修正（H9 AND 语义、design.md 文件名映射、新增模块定义）；删除 PROJECT.md 中复制 yaml 的必测场景表；教训防御表按机制分类；flag paths.py 导入路径疑问 | [experimental] |
|| v3.0 | 2026-06-01 | 大重构 | [experimental] |
|| v2.x | 2026-05-xx | 旧版本（已重构） | [deprecated] |

**稳定性定义与升级流程：**

| 稳定性标签 | 适用范围 | 定义 | 参与升级流程 | 责任人 |
|-----------|---------|------|-------------|--------|
| `[stable]` | 规则类 | 经过 2-4 周实战验证，规则可靠 | 否（终态；可被回退为 experimental，详见下方"回退机制"） | 项目维护者 |
| `[experimental]` | 规则类 | 新增内容，待验证（按章节分别评估） | 是（默认初始状态，由维护者评估后可升级 stable） | 项目维护者 |
| `[deprecated]` | 规则类 | 已废弃 | 否（终态；进入条件：发现严重缺陷或被新规则替代） | 项目维护者 |
| `[reference]` | 附录/资料类 | 参考文档，作为单一来源 | 否（默认稳定，不参与升级流程） | — |

**升级评估流程**：
- 评估时点：每两周一次（每月 1 日、16 日）
- 评估流程：项目维护者审查 git log / issue / PR，确认无相关 bug 报告
- experimental → stable 判定标准：连续 2 周无相关 bug 报告 + 至少 1 次实际 PR 应用，或在合成测试场景中触发并通过
- 升级操作：维护者在 PROJECT.md 更新章节稳定性标签，并记录升级理由
- 回退机制：若升级后发现 bug，立即回退为 `[experimental]` 并记录原因

---

## 提交前模板 [experimental]

**强制执行：`.pre-commit-config.yaml` + `.github/workflows/ci.yml`**

```
pre-commit 流程：lint → 任务粒度检查 → 路径检查 → git commit
CI 流程：test → schema → import-linter → design-first → 必测场景 → AST 兜底
```

pre-commit hooks（具体实现）：
1. `ruff check --fix`（配置：`pyproject.toml` → `[tool.ruff]`）
2. `ruff format`（配置：`pyproject.toml` → `[tool.ruff.format]`）
3. 任务粒度检查（脚本：`scripts/check_task_size.py`，阈值：MAX_FILES=3, MAX_LINES=200，**两者 AND**）
4. 路径字面量检查（脚本：`scripts/check_path_literals.py`，AST 静态分析）
5. 路径导入检查（脚本：`scripts/check_path_import.py`，AST 静态分析）
6. 临时文件路径检查（脚本：`scripts/check_temp_file_path.py`，AST 静态分析）

**性能预算**：pre-commit 总耗时上限 < 3 秒（基准假设：< 500 个 .py 文件 + 4 核 CPU 环境）。超出基准规模或 AST 检查超时时，由维护者从 `.pre-commit-config.yaml` 中移除耗时 hook（pre-commit 工具本身无自动降级），CI 任务列表中已配置同名 AST 检查作为兜底（见下方 CI 任务 6）。

CI 任务（具体实现）：
1. `pytest`（覆盖率阈值由 `pyproject.toml` → `[tool.pytest.ini_options]` → `addopts = --cov-fail-under=60` 指定，当前阶段值，详见 H10 阶段计划）
2. JSON Schema 校验（脚本：`scripts/validate_output_schemas.py`）
3. `import-linter`（配置：`pyproject.toml` → `[tool.importlinter]`）
4. Design-First 检查（脚本：`scripts/check_design_first.py`）
5. 必测场景检查（脚本：`scripts/check_required_test_scenarios.py`）
6. AST 检查兜底（脚本：`scripts/check_path_literals.py`、`scripts/check_path_import.py`、`scripts/check_temp_file_path.py`）——双重防御，覆盖开发者用 `--no-verify` 跳过 pre-commit 或 pre-commit 因性能预算超时降级的场景

---

## PR 模板必填字段 [experimental]

**取证机制**：PR 模板强制填写，CI 校验引用规范存在。

```markdown
## 规范引用
- 本次改动涉及的规则编号：H2, H7, H9（硬规则）和/或 S1（建议）
- 验证方式：pytest / ruff / pre-commit 脚本
```

（以上为示例，H2=输出位置、H7=路径导入、H9=任务粒度为典型组合）

**可引用的规则编号**：以"硬规则（违反即拒收）"表和"建议（软约束）"表为唯一来源。"路线图：待实施 / 预留规则"表中的 H4、H14、S4 不可作为取证依据。

CI 脚本校验（`scripts/validate_pr_reference.py`）：
1. 规则编号格式正确：H1、H2、H3、H5、H6、H7、H8、H9、H10、H11、H12、H13、S1、S2、S3
2. 编号在硬规则表或建议表中真实存在
3. 路线图中的规则（当前 H4、H14、S4）不可作为取证依据

**校验失败示例**：
- 若 PR 描述写"引用 H14"，validate_pr_reference.py 抛错：`错误：H14 当前为待实施状态（见路线图），不可作为取证依据。`
- 若 PR 描述写"引用 H4"，validate_pr_reference.py 抛错：`错误：H4 为预留规则（见路线图，规则定义见 S4），不可作为取证依据。`

---

## Run Pipeline 执行排查流程 [stable]

**当用户询问 Run_pipeline 脚本执行情况时，按以下步骤排查：**

### 并行执行模式 [experimental]（2026-06-23 新增）

**What**: `run_pipeline.py --parallel N` 控制并行度。

**How**:
- **默认 `N=1`（串行）**：实测 N=2 在 7.3GB 机器上触发 OOM Killed（见 Why）
- `N>1`：Stage 2 (IC) + Stage 3 (Backtest) 内的脚本按批并行，**每批 N 个完成才进下一批**（批间严格屏障）
- 仅 `PARALLELIZABLE_STAGES = {2, 3}` 内的脚本并行；Stage 0/1/4/5/6/7 始终串行
- 不跨 stage 边界拼批：Stage 2 全部完成才进 Stage 3
- 单脚本失败不取消同批其他 future（保持原有 `failed_scripts` 汇总语义）
- 重试策略不变（`MAX_RETRIES=3`, `RETRY_DELAY=30s`），重试发生在 worker 线程内

**Why**: 实测数据（2026-06-23）—— 单 IC 脚本耗时 ~28s，但**内存峰值远超设计预期**：
- ic_rsi_1d 单跑：2.46 GB（含市值/行业中性化 OLS）
- ic_amplitude_1d 单跑：>4 GB
- N=2 并行实测：1.77x 加速但 ic_amplitude **OOM Killed (exit -9)**，dmesg 确认全局 OOM
- 7.3GB 内存 - 系统占用 3.6GB ≈ 3.7GB 可用，无法承载 2 × 2.5GB IC 进程

**When**:
- 日常 pipeline 重跑：**默认 N=1**（安全）
- 高配机器（>16GB 可用内存）想加速：显式 `--parallel 2`（用户自担 OOM 风险）
- 调试 / 复现问题：`--parallel 1`（默认值）

**Don't**:
- ❌ 不要在 Stage 0（fetch_*）开启并行 — 部分数据源有限速 / 顺序依赖
- ❌ 不要把 Stage 4（comprehensive_factor）加入 `PARALLELIZABLE_STAGES` — 单脚本 ~2.6GB
- ❌ **不要在 7.3GB 机器上用 `--parallel 2`** — 已实测会 OOM（除非先减小中性化内存占用）

**Examples**:
```bash
# 默认串行（推荐）
python run_pipeline.py

# 高配机器尝试并行（用户自担 OOM 风险）
python run_pipeline.py --parallel 2

# 从某 IC 脚本开始（串行）
python run_pipeline.py --start-script ic_amplitude

# 跳过部分 stage
python run_pipeline.py --skip-stages 0 1
```

**Verify**: `pytest test_cases/test_run_pipeline_batching.py -v`（12 个用例覆盖批次切分逻辑）

设计文档: `designs/run_pipeline_parallel_design.md`（含 2026-06-23 实测数据与默认值调整记录）

### 执行顺序与日志位置

Run_pipeline 按 8 个阶段顺序执行（含 Stage 1.5 数据切割）。Stage 0-1.5 共享，Stage 2-7 按 pipeline 隔离：

|| 阶段 | 阶段名称 | 脚本数 | 日志目录 | 日志文件命名模式 | pipeline 隔离 |
|---|------|---------|--------|----------|-----------------|:---:|
| Stage 0 | 基础数据拉取 | 5 | `logs/` + `data_fetchers/logs/` | `fetch_*_2026-MM-DD.log` | 否（共享） |
| Stage 1 | 数据整合 | 1 | `data_fetchers/logs/` | `factor_generator_2026-MM-DD.log` | 否（共享） |
| Stage 1.5 | 数据切割 | 1 | stdout（pipeline_data_slicer 输出） | — | 共享执行，产出隔离 |
| Stage 2 | IC计算 | 14 | `factor_ic/logs/<alias>/` | `ic_*_2026-MM-DD.log`, `__main___2026-MM-DD.log` | ✅ |
| Stage 3 | 分层回测 | 14 | `backtest/logs/<alias>/` | `*_2026-MM-DD.log` | ✅ |
| Stage 4 | 综合因子 | 4 | `comprehensive_factor/logs/<alias>/` | `composite_*_2026-MM-DD.log` | ✅ |
| Stage 5 | 权重选择 | 1 | `comprehensive_factor/logs/<alias>/` | `composite_weight_selector_2026-MM-DD.log` | ✅ |
| Stage 6 | 股票选股 | 1 | `stock_selector/logs/<alias>/` | `stock_selector_2026-MM-DD.log` | ✅ |
| Stage 7 | 汇总报告 | 1 | `summary/logs/<alias>/` | `generate_*_2026-MM-DD.log` | ✅ |

### 排查步骤（标准化流程）

**步骤 1：确认执行日期**
- 获取当日日期（如 `2026-06-04`）
- 用户问"今天凌晨执行情况"→ 查询当天日志

**步骤 2：按阶段顺序检查日志**

依次检查以下日志目录中当日生成的日志文件：

```bash
# Stage 0: 基础数据拉取（logs/ 目录）
ls -la logs/*_2026-MM-DD.log
ls -la data_fetchers/logs/*_2026-MM-DD.log

# Stage 1: 数据整合
ls -la data_fetchers/logs/factor_generator_2026-MM-DD.log

# Stage 2: IC计算
ls -la factor_ic/logs/*_2026-MM-DD.log

# Stage 3: 分层回测
ls -la backtest/logs/*_2026-MM-DD.log

# Stage 4-6: 综合因子模块
ls -la comprehensive_factor/logs/*_2026-MM-DD.log

# Stage 7: 汇总报告
ls -la summary/logs/*_2026-MM-DD.log
```

**步骤 3：检查 data_fetchers 数据日期新鲜度**

**⚠️ 关键检查点**：必须验证每个 data_fetchers 脚本拉取的数据日期是否到了 T-1（前一日），否则后续模块可能使用过期数据。

检查方法（统一脚本） [experimental]：

> ⚠️ **factor_ic_data 用 Parquet metadata 读取**（~0ms，列式存储无需遍历）；其他 `.json.gz` 文件保持 `ijson` 流式扫描（避免 `json.load` 全量加载 OOM kill exit 137）。
> Parquet 迁移（2026-06-23）后，`factor_ic_data.parquet` 不再有"全量加载 OOM"风险——`pd.read_parquet(columns=[...])` 列投影读取，单脚本峰值内存 ~626MB。

```bash
# 一次性检查所有时间序列数据文件的日期新鲜度
python -c "
import gzip, ijson, json
from datetime import datetime, timedelta
import pyarrow.parquet as pq

yesterday = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')

# factor_ic_data: 从 Parquet file-level metadata 读取 dates（~0ms）
try:
    schema = pq.read_schema('data_fetchers/result/factor_ic_data.parquet')
    meta = schema.metadata or {}
    dates = json.loads(meta[b'dates']) if b'dates' in meta else []
    max_d = max(dates) if dates else ''
except Exception as e:
    max_d = f'ERR:{e}'
fresh = '✅ 符合' if max_d >= yesterday else '❌ 过期'
print(f'factor_ic_data.parquet: latest={max_d}  expected(T-1)={yesterday}  {fresh}')

# 其他 .json.gz 文件：ijson 流式扫描 data.item.date
files = [
    ('turnover_rate_data.json.gz','data_fetchers/result/turnover_rate_data.json.gz'),
    ('tail_trading_data.json.gz', 'data_fetchers/result/tail_trading_data.json.gz'),
]
for name, path in files:
    max_d = ''
    try:
        with gzip.open(path, 'rb') as f:
            for d in ijson.items(f, 'data.item.date'):
                if d and d > max_d:
                    max_d = d
    except Exception as e:
        max_d = f'ERR:{e}'
    fresh = '✅ 符合' if max_d >= yesterday else '❌ 过期'
    print(f'{name}: latest={max_d}  expected(T-1)={yesterday}  {fresh}')
"
```

**前置依赖**：`pyarrow>=10.0`（已在项目环境中预装）+ `ijson>=3.0`（验证：`python -c "import pyarrow, ijson; print(pyarrow.__version__, ijson.__version__)"`）。

**判定标准**：
- `latest_date >= T-1` → ✅ 数据新鲜，可继续排查后续模块
- `latest_date < T-1` → ❌ 数据过期，需检查对应 data_fetchers 脚本执行情况

**反向追溯（产物→上游脚本映射）** [experimental]：

发现某产物过期时，按下表定位上游失败脚本（`run_pipeline.py` 单脚本失败仅记入 `failed_scripts` 不中断流程，下游会静默用旧数据，必须反向追溯）：

|| 过期产物 | 上游脚本 | 关联 Stage | 检查日志 |
||---------|---------|-----------|---------|
|| `factor_ic_data.parquet` | `factor_generator.py` | Stage 1 | `data_fetchers/logs/factor_generator_2026-MM-DD.log` |
|| `turnover_rate_data.json.gz` | `fetch_turnover.py` | Stage 0 | `data_fetchers/logs/fetch_turnover_2026-MM-DD.log` |
|| `tail_trading_data.json.gz` | `fetch_tail_trading.py` | Stage 0 | `data_fetchers/logs/fetch_tail_trading_2026-MM-DD.log` |
|| `factor_data.json.gz` | `fetch_factor_cache.py` | Stage 0 | `logs/fetch_factor_cache_2026-MM-DD.log` |

**不需要检查日期新鲜度的文件**：
- `stock_list.json`（股票列表，非时间序列）
- `stock_industry.json`（行业分类，非时间序列）

**相关历史教训**：跳过逻辑必须检查日期新鲜度（`latest_date >= T-1`），而非只检查实体存在。（原标注"Pitfall 162 见 AGENTS.md"，AGENTS.md 已退役且全文无该定义；权威源已失，实质教训保留于此，不悬空重定向。）

**步骤 4：检索异常与警告**

使用 grep 扫描所有当日日志：

```bash
grep -r "ERROR\|Exception\|Traceback\|FAIL\|失败" \
  logs/*_2026-MM-DD.log \
  data_fetchers/logs/*_2026-MM-DD.log \
  factor_ic/logs/*_2026-MM-DD.log \
  backtest/logs/*_2026-MM-DD.log \
  comprehensive_factor/logs/*_2026-MM-DD.log \
  summary/logs/*_2026-MM-DD.log 2>/dev/null
```

**步骤 5：汇总报告**

输出格式 [experimental]：

| 模块 | 时间 | 状态 | 关键指标 | 产物 mtime / 数据 latest_date |
|------|------|------|----------|-------------------------------|
| 模块名 | HH:MM-HH:MM | ✅/⚠️/❌ | 耗时、记录数、验证结果 | 文件 mtime + 流式扫描得到的 latest_date（步骤 3 结果） |

> ⚠️ **关键判读规则**：状态列只反映"脚本退出码"，**必须叠加最后一列才能识别"脚本绿但数据陈旧"的静默故障**。
> 典型表现：Stage 1 脚本 OOM kill 后，Stage 2-7 全部"成功"，但产物 latest_date < T-1 ⇒ 实际是基于过期数据出报告，应整体判 ⚠️。

**异常分类**：
- **ERROR**：执行失败，需立即关注
- **WARNING**：数据缺失/不完整，需评估影响
- **INFO 级别的失败计数**：如 `失败 3` 通常在容忍范围内

### 常见异常快速定位

|| 异常信息 | 可能原因 | 排查方向 |
||---------|---------|----------|
|| `cannot reindex on an axis with duplicate labels` | 数据索引重复 | 检查数据文件中是否存在重复的 (date, stock_code) 组合 |
|| `SSL: CERTIFICATE_VERIFY_FAILED` | 外部数据源证书问题 | akshare 等外部 API 问题，不影响核心流程 |
|| `Max retries exceeded` | 网络超时/数据源不可达 | 检查网络连接或数据源状态 |
|| `数据完整性判断: full` | 无缓存/缓存过期 | 正常情况，全量计算模式 |
|| `缺失记录数: N (X%)` | 数据源部分缺失 | 评估缺失比例是否在容忍范围 |
|| 退出码 137 / 日志在某 Step 静默截断、无 Traceback | OOM kill（内存超限被 SIGKILL） | `dmesg -T \| grep -iE "oom\|killed process"` 或 `journalctl --since "今日 00:00" \| grep -iE "oom\|killed"`；机器仅 7.3GB 内存，`factor_generator.py` Step 12 序列化大 DataFrame 时高发 [experimental] |

### 执行顺序完整清单（run_pipeline.py v1.3）

详见 `run_pipeline.py` 文件头部注释或 `PIPELINE_SCRIPTS` 常量定义。

---

## 附录：pre-commit 与 CI 配置片段 [reference]

以下为 `.pre-commit-config.yaml` 和 `.github/workflows/ci.yml` 的核心配置，作为单一来源：

### pre-commit-config.yaml（核心片段）

```yaml
repos:
  - repo: local
    hooks:
      - id: ruff-check
        name: ruff check
        entry: ruff check --fix
        language: system
        types: [python]

      - id: ruff-format
        name: ruff format
        entry: ruff format
        language: system
        types: [python]

      - id: check-task-size
        name: task size check
        entry: python scripts/check_task_size.py
        language: system
        types: [python]

      - id: check-path-literals
        name: path literals check
        entry: python scripts/check_path_literals.py
        language: system
        types: [python]

      - id: check-path-import
        name: path import check
        entry: python scripts/check_path_import.py
        language: system
        types: [python]

      - id: check-temp-file-path
        name: temp file path check
        entry: python scripts/check_temp_file_path.py
        language: system
        types: [python]
```

### ci.yml（核心片段）

```yaml
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Install dependencies
        run: pip install -e .

      - name: Run pytest with coverage
        run: pytest

      - name: Validate output schemas
        run: python scripts/validate_output_schemas.py

      - name: Check import boundaries
        run: import-linter

      - name: Check design-first compliance
        run: python scripts/check_design_first.py

      - name: Check required test scenarios
        run: python scripts/check_required_test_scenarios.py

      - name: AST checks (fallback for skipped pre-commit)
        run: |
          python scripts/check_path_literals.py
          python scripts/check_path_import.py
          python scripts/check_temp_file_path.py
```

**注意**：以上为核心片段，完整配置见实际文件。修改 hooks 或 CI 任务时必须同步更新本附录。

---

*最后更新: 2026-06-26*

