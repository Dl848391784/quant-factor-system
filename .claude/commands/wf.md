---
description: 工作流阶段控制 - 用法 /wf next|back|jump <phase>|status|gate|done
---

运行工作流控制脚本（源真：`scripts/workflow/wf-lib.sh` + `wf-cmd.sh`）。参数透传给 `$ARGUMENTS`。

请执行下面的命令并据输出回应（这是 /wf `$ARGUMENTS` 的执行）：

```bash
bash scripts/workflow/wf-cmd.sh $ARGUMENTS
```

根据脚本输出向用户说明阶段变化。若输出含闸门提示，提醒用户 `/wf gate` 放行。
