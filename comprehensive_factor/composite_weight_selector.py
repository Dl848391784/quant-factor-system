#!/usr/bin/env python3
"""
权重选择器 - 从多种权重方式中选择最优权重

功能：
1. 从综合因子结果中提取评价指标
2. Min-Max归一化打分
3. 等权综合得分
4. 输出最优权重方法

使用方式：
    python weight_selector.py [--result-dir PATH] [--output PATH] [--return-period 1d]

版本历史：
- v1.0 (2026-06-03): 初始版本，实现权重选择功能
- v1.1 (2026-06-03): print→logger迁移，遵循PROJECT.md日志规范
- v1.2 (2026-06-03): 类型注解完善，docstring规范化
- v1.3 (2026-06-03): 边界处理优化（异常处理、EPSILON精度容差）
- v1.4 (2026-06-03): select_best_method() 添加空字典检查（防御性编程）
- v1.5 (2026-06-04): 10项Bug修复（架构重构→类封装）
- v1.6 (2026-06-04): 10项深度修复（不可变配置递归+统计策略统一+异常捕获）
- v1.7 (2026-06-04): 9项新修复（Python兼容性+契约校验+降级路径+日志精简+动态列宽）
- v1.8 (2026-06-04): SRP拆分→4类协作（ResultLoader+MetricExtractor+Scorer+ReportFormatter）
- v1.9 (2026-06-04): 5项修复（严格契约+删除未用变量+配置漂移+short_name配置驱动+单方法场景）
- v1.10 (2026-06-04): 纠错修复-单方法场景删除冗余特判，保留 warning 提示

作者: 云瑶
"""

# 标准库导入
import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import MappingProxyType


# 根目录模块导入 sys.path 处理（遵循 superpowers-workflow references/root-module-import-sys-path-pattern.md）
PROJECT_ROOT = Path(__file__).parent.parent.resolve()
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# 本地模块导入
from backtest.common.logger_config import get_logger  # noqa: E402


# =============================================================================
# 模块级常量
# =============================================================================

# 版本号（遵循 PROJECT.md 规范）
__version__ = "1.10"

# logger 实例（遵循 PROJECT.md 第380-500行日志规范）
_logger = get_logger(__name__)

# 浮点数精度容差（遵循 superpowers-workflow Pitfall: 浮点数除零无精度容差）
EPSILON = 1e-10


# =============================================================================
# 配置
# =============================================================================


def _freeze_config(obj: dict | list) -> MappingProxyType | tuple:
    """
    递归冻结配置对象

    将 dict 转为 MappingProxyType，list 转为 tuple，
    确保嵌套结构真正不可变。

    Args:
        obj: 待冻结的 dict 或 list

    Returns:
        不可变的 MappingProxyType 或 tuple
    """
    if isinstance(obj, dict):
        frozen_dict = {k: _freeze_config(v) if isinstance(v, (dict, list)) else v for k, v in obj.items()}
        return MappingProxyType(frozen_dict)
    elif isinstance(obj, list):
        return tuple(_freeze_config(item) if isinstance(item, (dict, list)) else item for item in obj)
    else:
        return obj


