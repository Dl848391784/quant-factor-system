"""
stock_selector_lr.py — LR 过滤训练 / 应用 / 训练数据持久化

从 stock_selector.py v3.12 拆分 (2026-06-26).
行为不变, 纯机械提取.

版本历史见 stock_selector.py 头注释.
"""

import json
import logging
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np
import pandas as pd


# sys.path 处理（遵循 MODULE.md M49）
PROJECT_ROOT = Path(__file__).parent.parent.resolve()
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))  # noqa: E402

from comprehensive_factor.common.factor_loader import load_factor_values  # noqa: E402
from factor_definitions import FACTOR_COL_TO_NAME_MAP  # noqa: E402
from stock_selector.common.logger_config import get_logger  # noqa: E402
from stock_selector.config import (  # noqa: E402
    StockSelectorConfig,
)
from stock_selector.history import _load_stock_name_map  # noqa: E402


if TYPE_CHECKING:
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler

_logger = get_logger(__name__)


def _discover_features(
    bottom_df: pd.DataFrame,
    feature_cols: list[str],
    top_n: int,
    logger: logging.Logger,
) -> list[str]:
    """v3.12: 数据驱动特征发现——Cohen's d 选 top N + 同族去重.

    在 Bottom90 历史样本上, 按 T+1 涨跌分组, 计算每个特征的 Cohen's d 效应量.
    按 |d| 降序贪心选取, 每次选入前检查与已选特征的 Pearson |r|,
    若 |r| > 0.7 则跳过 (同族共线性特征, 避免多变量系数翻转).

    根因: 原始特征 (factor_xxx) 与标准化特征 (factor_xxx_std) 高度相关
    (|r| ≈ 0.78~0.85) 但方向相反, 同时入选会导致 LR 多变量系数翻转.
    """
    up_mask = bottom_df["forward_return_1d"] > 0
    down_mask = bottom_df["forward_return_1d"] < 0

    scores: list[tuple[str, float]] = []
    for col in feature_cols:
        up_vals = bottom_df.loc[up_mask, col].dropna()
        down_vals = bottom_df.loc[down_mask, col].dropna()
        if len(up_vals) < 30 or len(down_vals) < 30:
            continue
        pooled_std = float(
            np.sqrt(
                ((len(up_vals) - 1) * up_vals.var() + (len(down_vals) - 1) * down_vals.var())
                / (len(up_vals) + len(down_vals) - 2)
            )
        )
        if pooled_std <= 0:
            continue
        d = float((up_vals.mean() - down_vals.mean()) / pooled_std)
        scores.append((col, abs(d)))

    scores.sort(key=lambda x: x[1], reverse=True)

    # v3.12: 同族去重 — 贪心选取, |r| > 0.7 视为同族, 跳过
    correlation_threshold = 0.7
    selected: list[str] = []
    skipped_due_to_correlation: list[tuple[str, str, float]] = []

    for feat_name, feat_d in scores:
        if len(selected) >= top_n:
            break
        if not selected:
            selected.append(feat_name)
            continue

        # 计算与已选特征的相关性
        feat_vals = bottom_df[feat_name].dropna()
        is_redundant = False
        for sel_feat in selected:
            sel_vals = bottom_df[sel_feat]
            # 对齐索引
            common_idx = feat_vals.index.intersection(sel_vals.dropna().index)
            if len(common_idx) < 30:
                continue
            r = float(feat_vals.loc[common_idx].corr(sel_vals.loc[common_idx]))
            if abs(r) > correlation_threshold:
                skipped_due_to_correlation.append((feat_name, sel_feat, r))
                is_redundant = True
                break

        if not is_redundant:
            selected.append(feat_name)

    logger.info(
        "特征发现: 扫描 %d 个特征, 选 top %d: %s",
        len(feature_cols),
        len(selected),
        ", ".join(f"{s[0]}({s[1]:.3f})" for s in scores if s[0] in selected),
    )
    if skipped_due_to_correlation:
        logger.debug(
            "特征去重: 跳过 %d 个同族特征 (|r| > %.1f): %s",
            len(skipped_due_to_correlation),
            correlation_threshold,
            ", ".join(f"{f}↔{s}(r={r:.2f})" for f, s, r in skipped_due_to_correlation[:5]),
        )
    return selected


