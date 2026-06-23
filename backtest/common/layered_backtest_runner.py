"""
分层回测公共入口模块

功能:
1. 提供统一的分层回测入口函数 run_layered_backtest
2. 抽象 Config 基类 LayerConfigBase
3. 抽象数据加载、回测执行、结果保存逻辑

设计参考:
- factor_ic/common/factor_ic_runner.py (run_simple_factor_ic)
- PROJECT.md 公共模块强制复用规范

使用方式:
```python
from backtest.common.layered_backtest_runner import run_layered_backtest, LayerConfigBase


# 定义因子特有 Config（薄声明模式：只声明 ClassVar 元数据，逻辑下沉基类）
class MyFactorLayerConfig(LayerConfigBase):
    factor_name: ClassVar[str] = "my_factor"
    factor_col: ClassVar[str] = "my_factor_value"  # 可选，默认=factor_name
    layer_names: ClassVar[Sequence[str]] = ("lowest", "lower", "normal", "higher", "highest")
    layer_descriptions: ClassVar[Sequence[str]] = ("极低层", "偏低层", "正常层", "偏高层", "极高层")
    # n_layers/factor_direction/long_layers/short_layers 由基类自动派生


# 调用公共入口
result = run_layered_backtest(
    factor_name="my_factor",
    factor_col="my_factor_value",
    config=MyFactorLayerConfig(),
    factor_calculator=my_calculate_func,  # 可选，预计算因子传 None
    data_source="path/to/factor_ic_data.json.gz",  # 可选
    logger=logger,
)
```

作者: 云瑶
创建日期: 2026-05-23
"""

import gzip
import json
import logging
import os
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, ClassVar, Literal

import pandas as pd

from backtest.common.convert_types import convert_to_native_types
from backtest.common.layered_backtest import LayeredBacktestEngine

# 导入公共模块
from backtest.common.logger_config import get_logger


# ============================================================================
# 项目根目录获取（可移植方式）
# ============================================================================


def _get_project_root() -> Path:
    """获取项目根目录（可移植方式）

    优先级：
    1. 环境变量 FACTOR_IC_ROOT
    2. 配置文件 factor_ic_root.txt（当前目录或父目录）
    3. backtest 模块上两级（从 common/ 模块位置推导）

    返回：
        项目根目录 Path 对象
    """
    # 1. 环境变量
    env_root = os.environ.get("FACTOR_IC_ROOT")
    if env_root:
        return Path(env_root)

    # 2. 配置文件
    for search_dir in [Path.cwd(), Path.cwd().parent]:
        config_file = search_dir / "factor_ic_root.txt"
        if config_file.exists():
            return Path(config_file.read_text().strip())

    # 3. 从模块位置推导（backtest/common/layered_backtest_runner.py 上两级）
    # __file__ = .../backtest/common/layered_backtest_runner.py
    # parent = backtest/common/
    # parent.parent = backtest/
    # parent.parent.parent = 项目根目录
    try:
        module_path = Path(__file__).resolve()
        return module_path.parent.parent.parent
    except Exception:
        # 最后兜底：当前工作目录
        return Path.cwd()


PROJECT_ROOT = _get_project_root()


# ============================================================================
# Config 基类
# ============================================================================


