"""
数据切分器：将主数据源按日期范围切分为 train / test / holdout 三个子集。

遵循 reverse_discovery/MODULE.md：
- D2: 时间隔离——训练段与验证段不重叠，purge 窗口隔离
- D3: 不修改主数据源，只生成子集文件
- P1: Walk-Forward 切分规则（本脚本实现单次切分，Walk-Forward 多轮后续增强）
- P2: Purge 窗口 = 2 天（交易日）
- P3: 时序对齐——因子@T-1 ↔ 收益@T

输出 schema 与主数据源完全一致（dates + data），额外增加 metadata 字段。
正向 pipeline（factor_ic / backtest）只读 dates + data，metadata 不影响兼容。

使用方式：
    from reverse_discovery.data_splitter import split_data

    split_data(
        train_end="2026-03-15",
        test_end="2026-05-10",
        purge_days=2,
    )

CLI 入口：
    python -m reverse_discovery.data_splitter --train-end 2026-03-15 --test-end 2026-05-10

更新历史：
- v1.0 (2026-06-18): 初始版本，单次切分 + ijson 流式读写
"""

import gzip
import json
from datetime import datetime
from pathlib import Path

import ijson
from paths import FACTOR_IC_DATA, REVERSE_DISCOVERY_RESULT
from reverse_discovery.common.logger_config import get_logger


logger = get_logger(__name__)

__version__ = "1.0"


def compute_date_splits(
    dates: list[str],
    train_end: str,
    test_end: str,
    purge_days: int = 2,
) -> dict[str, list[str]]:
    """
    根据日期范围和 purge 窗口，计算 train / test / holdout 三段日期列表。

    切分逻辑（遵循 MODULE.md P2）：
        dates 数组中日期按升序排列：
        - train: dates[0] ~ dates[train_cutoff_idx]（train_end 往前剔除 purge_days 个交易日）
        - test:  train_end < d <= test_end
        - holdout: d > test_end

    参数:
        dates: 主数据源中所有交易日期（升序，"YYYY-MM-DD" 字符串）
        train_end: 训练段截止日期（"YYYY-MM-DD"）
        test_end: 测试段截止日期（"YYYY-MM-DD"）
        purge_days: purge 窗口天数（交易日数，默认 2）

    返回:
        {"train": [...], "test": [...], "holdout": [...]}

    异常:
        ValueError: train_end / test_end 不在 dates 范围内，或 train_end >= test_end
    """
    if not dates:
        raise ValueError("dates 列表为空")

    if train_end >= test_end:
        raise ValueError(f"train_end ({train_end}) 必须早于 test_end ({test_end})")

    # 校验 train_end 和 test_end 在 dates 范围内
    if train_end < dates[0]:
        raise ValueError(f"train_end ({train_end}) 早于数据起始日期 ({dates[0]})")
    if test_end > dates[-1]:
        raise ValueError(f"test_end ({test_end}) 晚于数据结束日期 ({dates[-1]})")

    # 找到 train_end 在 dates 中的索引
    train_end_idx = None
    for i, d in enumerate(dates):
        if d == train_end:
            train_end_idx = i
            break
    if train_end_idx is None:
        raise ValueError(f"train_end ({train_end}) 不在 dates 列表中")

    # train_cutoff_idx = train_end_idx - purge_days
    # train 段包含 dates[0] ~ dates[train_cutoff_idx]
    train_cutoff_idx = train_end_idx - purge_days
    if train_cutoff_idx < 0:
        raise ValueError(f"purge_days ({purge_days}) 过大，train 段为空（train_end_idx={train_end_idx}）")

    train_dates = dates[: train_cutoff_idx + 1]
    test_dates = [d for d in dates if train_end < d <= test_end]
    holdout_dates = [d for d in dates if d > test_end]

    # 校验三段无重叠
    train_set = set(train_dates)
    test_set = set(test_dates)
    holdout_set = set(holdout_dates)
    assert not (train_set & test_set), "train 与 test 有重叠"
    assert not (train_set & holdout_set), "train 与 holdout 有重叠"
    assert not (test_set & holdout_set), "test 与 holdout 有重叠"

    return {
        "train": train_dates,
        "test": test_dates,
        "holdout": holdout_dates,
    }