def calibrate_lr_filter(
    training_data_dir: str | Path,
    weight_method: str,
    top_n: int = 30,
    n_features: int = 10,
    train_window: int = 120,
    min_oos_auc: float = 0.55,
    min_training_days: int = 90,
    filter_quantile: float = 0.3,
    logger: logging.Logger | None = None,
) -> tuple["LogisticRegression | None", "StandardScaler | None", list[str], float]:
    """v3.10: 从 lr_training_data 读取训练样本, 训练 LR 模型.

    与 v3.9.2 的根本区别:
    - 训练样本来自 lr_training_data (真实 Bottom90), 不再用 return_5d 代理
    - 训练分布 = 应用分布 (第一性原理)
    - 需要检查训练天数 ≥ min_training_days, 不足则返回 None
    - forward_return_1d 为 null 的行跳过 (T+1 未补写)

    流程:
    1. 从 training_data_dir 读取 weight_method 分区下所有 selection_date
    2. 过滤 forward_return_1d 非 null 的行
    3. 检查有效天数 ≥ min_training_days
    4. _discover_features: Cohen's d 选 top N (样本来自真实 Bottom90)
    5. Walk-forward OOS 验证
    6. 全样本训练最终模型

    Args:
        training_data_dir: lr_training_data 根目录.
        weight_method: 权重方式 (如 'equal_weight').
        top_n: Bottom N (用于日志, 默认 30).
        n_features: top N 特征数 (Cohen's d 排序).
        train_window: walk-forward 训练窗口天数.
        min_oos_auc: OOS AUC 门槛.
        min_training_days: 最小训练天数, 不足返回 None.
        filter_quantile: 排除底 N% (用于日志).
        logger: 日志对象.

    Returns:
        (model, scaler, selected_features, oos_auc).
        如果训练数据不足或 OOS 验证不通过, 返回 (None, None, [], 0.0).
    """
    if logger is None:
        logger = _logger

    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import roc_auc_score
    from sklearn.preprocessing import StandardScaler

    # 1) 从 lr_training_data 读取训练样本
    wm_dir = Path(training_data_dir) / f"weight_method={weight_method}"
    if not wm_dir.exists():
        logger.info("LR 校准: 训练数据目录不存在 (%s), 跳过过滤", wm_dir)
        return None, None, [], 0.0

    # 逐个 selection_date 分区读取 (避免 ds.dataset schema merge 冲突)
    import os

    parts: list[pd.DataFrame] = []
    for date_dir_name in sorted(os.listdir(wm_dir)):
        if not date_dir_name.startswith("selection_date="):
            continue
        date_str = date_dir_name.replace("selection_date=", "")
        parquet_path = wm_dir / date_dir_name / "part-0.parquet"
        if not parquet_path.exists():
            continue
        try:
            part_df = pd.read_parquet(parquet_path)
            part_df["selection_date"] = date_str  # 显式注入分区键
            parts.append(part_df)
        except Exception as e:
            logger.debug("LR 校准: 读取 %s 失败: %s", parquet_path, e)
            continue

    if not parts:
        logger.info("LR 校准: 训练数据为空 (%s), 跳过过滤", weight_method)
        return None, None, [], 0.0

    bottom_df = pd.concat(parts, ignore_index=True)

    # 过滤 forward_return_1d 非 null 的行 (T+1 已补写)
    bottom_df = bottom_df.dropna(subset=["forward_return_1d"]).copy()

    if bottom_df.empty:
        logger.info("LR 校准: 无已补写 forward_return_1d 的样本, 跳过过滤")
        return None, None, [], 0.0

    # 检查训练天数
    if "selection_date" not in bottom_df.columns:
        logger.warning("LR 校准: 训练数据缺少 selection_date 列, 跳过过滤")
        return None, None, [], 0.0

    dates = sorted(bottom_df["selection_date"].unique())
    n_valid_days = len(dates)

    if n_valid_days < min_training_days:
        logger.info(
            "LR 校准: 训练天数 %d < 门槛 %d, 跳过过滤 (积累中)",
            n_valid_days,
            min_training_days,
        )
        return None, None, [], 0.0

    logger.info(
        "LR 校准: %d 天训练数据, %d 条记录, weight_method=%s",
        n_valid_days,
        len(bottom_df),
        weight_method,
    )

    # 确定特征列 (factor_ 前缀的列, 排除非数值如 factor_direction)
    feature_cols = [
        c
        for c in bottom_df.columns
        if c.startswith("factor_") and bottom_df[c].dtype in ("float64", "float32", "int64", "int32")
    ]
    if not feature_cols:
        logger.warning("LR 校准: 训练数据无 factor_ 前缀列, 跳过过滤")
        return None, None, [], 0.0

    # 2) 数据驱动特征发现
    selected_features = _discover_features(bottom_df, feature_cols, n_features, logger)

    if len(selected_features) < 3:
        logger.warning("LR 校准: 有效特征不足 (%d < 3), 跳过过滤", len(selected_features))
        return None, None, [], 0.0

    # 3) Walk-forward OOS 验证
    date_to_data = {d: bottom_df[bottom_df["selection_date"] == d] for d in dates}
    oos_aucs: list[float] = []

    for i in range(train_window, len(dates)):
        train_dates = dates[i - train_window : i]
        test_date = dates[i]

        train_data = pd.concat([date_to_data[d] for d in train_dates], ignore_index=True)
        test_data = date_to_data[test_date]

        X_train = train_data[selected_features]
        y_train = (train_data["forward_return_1d"] > 0).astype(int)
        X_test = test_data[selected_features]
        y_test = (test_data["forward_return_1d"] > 0).astype(int)

        train_valid = X_train.notna().all(axis=1)
        test_valid = X_test.notna().all(axis=1)
        X_train = X_train[train_valid]
        y_train = y_train[train_valid]
        X_test = X_test[test_valid]
        y_test = y_test[test_valid]

        if len(X_train) < 100 or len(X_test) < 5:
            continue
        if y_train.nunique() < 2 or y_test.nunique() < 2:
            continue

        scaler = StandardScaler()
        model = LogisticRegression(max_iter=1000, random_state=42)
        try:
            model.fit(scaler.fit_transform(X_train), y_train)
            y_pred = model.predict_proba(scaler.transform(X_test))[:, 1]
            oos_aucs.append(float(roc_auc_score(y_test, y_pred)))
        except (ValueError, np.linalg.LinAlgError) as e:
            logger.debug("LR walk-forward 窗口 %s 失败: %s", test_date, e)
            continue

    if not oos_aucs:
        logger.warning("LR 校准: walk-forward 无有效窗口, 跳过过滤")
        return None, None, [], 0.0

    mean_auc = float(np.mean(oos_aucs))
    median_auc = float(np.median(oos_aucs))
    pct_above = float(np.mean(np.array(oos_aucs) > min_oos_auc) * 100)
    logger.info(
        "LR walk-forward OOS: AUC=%.3f±%.3f (中位 %.3f), >%.2f: %.0f%%, 窗口数=%d",
        mean_auc,
        float(np.std(oos_aucs)),
        median_auc,
        min_oos_auc,
        pct_above,
        len(oos_aucs),
    )

    if mean_auc < min_oos_auc:
        logger.warning(
            "LR 校准: OOS AUC %.3f < 门槛 %.2f, 跳过过滤",
            mean_auc,
            min_oos_auc,
        )
        return None, None, selected_features, mean_auc

    # 4) 用全样本训练最终模型
    X_full = bottom_df[selected_features]
    y_full = (bottom_df["forward_return_1d"] > 0).astype(int)
    full_valid = X_full.notna().all(axis=1)
    X_full = X_full[full_valid]
    y_full = y_full[full_valid]

    final_scaler = StandardScaler()
    final_model = LogisticRegression(max_iter=1000, random_state=42)
    final_model.fit(final_scaler.fit_transform(X_full), y_full)

    logger.info(
        "LR 校准完成: %d 特征, OOS AUC=%.3f, 过滤底 %.0f%%",
        len(selected_features),
        mean_auc,
        filter_quantile * 100,
    )
    return final_model, final_scaler, selected_features, mean_auc