# 内部可变配置（用于构建，不会被外部直接访问）
_DEFAULT_CONFIG_INTERNAL = {
    # 评价指标配置（v2.35: P3 只做多对齐——移除4个多空/空头指标，新增2个L1指标）
    # 公理1: 只做多策略不能做空，多空/空头指标无意义（design.md §2.3）
    "metrics": {
        # 收益类指标（越大越好）
        "long_return_annual": {
            "direction": "higher_better",
            "weight": 1.0,
            "description": "多头年化收益",
            "short_name": "l_ret_ann",
        },
        "long_sharpe": {
            "direction": "higher_better",
            "weight": 1.0,
            "description": "多头夏普比率",
            "short_name": "l_sharpe",
        },
        "layer_1_annual": {  # v2.35: P3 新增——L1绝对年化收益（只做多核心指标）
            "direction": "higher_better",
            "weight": 1.0,
            "description": "Layer1买入层年化收益",
            "short_name": "l1_ret_ann",
        },
        "layer_1_sharpe": {  # v2.35: P3 新增——L1夏普（稳定性）
            "direction": "higher_better",
            "weight": 1.0,
            "description": "Layer1买入层夏普比率",
            "short_name": "l1_sharpe",
        },
        "monotonicity_abs": {
            "direction": "higher_better",
            "weight": 1.0,
            "description": "单调性相关性绝对值",
            "short_name": "mono_abs",
        },
        # 成本风险类指标（越小越好）
        "turnover_long_avg": {
            "direction": "lower_better",
            "weight": 1.0,
            "description": "多头换手率",
            "short_name": "to_long",
        },
        "max_drawdown": {
            "direction": "lower_better",
            "weight": 1.0,
            "description": "最大回撤（绝对值越小越好）",
            "short_name": "max_dd",
        },
    },
    # 权重方式列表（转为 tuple）
    "weight_methods": [
        "equal_weight",
        "ic_weight",
        "icir_weight",
        "rolling_icir_weight",
    ],
    # 多头分层列表（转为 tuple）
    "long_layers": ["layer_1", "layer_2"],
    # 结果文件目录
    "result_dir": "result",
    # 返回周期
    "return_period": "1d",
}

# 不可变配置
DEFAULT_CONFIG = _freeze_config(_DEFAULT_CONFIG_INTERNAL)


# =============================================================================
# 配置值对象（问题 3 修复：消除配置漂移风险）
# =============================================================================


class WeightSelectorConfig:
    """
    权重选择器配置（不可变值对象）

    职责：封装 metric_configs 和 long_layers，确保三类引用同一份配置。
    三类（MetricExtractor、Scorer、ReportFormatter）通过 config 属性访问，
    单测时只需注入一处。
    """

    __slots__ = ("_metrics", "_long_layers")

    def __init__(self, metrics: MappingProxyType, long_layers: tuple[str, ...]):
        """
        初始化配置值对象

        Args:
            metrics: 不可变指标配置
            long_layers: 多头分层列表（tuple）
        """
        self._metrics = metrics
        self._long_layers = long_layers

    @classmethod
    def from_dict(cls, metric_configs: dict[str, dict], long_layers: list[str]) -> "WeightSelectorConfig":
        """
        从可变配置创建不可变值对象

        Args:
            metric_configs: 可变指标配置字典
            long_layers: 多头分层列表

        Returns:
            WeightSelectorConfig 实例
        """
        frozen_metrics = _freeze_config(metric_configs)
        frozen_layers = tuple(long_layers)
        return cls(metrics=frozen_metrics, long_layers=frozen_layers)

    @property
    def metrics(self) -> MappingProxyType:
        """获取不可变指标配置"""
        return self._metrics

    @property
    def long_layers(self) -> tuple[str, ...]:
        """获取多头分层列表"""
        return self._long_layers


# =============================================================================
# 核心类（问题 7 修复：SRP 拆分）
# =============================================================================


class ResultLoader:
    """
    结果加载器（IO 层）

    职责：加载综合因子结果文件，处理文件缺失和 JSON 解析异常。
    """

    def __init__(self, logger: logging.Logger | None = None):
        """
        初始化结果加载器

        Args:
            logger: 日志器（可选）
        """
        self._logger = logger or _logger

    def load(
        self,
        result_dir: Path,
        weight_methods: tuple[str, ...],
        return_period: str,
        strict: bool = False,
    ) -> dict[str, dict]:
        """
        加载综合因子结果文件

        Args:
            result_dir: 结果目录
            weight_methods: 权重方式列表（tuple）
            return_period: 返回周期
            strict: 严格模式，JSON 解析失败时抛异常

        Returns:
            Dict[weight_method, result_data]

        Raises:
            FileNotFoundError: 结果目录不存在
            json.JSONDecodeError: strict=True 且 JSON 解析失败
        """
        if not result_dir.exists():
            raise FileNotFoundError(f"结果目录不存在: {result_dir}")

        results = {}
        # 问题 2 修复：删除未使用的 missing_files，与 corrupted_files 对齐
        corrupted_files = []

        for method in weight_methods:
            filepath = result_dir / f"composite_{method}_{return_period}.json"
            if not filepath.exists():
                # 循环内 warning（与 corrupted_files 处理方式一致）
                self._logger.warning("文件不存在: %s", filepath)
                continue

            try:
                with open(filepath, encoding="utf-8") as f:
                    results[method] = json.load(f)
                self._logger.debug("成功加载: %s", filepath)
            except json.JSONDecodeError as e:
                corrupted_files.append(str(filepath))
                if strict:
                    raise
                self._logger.error("JSON解析失败: %s, 位置 %s", filepath, e.pos)
                continue

        if corrupted_files:
            self._logger.warning("检测到 %s 个 JSON 损坏文件: %s", len(corrupted_files), corrupted_files)

        return results


