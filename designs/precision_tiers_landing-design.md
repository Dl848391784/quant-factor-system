# 精度分层落地设计（precision tiers landing）

> 2026-09-02。来源：用户目标「3 个都落地，直到真正能提高精度且不需要耗费太多的额外时间和 token，跑测试工作流验证（ac-deepseek1）」。
> 背景调研结论：大项目精度质变靠「编译器验证的解析结果」，通用性押 LSP 协议而非单语言 SCIP indexer；分层置信度模型参照 CALM/trace-mcp（textual → inferred → resolved）。

## 关键事实（动手前已查证）

- codegraph CLI 是外部 npm 包 `@colbymchenry/codegraph`，**不 fork**；但 db `edges.metadata` 已含 `{"confidence":0.4~0.95,"resolvedBy":"exact-match|instance-method|qualified-name"}`——置信度数据**已存在，只是 CLI 输出不展示**。
- `unresolved_refs` 表 8345 行（本项目），是精度丢失的兜底池：含 `reference_name/file_path/line`——CLI `callers` 完全不看它（实测 `codegraph callers load_factor_values` 返回 "No callers found"，而 impact 有结果）。
- H15 门禁要求「改源码前跑 codegraph 查询留痕」不能变慢，故 inject hook **零改动**（token 开销零增量），精度提升走按需查询路径。

## 三层落地内容

### Layer 0：cgx 精确查询脚本（本仓 scripts/）

`scripts/cgx.py`，子命令：

- `callers <symbol>`：直查 db——① `edges(kind='calls')` 命中按 confidence 分档标注：`[resolved ≥0.85]` / `[inferred 0.5~0.85]` / `[textual <0.5]`，附 `resolvedBy`；② `unresolved_refs` 中 `reference_name` 匹配的调用点单列 `candidates (unresolved)` 段——这是 CLI 今天完全丢失的召回。
- `impact <symbol>`：callers + `contains` 内含节点 + `imports` 反向引用，同置信度标注。
- `--json` 输出供 agent/脚本消费。
- H11 日志 % 惰性；H12 退出码（0 正常含零命中 / 1 未预期错误）；db 缺失 → stderr 明确报错 exit 1（不静默）。

### Layer 1：Serena MCP（用户级，跨项目通用）

- 安装：`uv tool install serena-agent`（阿里云 PyPI 镜像，本机 npm/PyPI 默认源极慢）。
- 注册：`claude mcp add --scope user`（用户级 = 未来任何项目 + dl worktree 会话免项目级 MCP 审批提示）。
- Python 语言服务器降级链：默认 pyright 系（需 npm 下载，本机须 npmmirror）→ 失败则切 jedi（纯 pip）。
- **token 开销实测**：stdio 握手 dump tools/list schema 字节数，写入本设计验收节；若 >8k token 则用 serena 配置裁剪工具集。
- 验收：`find_symbol` + `find_referencing_symbols` 对本仓真实 symbol 返回正确结果。

### Layer 2：SCIP 规模触发门（scripts/check_scale_gate.py）

- 统计 git 跟踪源码行数/文件数；阈值：LOC > 300k 或 文件数 > 5000 → 打印 SCIP 升级指引（scip-java/Sourcegraph 自托管），`--strict` 时 exit 1 供 CI 用，默认 exit 0（advisory）。
- 当前仓 ~万行级，预期输出「未触发」——落地的是**机制**而非启用。

## 文件清单与分批（H9：单批 ≤3 文件 AND ≤200 行）

| 批 | 文件 | 行数估 |
|---|---|---|
| B1 | designs/precision_tiers_landing-design.md（本文件） | ~120 |
| B2 | scripts/cgx.py | ~150 |
| B3 | scripts/test_cgx.py | ~110 |
| B4 | scripts/check_scale_gate.py + scripts/test_check_scale_gate.py | ~140 |
| B5 | CLAUDE.md §3 执行映射加 cgx 行 | ~5 |

Serena 无仓内文件（装用户级 ~/.claude.json + ~/.serena/）。

## 验证方案（ac-deepseek1 测试工作流）

1. cgx/check_scale_gate 先过 pytest + 手工冒烟（真实 symbol 输出置信度分层、unresolved 召回对比 CLI 基线）。
2. Serena 冒烟 + schema token 实测。
3. 起一个 dl 测试工作流（`ac-deepseek1 --dl`，deepseek-v4-flash 弱模型）：任务 = 对指定 symbol 做 callers/impact 影响面分析。验收口径：
   - 模型用上 cgx 分层输出（transcript/evidence 可见置信度标注被引用）；
   - 对比基线：CLI `callers` 漏的 unresolved 候选被 cgx 召回；
   - 段耗时/token 从台账读，与常规分析步同量级（无数量级劣化）。
4. 验收数据回填本文件「验收记录」节。

## 风险

- Serena 首次索引语言服务器下载依赖 npm（镜像已配）；失败降级 jedi。
- 用户级 MCP 对全项目加 schema 开销 → B 批验收时实测，超标即裁剪工具集或降级为项目级注册。
- cgx 直查 db schema 依赖 codegraph 内部表结构（nodes/edges/unresolved_refs）——version 变动风险由测试兜底（test_cgx 用临时 fixture db，不依赖真实仓）。

## 验收记录

（验证后回填）

### 落地实测（2026-09-03，主会话）

- **Layer 0 cgx**：`scripts/cgx.py`（200 行）+ 7 测试全绿。精度对比实证：CLI `codegraph callers load_factor_values` → "No callers found"；cgx → [textual] 召回 6 个真实调用点（stock_selector 2 文件 4 点 + 2 测试文件），与 grep 真值一致。`run_factor_ic` 29 条边全部带 conf/resolvedBy 分档（[resolved] 0.90 exact-match 等）。同名多 target（3 模块 convert_to_native_types）按调用点去重正常。
- **Layer 1 Serena**：schema 从 23 工具 ~6.8k token 裁到 12 工具 **~4.3k token**（stdio 握手实测 tools/list 字节数/4；裁剪面=memory/onboarding/config/批量编辑类，全局 `~/.serena/serena_config.yml` excluded_tools）。语言服务器选型实证：jedi-language-server 0.47 与 pyrefly 初装均失败——根因① uv tool 只暴露 3 个 entry point，`jedi-language-server`/`pyrefly` 不在 PATH（已 symlink 到 ~/.local/bin）；根因② solidlsp 硬编码 `uvx -p 3.13 --from pyrefly==1.1.1` 走默认 PyPI 下载卡死（已配 `~/.config/uv/uv.toml` 阿里云镜像 + 预热缓存）。**pyrefly find_referencing_symbols 跨文件返回空 `{}`（能力不满足），jedi 返回真实跨文件引用**（含 codegraph 丢边的 stock_selector 两文件）→ 定 jedi。首调 find_symbol 56.6s（jedi 建 workspace 符号缓存，每会话一次性），后续调用 ~2.5s。
- **Layer 2 触发门**：本仓 434 源码文件 / 109,821 行 → 未触发（阈值 5000/30 万）。4 测试全绿（advisory/strict/非 git 仓 exit 3）。
- **MCP 注册**：`claude mcp add --scope user` 已生效，`claude mcp list` 健康检查 Connected。

### 测试工作流验证（cgx_verify1，ac-deepseek1 / deepseek-v4-flash）

（运行后回填：模型是否用上 cgx 分层输出、unresolved/textual 召回是否被引用、段耗时/token 台账）
