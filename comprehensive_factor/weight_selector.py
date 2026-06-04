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
- v1.5 (2026-06-04): 10项Bug修复（参见下方"问题修复清单"）

作者: 云瑶
"""

# 标准库导入
import argparse
import copy
import json
import logging
import sys
from datetime import UTC, datetime
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
__version__ = "1.5"

# logger 实例（遵循 PROJECT.md 第380-500行日志规范）
_logger = get_logger(__name__)

# 浮点数精度容差（遵循 superpowers-workflow Pitfall: 浮点数除零无精度容差）
EPSILON = 1e-10


# =============================================================================
# 配置
# =============================================================================

# 内部可变配置（用于构建，不会被外部直接访问）
_DEFAULT_CONFIG_INTERNAL = {
    # 评价指标配置
    "metrics": {
        # 收益类指标（越大越好）
        "long_short_return_annual": {
            "direction": "higher_better",
            "weight": 1.0,
            "description": "多空年化收益",
        },
        "long_short_sharpe": {
            "direction": "higher_better",
            "weight": 1.0,
            "description": "多空夏普比率",
        },
        "long_return_annual": {
            "direction": "higher_better",
            "weight": 1.0,
            "description": "多头年化收益",
        },
        "long_sharpe": {
            "direction": "higher_better",
            "weight": 1.0,
            "description": "多头夏普比率",
        },
        "monotonicity_abs": {
            "direction": "higher_better",
            "weight": 1.0,
            "description": "单调性相关性绝对值",
        },
        "long_short_net_daily": {
            "direction": "higher_better",
            "weight": 1.0,
            "description": "成本后日收益",
        },
        # 成本风险类指标（越小越好）
        "turnover_long_avg": {
            "direction": "lower_better",
            "weight": 1.0,
            "description": "多头换手率",
        },
        "turnover_short_avg": {
            "direction": "lower_better",
            "weight": 1.0,
            "description": "空头换手率",
        },
        "max_drawdown": {
            "direction": "lower_better",
            "weight": 1.0,
            "description": "最大回撤（绝对值越小越好）",
        },
    },
    # 权重方式列表
    "weight_methods": [
        "equal_weight",
        "ic_weight",
        "icir_weight",
        "rolling_icir_weight",
    ],
    # 多头分层列表（用于计算多头收益/夏普）
    # 遵循 backtest MODULE.md 约束：long_layers=[layer_1, layer_2]（问题 2 修复）
    "long_layers": ["layer_1", "layer_2"],
    # 结果文件目录
    "result_dir": "result",
    # 返回周期
    "return_period": "1d",
}

# 不可变配置（遵循 Pitfall: 模块级可变 dict 存在意外修改风险）
# 使用 MappingProxyType 包装，防止外部修改（问题 8 修复）
DEFAULT_CONFIG = MappingProxyType(_DEFAULT_CONFIG_INTERNAL)


# =============================================================================
# 核心函数
# =============================================================================


def load_composite_results(
    result_dir: Path, weight_methods: list[str], return_period: str, logger: logging.Logger | None = None
) -> dict[str, dict]:
    """
    加载综合因子结果文件

    Args:
        result_dir: 结果目录
        weight_methods: 权重方式列表
        return_period: 返回周期
        logger: 日志器（可选）

    Returns:
        Dict[weight_method, result_data]

    Raises:
        FileNotFoundError: 结果目录不存在
    """
    if logger is None:
        logger = _logger

    # 验证结果目录存在
    if not result_dir.exists():
        raise FileNotFoundError(f"结果目录不存在: {result_dir}")

    results = {}
    for method in weight_methods:
        filepath = result_dir / f"composite_{method}_{return_period}.json"
        if not filepath.exists():
            logger.warning(f"文件不存在: {filepath}")
            continue

        try:
            with open(filepath, encoding="utf-8") as f:
                results[method] = json.load(f)
            # 问题 10 修复：记录每个文件加载成功
            logger.debug(f"成功加载: {filepath}")
        except json.JSONDecodeError as e:
            logger.error(f"JSON解析失败: {filepath}, 位置 {e.pos}")
            continue

    return results


class WeightSelector:
    """
    权重选择器类（问题 7 修复：封装配置，减少参数穿透）

    将 metric_configs 作为构造参数注入，避免四个函数间重复传参。
    便于单元测试和配置管理。

    使用方式:
        selector = WeightSelector(metric_configs=DEFAULT_CONFIG["metrics"])
        results = load_composite_results(...)
        metrics_data = selector.extract_metrics(results)
        normalized_scores = selector.normalize_minmax(metrics_data)
        final_scores = selector.calculate_weighted_score(normalized_scores)
        best_method, best_score, ranked = selector.select_best_method(final_scores)
        output = selector.generate_output(metrics_data, normalized_scores, final_scores, ...)
        selector.log_summary(best_method, best_score, ranked, normalized_scores)
    """

    def __init__(
        self,
        metric_configs: dict[str, dict],
        long_layers: list[str] | None = None,
        logger: logging.Logger | None = None,
    ):
        """
        初始化权重选择器

        Args:
            metric_configs: 指标配置字典
            long_layers: 多头分层列表（默认：["layer_1", "layer_2"]）
            logger: 日志器（可选）
        """
        # 使用 copy.deepcopy 确保配置不被意外修改（问题 8 补充）
        self._metric_configs = copy.deepcopy(metric_configs)
        self._long_layers = long_layers or ["layer_1", "layer_2"]
        self._logger = logger or _logger

    @property
    def metric_configs(self) -> dict[str, dict]:
        """获取指标配置"""
        return self._metric_configs

    @property
    def long_layers(self) -> list[str]:
        """获取多头分层列表"""
        return self._long_layers

    def extract_metrics(self, results: dict[str, dict]) -> dict[str, dict[str, float]]:
        """
        从综合因子结果中提取评价指标

        Args:
            results: 综合因子结果字典

        Returns:
            Dict[weight_method, Dict[metric_name, value]]
        """
        metrics_data = {}

        for method, data in results.items():
            backtest = data.get("backtest_result", {})
            long_short = backtest.get("long_short", {})
            monotonicity = backtest.get("monotonicity", {})
            trading = backtest.get("trading_cost_analysis", {})
            layer_stats = backtest.get("layer_stats", {})

            # 提取多头分层数据（遍历而非硬编码）
            long_layer_data = []
            for layer_name in self._long_layers:
                layer_data = layer_stats.get(layer_name, {})
                if layer_data:
                    long_layer_data.append(layer_data)

            # 计算多头指标平均值
            if long_layer_data:
                long_return_annual = sum(layer.get("annual_return", 0) for layer in long_layer_data) / len(
                    long_layer_data
                )
                long_sharpe = sum(layer.get("sharpe_ratio", 0) for layer in long_layer_data) / len(long_layer_data)
                # max_drawdown 先 abs() 再 max()
                max_drawdown = max(abs(layer.get("max_drawdown", 0)) for layer in long_layer_data)
            else:
                long_return_annual = 0
                long_sharpe = 0
                max_drawdown = 0

            # 提取指标值
            metrics_data[method] = {
                "long_short_return_annual": long_short.get("long_short_return_annual", 0),
                "long_short_sharpe": long_short.get("long_short_sharpe", 0),
                "long_return_annual": long_return_annual,
                "long_sharpe": long_sharpe,
                "monotonicity_abs": abs(monotonicity.get("correlation", 0)),
                "long_short_net_daily": trading.get("long_short_net_daily", 0),
                "turnover_long_avg": long_short.get("turnover_long_avg", 0),
                "turnover_short_avg": long_short.get("turnover_short_avg", 0),
                "max_drawdown": max_drawdown,
            }

        return metrics_data

    def normalize_minmax(self, metrics_data: dict[str, dict[str, float]]) -> dict[str, dict[str, float]]:
        """
        Min-Max归一化

        Args:
            metrics_data: 原始指标数据

        Returns:
            Dict[weight_method, Dict[metric_name, normalized_score]]
        """
        methods = list(metrics_data.keys())
        normalized_scores = {method: {} for method in methods}

        for metric_name, config in self._metric_configs.items():
            values = [metrics_data[m].get(metric_name, 0) for m in methods]
            min_val = min(values)
            max_val = max(values)

            diff = max_val - min_val
            for method in methods:
                val = metrics_data[method].get(metric_name, 0)
                if abs(diff) < EPSILON:
                    norm_score = 1.0
                elif config["direction"] == "higher_better":
                    norm_score = (val - min_val) / diff
                else:
                    norm_score = (max_val - val) / diff

                normalized_scores[method][metric_name] = norm_score

        return normalized_scores

    def calculate_weighted_score(self, normalized_scores: dict[str, dict[str, float]]) -> dict[str, float]:
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
                weight = self._metric_configs.get(metric_name, {}).get("weight", 1.0)
                weighted_sum += score * weight
                total_weight += weight

            final_scores[method] = weighted_sum / total_weight if total_weight > 0 else 0.0

        return final_scores

    def select_best_method(self, final_scores: dict[str, float]) -> tuple[str, float, list[tuple[str, float]]]:
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
        return best_method, best_score, ranked

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
                "created_at": datetime.now(UTC).isoformat(),
                "total_methods": len(final_scores),
                "total_metrics": len(self._metric_configs),
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
                for k, v in self._metric_configs.items()
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
        输出摘要信息到日志（问题 9 修复：合并分隔线，精简输出）

        Args:
            best_method: 最优方法
            best_score: 最优得分
            ranked_methods: 排名列表
            normalized_scores: 归一化得分
        """
        # 问题 9 修复：合并为单条带标题的摘要日志
        metrics_list = list(self._metric_configs.keys())

        # 表头
        header = f"{'排名':>4} {'方法':<25}"
        for m in metrics_list:
            short_name = (
                m.replace("long_short_", "ls_")
                .replace("long_", "l_")
                .replace("turnover_", "to_")
                .replace("monotonicity_", "mono_")
                .replace("max_drawdown", "max_dd")
            )
            header += f" {short_name:>10}"
        header += f" {'综合得分':>10}"

        self._logger.info("=" * 60)
        self._logger.info("权重选择器 - 综合得分排名")
        self._logger.info(header)
        self._logger.info("-" * 60)

        # 排名行
        for rank, (method, score) in enumerate(ranked_methods, 1):
            row = f"{rank:>4} {method:<25}"
            for m in metrics_list:
                row += f" {normalized_scores[method].get(m, 0):>10.4f}"
            row += f" {score:>10.4f}"
            self._logger.info(row)

        self._logger.info("=" * 60)
        self._logger.info(f"最优权重方法: {best_method} | 综合得分: {best_score:.4f}")


