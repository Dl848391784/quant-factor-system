"""web_ui/common/lr_training_status.py

v0.4.8 R2a: LR 训练数据状态 web_ui 内部实现
H1.1 严守: 不修改 data_loaders, web_ui 直接读 lr_training_data HIVE 分区

数据源: comprehensive_factor/result/<pipeline>/lr_training_data/
结构: HIVE 分区, weight_method=<wm>/selection_date=<date>/part-0.parquet
字段: forward_return_1d (用于 T+1 补写百分比)

返回: [{method, days, rows, t1_pct, status}, ...]
"""

from __future__ import annotations

import logging
from pathlib import Path

import pyarrow.parquet as pq


# 路径: 复用 paths 模块定义 (H7 路径导入规则)
def _get_lr_root() -> Path:
    """web_ui 内部从 paths 模块获取 lr_training_data 根目录
    强制走 ob_quality pipeline (v0.4.8 简化: web_ui 只展示 ob_quality)
    """
    from paths import COMPREHENSIVE_FACTOR_RESULT

    return COMPREHENSIVE_FACTOR_RESULT / "lr_training_data"


def load_status(logger: logging.Logger) -> list[dict]:
    """v0.4.8 R2a: 扫描 lr_training_data HIVE 分区, 返回各权重方法的训练状态

    Args:
        logger: 日志记录器

    Returns:
        [{method, days, rows, t1_pct, status}, ...]
        降级: 目录不存在 → []
    """
    lr_root = _get_lr_root()
    if not lr_root.exists():
        logger.debug("lr_training_data 目录不存在: %s", lr_root)
        return []

    rows: list[dict] = []
    for wm_dir in sorted(lr_root.iterdir()):
        if not wm_dir.is_dir() or not wm_dir.name.startswith("weight_method="):
            continue
        wm = wm_dir.name.replace("weight_method=", "")
        n_days = 0
        n_rows = 0
        n_with_ret = 0
        for date_dir in sorted(wm_dir.iterdir()):
            if not date_dir.is_dir() or not date_dir.name.startswith("selection_date="):
                continue
            parquet_path = date_dir / "part-0.parquet"
            if not parquet_path.exists():
                continue
            try:
                df = pq.read_table(parquet_path, columns=["forward_return_1d"]).to_pandas()
                n_days += 1
                n_rows += len(df)
                n_with_ret += int(df["forward_return_1d"].notna().sum())
            except Exception as e:
                logger.debug("读 lr_training_data 失败: %s (%s)", parquet_path, e)
                continue
        if n_days == 0:
            continue
        t1_pct = n_with_ret / n_rows * 100 if n_rows > 0 else 0.0
        status = "✓ 可训练" if n_days >= 90 else f"积累中 ({n_days}/90 天)"
        rows.append(
            {
                "method": wm,
                "days": n_days,
                "rows": n_rows,
                "t1_pct": round(t1_pct, 1),
                "status": status,
            }
        )
    logger.info("LR 训练数据状态 (web_ui 内部): %d 个权重方法已加载", len(rows))
    return rows