class MetricExtractor:
    """
    指标提取器（业务层）

    职责：从综合因子结果中提取评价指标，处理字段缺失异常。
    """

    def __init__(
        self,
        config: WeightSelectorConfig,
        logger: logging.Logger | None = None,
    ):
        """
        初始化指标提取器（问题 3 修复：接收 config 对象）

        Args:
            config: 权重选择器配置（不可变值对象）
            logger: 日志器（可选）
        """
        self._config = config
        self._logger = logger or _logger

    @property
    def metric_configs(self) -> MappingProxyType:
        """获取指标配置"""
        return self._config.metrics

    @property
    def long_layers(self) -> tuple[str, ...]:
        """获取多头分层列表"""
        return self._config.long_layers

    def extract(self, results: dict[str, dict]) -> dict[str, dict[str, float]]:
        """
        从综合因子结果中提取评价指标

        Args:
            results: 综合因子结果字典

        Returns:
            Dict[weight_method, Dict[metric_name, value]]

        Raises:
            ValueError: 所有方法提取失败
        """
        metrics_data = {}
        # v2.35: P3 只做多对齐——required_fields 移除多空/空头指标
        required_fields = [
            "turnover_long_avg",
        ]

        failed_methods = []

        for method, data in results.items():
            try:
                backtest = data.get("backtest_result", {})
                if not backtest:
                    raise ValueError("backtest_result 字段缺失")

                long_short = backtest.get("long_short", {})
                monotonicity = backtest.get("monotonicity", {})
                layer_stats = backtest.get("layer_stats", {})

                # 检查必需字段
                for field in required_fields:
                    if field not in long_short:
                        raise ValueError(f"必需字段缺失: {field}")

                if "correlation" not in monotonicity:
                    raise ValueError("必需字段缺失: monotonicity.correlation")

                # 提取多头分层数据
                # 从 backtest meta 动态读取 long_layers（整数列表），而非 hardcode 固定层号
                # 根因: IC>0 因子 long_layers=[1,2]，IC<0 因子 long_layers=[4,5]
                #       hardcode ["layer_1","layer_2"] 对 IC<0 因子取到做空层，方向反了
                meta = backtest.get("meta", {})
                meta_long_layers = meta.get("long_layers", None)

                if meta_long_layers:
                    # 动态: [4, 5] -> ["layer_4", "layer_5"]
                    long_layer_names = [f"layer_{n}" for n in meta_long_layers]
                else:
                    # 回退: 旧数据无 meta 字段时用配置默认值（向后兼容）
                    long_layer_names = list(self._config.long_layers)

                long_layer_data = []
                for layer_name in long_layer_names:
                    layer_data = layer_stats.get(layer_name, {})
                    if layer_data:
                        long_layer_data.append(layer_data)

                if not long_layer_data:
                    raise ValueError(f"多头分层数据缺失: {long_layer_names}")

                # 检查层内必需字段
                for layer in long_layer_data:
                    for field in ["annual_return", "sharpe_ratio", "max_drawdown"]:
                        if field not in layer:
                            raise ValueError(f"多头层必需字段缺失: {field}")

                long_return_annual = sum(layer["annual_return"] for layer in long_layer_data) / len(long_layer_data)
                long_sharpe = sum(layer["sharpe_ratio"] for layer in long_layer_data) / len(long_layer_data)
                max_drawdown = sum(abs(layer["max_drawdown"]) for layer in long_layer_data) / len(long_layer_data)

                # v2.35: P3 新增--提取首个做多层指标（只做多核心指标）
                # 修复: 从动态 long_layer_names 取首个做多层，而非硬编码 layer_1
                # 根因: IC<0 因子 long_layers=[4,5]，layer_1 是做空层不是买入层
                first_long_layer_name = long_layer_names[0]  # e.g. "layer_4"
                first_long_layer = layer_stats.get(first_long_layer_name, {})
                layer_1_annual = first_long_layer.get("annual_return")
                layer_1_sharpe = first_long_layer.get("sharpe_ratio")

                metrics_data[method] = {
                    "long_return_annual": long_return_annual,
                    "long_sharpe": long_sharpe,
                    "layer_1_annual": layer_1_annual if layer_1_annual is not None else 0.0,
                    "layer_1_sharpe": layer_1_sharpe if layer_1_sharpe is not None else 0.0,
                    "monotonicity_abs": abs(monotonicity["correlation"]),
                    "turnover_long_avg": long_short["turnover_long_avg"],
                    "max_drawdown": max_drawdown,
                }
            except (ValueError, KeyError) as e:
                self._logger.warning("[%s] 提取失败，跳过: %s", method, e)
                failed_methods.append(method)

        if not metrics_data:
            raise ValueError(f"所有方法提取失败: {failed_methods}")

        if failed_methods:
            self._logger.warning("部分方法提取失败: %s，剩余 %s 个有效方法", failed_methods, len(metrics_data))

        return metrics_data


