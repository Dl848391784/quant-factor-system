#!/usr/bin/env python3
"""Stage 1.5: 为每个 pipeline 切割数据子集。

读取主数据源 → 按 pipelines.yaml 的 filter 切割 → 写入 data_fetchers/result/<alias>/
- filter=null: 创建 symlink（不复制）
- filter=表达式: pandas query 后写新 parquet

退出码：0=成功 / 1=运行时错误

稳定性：[experimental] 2026-06-26
"""

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd  # noqa: E402
from pipeline_context import load_pipeline_config, resolve_filter  # noqa: E402


def slice_pipeline(alias: str, filter_expr: str | None, source: Path, output: Path) -> None:
    """为单个 pipeline 切割数据。

    Args:
        alias: pipeline 别名
        filter_expr: pandas query 表达式（None 表示全量）
        source: 主数据源路径
        output: 输出路径
    """
    output.parent.mkdir(parents=True, exist_ok=True)

    if filter_expr is None:
        # 无过滤：symlink 到主数据源
        # 但如果 output 已是真实文件（非 symlink），说明是手动切割的数据，跳过保护
        if output.exists() and not output.is_symlink():
            print(f"  [{alias}] 跳过: 已存在手动切割的数据文件")
            return
        if output.is_symlink():
            output.unlink()
        output.symlink_to(source)
        print(f"  [{alias}] symlink -> {source}")
    else:
        # 有过滤：query 后写新文件
        resolved = resolve_filter(filter_expr)
        df = pd.read_parquet(source)
        before = len(df)
        df = df.query(resolved)
        after = len(df)
        df.to_parquet(output, index=False)
        print(f"  [{alias}] filter='{resolved}' | {before} -> {after} rows -> {output}")


def main() -> None:
    config = load_pipeline_config()
    source = PROJECT_ROOT / "data_fetchers" / "result" / "factor_ic_data.parquet"

    if not source.exists():
        print("[ERROR] 主数据源不存在:", source)
        sys.exit(1)

    print("=== Pipeline Data Slicer ===")
    print(f"主数据源: {source}")

    for alias, pipeline_cfg in config.items():
        filter_expr = pipeline_cfg.get("filter") if pipeline_cfg else None
        output = PROJECT_ROOT / "data_fetchers" / "result" / alias / "factor_ic_data.parquet"
        slice_pipeline(alias, filter_expr, source, output)

    print(f"\n完成: {len(config)} 个 pipeline 数据已就绪")


if __name__ == "__main__":
    main()