# =============================================================================
# 主函数
# =============================================================================


def main():
    """主函数"""
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
    args = parser.parse_args()

    # 确定路径
    script_dir = Path(__file__).parent
    result_dir = Path(args.result_dir) if args.result_dir else script_dir / DEFAULT_CONFIG["result_dir"]
    output_path = Path(args.output) if args.output else result_dir / "weight_selection_result.json"

    # 问题 9 修复：合并路径信息为一行
    _logger.info(f"result_dir={result_dir} | output={output_path}")

    # 创建权重选择器实例（问题 7 修复：使用类封装）
    selector = WeightSelector(
        metric_configs=dict(DEFAULT_CONFIG["metrics"]),  # 转为可变 dict
        long_layers=list(DEFAULT_CONFIG.get("long_layers", ["layer_1", "layer_2"])),
    )

    # 加载数据
    _logger.info("加载综合因子结果...")
    results = load_composite_results(
        result_dir=result_dir,
        weight_methods=list(DEFAULT_CONFIG["weight_methods"]),
        return_period=args.return_period,
    )

    if not results:
        _logger.error("未找到任何结果文件")
        sys.exit(1)  # 问题 4 修复：退出码为 1

    _logger.info(f"加载 {len(results)} 个权重方式")

    # 问题 5 修复：校验加载结果完整性
    expected_methods = list(DEFAULT_CONFIG["weight_methods"])
    if len(results) < len(expected_methods):
        missing_methods = [m for m in expected_methods if m not in results]
        _logger.warning(f"部分权重方式结果缺失 ({len(results)}/{len(expected_methods)}): {missing_methods}")

    # 提取指标（使用类方法）
    _logger.info("提取评价指标...")
    metrics_data = selector.extract_metrics(results)
    _logger.info(f"提取 {len(selector.metric_configs)} 个指标")

    # 归一化（使用类方法）
    _logger.info("Min-Max归一化...")
    normalized_scores = selector.normalize_minmax(metrics_data)

    # 计算综合得分（使用类方法）
    _logger.info("计算综合得分（等权）...")
    final_scores = selector.calculate_weighted_score(normalized_scores)

    # 选择最优方法（使用类方法）
    best_method, best_score, ranked_methods = selector.select_best_method(final_scores)

    # 输出摘要（使用类方法）
    selector.log_summary(best_method, best_score, ranked_methods, normalized_scores)

    # 生成输出（使用类方法）
    output = selector.generate_output(
        metrics_data=metrics_data,
        normalized_scores=normalized_scores,
        final_scores=final_scores,
        best_method=best_method,
        best_score=best_score,
        ranked_methods=ranked_methods,
    )

    # 保存结果（问题 3 修复：写入前创建目录）
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    _logger.info(f"结果已保存: {output_path}")


if __name__ == "__main__":
    main()