def apply_lr_filter(
    bottom_stocks: list[dict[str, Any]],
    data_source: str | Path,
    selection_date: str,
    top_n: int,
    model: "LogisticRegression",
    scaler: "StandardScaler",
    selected_features: list[str],
    filter_quantile: float,
    logger: logging.Logger | None = None,
) -> tuple[list[dict[str, Any]], int]:
    """v3.13: 用 LR 模型对 Bottom90 全部打分, 按 proba_up 降序输出 (不截断).

    从 data_source 加载当日特征数据 (selected_features 列), 不依赖调用方 factor_df.
    模型输出 proba_up = P(T+1 > 0). 全部股票按 proba_up 降序排列输出,
    每只股票附带 lr_proba_up 字段, 不做排除/截断.
    """
    if logger is None:
        logger = _logger

    if model is None or scaler is None or not selected_features:
        logger.info("LR 过滤: 模型不可用, 返回原始排序 (无 lr_proba_up)")
        return bottom_stocks, 0

    # v3.11 修复: 训练特征名 (factor_xxx / factor_xxx_std) → parquet 原始列名 (xxx) 映射
    # lr_training_data 中列名带 factor_ 前缀和 _std 后缀, 但 parquet 中是原始列名
    def _map_feat_to_parquet(feat: str) -> str:
        base = feat
        if base.startswith("factor_"):
            base = base[7:]
        if base.endswith("_std"):
            base = base[:-4]
        return base

    # 建立 训练特征 → parquet列名 映射, 去重加载 parquet 列
    feat_to_parquet = {f: _map_feat_to_parquet(f) for f in selected_features}
    unique_parquet_feats = list(dict.fromkeys(feat_to_parquet.values()))

    # 加载当日特征数据 (仅 unique_parquet_feats 列, 开销极小)
    day_df = load_factor_values(unique_parquet_feats, data_source, logger)
    day_df = day_df[day_df["date"].apply(lambda d: pd.Timestamp(d).strftime("%Y-%m-%d")) == selection_date].copy()
    asset_index = day_df.set_index("asset") if "asset" in day_df.columns else day_df

    # v3.12: 检测当天全 NaN 的特征列, 用 0 填充 (scaler 之后均值=0, 等价于中性贡献)
    # 根因: 部分因子 (如 capital_flow_ratio_trend) 在最新一天可能全 NaN (增量采集延迟),
    # 任何一个特征 NaN 会导致整只股票被判 "特征缺失" → 90/90 全中性概率 → LR 过滤无效
    all_nan_feats = [f for f in unique_parquet_feats if day_df[f].isna().all()]
    if all_nan_feats:
        logger.warning(
            "LR 过滤: 当天全 NaN 特征 %d 个, 用 0 填充: %s",
            len(all_nan_feats),
            ", ".join(all_nan_feats[:5]),
        )
        day_df[all_nan_feats] = 0.0
        asset_index = day_df.set_index("asset") if "asset" in day_df.columns else day_df

    # 收集每只股票的特征和模型打分
    scored: list[tuple[dict[str, Any], float]] = []
    missing_features = 0  # 不在数据源中的股票数
    for stock in bottom_stocks:
        code = stock["code"]
        if code not in asset_index.index:
            missing_features += 1
            scored.append((stock, 0.5))  # 数据不可用 → 中性概率
            continue

        row = asset_index.loc[code]
        if isinstance(row, pd.DataFrame):
            row = row.iloc[0]

        # 按 selected_features 顺序构建特征向量 (重复的 parquet 列会读到同一个值)
        # v3.12: 个别股票的 NaN 特征用 0 填充 (scaler 之后均值=0, 中性贡献)
        feature_vals = []
        for feat in selected_features:
            parquet_col = feat_to_parquet[feat]
            val = row.get(parquet_col, np.nan)
            if isinstance(val, pd.Series):
                val = val.iloc[0]
            if pd.isna(val):
                val = 0.0
            feature_vals.append(float(val))

        X = pd.DataFrame([feature_vals], columns=selected_features)
        proba_up = float(model.predict_proba(scaler.transform(X))[0, 1])
        scored.append((stock, proba_up))

    if missing_features > 0:
        logger.info(
            "LR 过滤: %d/%d 只股票不在数据源中, 使用中性概率 0.5",
            missing_features,
            len(scored),
        )

    # 按 proba_up 降序排 (概率高的 = 预测涨的 = 排前面)
    scored.sort(key=lambda x: x[1], reverse=True)

    # v3.13: 不再排除/截断, 全部按 proba_up 降序输出, 每只股票附带 lr_proba_up
    filtered = []
    for idx, (stock, proba) in enumerate(scored, start=1):
        stock["rank"] = idx
        stock["lr_proba_up"] = round(proba, 4)
        filtered.append(stock)

    logger.info(
        "LR 打分: %d 只候选全部输出 (按 proba_up 降序, 不截断)",
        len(scored),
    )

    return filtered, 0


