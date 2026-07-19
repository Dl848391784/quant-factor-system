# Design: 证据链用户可见性 (A 追加摘要 + B CLI 查看)

> **触发**: 用户反馈"看不到证据链是否完整/合理，只能上机器看文件"。
> **用户拍板**: A + B 组合。
> **遵循**: 门控哲学（hook 强保证非 agent 自觉 / 磁盘结构化 / 零验证 token）; hermes-plugin-hooks-context-injection Failure Mode 1(静默) 5(重启双进程)。

## 影响范围

- [x] hermes plugin `evidence-chain-gate` (~/.hermes/plugins, 非 git)
- [x] hermes 全局 CLI 脚本 (~/.hermes/scripts, 非 git)
- [ ] factor_ic_analyzer 项目业务代码 — 不涉及

## A · transform_llm_output 追加证据链摘要（被动可见）

**What**: 我给结论时，回复末尾自动附一行证据链状态 + 文件路径，用户无需上机器即可见。

**机制确认**（已读 turn_finalizer.py 源码取证）:
- `transform_llm_output` hook 在回复返回前触发，**first non-empty string wins**（L408-426）
- 签名: `hook(response_text, session_id, model, platform)`, 返回字符串则替换 final_response
- ⚠️ 拿不到 `turn_id`/`user_message`——需自己推导

**How**（gate.py 新增 `on_transform_llm_output`）:
1. 无 `user_message`，无法跑 `_is_analysis_question` 精确判定 → **代理判定**: 取 `session_id` 目录下**最新 mtime** 的证据链文件；若本 session 无任何证据链文件 → 返回 None（非分析轮不追加，零噪音）
2. 有证据链文件 → 追加:
   ```
   \n\n---\n📎 证据链: [READ×N VERIFY×N COUNTER×N] ✅完备 / ⚠️缺X · {文件名}
   ```
3. **死循环防护**: 检查 `response_text` 已含 `📎 证据链:` 则返回 None（防重复追加）
4. **静默 fail-soft 防护**（Failure Mode 1）: 异常时 `logger.warning` + 返回 None（不吞错）

**平台范围**: 所有平台（WebUI/Telegram 都可见）——用户在 WebUI 提的需求，不强加 platform 过滤（过度设计）。

**Don't**: ❌ 不追加完整证据链内容（token 膨胀，违背"膨胀全文注入非解法"）; ❌ 不动 post_llm_call（那是通知型，改不了回复）

## B · CLI 查看工具（主动详查）

**What**: 终端命令格式化查看证据链明细，供用户想看完整 READ/COUNTER/VERIFY/CONTRACT 时用。

**How**: `~/.hermes/scripts/show_evidence.py [session_id] [--latest]`
- 无参: 列出最近 session 目录 + 各 turn 证据链摘要（标签计数 + 完备状态 + mtime）
- `session_id`: 该 session 全部 turn 的完整证据链内容（彩色标签高亮）
- `--latest`: 只看最新一个 turn 完整内容
- 直接读 `~/.hermes/evidence_chains/`, 零依赖（stdlib + 可选 color）

## 改动文件

| 文件 | 改动 |
|---|---|
| `~/.hermes/plugins/evidence-chain-gate/gate.py` | +`on_transform_llm_output` (~50行) |
| `~/.hermes/plugins/evidence-chain-gate/__init__.py` | 注册 transform_llm_output hook |
| `~/.hermes/plugins/evidence-chain-gate/plugin.yaml` | hooks 列表 +transform_llm_output |
| `~/.hermes/scripts/show_evidence.py` | 新建 CLI (~80行) |

## 验证

1. 单测 `on_transform_llm_output`: 无证据链→None / 有→追加 / 已含标记→None(防重)
2. show_evidence.py 无参 + 带 session + --latest 三种跑通
3. 语法检查 + import 实测（非仅注册, Failure Mode 1）
4. 提示重启 gateway + WebUI (Failure Mode 5)
