"""Pipeline 上下文管理：读取配置、解析别名、提供查询接口。

稳定性：[experimental] 2026-06-26
"""

import os
from datetime import timedelta
from pathlib import Path


PROJECT_ROOT = Path(__file__).parent


def get_pipeline_alias() -> str:
    """获取当前 pipeline 别名（环境变量）。

    未设置时默认 "default"，与现有行为一致。
    """
    return os.environ.get("PIPELINE_ALIAS", "default")


def load_pipeline_config() -> dict:
    """加载 pipelines.yaml。

    配置文件不存在时返回 default 单 pipeline 兜底。
    """
    import yaml

    config_path = PROJECT_ROOT / "pipelines" / "pipelines.yaml"
    if not config_path.exists():
        return {"default": {"filter": None, "description": "全量数据（无配置文件）"}}
    with open(config_path) as f:
        return yaml.safe_load(f)


def resolve_filter(filter_expr: str | None) -> str | None:
    """解析 filter 表达式中的动态占位符。

    支持的占位符：
      {latest_date}            → 主数据源最大日期
      {latest_date_minus_30}   → 最大日期 -30 天
      {latest_date_minus_60}   → 最大日期 -60 天
    """
    if filter_expr is None:
        return None

    import pandas as pd

    master = PROJECT_ROOT / "data_fetchers" / "result" / "factor_ic_data.parquet"
    dates = pd.read_parquet(master, columns=["date"])["date"]
    latest_date = pd.to_datetime(dates).max()

    replacements = {
        "{latest_date}": latest_date.strftime("%Y-%m-%d"),
        "{latest_date_minus_30}": (latest_date - timedelta(days=30)).strftime("%Y-%m-%d"),
        "{latest_date_minus_60}": (latest_date - timedelta(days=60)).strftime("%Y-%m-%d"),
    }
    result = filter_expr
    for placeholder, value in replacements.items():
        result = result.replace(placeholder, value)
    return result
