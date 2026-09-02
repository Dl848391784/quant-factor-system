#!/usr/bin/env python3
"""check_scale_gate.py - 仓库规模触发门：超过阈值提示升级 SCIP 精确索引。

背景（designs/precision_tiers_landing-design.md Layer 2）：codegraph/LSP 组合在
中小仓足够；单仓超阈值（LOC > 30 万 或 源文件 > 5000）后 LSP 索引时间/内存
不可接受，应升级 SCIP（scip-java 等编译器插桩索引 + Sourcegraph 自托管，CI 产出）。

默认 advisory（超阈值打印指引，exit 0）；--strict 超阈值 exit 1（供 CI 强制）。
退出码（H12）：0=正常；1=--strict 下超阈值或未预期错误；3=无法统计（如非 git 仓）。
"""

import argparse
import subprocess
import sys
from pathlib import Path


SOURCE_EXTS = {".py", ".java", ".go", ".rs", ".js", ".ts", ".c", ".cc", ".h", ".rb"}
LOC_THRESHOLD = 300_000
FILES_THRESHOLD = 5_000

SCIP_GUIDE = """\
⚠️ 仓库规模超阈值，建议升级 SCIP 精确索引：
  1. Java: scip-java（Maven/Gradle 插件，CI 产出 .scip）
  2. 托管: Sourcegraph 自托管（跨仓精确导航）或 scip-search CLI 本地查
  3. 过渡: Serena(LSP) 仍可用，但首次索引时间/内存将不可接受
阈值：LOC > {loc} 或 源文件数 > {files}（designs/precision_tiers_landing-design.md）"""


def collect_stats(root: Path) -> tuple[int, int]:
    """统计 git 跟踪的源码文件数与总行数。返回 (files, loc)。"""
    proc = subprocess.run(["git", "ls-files"], capture_output=True, text=True, cwd=root, check=True)
    files = [f for f in proc.stdout.splitlines() if Path(f).suffix in SOURCE_EXTS]
    loc = 0
    for rel in files:
        try:
            with open(root / rel, "rb") as fh:
                loc += sum(1 for _ in fh)
        except OSError:
            continue  # 文件在索引里但磁盘缺失（稀疏检出等），跳过不计
    return len(files), loc


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="仓库规模触发门：超阈值提示升级 SCIP")
    parser.add_argument("--strict", action="store_true", help="超阈值 exit 1（CI 强制模式）")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args(argv)

    try:
        files, loc = collect_stats(args.root)
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        print(f"check_scale_gate: 无法统计（非 git 仓或 git 不可用）: {e}", file=sys.stderr)
        return 3

    print(f"源码文件 {files} 个，{loc} 行（阈值：{FILES_THRESHOLD} 文件 / {LOC_THRESHOLD} 行）")
    exceeded = files > FILES_THRESHOLD or loc > LOC_THRESHOLD
    if not exceeded:
        print("✓ 未触发 SCIP 升级阈值，codegraph + LSP 组合足够")
        return 0
    print(SCIP_GUIDE.format(loc=f"{LOC_THRESHOLD:,}", files=f"{FILES_THRESHOLD:,}"))
    return 1 if args.strict else 0


if __name__ == "__main__":
    sys.exit(main())