class Scorer:
    """
    评分器（数学层）

    职责：归一化指标、计算加权得分、选择最优方法。
    """

    def __init__(self, config: WeightSelectorConfig, logger: logging.Logger | None = None):
        """
        初始化评分器（问题 3 修复：接收 config 对象）

        Args:
            config: 权重选择器配置（不可变值对象）
            logger: 日志器（可选）
        """
        self._config = config
        self._logger = logger or _logger

    def normalize(self, metrics_data: dict[str, dict[str, float]]) -> dict[str, dict[str, float]]:
        """
        Min-Max归一化

        Args:
            metrics_data: 原始指标数据

        Returns:
            Dict[weight_method, Dict[metric_name, normalized_score]]

        Raises:
            KeyError: 字段缺失（契约违反）
        """
        methods = list(metrics_data.keys())
        normalized_scores = {method: {} for method in methods}

        for metric_name, config in self._config.metrics.items():
            values = [metrics_data[m][metric_name] for m in methods]
            min_val = min(values)
            max_val = max(values)

            diff = max_val - min_val
            for method in methods:
                val = metrics_data[method][metric_name]
                if abs(diff) < EPSILON:
                    norm_score = 1.0
                elif config["direction"] == "higher_better":
                    norm_score = (val - min_val) / diff
                else:
                    norm_score = (max_val - val) / diff

                normalized_scores[method][metric_name] = norm_score

        return normalized_scores

    def calculate_weighted(self, normalized_scores: dict[str, dict[str, float]]) -> dict[str, float]:
        """
        计算加权综合得分

        Args:
            normalized_scores: 归一化得分

        Returns:
            Dict[weight_method, weighted_score]
        """
        final_scores = {}

        for method, scores in normalized_scores.items():
            total_weight = 0.0
            weighted_sum = 0.0

            for metric_name, score in scores.items():
                # 问题 1 修复：直接访问，与 normalize 保持同档校验强度
                weight = self._config.metrics[metric_name]["weight"]
                weighted_sum += score * weight
                total_weight += weight

            final_scores[method] = weighted_sum / total_weight if total_weight > 0 else 0.0

        return final_scores

    def select_best(self, final_scores: dict[str, float]) -> tuple[str, float, list[tuple[str, float]]]:
        """
        选择最优方法

        Args:
            final_scores: 综合得分

        Returns:
            tuple[str, float, list]: (best_method, best_score, ranked_methods)

        Raises:
            ValueError: final_scores 为空字典
        """
        if not final_scores:
            raise ValueError("final_scores 不能为空")

        ranked = sorted(final_scores.items(), key=lambda x: x[1], reverse=True)
        best_method, best_score = ranked[0]

        # 检测并列第一
        if len(ranked) >= 2:
            second_score = ranked[1][1]
            if abs(best_score - second_score) < EPSILON:
                tied_methods = [m for m, s in ranked if abs(s - best_score) < EPSILON]
                self._logger.warning(
                    "检测到并列第一: %s (得分均为 %.4f)，当前选择依赖输入顺序: %s",
                    tied_methods,
                    best_score,
                    best_method,
                )

        return best_method, best_score, ranked