def _build_metadata(
    split_type: str,
    train_end: str,
    test_end: str,
    purge_days: int,
    date_range: dict[str, str],
    trading_days: int,
    parent_source: str,
) -> dict:
    """
    构建子集文件的 metadata 字段。

    遵循 MODULE.md 输出结构模板 + AGENTS.md 硬规则 #4（字段非空）。
    """
    return {
        "source": "reverse_discovery/data_splitter.py",
        "split_type": split_type,
        "split_train_end_date": train_end,
        "split_test_end_date": test_end,
        "split_purge_days": purge_days,
        "date_range": date_range,
        "trading_days": trading_days,
        "parent_source": parent_source,
        "generated_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
    }


def _write_subset(
    output_path: Path,
    metadata: dict,
    subset_dates: list[str],
    data_source: Path,
    target_dates: set[str],
) -> int:
    """
    流式写入一个子集文件。

    用 ijson 流式读取主数据源的 data 数组，过滤出 target_dates 中的记录，
    流式写入输出文件。不在内存中累积全部记录。

    参数:
        output_path: 输出文件路径
        metadata: metadata 字典
        subset_dates: 该子集的日期列表（写入 dates 字段）
        data_source: 主数据源路径
        target_dates: 该子集需要保留的日期集合

    返回:
        写入的记录数
    """
    logger.info("写入子集文件: %s", output_path)
    logger.info("目标日期数: %d", len(target_dates))

    output_path.parent.mkdir(parents=True, exist_ok=True)

    n_records = 0
    with gzip.open(output_path, "wt", encoding="utf-8") as out_f:
        # 1. 写 metadata + dates（小数据，直接 json.dumps）
        out_f.write('{"metadata": ')
        out_f.write(json.dumps(metadata, ensure_ascii=False))
        out_f.write(', "dates": ')
        out_f.write(json.dumps(subset_dates, ensure_ascii=False))
        out_f.write(', "data": [')

        # 2. 流式读 data 数组，过滤 + 写入
        first_record = True
        with gzip.open(data_source, "rb") as in_f:
            for record in ijson.items(in_f, "data.item", use_float=True):
                record_date = record.get("date")
                if record_date not in target_dates:
                    continue
                if not first_record:
                    out_f.write(",")
                out_f.write(json.dumps(record, ensure_ascii=False))
                first_record = False
                n_records += 1

        # 3. 闭合 data 数组和 JSON 对象
        out_f.write("]}")

    logger.info("写入完成: %d 条记录", n_records)
    return n_records