def save_lr_training_data(
    bottom_stocks: list[dict[str, Any]],
    factor_df: pd.DataFrame,
    weight_config: dict[str, Any],
    config: "StockSelectorConfig",
    selection_date: str,
    logger: logging.Logger | None = None,
) -> Path | None:
    """v3.10: 持久化 Bottom90 训练数据到 Parquet 双分区数据集.

    分区布局:
        lr_training_data/weight_method=<method>/selection_date=YYYY-MM-DD/part-0.parquet

    每天每个 weight_method 写 90 行, 含因子权重 + 因子原始值 + composite 得分.
    forward_return_1d 当天为 null, 次日由 backfill_forward_return_1d() 补写.
    同日重跑覆盖该分区.

    Args:
        bottom_stocks: Bottom90 股票列表 (composite 升序最低 90 只).
        factor_df: 当日全特征数据 (含因子列, index 对齐 bottom_stocks).
        weight_config: 权重配置 (含 best_selection.method, meta.weight_meta.last_day_weights).
        config: 选股配置.
        selection_date: 选股日期 'YYYY-MM-DD'.
        logger: 日志.

    Returns:
        分区目录路径, 失败返回 None.
    """
    if logger is None:
        logger = _logger

    import pyarrow as pa
    import pyarrow.parquet as pq
    from paths import LR_TRAINING_DATA_DIR

    if not bottom_stocks:
        logger.warning("save_lr_training_data: bottom_stocks 为空, 跳过")
        return None

    # v3.11: weight_method 从 meta.weight_method 读取 (composite JSON 结构)
    #   之前从 best_selection.method 读取, 但 v3.11 循环传入的是 composite JSON (无 best_selection)
    meta = weight_config.get("meta", {})
    weight_method = meta.get("weight_method", "equal_weight")
    composite_score = float(weight_config.get("best_selection", {}).get("composite_score", 0.0))

    # 确定因子列 (从 factor_df 中排除非因子列, 提前到权重处理之前)
    exclude = {
        "date",
        "asset",
        "forward_return_1d",
        "forward_return_3d",
        "forward_return_5d",
        "past_return_1d",
        "return_3d",
        "return_5d",
        "return_acceleration_5d",
        "close",
        "high",
        "low",
        "open",
        "volume",
        "amount",
        "turnover_rate",
    }
    factor_cols = [
        c
        for c in factor_df.columns
        if c not in exclude
        and c.startswith(
            (
                "amplitude",
                "bollinger",
                "capital",
                "downside",
                "industry",
                "interaction",
                "ma",
                "momentum",
                "near",
                "price",
                "rsi",
                "tail",
                "turnover",
                "volume",
                "amplitude_",
            )
        )
    ]

    # 因子权重 (从 weight_meta.last_day_weights 或 meta.weights 读取, 等权方式自动生成 1/n)
    weight_meta = meta.get("weight_meta", {})
    last_day_weights = weight_meta.get("last_day_weights", {})
    if not last_day_weights:
        # v3.11: icir_weight/ic_weight 的权重存在 meta.weights 中 (非 weight_meta.last_day_weights)
        last_day_weights = meta.get("weights", {})
    if not last_day_weights:
        # equal_weight / icir_weight / ic_weight 无显式权重 → 等权 1/n
        n_factors = len(factor_cols) if factor_cols else 1
        last_day_weights = dict.fromkeys(factor_cols, 1.0 / n_factors)
        logger.info(
            "save_lr_training_data: 无显式权重 (weight_method=%s), 生成等权 1/%d",
            weight_method,
            n_factors,
        )

    # 映射因子逻辑名→列名
    name_to_col = {v: k for k, v in FACTOR_COL_TO_NAME_MAP.items()}
    weights_col_map = {name_to_col.get(k, k): v for k, v in last_day_weights.items()}

    # 股票名称映射
    stock_name_map = _load_stock_name_map()

    # 构建行数据
    run_id = str(uuid.uuid4())
    created_at = datetime.now(timezone.utc)

    rows: list[dict[str, Any]] = []
    for stock in bottom_stocks:
        code = stock["code"]
        composite_value = float(stock["composite_value"])
        rank = int(stock.get("rank", 0))

        row: dict[str, Any] = {
            "rank": rank,
            "code": code,
            "stock_name": stock_name_map.get(code, ""),
            "composite_value": composite_value,
            "composite_score": composite_score,
            "factor_direction": config.factor_direction,
            # weight_method 是 Hive 分区键, 不写入 body (与 selection_date 同理)
            "forward_return_1d": None,  # 次日补写
            "created_at": created_at,
            "run_id": run_id,
        }

        # 因子权重列 (weight_<factor_col>)
        for fcol, w_val in weights_col_map.items():
            row[f"weight_{fcol}"] = float(w_val)

        # 因子原始值列 (factor_<factor_col>)
        if code in factor_df["asset"].values:
            stock_row = factor_df[factor_df["asset"] == code].iloc[0]
            for fcol in factor_cols:
                val = stock_row.get(fcol)
                row[f"factor_{fcol}"] = float(val) if pd.notna(val) else None
        else:
            for fcol in factor_cols:
                row[f"factor_{fcol}"] = None

        rows.append(row)

    df = pd.DataFrame(rows)

    # 显式 schema
    schema_fields = [
        pa.field("rank", pa.int16(), nullable=False),
        pa.field("code", pa.string(), nullable=False),
        pa.field("stock_name", pa.string(), nullable=True),
        pa.field("composite_value", pa.float64(), nullable=False),
        pa.field("composite_score", pa.float64(), nullable=False),
        pa.field("factor_direction", pa.string(), nullable=False),
        # weight_method 是 Hive 分区键, 不在 schema 中 (pyarrow 读取时自动注入)
        pa.field("forward_return_1d", pa.float64(), nullable=True),
        pa.field("created_at", pa.timestamp("us", tz="UTC"), nullable=False),
        pa.field("run_id", pa.string(), nullable=False),
    ]
    # 动态添加权重列和因子列
    weight_col_names = [f"weight_{c}" for c in weights_col_map]
    factor_col_names = [f"factor_{c}" for c in factor_cols]
    for cn in weight_col_names:
        schema_fields.append(pa.field(cn, pa.float64(), nullable=True))
    for cn in factor_col_names:
        schema_fields.append(pa.field(cn, pa.float64(), nullable=True))

    schema = pa.schema(schema_fields)

    # 写入: 双分区 weight_method/selection_date
    dataset_root = Path(LR_TRAINING_DATA_DIR)
    partition_dir = dataset_root / f"weight_method={weight_method}" / f"selection_date={selection_date}"

    try:
        table = pa.Table.from_pandas(df, schema=schema, preserve_index=False)
    except (pa.ArrowException, ValueError, TypeError) as e:
        logger.exception("save_lr_training_data: DataFrame → Arrow Table 转换失败")
        raise RuntimeError(f"save_lr_training_data: schema 转换失败: {type(e).__name__}: {e}") from e

    # file-level metadata
    existing_meta = table.schema.metadata or {}
    table = table.replace_schema_metadata(
        {
            **existing_meta,
            b"weight_method": weight_method.encode("utf-8"),
            b"selection_date": selection_date.encode("utf-8"),
            b"n_stocks": str(len(rows)).encode("utf-8"),
            b"factor_cols_json": json.dumps(factor_cols, ensure_ascii=False).encode("utf-8"),
            b"weight_cols_json": json.dumps(weight_col_names, ensure_ascii=False).encode("utf-8"),
            b"generated_at": created_at.strftime("%Y-%m-%dT%H:%M:%S%z").encode("utf-8"),
        }
    )

    try:
        partition_dir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        logger.exception("save_lr_training_data: 创建分区目录失败: %s", partition_dir)
        raise RuntimeError(f"save_lr_training_data: 创建目录失败: {partition_dir}") from e

    target_path = partition_dir / "part-0.parquet"
    temp_path = partition_dir / "part-0.parquet.tmp"
    replaced = False
    try:
        pq.write_table(table, temp_path, compression="snappy")
        os.replace(temp_path, target_path)
        replaced = True
    except (pa.ArrowException, OSError) as e:
        logger.exception("save_lr_training_data: Parquet 写入失败: %s", target_path)
        raise RuntimeError(f"save_lr_training_data: 写入失败: {target_path}") from e
    finally:
        if not replaced:
            temp_path.unlink(missing_ok=True)

    logger.info(
        "LR 训练数据已写入: %s (n=%d, 权重列=%d, 因子列=%d, 大小=%.2f KB)",
        partition_dir,
        len(rows),
        len(weight_col_names),
        len(factor_col_names),
        target_path.stat().st_size / 1024,
    )
    return partition_dir