class ReportFormatter:
    """
    报告格式化器（输出层）

    职责：生成 JSON 输出结构、格式化日志摘要。
    """

    def __init__(self, config: WeightSelectorConfig, logger: logging.Logger | None = None):
        """
        初始化报告格式化器（问题 3 修复：接收 config 对象）

        Args:
            config: 权重选择器配置（不可变值对象）
            logger: 日志器（可选）
        """
        self._config = config
        self._logger = logger or _logger

    def generate_output(
        self,
        metrics_data: dict[str, dict[str, float]],
        normalized_scores: dict[str, dict[str, float]],
        final_scores: dict[str, float],
        best_method: str,
        best_score: float,
        ranked_methods: list[tuple[str, float]],
    ) -> dict[str, dict]:
        """
        生成输出结果

        Args:
            metrics_data: 原始指标数据
            normalized_scores: 归一化得分
            final_scores: 综合得分
            best_method: 最优方法
            best_score: 最优得分
            ranked_methods: 排名列表

        Returns:
            dict[str, dict]: 输出字典
        """
        ranking = []
        for rank, (method, score) in enumerate(ranked_methods, 1):
            ranking.append(
                {
                    "rank": rank,
                    "method": method,
                    "composite_score": round(score, 4),
                    "metric_scores": {k: round(v, 4) for k, v in normalized_scores[method].items()},
                    "raw_values": {k: round(v, 6) for k, v in metrics_data[method].items()},
                }
            )

        output = {
            "meta": {
                "created_at": datetime.now(timezone.utc).isoformat(),
                "total_methods": len(final_scores),
                "total_metrics": len(self._config.metrics),
                "normalization_method": "min-max",
                "weight_strategy": "equal-weight",
            },
            "best_selection": {
                "method": best_method,
                "composite_score": round(best_score, 4),
                "selection_reason": "综合得分最高",
            },
            "ranking": ranking,
            "metric_configs": {
                k: {
                    "direction": v["direction"],
                    "weight": v["weight"],
                    "description": v.get("description", ""),
                }
                for k, v in self._config.metrics.items()
            },
        }

        return output

    def log_summary(
        self,
        best_method: str,
        best_score: float,
        ranked_methods: list[tuple[str, float]],
        normalized_scores: dict[str, dict[str, float]],
    ) -> None:
        """
        输出摘要信息到日志

        Args:
            best_method: 最优方法
            best_score: 最优得分
            ranked_methods: 排名列表
            normalized_scores: 归一化得分
        """
        metrics_list = list(self._config.metrics.keys())

        # 动态计算方法列宽
        max_method_len = max(len(m) for m, _ in ranked_methods) if ranked_methods else 25
        method_col_width = max(max_method_len, 10)

        # 表头
        header = f"{'排名':>4} {'方法':<{method_col_width}}"
        for m in metrics_list:
            # 问题 4 修复：使用配置驱动的 short_name
            short_name = self._config.metrics[m]["short_name"]
            header += f" {short_name:>10}"
        header += f" {'综合得分':>10}"

        self._logger.info("权重选择器 - 综合得分排名")
        self._logger.info(header)
        self._logger.info("-" * 60)

        # 排名行
        for rank, (method, score) in enumerate(ranked_methods, 1):
            row = f"{rank:>4} {method:<{method_col_width}}"
            for m in metrics_list:
                row += f" {normalized_scores[method].get(m, 0):>10.4f}"
            row += f" {score:>10.4f}"
            self._logger.info(row)

        self._logger.info("最优权重方法: %s | 综合得分: %.4f", best_method, best_score)