@dataclass
class LayerConfigBase:
    """分层配置基类

    子类只需声明：
    - factor_name: ClassVar[str]（因子名称，用于日志、结果文件命名）
    - factor_col: ClassVar[str]（数据源列名，默认=factor_name，预计算因子需显式声明）
    - layer_names: ClassVar[Sequence[str]]（分层标签，纯英文/拼音，用于目录/列名）
    - layer_descriptions: ClassVar[Sequence[str]]（分层描述，含中文，用于日志显示）

    派生逻辑（基类自动处理）：
    - ic_source: 若子类未声明，按 factor_name 拼接默认路径
    - n_layers: 由 len(layer_names) 派生
    - factor_direction: 从 IC 结果文件加载（ic_mean < 0 为 negative，否则 positive）
    - long_layers/short_layers: 由 n_layers 和 factor_direction 派生
    - layer_names_dict: 运行时转换为 {层号: 描述} 格式供日志显示

    类定义期校验（__init_subclass__，类加载时即生效，违反触发 import-time 失败）：
    - len(layer_names) >= 2
    - len(layer_descriptions) == len(layer_names) （若 layer_descriptions 非空）
      防止文档（"5 层"等模式描述）与实现脱节、防止 layer_names_dict 派生时静默回退。

    示例：
        class Return5dLayerConfig(LayerConfigBase):
            factor_name: ClassVar[str] = 'return_5d'
            layer_names: ClassVar[Sequence[str]] = (
                'lowest', 'lower', 'normal', 'higher', 'highest'
            )
            layer_descriptions: ClassVar[Sequence[str]] = (
                '极低层(5日涨幅最小)',
                '偏低层(5日小幅下跌)',
                '正常层(5日变化不大)',
                '偏高层(5日小幅上涨)',
                '极高层(5日涨幅最大)'
            )
    """

    # === 因子元数据（子类必须声明 factor_name） ===
    factor_name: ClassVar[str] = ""  # 子类必须覆盖
    factor_col: ClassVar[str] = ""  # 子类可选，默认=factor_name
    ic_source: ClassVar[str] = ""  # 子类可选，默认按 factor_name 拼接
    layer_names: ClassVar[Sequence[str]] = ()  # 子类必须覆盖，纯标签（用于目录/列名）
    layer_descriptions: ClassVar[Sequence[str]] = ()  # 子类可选，含中文描述（用于日志）

    # === 运行时派生（实例字段，field(init=False)） ===
    ic_source_resolved: str = field(init=False)  # 实际使用的 IC 文件路径
    layer_names_dict: dict[str, str] = field(init=False)  # 层号→描述映射
    factor_col_resolved: str = field(init=False)  # 实际使用的数据列名
    n_layers: int = field(init=False)

    # === 通用参数（有默认值） ===
    long_layers: list[int] | None = None
    short_layers: list[int] | None = None
    trade_cost_rate: float = 0.003
    min_stocks_per_layer: int = 10

    # === 派生字段（无默认值，field(init=False)） ===
    factor_direction: Literal["positive", "negative"] = field(init=False)

    def __init_subclass__(cls, **kwargs: Any) -> None:
        """类定义期校验：layer_names / layer_descriptions 长度一致性。

        在类加载（import）时即生效，违反时抛 ValueError，按规则 #6 应映射到
        退出码 2（import-time 配置失败）。这是文档（"percentile 5 层"等模式
        描述）与实现的硬契约，防止下游 layer_names_dict 静默回退到英文标签
        而出现"日志少了中文描述但程序仍能跑"的退化场景。
        """
        super().__init_subclass__(**kwargs)
        # 抽象基类自身不参与（factor_name 默认空），仅校验真正的子类声明
        names = cls.layer_names
        if not names:
            return  # 抽象/中间类，留给 __post_init__ 在实例化时再卡 factor_name
        if len(names) < 2:
            raise ValueError(f"{cls.__name__}: layer_names 至少需要 2 层，当前: {len(names)}")
        descs = cls.layer_descriptions
        if descs and len(descs) != len(names):
            raise ValueError(
                f"{cls.__name__}: layer_descriptions 长度({len(descs)}) "
                f"与 layer_names 长度({len(names)}) 不一致，"
                f"请确保两者一一对应（或将 layer_descriptions 留空以回退到 layer_names）"
            )

    def __post_init__(self):
        """初始化后处理：派生配置 + 打印日志"""
        logger = get_logger(self.factor_name or "backtest")

        # 1. 校验 factor_name
        if not self.factor_name:
            raise ValueError(f"子类必须声明 factor_name ClassVar，当前类: {self.__class__.__name__}")

        # 2. 拼接 ic_source_resolved（子类声明优先，否则默认路径）
        #    子类可显式声明 ic_source 以暴露派生路径
        cls_ic_source = self.__class__.ic_source
        if cls_ic_source:
            self.ic_source_resolved = cls_ic_source
        else:
            self.ic_source_resolved = f"factor_ic/result/ic_{self.factor_name}_1d_analysis_result.json"

        # 3. 派生 factor_col_resolved（子类声明优先，否则回退 factor_name）
        cls_factor_col = self.__class__.factor_col
        if cls_factor_col:
            self.factor_col_resolved = cls_factor_col
        else:
            self.factor_col_resolved = self.factor_name

        # 4. 校验 layer_names
        n = len(self.layer_names)
        if n < 2:
            raise ValueError(f"layer_names 至少需要 2 层，当前: {n}")

        # 5. 派生 n_layers
        self.n_layers = n

        # 6. 生成 layer_names_dict（层序 1-based）
        #    优先使用 layer_descriptions（含中文，用于日志），否则回退 layer_names
        descriptions = self.__class__.layer_descriptions
        if descriptions and len(descriptions) == n:
            self.layer_names_dict = {str(i + 1): desc for i, desc in enumerate(descriptions)}
        else:
            self.layer_names_dict = {str(i + 1): name for i, name in enumerate(self.layer_names)}

        # 6. 加载 IC 元数据，派生 factor_direction
        ic_meta = self._load_ic_meta()
        self.factor_direction = ic_meta["direction"]  # 禁止隐式默认值

        # 7. 派生多空组合
        if self.long_layers is None or self.short_layers is None:
            self.long_layers, self.short_layers = self._derive_long_short()

        # 8. 仅打印派生结果（完整配置摘要由 run_layered_backtest 打印一次）
        logger.info("IC文件: %s", self.ic_source_resolved)
        logger.info("因子方向: %s (来源: IC分析结果, ic_mean=%.4f)", self.factor_direction, ic_meta["ic_mean"])
        # 9. 派生元数据汇总（关键观测点：定位"为什么这个因子的多空层是这样划分的"）
        logger.info(
            "派生元数据汇总: factor_name=%s direction=%s n_layers=%d long_layers=%s short_layers=%s",
            self.factor_name,
            self.factor_direction,
            self.n_layers,
            self.long_layers,
            self.short_layers,
        )

    def _load_ic_meta(self) -> dict[str, Any]:
        """加载 IC 分析结果（基类通用方法）

        从 ic_source JSON 文件读取，统一从 ic_metrics 子字段取值。

        返回：
            {'direction': str, 'ic_mean': float, 'icir': float, 'p_value': float}

        异常：
            FileNotFoundError: IC 文件不存在
            KeyError: direction 字段缺失（禁止隐式默认值）
        """
        ic_file = PROJECT_ROOT / self.ic_source_resolved

        if not ic_file.exists():
            raise FileNotFoundError(
                f"IC 分析结果文件不存在: {ic_file}\n请先运行 factor_ic/{self.factor_name}_1d.py 生成 IC 分析结果"
            )

        with open(ic_file, encoding="utf-8") as f:
            data = json.load(f)

        # 统一从 ic_metrics 子字段读取（问题5修复）
        ic_metrics = data.get("ic_metrics")
        if ic_metrics is None:
            raise KeyError(f"IC 结果文件缺少 'ic_metrics' 字段: {ic_file}\n顶层字段: {list(data.keys())}")

        # 提取必需字段
        ic_mean = ic_metrics.get("ic_mean")
        if ic_mean is None:
            raise KeyError("ic_metrics 缺少 'ic_mean' 字段")

        # direction 从 ic_mean 符号派生（问题5修复：统一来源）
        direction = "negative" if ic_mean < 0 else "positive"

        return {
            "direction": direction,
            "ic_mean": float(ic_mean),
            "icir": float(ic_metrics.get("icir", 0)),
            "p_value": ic_metrics.get("p_value"),
        }

    def _derive_long_short(self) -> tuple[list[int], list[int]]:
        """根据 n_layers 和 factor_direction 派生多空组合

        规则：
        - 正向因子：多头取高层，空头取低层
        - 反向因子：多头取低层，空头取高层
        - 多头/空头各取约 40%（向下取整，至少 1 层）
        """
        if self.n_layers == 1:
            return [1], [1]

        n_long = max(1, int(self.n_layers * 0.4))
        n_short = max(1, int(self.n_layers * 0.4))

        if self.factor_direction == "positive":
            long_layers = list(range(self.n_layers - n_long + 1, self.n_layers + 1))
            short_layers = list(range(1, n_short + 1))
        else:
            long_layers = list(range(1, n_long + 1))
            short_layers = list(range(self.n_layers - n_short + 1, self.n_layers + 1))

        return long_layers, short_layers

    def validate(self) -> None:
        """校验配置完整性"""
        if self.n_layers < 2:
            raise ValueError(f"n_layers 至少需要 2 层，当前: {self.n_layers}")

        if not self.long_layers or not self.short_layers:
            raise ValueError("long_layers 和 short_layers 不能为空")

        for layer_id in self.long_layers:
            if layer_id > self.n_layers or layer_id < 1:
                raise ValueError(f"long_layers 层编号 {layer_id} 越界，有效范围 [1, {self.n_layers}]")

        for layer_id in self.short_layers:
            if layer_id > self.n_layers or layer_id < 1:
                raise ValueError(f"short_layers 层编号 {layer_id} 越界，有效范围 [1, {self.n_layers}]")