def backfill_forward_return_1d(
    data_source: str | Path,
    logger: logging.Logger | None = None,
) -> int:
    """v3.10: 补写 lr_training_data 中 forward_return_1d 为 null 的分区.

    流程:
    1. 扫描 lr_training_data 下所有 weight_method/selection_date 分区
    2. 找到 forward_return_1d 为 null 的分区
    3. 从 data_source 读取次日 forward_return_1d
    4. 原子覆盖回写

    Returns:
        补写的行数
    """
    if logger is None:
        logger = _logger

    import pyarrow as pa
    import pyarrow.parquet as pq
    from paths import LR_TRAINING_DATA_DIR

    dataset_root = Path(LR_TRAINING_DATA_DIR)
    if not dataset_root.exists():
        logger.info("backfill: lr_training_data 目录不存在, 跳过")
        return 0

    # 扫描所有分区
    total_backfilled = 0
    for wm_dir in sorted(dataset_root.iterdir()):
        if not wm_dir.is_dir() or not wm_dir.name.startswith("weight_method="):
            continue
        weight_method = wm_dir.name.replace("weight_method=", "")

        for date_dir in sorted(wm_dir.iterdir()):
            if not date_dir.is_dir() or not date_dir.name.startswith("selection_date="):
                continue
            selection_date = date_dir.name.replace("selection_date=", "")
            parquet_path = date_dir / "part-0.parquet"
            if not parquet_path.exists():
                continue

            # 读取现有数据
            try:
                table = pq.read_table(parquet_path)
                df = table.to_pandas()
            except (OSError, ValueError) as e:
                logger.warning("backfill: 读取 %s 失败: %s", parquet_path, e)
                continue

            # 检查是否需要补写
            if "forward_return_1d" not in df.columns:
                continue
            null_mask = df["forward_return_1d"].isna()
            if not null_mask.any():
                continue  # 已补写

            # 从 data_source 读取次日 forward_return_1d
            try:
                full_df = pd.read_parquet(
                    data_source,
                    columns=["date", "asset", "forward_return_1d"],
                )
                # 次日数据: selection_date 的 forward_return_1d 就是 T+1 收益
                next_day_data = full_df[
                    full_df["date"].apply(lambda d: pd.Timestamp(d).strftime("%Y-%m-%d")) == selection_date
                ]
                code_to_ret = dict(zip(next_day_data["asset"], next_day_data["forward_return_1d"], strict=True))

                # 补写
                for idx in df[null_mask].index:
                    code = df.loc[idx, "code"]
                    if code in code_to_ret:
                        ret = code_to_ret[code]
                        df.loc[idx, "forward_return_1d"] = float(ret) if pd.notna(ret) else None

                # 仍为 null 的说明次日数据不可用 (可能是最新一天, 还没 T+1)
                still_null = df["forward_return_1d"].isna().sum()
                if still_null == len(df):
                    logger.debug("backfill: %s/%s 次日数据不可用, 跳过", weight_method, selection_date)
                    continue

                # 原子覆盖回写
                schema = table.schema
                new_table = pa.Table.from_pandas(df, schema=schema, preserve_index=False)
                temp_path = parquet_path.parent / "part-0.parquet.tmp"
                pq.write_table(new_table, temp_path, compression="snappy")
                os.replace(temp_path, parquet_path)

                backfilled = int(len(df) - still_null - (~null_mask).sum())
                total_backfilled += backfilled
                logger.info(
                    "backfill: %s/%s 补写 %d 行 (剩余 %d 行无次日数据)",
                    weight_method,
                    selection_date,
                    backfilled,
                    still_null,
                )
            except (OSError, ValueError, KeyError) as e:
                logger.warning("backfill: %s/%s 失败: %s", weight_method, selection_date, e)
                continue

    if total_backfilled > 0:
        logger.info("backfill: 共补写 %d 行 forward_return_1d", total_backfilled)
    return total_backfilled