def split_data(
    train_end: str,
    test_end: str,
    purge_days: int = 2,
    data_source: Path | None = None,
    output_dir: Path | None = None,
) -> dict[str, Path | None]:
    """
    将主数据源切分为 train / test / holdout 三个子集文件。

    参数:
        train_end: 训练段截止日期（"YYYY-MM-DD"）
        test_end: 测试段截止日期（"YYYY-MM-DD"）
        purge_days: purge 窗口天数（交易日，默认 2）
        data_source: 主数据源路径（默认 paths.FACTOR_IC_DATA）
        output_dir: 输出目录（默认 paths.REVERSE_DISCOVERY_RESULT）

    返回:
        {"train": Path, "test": Path, "holdout": Path}

    异常:
        FileNotFoundError: 主数据源不存在
        ValueError: 日期参数不合法
    """
    data_source = data_source or FACTOR_IC_DATA
    output_dir = output_dir or REVERSE_DISCOVERY_RESULT

    if not data_source.exists():
        raise FileNotFoundError(f"主数据源不存在: {data_source}\n请先运行 data_fetchers/factor_generator.py 生成数据")

    logger.info("=== 数据切分开始 ===")
    logger.info("主数据源: %s", data_source)
    logger.info("train_end=%s, test_end=%s, purge_days=%d", train_end, test_end, purge_days)

    # 1. 流式读取 dates 数组
    logger.info("读取 dates 数组...")
    with gzip.open(data_source, "rb") as f:
        dates = list(ijson.items(f, "dates.item", use_float=True))
    logger.info("交易日总数: %d", len(dates))

    # 2. 计算三段日期
    splits = compute_date_splits(dates, train_end, test_end, purge_days)

    train_dates = splits["train"]
    test_dates = splits["test"]
    holdout_dates = splits["holdout"]

    logger.info("train: %d 天 (%s ~ %s)", len(train_dates), train_dates[0], train_dates[-1])
    if test_dates:
        logger.info("test: %d 天 (%s ~ %s)", len(test_dates), test_dates[0], test_dates[-1])
    else:
        logger.warning("test 段为空")
    if holdout_dates:
        logger.info("holdout: %d 天 (%s ~ %s)", len(holdout_dates), holdout_dates[0], holdout_dates[-1])
    else:
        logger.warning("holdout 段为空")

    # 3. 写入三个子集文件
    parent_source_str = str(data_source)

    # train
    train_meta = _build_metadata(
        "train",
        train_end,
        test_end,
        purge_days,
        {"start": train_dates[0], "end": train_dates[-1]},
        len(train_dates),
        parent_source_str,
    )
    train_path = output_dir / f"factor_ic_data_train_{train_end}.json.gz"
    _write_subset(train_path, train_meta, train_dates, data_source, set(train_dates))

    # test
    test_path = output_dir / f"factor_ic_data_test_{train_end}.json.gz"
    if test_dates:
        test_meta = _build_metadata(
            "test",
            train_end,
            test_end,
            purge_days,
            {"start": test_dates[0], "end": test_dates[-1]},
            len(test_dates),
            parent_source_str,
        )
        _write_subset(test_path, test_meta, test_dates, data_source, set(test_dates))
    else:
        logger.warning("test 段为空，跳过写入 test 文件")
        test_path = None

    # holdout
    holdout_path = output_dir / "factor_ic_data_holdout.json.gz"
    if holdout_dates:
        holdout_meta = _build_metadata(
            "holdout",
            train_end,
            test_end,
            purge_days,
            {"start": holdout_dates[0], "end": holdout_dates[-1]},
            len(holdout_dates),
            parent_source_str,
        )
        _write_subset(holdout_path, holdout_meta, holdout_dates, data_source, set(holdout_dates))
    else:
        logger.warning("holdout 段为空，跳过写入 holdout 文件")
        holdout_path = None

    logger.info("=== 数据切分完成 ===")
    return {"train": train_path, "test": test_path, "holdout": holdout_path}


def main():
    """
    CLI 主入口。

    用法:
        python -m reverse_discovery.data_splitter \\
            --train-end 2026-03-15 \\
            --test-end 2026-05-10 \\
            --purge-days 2
    """
    import argparse

    parser = argparse.ArgumentParser(description="逆向因子发现 - 数据切分器")
    parser.add_argument("--train-end", required=True, help="训练段截止日期（YYYY-MM-DD）")
    parser.add_argument("--test-end", required=True, help="测试段截止日期（YYYY-MM-DD）")
    parser.add_argument("--purge-days", type=int, default=2, help="Purge 窗口天数（交易日，默认 2）")
    parser.add_argument(
        "--data-source",
        type=str,
        default=None,
        dest="data_source",
        help="主数据源路径（默认使用 factor_ic_data.json.gz）",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default=None,
        dest="output_dir",
        help="输出目录（默认 reverse_discovery/result/）",
    )

    args = parser.parse_args()

    result = split_data(
        train_end=args.train_end,
        test_end=args.test_end,
        purge_days=args.purge_days,
        data_source=Path(args.data_source) if args.data_source else None,
        output_dir=Path(args.output_dir) if args.output_dir else None,
    )

    for name, path in result.items():
        if path is not None:
            logger.info("[CLI] %s -> %s", name, path)
        else:
            logger.info("[CLI] %s -> (空，未生成)", name)


if __name__ == "__main__":
    main()