# ============================================================================
# 数据加载
# ============================================================================


# 收益列固定 schema（遵循 PROJECT.md 跨模块数据路径规范第 1 条）
_RETURN_COLS: tuple[str, ...] = ("forward_return_1d", "forward_return_3d", "forward_return_5d")
_INDEX_COLS: tuple[str, ...] = ("date", "asset")


def load_factor_return_data(
    data_source: str | Path | None = None,
    required_factor_cols: list[str] | None = None,
    logger: logging.Logger | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """从统一数据源加载因子和收益数据（ijson 流式 + 列过滤）

    参数:
        data_source: 数据源文件路径（默认使用 DEFAULT_DATA_SOURCE）
        required_factor_cols: 因子数据必需字段列表（仅保留这些 + index + return 列）
        logger: 日志对象

    返回:
        (factor_df, return_df)

    更新历史:
        - 2026-05-27 v2.7: 从统一数据源 factor_ic_data.json.gz 读取
        - 2026-06-13 v2.8: 改用 ijson 流式解析 + 列过滤，避免 json.load 全量加载导致 OOM
          (factor_ic_data.json.gz 解压后 2.17GB，json.load 物理内存峰值 4+GB 触发 OOM)
        - 2026-06-13 v2.8.1: 修复 numeric_cols 误纳入 _INDEX_COLS 导致
          float('YYYY-MM-DD') ValueError（return_3d / past_return_1d / return_5d /
          ma5_deviation / near_high_ratio_5 等 required_cols 含 'date'/'asset' 的因子）

    注意:
        - 遵循 PROJECT.md 跨模块数据路径规范
        - factor_ic_data.json.gz 包含行情+因子+收益数据，单文件读取
        - 流式解析逐条 yield 记录，结合 keep_cols 列过滤，内存峰值降低 ~10x
    """
    from backtest.common.data_loader import DEFAULT_DATA_SOURCE

    if logger is None:
        logger = get_logger(__name__)

    # 使用默认数据源
    if data_source is None:
        data_source = DEFAULT_DATA_SOURCE

    data_source = Path(data_source)

    # 加载统一数据源
    logger.info("加载统一数据源: %s", data_source)

    if not data_source.exists():
        raise FileNotFoundError(
            f"统一数据源文件不存在: {data_source}\n请先运行 data_fetchers/factor_generator.py 生成数据"
        )

    # 1) 计算需要保留的列集合（最小必要列）
    #    - index: date, asset（必须，str 类型）
    #    - return: forward_return_1d/3d/5d（必须，float 类型，分离到 return_df）
    #    - factor: required_factor_cols 指定的因子列（仅保留这些，假定 float 类型）
    #
    # 注意：此处不做顶层 key 校验。yajl2_c 后端的 ijson.kvitems(f, "") 在尝试
    # yield "data" key 之前会完整解析 data 对应的 value（1.5M 条 list），导致
    # 4 GB+ 内存峰值（与 json.load 等价）。改为：直接流式 ijson.items(f, "data.item")，
    # 若 'data' 不存在则 yield 0 条，下面用 n_records == 0 兜底报错。
    keep_cols: set[str] = set(_INDEX_COLS) | set(_RETURN_COLS)
    if required_factor_cols:
        keep_cols |= set(required_factor_cols)
    # is_untradeable: 不可交易标记列（涨停类），回测需排除
    keep_cols.add("is_untradeable")
    # is_low_liquidity (R1): 低流动性标记列（截面成交额 P5），回测需排除
    keep_cols.add("is_low_liquidity")

    # 数值列白名单：return + factor（数据源中数值以 Decimal/字符串序列化，需提前 float 化）
    # 显式排除 _INDEX_COLS：date/asset 是 str，部分因子（如 return_3d / past_return_1d /
    # ma5_deviation 等）的 required_cols 含 'date'/'asset'，若纳入数值白名单将触发
    # float('YYYY-MM-DD') ValueError（factor_cli 退出码 3 = DATA_STRUCTURE_ERROR）。
    # 3) 读取数据（Parquet 列式存储）
    import pyarrow.parquet as pq

    logger.info("从 Parquet 读取: %s", data_source)

    schema = pq.read_schema(data_source)
    available_cols = set(schema.names)
    read_cols = [col for col in sorted(keep_cols) if col in available_cols]

    # 列投影读取（物理只读目标列）
    full_df: pd.DataFrame = pd.read_parquet(data_source, columns=read_cols)

    # 补充缺失列为 NaN
    for col in keep_cols:
        if col not in full_df.columns:
            full_df[col] = pd.NA

    # 校验收益列存在
    for col in _RETURN_COLS:
        if col not in available_cols:
            raise ValueError(f"数据源中缺少收益列 '{col}'，当前列: {sorted(available_cols)}")

    # 校验必需因子列存在
    if required_factor_cols:
        for col in required_factor_cols:
            if col not in available_cols:
                available_factor = [c for c in sorted(available_cols) if c not in _INDEX_COLS and c not in _RETURN_COLS]
                raise ValueError(f"因子数据中缺少 '{col}' 列\n可用因子列: {available_factor}")

    logger.info(
        "统一数据源(Parquet): %d 条记录，原始 %d 列 → 读取 %d 列",
        len(full_df),
        len(available_cols),
        len(full_df.columns),
    )

    # 5.5) 过滤不可交易股票（涨停类，T 日尾盘无法买入）
    # 向后兼容: 旧数据无此列时跳过过滤
    if "is_untradeable" in full_df.columns:
        untradeable_mask = full_df["is_untradeable"].fillna(0).astype(int) == 1
        untradeable_count = int(untradeable_mask.sum())
        if untradeable_count > 0:
            full_df = full_df[~untradeable_mask].reset_index(drop=True)
            logger.info(
                "过滤不可交易股票(涨停类): 排除 %d 条, 剩余 %d 条",
                untradeable_count,
                len(full_df),
            )
    else:
        logger.warning("数据缺少 is_untradeable 列，跳过不可交易股票过滤")

    # 5.6) 过滤低流动性股票 (R1, designs/feat_liquidity_filter_to_factor_generator.md)
    # 截面成交额 P5 切除尾部, 排除 IC 假设失效区.
    # 向后兼容: 旧数据无此列时跳过过滤.
    if "is_low_liquidity" in full_df.columns:
        low_liq_mask = full_df["is_low_liquidity"].fillna(0).astype(int) == 1
        low_liq_count = int(low_liq_mask.sum())
        if low_liq_count > 0:
            full_df = full_df[~low_liq_mask].reset_index(drop=True)
            logger.info(
                "过滤低流动性股票(截面成交额 P5): 排除 %d 条, 剩余 %d 条",
                low_liq_count,
                len(full_df),
            )
    else:
        logger.warning("数据缺少 is_low_liquidity 列，跳过低流动性股票过滤")

    # 6) 分离 return_df / factor_df
    #    用 .copy() 切片产生独立 DataFrame，然后 del full_df 释放原引用
    #    避免 full_df + return_df + factor_df 三份同时存在导致内存翻倍
    return_df = full_df[list(_INDEX_COLS) + list(_RETURN_COLS)].copy()
    logger.info("收益数据: %d 条记录", len(return_df))

    # is_untradeable / is_low_liquidity 是过滤辅助列，不应出现在 factor_df
    _AUX_COLS = {"is_untradeable", "is_low_liquidity"}
    factor_cols = [col for col in full_df.columns if col not in _RETURN_COLS and col not in _AUX_COLS]
    factor_df = full_df[factor_cols].copy()
    logger.info("因子数据: %d 条记录，%d 列", len(factor_df), len(factor_cols))

    # 释放 full_df 引用（return_df / factor_df 已是独立切片）
    del full_df

    return factor_df, return_df


# ============================================================================
# 公共入口函数
# ============================================================================


def run_layered_backtest(
    factor_name: str,
    factor_col: str,
    config: LayerConfigBase,
    factor_calculator: Callable | None = None,
    required_factor_cols: list[str] | None = None,
    data_source: str | Path | None = None,
    output_dir: str | Path | None = None,
    verbose: bool = True,
    logger: logging.Logger | None = None,
) -> dict:
    """分层回测公共入口

    参数:
        factor_name: 因子名称（用于输出文件命名）
        factor_col: 因子列名（在 factor_df 中）
        config: 分层配置对象（继承 LayerConfigBase）
        factor_calculator: 因子计算函数（可选，若因子已在数据源中则不需要）
        required_factor_cols: 因子数据必需字段列表（可选）
        data_source: 数据源文件路径（可选，默认使用 DEFAULT_DATA_SOURCE）
        output_dir: 输出目录（默认 backtest/result/）
        verbose: 是否打印详细信息
        logger: 日志对象

    返回:
        回测结果字典

    更新历史（2026-05-27）：
        - v2.7: 移除 cache_dir 和 additional_data_files 参数，改为统一数据源

    使用示例:
        # 简单因子（已在数据源中）
        result = run_layered_backtest(
            factor_name='volume_ratio',
            factor_col='volume_ratio_5',
            config=VolumeRatioLayerConfig()
        )

        # 需要计算的因子（turnover_surge 已在数据源中）
        result = run_layered_backtest(
            factor_name='turnover_surge',
            factor_col='turnover_surge',
            config=TurnoverSurgeLayerConfig(),
            required_factor_cols=['turnover_rate', 'close']
        )
    """
    if logger is None:
        logger = get_logger(__name__)

    # 校验配置
    config.validate()

    logger.info("=" * 40)
    logger.info("%s 分层回测", factor_name)
    logger.info("=" * 40)

    if verbose:
        logger.info("配置信息:")
        logger.info("  分层数量: %d (percentile)", config.n_layers)
        logger.info("  因子方向: %s", config.factor_direction)
        logger.info("  多头组合: Layer %s", config.long_layers)
        logger.info("  空头组合: Layer %s", config.short_layers)
        logger.info("  最小股票数: %d", config.min_stocks_per_layer)
        logger.info("  交易成本率: %.2f%%", config.trade_cost_rate * 100)

    # 加载数据（从统一数据源）
    factor_df, return_df = load_factor_return_data(
        data_source=data_source, required_factor_cols=required_factor_cols, logger=logger
    )

    # 因子计算（如果需要）
    if factor_calculator:
        logger.info("计算 %s 因子...", factor_name)
        factor_df = factor_calculator(factor_df)

    # 校验因子列存在
    if factor_col not in factor_df.columns:
        available_cols = [c for c in factor_df.columns if c not in ["date", "asset"]]
        raise ValueError(f"因子列 '{factor_col}' 不存在于 factor_df 中，可用因子列: {available_cols}")

    # 数据统计
    if verbose:
        logger.info("数据统计:")
        logger.info("  日期范围: %s ~ %s", factor_df["date"].min(), factor_df["date"].max())
        logger.info("  股票数量: %d", factor_df["asset"].nunique())
        valid_factor = factor_df[factor_col].dropna()
        if len(valid_factor) > 0:
            logger.info("  %s 范围: %.2f ~ %.2f", factor_col, valid_factor.min(), valid_factor.max())
            logger.info("  %s 均值: %.2f", factor_col, valid_factor.mean())

    # percentile 分层无需阈值验证（自适应数据范围）

    # 创建回测引擎
    logger.info("创建回测引擎...")
    engine = LayeredBacktestEngine(
        factor_df=factor_df,
        return_df=return_df,
        factor_col=factor_col,
        return_col="forward_return_1d",
        date_col="date",
        asset_col="asset",
    )

    # 执行分层回测
    logger.info("执行分层回测...")
    # percentile 模式：强制使用（v1.5 规范），每层固定比例

    result = engine.run(
        layer_method="percentile",
        n_layers=config.n_layers,
        factor_direction=config.factor_direction,
        long_layers=config.long_layers,
        short_layers=config.short_layers,
        min_stocks_per_layer=config.min_stocks_per_layer,
        trade_cost_rate=config.trade_cost_rate,
    )

    # 添加因子特定信息
    result["meta"]["factor_name"] = factor_name
    result["meta"]["layer_names"] = config.layer_names

    # 生成报告
    report = engine.generate_report(result)
    logger.info(report)

    # 分层说明
    logger.info("=" * 40)
    logger.info("%s 分层说明", factor_name)
    logger.info("=" * 40)
    for layer_id in range(1, config.n_layers + 1):
        layer_key = str(layer_id)
        name = config.layer_names_dict.get(layer_key, f"Layer{layer_id}")
        logger.info(
            "  Layer%d (%s): percentile %d-%d%%",
            layer_id,
            name,
            (layer_id - 1) * 100 // config.n_layers,
            layer_id * 100 // config.n_layers,
        )

    # 保存结果
    if output_dir is None:
        output_dir = PROJECT_ROOT / "backtest" / "result"

    Path(output_dir).mkdir(parents=True, exist_ok=True)

    output_file = Path(output_dir) / f"{factor_name}_layered_backtest.json"

    output_data = {
        "meta": result["meta"],
        "layer_stats": result["layer_stats"],
        "long_short": result["long_short"],
        "monotonicity": result["monotonicity"],
        "trading_cost_analysis": result["trading_cost_analysis"],
        "config": {
            "n_layers": config.n_layers,
            "layer_names": config.layer_names,
            "factor_direction": config.factor_direction,
            "long_layers": config.long_layers,
            "short_layers": config.short_layers,
            "trade_cost_rate": config.trade_cost_rate,
            "min_stocks_per_layer": config.min_stocks_per_layer,
        },
        "created_at": datetime.now().isoformat(),
    }

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(convert_to_native_types(output_data), f, indent=2, ensure_ascii=False)

    logger.info("结果已保存: %s", output_file)

    # 保存每日明细
    daily_file = Path(output_dir) / f"{factor_name}_layered_backtest_daily.json.gz"
    daily_data = {
        "meta": {
            "n_days": result["meta"]["n_days_total"],
            "columns": ["date", "layer", "n_stocks", "return", "turnover"],
        },
        "data": result["daily_records"],
    }

    with gzip.open(daily_file, "wt", encoding="utf-8") as f:
        json.dump(convert_to_native_types(daily_data), f, indent=2, ensure_ascii=False)

    logger.info("每日明细已保存: %s", daily_file)

    return result


# ============================================================================
# CLI 入口
# ============================================================================

# create_cli_entrypoint 已被 factor_cli_main (factor_cli.py) 完全替代
# 删除原因：
# 1. 所有回测脚本均已迁移至 factor_cli_main（grep 验证：无 .py 文件导入此函数）
# 2. 裸整数退出码与 ExitCode 枚举语义冲突（如退出码 2 分别表示"数据文件不存在"和"无有效数据")
# 3. factor_cli_main 提供更完善的 CLI（ExitCode 枚举、_die 辅助函数、add_cli_args 扩展）
# 原代码见 git history: v1.36+