# =============================================================================
# 主函数
# =============================================================================


def main():
    """
    主函数（组装 4 类协作）

    流程：
    1. ResultLoader 加载结果文件
    2. MetricExtractor 提取评价指标
    3. Scorer 归一化、加权、选最优
    4. ReportFormatter 生成输出、日志摘要
    """
    parser = argparse.ArgumentParser(description="权重选择器 - 从多种权重方式中选择最优权重")
    parser.add_argument(
        "--result-dir",
        type=str,
        default=None,
        help="结果目录路径（默认：脚本所在目录/result）",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="输出文件路径（默认：result_dir/weight_selection_result.json）",
    )
    parser.add_argument(
        "--return-period",
        type=str,
        default="1d",
        help="返回周期（默认：1d）",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="严格模式，JSON 解析失败时抛异常而非跳过",
    )
    args = parser.parse_args()

    try:
        # 确定路径
        from paths import COMPREHENSIVE_FACTOR_RESULT

        result_dir = Path(args.result_dir) if args.result_dir else COMPREHENSIVE_FACTOR_RESULT
        output_path = Path(args.output) if args.output else result_dir / "weight_selection_result.json"

        _logger.info("result_dir=%s | output=%s", result_dir, output_path)

        # 创建不可变配置值对象（问题 3 修复：消除配置漂移风险）
        config = WeightSelectorConfig.from_dict(
            metric_configs={k: dict(v) for k, v in DEFAULT_CONFIG["metrics"].items()},
            long_layers=list(DEFAULT_CONFIG["long_layers"]),
        )

        # 组装 4 类（问题 7 修复：SRP 拆分）
        loader = ResultLoader()
        extractor = MetricExtractor(config=config)
        scorer = Scorer(config=config)
        formatter = ReportFormatter(config=config)

        # 1. 加载结果文件
        results = loader.load(
            result_dir=result_dir,
            weight_methods=DEFAULT_CONFIG["weight_methods"],
            return_period=args.return_period,
            strict=args.strict,
        )

        if not results:
            _logger.error("未找到任何结果文件")
            sys.exit(1)

        _logger.info("加载 %s 个权重方式", len(results))

        # 校验完整性
        expected_methods = DEFAULT_CONFIG["weight_methods"]
        if len(results) < len(expected_methods):
            missing_methods = [m for m in expected_methods if m not in results]
            _logger.warning(
                "部分权重方式结果缺失 (%s/%s): %s",
                len(results),
                len(expected_methods),
                missing_methods,
            )

        # 2. 提取指标
        _logger.debug("提取评价指标...")
        metrics_data = extractor.extract(results)
        _logger.debug("提取 %s 个指标", len(extractor.metric_configs))

        # 单方法场景提示（流程仍正常走 normalize/score/select）
        if len(metrics_data) == 1:
            _logger.warning("仅 1 个方法，评分结果无比较意义")

        # 3. 归一化
        _logger.debug("Min-Max归一化...")
        normalized_scores = scorer.normalize(metrics_data)

        # 4. 计算综合得分
        _logger.debug("计算综合得分（等权）...")
        final_scores = scorer.calculate_weighted(normalized_scores)

        # 5. 选择最优方法
        best_method, best_score, ranked_methods = scorer.select_best(final_scores)

        # 6. 输出摘要
        formatter.log_summary(best_method, best_score, ranked_methods, normalized_scores)

        # 7. 生成输出
        output = formatter.generate_output(
            metrics_data=metrics_data,
            normalized_scores=normalized_scores,
            final_scores=final_scores,
            best_method=best_method,
            best_score=best_score,
            ranked_methods=ranked_methods,
        )

        # 8. 保存结果
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(output, f, ensure_ascii=False, indent=2)

        _logger.info("结果已保存: %s", output_path)

    except Exception as e:
        _logger.exception("权重选择器执行失败: %s", e)
        sys.exit(1)


if __name__ == "__main__":
    main()
