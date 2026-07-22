---
description: 工作流阶段控制 - 用法 /wf next|back|jump <phase>|status|gate|done
---

运行工作流控制脚本。参数透传给 `$ARGUMENTS`。

**必须用主仓库的 wf-cmd.sh（绝对路径），不能用 worktree 内的相对路径**——worktree 内的脚本是 git checkout 快照，主仓库改动不会同步，且相对路径会让 `WF_REPO_ROOT` 误解析到 worktree 根、读不到主仓库的 state.json。

请执行（用 git 反查主仓库根，再调主仓库脚本）：

```bash
bash "$(dirname "$(git rev-parse --git-common-dir)")/scripts/workflow/wf-cmd.sh" $ARGUMENTS
```

根据脚本输出向用户说明阶段变化。若输出含闸门提示，提醒用户 `/wf gate` 放行。
