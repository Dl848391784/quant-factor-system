import sys
from pathlib import Path


# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from typing import Any

import numpy as np
import pandas as pd

# 导入公共日志模块（遵循 PROJECT.md 强制复用规范）
from backtest.common.logger_config import get_logger


logger = get_logger(__name__)


def _coalesce(val: Any, default: float = 0.0) -> Any:
    """
    安全取值：只替换 None，保留 NaN、0.0 和负数

    注意: 在 generate_report 中不应将 _coalesce 结果传给 _format_pct，
        因为 _coalesce 将 None → 0.0，会导致 _format_pct 显示 "0.00%"
        而非 "N/A"。应直接将原始值传给 _format_pct（它已能处理 None/NaN）。

    参数:
        val: 可能为 None 的值
        default: None 时的默认值（默认 0.0）

    返回:
        若 val 为 None，返回 default
        若 val 为 NaN/0.0/负数，原样返回（这些是合法值）
    """
    if val is None:
        return default
    return val


def _format_pct(val: Any, decimals: int = 2, suffix: str = "%") -> str:
    """
    格式化百分比：NaN 显示 N/A，数值显示百分比

    用法:
        daily_ret = stats.get('daily_return_mean')  # 直接取值，None/NaN 均可处理
        lines.append(f"日均收益: {_format_pct(daily_ret, 4)}")
        # 输出：None/NaN → "N/A"，数值 → "12.34%"

    参数:
        val: 可能为 NaN 的值
        decimals: 小数位数（默认 2）
        suffix: 后缀（默认 '%'）

    返回:
        若 val 为 None 或 NaN，返回 "N/A"
        否则返回 f"{val*100:.{decimals}f}{suffix}"
    """
    if val is None or pd.isna(val):
        return "N/A"
    return f"{val * 100:.{decimals}f}{suffix}"


class LayeredBacktestEngine:
    """
    通用分层回测引擎

    用法:
        engine = LayeredBacktestEngine(factor_df, return_df, factor_col='rsi_6')
        result = engine.run(
            layer_method='fixed_threshold',
            thresholds=[0, 20, 40, 60, 80, 100],
            factor_direction='negative',
            long_layers=[1, 2],
            short_layers=[4, 5]
        )
    """

    def __init__(
        self,
        factor_df: pd.DataFrame,
        return_df: pd.DataFrame,
        factor_col: str = "factor_value",
        return_col: str = "forward_return",
        date_col: str = "date",
        asset_col: str = "asset",
        volume_col: str | None = None,
    ):
        """
        初始化回测引擎

        参数:
            factor_df: 因子数据，必须包含 [date_col, asset_col, factor_col]
            return_df: 收益数据，必须包含 [date_col, asset_col, return_col]
            factor_col: 因子值列名
            return_col: 未来收益列名
            date_col: 日期列名
            asset_col: 资产代码列名
            volume_col: 成交量列名（用于停牌过滤，可选）
        """
        self.factor_col = factor_col
        self.return_col = return_col
        self.date_col = date_col
        self.asset_col = asset_col
        self.volume_col = volume_col

        # 合并数据
        self._merge_data(factor_df, return_df)

    def _merge_data(self, factor_df: pd.DataFrame, return_df: pd.DataFrame):
        """合并因子和收益数据（T-1 对齐，消除前视偏差）

        交易规则（PROJECT.md）：T-1 日数据 → T 日 09:25 算 → T 日尾盘买 → T+1 日卖
        - factor[D] 基于 D 日收盘价计算，只能在 D+1 日 09:25 使用
        - forward_return_1d[D] = D→D+1 收益
        - 正确配对：factor[D-1] → forward_return_1d[D]（T-1 因子 → T→T+1 收益）

        修复前（前视偏差）：factor[D] → forward_return_1d[D]，等于偷看 D 日收盘后买 D 日收盘
        修复后：将因子日期 shift +1 交易日，使 factor[D] 与 forward_return_1d[D+1] 配对
        """
        # 选择需要的列
        factor_cols = [self.date_col, self.asset_col, self.factor_col]
        if self.volume_col and self.volume_col in factor_df.columns:
            factor_cols.append(self.volume_col)

        return_cols = [self.date_col, self.asset_col, self.return_col]

        factor_subset = factor_df[factor_cols].copy()
        return_subset = return_df[return_cols].copy()

        # T-1 对齐：因子日期 shift +1 交易日
        # factor[D] 重标记为 D+1，merge 后与 forward_return_1d[D+1]（D+1→D+2 收益）配对
        all_dates = sorted(
            set(factor_subset[self.date_col].unique())
            | set(return_subset[self.date_col].unique())
        )
        date_to_next = {all_dates[i]: all_dates[i + 1] for i in range(len(all_dates) - 1)}
        factor_subset[self.date_col] = factor_subset[self.date_col].map(date_to_next)
        # 最后一个交易日的因子无次日收益，丢弃
        factor_subset = factor_subset.dropna(subset=[self.date_col])

        # 合并
        self.merged_df = pd.merge(factor_subset, return_subset, on=[self.date_col, self.asset_col], how="inner")

        # 获取日期列表
        self.dates = sorted(self.merged_df[self.date_col].unique())

        # 内存优化（v1.6 修正：因子列必须 float64，禁用 float32）
        # 因子列用于 percentile 分层，float32 精度损失会导致分层偏差
        # 收益列用于累计收益计算 (1+r).cumprod()，float64 防长时间序列误差累积
        self.merged_df[self.asset_col] = self.merged_df[self.asset_col].astype("category")
        if self.factor_col in self.merged_df.columns:
            # 禁用 float32：rank 分层需要精确区分相邻因子值
            # float32 精度约7位有效数字，1.0000001 vs 1.0000002 会被截断为相同值
            self.merged_df[self.factor_col] = self.merged_df[self.factor_col].astype("float64")
        if self.return_col in self.merged_df.columns:
            self.merged_df[self.return_col] = self.merged_df[self.return_col].astype("float64")

    def run(
        self,
        layer_method: str = "percentile",
        n_layers: int = 5,
        thresholds: list[float] | None = None,
        factor_direction: str = "positive",
        long_layers: list[int] | None = None,
        short_layers: list[int] | None = None,
        min_stocks_per_layer: int = 10,
        trade_cost_rate: float = 0.003,
    ) -> dict:
        """
        执行分层回测

        参数:
            layer_method: 分层方法
                - 'percentile': 百分位分层（每层20%）
                    - 层编号语义（v1.6 补充）：
                      - percentile 分层后，Layer 1 包含因子值最低的20%股票
                      - Layer n_layers 包含因子值最高的20%股票
                      - 正向因子（factor_direction='positive'）：Layer n_layers 是"最好的层"（高因子值预期高收益）
                      - 反向因子（factor_direction='negative'）：Layer 1 是"最好的层"（低因子值预期高收益）
                      - 这与默认多空层设置一致：正向因子 long_layers=[n-1, n]，反向因子 long_layers=[1, 2]
                - 'fixed_threshold': 固定阈值分层（需指定thresholds，已废弃）
            n_layers: 分层数量
                - percentile 模式：有效，控制分层数量（默认5层）
                - fixed_threshold 模式：无效，由 thresholds 长度决定（n层 = len(thresholds) - 1）
            thresholds: 固定阈值列表，如 [0, 20, 40, 60, 80, 100]
                - 仅 fixed_threshold 模式使用
                - 必须至少包含2个阈值点，严格递增
            factor_direction: 因子方向
                - 'positive': 正向因子，高值=高收益预期
                - 'negative': 反向因子，低值=高收益预期
            long_layers: 多头组合的层编号（从1开始）
                - 若未指定，根据 factor_direction 自动设置：
                  正向因子取高层 [n-1, n]，反向因子取低层 [1, 2]
            short_layers: 空头组合的层编号
                - 若未指定，根据 factor_direction 自动设置：
                  正向因子取低层 [1, 2]，反向因子取高层 [n-1, n]
            min_stocks_per_layer: 每层最少股票数
            trade_cost_rate: 单边交易成本率

        返回:
            回测结果字典，包含：
            - meta: 元数据（分层数量、因子方向、回测天数等）
            - layer_stats: 各层统计（收益、夏普、换手率等）
            - long_short: 多空组合统计
            - monotonicity: 单调性检验
            - trading_cost_analysis: 交易成本分析
            - daily_records: 每日详细记录
        """
        # ========== 参数校验 ==========
        # 校验 factor_direction
        valid_directions = ["positive", "negative"]
        if factor_direction not in valid_directions:
            raise ValueError(f"factor_direction 必须是 'positive' 或 'negative', 当前值: '{factor_direction}'")

        # 校验 layer_method
        valid_methods = ["percentile", "fixed_threshold"]
        if layer_method not in valid_methods:
            raise ValueError(f"layer_method 必须是 'percentile' 或 'fixed_threshold', 当前值: '{layer_method}'")

        # 校验 thresholds（fixed_threshold 模式）
        if layer_method == "fixed_threshold":
            if thresholds is None or len(thresholds) < 2:
                raise ValueError("fixed_threshold 模式需要 thresholds 参数，且至少包含2个阈值点")
            # 校验阈值递增
            for i in range(len(thresholds) - 1):
                if thresholds[i] >= thresholds[i + 1]:
                    raise ValueError(
                        f"thresholds 必须严格递增，第{i}个阈值 {thresholds[i]} >= 第{i + 1}个阈值 {thresholds[i + 1]}"
                    )

        logger.info("开始分层回测: layer_method=%s, factor_direction=%s", layer_method, factor_direction)

        # ========== 确定分层数量（先修正 n_layers）==========
        # 必须在设置默认多空层之前，避免层编号越界
        if layer_method == "fixed_threshold" and thresholds:
            n_layers = len(thresholds) - 1

        # ========== 设置默认多空组合（依赖已修正的 n_layers）==========
        # 多头：正向因子取高层，反向因子取低层
        # 空头：正向因子取低层，反向因子取高层
        # 特殊处理：n_layers=1 时，long_layers 和 short_layers 都为 [1]
        if long_layers is None:
            if n_layers == 1:
                # 单层模式：多头和空头都取唯一的层
                long_layers = [1]
            else:
                long_layers = [n_layers - 1, n_layers] if factor_direction == "positive" else [1, 2]
        if short_layers is None:
            if n_layers == 1:
                # 单层模式：空头也取唯一的层（此时多空组合无意义）
                short_layers = [1]
            else:
                short_layers = [1, 2] if factor_direction == "positive" else [n_layers - 1, n_layers]

        # ========== 校验多空层编号不越界 ==========
        max_layer = n_layers
        for layer_id in long_layers:
            if layer_id > max_layer or layer_id < 1:
                raise ValueError(
                    f"long_layers 越界: 层编号 {layer_id} 不在有效范围 [1, {max_layer}]，"
                    f"当前 n_layers={n_layers}，请检查 thresholds 参数"
                )
        for layer_id in short_layers:
            if layer_id > max_layer or layer_id < 1:
                raise ValueError(
                    f"short_layers 越界: 层编号 {layer_id} 不在有效范围 [1, {max_layer}]，"
                    f"当前 n_layers={n_layers}，请检查 thresholds 参数"
                )

        # 每日处理（预先按日期分组，时间复杂度 O(n) 而非 O(n²)）
        # 原布尔索引每次全表扫描，groupby 一次分组后遍历
        daily_records = []
        prev_assignment = None

        # 预先按日期分组（self.dates 已排序）
        grouped_by_date = self.merged_df.groupby(self.date_col)

        for date in self.dates:
            # 获取当日数据（groupby 后，直接取组，无需全表扫描）
            try:
                day_data = grouped_by_date.get_group(date).copy()
            except KeyError:
                # 该日期无数据（如停牌日），跳过
                continue

            # 停牌过滤
            if self.volume_col and self.volume_col in day_data.columns:
                day_data = day_data[day_data[self.volume_col] > 0]

            # 过滤因子为NaN的数据
            day_data = day_data[day_data[self.factor_col].notna()]

            if len(day_data) < min_stocks_per_layer:
                continue

            # 分层
            layer_assignment = self.get_layer_assignment(
                date, day_data[self.factor_col], layer_method, n_layers, thresholds
            )

            # 分层结果赋值（day_data 已 .copy()，此处赋值安全）
            day_data["_layer"] = layer_assignment

            # 计算各层收益
            layer_returns = self.calculate_layer_returns(
                date, day_data["_layer"], day_data[self.return_col], min_stocks_per_layer
            )

            # 计算换手率
            turnover_rates = self.calculate_turnover(
                prev_assignment,
                dict(
                    zip(
                        day_data[self.asset_col].astype(str),  # 确保asset为字符串
                        day_data["_layer"],
                    )
                ),
            )

            # 记录每日结果
            for layer_id in range(1, n_layers + 1):
                n_stocks = int((day_data["_layer"] == layer_id).sum())  # 转为int避免JSON序列化问题
                # 安全转换：NaN → None（避免 json.dumps 抛 ValueError）
                raw_return = layer_returns.get(layer_id, np.nan)
                safe_return = None if pd.isna(raw_return) else float(raw_return)
                daily_records.append(
                    {
                        "date": date,
                        "layer": int(layer_id),  # 转为int
                        "n_stocks": n_stocks,
                        "return": safe_return,
                        "turnover": float(turnover_rates.get(layer_id, 0.0)),  # 转为float
                    }
                )

            prev_assignment = dict(zip(day_data[self.asset_col].astype(str), day_data["_layer"]))

        # 构建结果DataFrame
        daily_df = pd.DataFrame(daily_records)

        # 汇总统计
        result = self._aggregate_results(
            daily_df, n_layers, long_layers, short_layers, factor_direction, trade_cost_rate, layer_method, thresholds
        )

        return result

    def get_layer_assignment(
        self, date: str, factor_values: pd.Series, method: str, n_layers: int, thresholds: list[float] | None
    ) -> pd.Series:
        """
        计算股票分层归属

        返回: Series(index=asset, value=layer_id)
        """
        if method == "percentile":
            # 百分位分层（method='first' 保证唯一秩）
            #
            # 精度要求：因子值必须以 float64 存储。float32 精度损失会导致：
            #   - 相邻因子值在存储时被截断为相同值
            #   - method='first' 虽能给相同值分配不同秩，但无法恢复原始顺序信息
            #   - 分层结果偏离预期（本应分层N的股票被错误归入分层M）
            #
            # 分层均匀性：当 N (股票数) 不能被 n_layers 整除时，
            #   - ceil(N/n_layers) 支股票会归入最后一层
            #   - 例如 N=3003, n_layers=5 → Layer1-4 各600支，Layer5 有603支
            #   - 这是 rank+ceil 算法的数学特性，非bug
            #
            # method='first' vs 'average'：
            #   - 'first': 相同值按出现顺序分配不同秩，保证分层覆盖所有股票
            #   - 'average': 相同值获得相同平均秩，可能导致某层股票过多
            factor_values_f64 = factor_values.astype("float64")
            ranks = factor_values_f64.rank(pct=True, method="first")
            layer_assignment = np.ceil(ranks * n_layers).astype(int)
            # 边界处理：rank=1.0 → ceil(5.0)=5, clip后归Layer5
            layer_assignment = layer_assignment.clip(1, n_layers)

        elif method == "fixed_threshold" and thresholds:
            # 固定阈值分层（最后一层右闭区间，其余右开）
            # 顺序依赖说明：
            #   1. 先处理边界外数据（低于最小阈值归Layer1，高于最大阈值归Layer n）
            #   2. 再处理边界内数据（循环归层）
            #   若调整顺序，需确保边界外数据不被循环覆盖
            # 使用显式 bool mask 替代哨兵值，避免歧义（v1.6 修正）
            layer_assignment = pd.Series(0, index=factor_values.index)  # 层号：0=未归层，1-n=已归层
            assigned = pd.Series(False, index=factor_values.index)  # 是否已归层的显式标记

            # ========== 边界处理（必须在循环前执行）==========
            # 低于最小阈值：归入 Layer 1
            below_min_mask = factor_values < thresholds[0]
            if below_min_mask.any():
                n_below = below_min_mask.sum()
                pct_below = n_below / len(factor_values) * 100
                logger.warning(
                    "fixed_threshold 边界警告: %s 个股票 (%.2f%%) 因子值低于最小阈值 %s，已归入 Layer1。"
                    "建议：检查 thresholds 参数是否覆盖数据范围，或使用 percentile 分层。",
                    n_below,
                    pct_below,
                    thresholds[0],
                )
                layer_assignment[below_min_mask] = 1
                assigned[below_min_mask] = True

            # 超最大阈值：归入最后一层
            above_max_mask = factor_values > thresholds[-1]
            if above_max_mask.any():
                n_above = above_max_mask.sum()
                pct_above = n_above / len(factor_values) * 100
                logger.warning(
                    "fixed_threshold 边界警告: %s 个股票 (%.2f%%) 因子值超过最大阈值 %s，已归入 Layer%s。"
                    "建议：检查 thresholds 参数是否覆盖数据范围，或使用 percentile 分层。",
                    n_above,
                    pct_above,
                    thresholds[-1],
                    n_layers,
                )
                layer_assignment[above_max_mask] = n_layers
                assigned[above_max_mask] = True

            # ========== 边界内循环归层 ==========
            for i in range(len(thresholds) - 1):
                lower = thresholds[i]
                upper = thresholds[i + 1]
                # 最后一层（i == len(thresholds) - 2）：右闭区间 [lower, upper]
                # 其余层：右开区间 [lower, upper)
                # 注意：len(thresholds) - 1 个区间，最后一个区间索引为 len(thresholds) - 2
                if i == len(thresholds) - 2:  # 最后一个区间（Layer n_layers）
                    mask = (factor_values >= lower) & (factor_values <= upper)
                else:  # 前 len(thresholds) - 2 个区间（Layer 1 到 n_layers-1）
                    mask = (factor_values >= lower) & (factor_values < upper)
                # 只处理未归层的股票（显式 bool mask，避免哨兵值歧义）
                mask_unassigned = mask & ~assigned
                layer_assignment[mask_unassigned] = i + 1
                assigned[mask_unassigned] = True

            # 断言：所有股票都已归层
            unassigned_mask = ~assigned
            if unassigned_mask.any():
                logger.error(
                    "fixed_threshold 逻辑错误: %s 个股票未归层，请检查 thresholds 参数是否覆盖数据范围",
                    unassigned_mask.sum(),
                )
                raise ValueError("fixed_threshold 分层逻辑错误：存在未归层的股票")

        else:
            raise ValueError(f"Unknown layer method: {method}")

        return layer_assignment

    def calculate_layer_returns(
        self, date: str, layer_assignment: pd.Series, returns: pd.Series, min_stocks: int = 10
    ) -> dict[int, float]:
        """
        计算各层收益（等权平均）

        参数:
            date: 日期
            layer_assignment: 分层归属
            returns: 收益序列
            min_stocks: 最少股票数

        返回:
            各层收益字典 {layer_id: return}
        """
        layer_returns = {}

        # 遍历顺序：从小到大，与后续 range(1, n_layers+1) 风格一致
        for layer_id in sorted(layer_assignment.dropna().unique()):
            if layer_id == 0:
                continue

            layer_mask = layer_assignment == layer_id
            layer_returns_vals = returns[layer_mask]

            # 空层检查
            if len(layer_returns_vals) < min_stocks:
                layer_returns[int(layer_id)] = np.nan
                continue

            # 过滤NaN收益
            valid_returns = layer_returns_vals.dropna()

            if len(valid_returns) < min_stocks // 2:
                layer_returns[int(layer_id)] = np.nan
            else:
                layer_returns[int(layer_id)] = float(valid_returns.mean())  # 转为float

        return layer_returns

    def calculate_turnover(
        self, prev_assignment: dict[str, Any] | None, curr_assignment: dict[str, Any]
    ) -> dict[int, float]:
        """
        计算换手率

        换手率 = 新入股票数 / 层股票总数

        参数类型说明:
            layer_id 实际类型为 numpy.int64（来自 pd.Series），标注 Any 防误导
        """
        turnover_rates = {}

        if prev_assignment is None:
            return turnover_rates

        # 获取所有层
        all_layers = set(curr_assignment.values())

        for layer_id in all_layers:
            # 当前层股票
            curr_stocks = {s for s, l in curr_assignment.items() if l == layer_id}

            # 前一期该层股票
            prev_stocks = {s for s, l in prev_assignment.items() if l == layer_id}

            # 新入股票
            new_stocks = curr_stocks - prev_stocks

            # 换手率
            if len(curr_stocks) > 0:
                turnover_rates[int(layer_id)] = float(len(new_stocks) / len(curr_stocks))
            else:
                turnover_rates[int(layer_id)] = 0.0

        return turnover_rates

    @staticmethod
    def _calc_daily_ls(group: pd.DataFrame, long_layers: list[int], short_layers: list[int]) -> pd.Series:
        """
        计算每日多空收益和换手率（静态方法，显式传参避免闭包捕获）

        参数:
            group: 单日数据 DataFrame
            long_layers: 多头组合层编号
            short_layers: 空头组合层编号

        返回:
            pd.Series: {'long_return', 'short_return', 'long_short_return', 'long_turnover', 'short_turnover'}
        """
        long_rets = group[group["layer"].isin(long_layers)]["return"].dropna()
        short_rets = group[group["layer"].isin(short_layers)]["return"].dropna()

        # 换手率：按日期分组取均值，避免多头多层重复计次
        long_turnover_vals = group[group["layer"].isin(long_layers)]["turnover"].dropna()
        short_turnover_vals = group[group["layer"].isin(short_layers)]["turnover"].dropna()

        if len(long_rets) > 0 and len(short_rets) > 0:
            return pd.Series(
                {
                    "long_return": long_rets.mean(),
                    "short_return": short_rets.mean(),
                    "long_short_return": long_rets.mean() - short_rets.mean(),
                    "long_turnover": long_turnover_vals.mean() if len(long_turnover_vals) > 0 else 0,
                    "short_turnover": short_turnover_vals.mean() if len(short_turnover_vals) > 0 else 0,
                }
            )
        return pd.Series(
            {
                "long_return": np.nan,
                "short_return": np.nan,
                "long_short_return": np.nan,
                "long_turnover": np.nan,
                "short_turnover": np.nan,
            }
        )

    def _aggregate_results(
        self,
        daily_df: pd.DataFrame,
        n_layers: int,
        long_layers: list[int],
        short_layers: list[int],
        factor_direction: str,
        trade_cost_rate: float,
        layer_method: str,
        thresholds: list[float] | None,
    ) -> dict:
        """汇总统计结果"""

        # ========== 空数据前置检查 ==========
        # 若所有日期数据量均不足 min_stocks_per_layer，daily_df 为空
        if len(daily_df) == 0:
            logger.warning(
                "回测无有效数据：所有日期数据量均不足 min_stocks_per_layer，"
                "请检查数据范围或降低 min_stocks_per_layer 参数"
            )
            # 构造结构完整但值为 None 的 layer_stats（与正常返回结构一致）
            layer_stats = {}
            for layer_id in range(1, n_layers + 1):
                layer_stats[f"layer_{layer_id}"] = {
                    "n_days": 0,
                    "n_stocks_avg": 0,
                    "daily_return_mean": None,
                    "daily_return_std": None,
                    "cumulative_return": None,
                    "annual_return": None,
                    "annual_volatility": None,
                    "sharpe_ratio": None,
                    "max_drawdown": None,
                    "turnover_avg": None,
                }
            return {
                "meta": {
                    "n_layers": n_layers,
                    "factor_direction": factor_direction,
                    "long_layers": long_layers,
                    "short_layers": short_layers,
                    "min_stocks_per_layer": 0,
                    "trade_cost_rate": trade_cost_rate,
                    "layer_method": layer_method,
                    "thresholds": thresholds,
                    "n_days_total": 0,
                    "n_assets_total": int(self.merged_df[self.asset_col].nunique()),  # nunique统计实际出现的唯一值
                },
                "layer_stats": layer_stats,
                "long_short": {},
                "monotonicity": {"correlation": None, "quality": "no_data", "layer_returns": [None] * n_layers},
                "trading_cost_analysis": {},
                "daily_records": [],
            }

        # 各层统计
        layer_stats = {}
        for layer_id in range(1, n_layers + 1):
            layer_data = daily_df[daily_df["layer"] == layer_id]

            # 过滤NaN收益
            # 假设说明：NaN 日（停牌、数据缺失）不参与收益计算
            #   - dropna() 后索引可能不连续（部分交易日缺失）
            #   - cumprod() 对非连续索引有效：所有非 NaN 日收益连乘
            #   - 语义：忽略停牌日收益，反映实际可交易时段的累计表现
            valid_returns = layer_data["return"].dropna()

            if len(valid_returns) == 0:
                layer_stats[f"layer_{layer_id}"] = {
                    "n_days": int(len(layer_data)),
                    "n_stocks_avg": 0,
                    "daily_return_mean": None,
                    "daily_return_std": None,
                    "cumulative_return": None,
                    "annual_return": None,
                    "annual_volatility": None,
                    "sharpe_ratio": None,
                    "max_drawdown": None,
                    "turnover_avg": None,
                }
                continue

            daily_return_mean = valid_returns.mean()
            daily_return_std = valid_returns.std()

            # 累计收益（假设：停牌日不参与计算，反映实际可交易时段表现）
            cum_returns = (1 + valid_returns).cumprod() - 1
            cumulative_return = cum_returns.iloc[-1] if len(cum_returns) > 0 else 0

            # 年化收益和波动
            annual_return = daily_return_mean * 252
            annual_volatility = daily_return_std * np.sqrt(252)

            # 夏普比率
            sharpe_ratio = annual_return / annual_volatility if annual_volatility > 0 else np.nan

            # 最大回撤（除零保护：净值归零时回撤应为 -1.0，而非 0）
            cum_series = (1 + valid_returns).cumprod()
            rolling_max = cum_series.expanding().max()
            # 除零保护：若 rolling_max == 0（净值归零），回撤 = -1.0（完全亏损）
            with np.errstate(divide="ignore", invalid="ignore"):
                drawdowns = (cum_series - rolling_max) / rolling_max
                drawdowns = np.where(rolling_max == 0, -1.0, drawdowns)  # 净值归零时回撤-1.0
            drawdowns = pd.Series(drawdowns, index=cum_series.index)
            max_drawdown = drawdowns.min()

            # 换手率
            turnover_data = layer_data["turnover"].dropna()
            turnover_avg = turnover_data.mean() if len(turnover_data) > 0 else 0

            layer_stats[f"layer_{layer_id}"] = {
                "n_days": int(len(layer_data)),  # 转 int 避免 JSON 序列化问题
                "n_stocks_avg": float(layer_data["n_stocks"].mean()),  # 转 float
                "daily_return_mean": float(daily_return_mean),
                "daily_return_std": float(daily_return_std),
                "cumulative_return": float(cumulative_return),
                "annual_return": float(annual_return),
                "annual_volatility": float(annual_volatility),
                "sharpe_ratio": float(sharpe_ratio) if not np.isnan(sharpe_ratio) else None,
                "max_drawdown": float(max_drawdown),
                "turnover_avg": float(turnover_avg),
            }

        # 多空组合统计（v1.6 修正：保留所有日期，年化考虑覆盖率）
        # pandas ≥ 2.2 下 groupby.apply 可能产生多级索引，改用 concat 更稳定
        # 显式排序日期：保证时间序列顺序，便于后续累计收益计算
        total_days = len(sorted(daily_df["date"].unique()))  # 总天数（含NaN日）
        daily_ls_list = []
        for date_val, group in daily_df.groupby("date", sort=True):
            ls_series = LayeredBacktestEngine._calc_daily_ls(group, long_layers, short_layers)
            # 保留所有日期（包括 NaN），用于计算总天数和覆盖率
            ls_series["date"] = date_val
            daily_ls_list.append(ls_series)

        if len(daily_ls_list) > 0:
            long_short_df = pd.DataFrame(daily_ls_list)
        else:
            long_short_df = pd.DataFrame()  # 空 DataFrame

        # 多空组合统计
        long_short_stats = {}
        if len(long_short_df) > 0:
            # 有效天数：用于均值计算（自动忽略 NaN）
            valid_days = long_short_df["long_short_return"].notna().sum()
            coverage = valid_days / total_days if total_days > 0 else 0

            ls_mean = long_short_df["long_short_return"].mean()  # 有效天数均值
            ls_std = long_short_df["long_short_return"].std()

            # 年化计算：考虑覆盖率（v1.6 修正）
            # 语义：如果某因子只有60%的交易日有数据，年化收益应乘以覆盖率
            ls_annual = ls_mean * 252 * coverage
            ls_vol = ls_std * np.sqrt(252)  # 波动率不需要覆盖率（假设NaN日波动为0）

            # 安全转换：NaN → None（避免 json.dumps 抛 ValueError）
            def safe_float(val):
                return None if pd.isna(val) else float(val)

            # 年化计算考虑覆盖率（v1.6 修正）
            long_mean = long_short_df["long_return"].mean()
            short_mean = long_short_df["short_return"].mean()
            long_turnover_mean = long_short_df["long_turnover"].mean()
            short_turnover_mean = long_short_df["short_turnover"].mean()

            long_short_stats = {
                "long_return_daily": safe_float(long_mean),
                "long_return_annual": safe_float(long_mean * 252 * coverage),
                "short_return_daily": safe_float(short_mean),
                "short_return_annual": safe_float(short_mean * 252 * coverage),
                "long_short_return_daily": safe_float(ls_mean),
                "long_short_return_annual": safe_float(ls_annual),
                "long_short_sharpe": safe_float(ls_annual / ls_vol) if ls_vol > 0 else None,
                "long_short_volatility": safe_float(ls_vol),
                # 换手率：统一命名（turnover_xxx_avg，与 layer_stats.turnover_avg 风格一致）
                "turnover_long_avg": safe_float(long_turnover_mean),
                "turnover_short_avg": safe_float(short_turnover_mean),
                "n_days": int(valid_days),  # 有效天数（转 int 避免 JSON 序列化问题）
                "n_days_total": int(total_days),  # 总天数（含NaN日）
                "coverage": float(coverage),  # 数据覆盖率
            }

        # 单调性检验
        monotonicity = self._calculate_monotonicity(layer_stats, n_layers, factor_direction)

        # 交易成本分析
        trading_cost_analysis = self._calculate_trading_costs(long_short_stats, trade_cost_rate)

        # 元数据
        meta = {
            "n_layers": n_layers,
            "factor_direction": factor_direction,
            "long_layers": long_layers,
            "short_layers": short_layers,
            # 简化 min 表达式：用 groupby 替代循环
            "min_stocks_per_layer": int(daily_df.groupby("layer")["n_stocks"].min().min()) if len(daily_df) > 0 else 0,
            "trade_cost_rate": trade_cost_rate,
            "layer_method": layer_method,
            "thresholds": thresholds,
            "n_days_total": int(len(daily_df["date"].unique())),  # 转 int 避免 JSON 序列化问题
            "n_assets_total": int(self.merged_df[self.asset_col].nunique()),  # nunique统计实际出现的唯一值
        }

        return {
            "meta": meta,
            "layer_stats": layer_stats,
            "long_short": long_short_stats,
            "monotonicity": monotonicity,
            "trading_cost_analysis": trading_cost_analysis,
            "daily_records": daily_df.to_dict("records"),
        }

    def _calculate_monotonicity(self, layer_stats: dict, n_layers: int, factor_direction: str) -> dict:
        """
        计算分层单调性

        对于反向因子，期望 Layer1收益 > Layer2 > ... > Layer5
        单调性应为负值
        """
        layer_returns = []
        for i in range(1, n_layers + 1):
            ret = layer_stats.get(f"layer_{i}", {}).get("daily_return_mean")
            # pd.notna 同时检查 NaN 和 None，语义更清晰
            if pd.notna(ret):
                layer_returns.append(ret)
            else:
                layer_returns.append(np.nan)

        # 计算相关系数
        valid_idx = [i for i, r in enumerate(layer_returns) if not pd.isna(r)]
        if len(valid_idx) >= 2:
            layer_ids = np.array([i + 1 for i in valid_idx])
            returns = np.array([layer_returns[i] for i in valid_idx])

            correlation = np.corrcoef(layer_ids, returns)[0, 1]

            # 对于反向因子，期望负相关
            if factor_direction == "negative":
                monotonic_quality = "good" if correlation < -0.5 else ("moderate" if correlation < 0 else "poor")
            else:
                monotonic_quality = "good" if correlation > 0.5 else ("moderate" if correlation > 0 else "poor")

            return {"correlation": float(correlation), "quality": monotonic_quality, "layer_returns": layer_returns}

        return {"correlation": None, "quality": "insufficient_data", "layer_returns": layer_returns}

    def _calculate_trading_costs(self, long_short_stats: dict, trade_cost_rate: float) -> dict:
        """计算交易成本"""
        if not long_short_stats:
            return {}

        # 安全取值：显式处理 NaN（v1.6 修正）
        # 换手率 NaN → 成本按 0 处理（语义：换手率未知时无法计算交易成本）
        long_turnover_raw = long_short_stats.get("turnover_long_avg")
        short_turnover_raw = long_short_stats.get("turnover_short_avg")
        long_turnover = 0.0 if pd.isna(long_turnover_raw) else float(long_turnover_raw)
        short_turnover = 0.0 if pd.isna(short_turnover_raw) else float(short_turnover_raw)

        # 收益：保持 None/NaN 不替换为 0.0
        # 语义区分：None=收益未知 ≠ 0.0=收益恰好为零
        long_daily_ret = long_short_stats.get("long_return_daily")
        short_daily_ret = long_short_stats.get("short_return_daily")

        # 多头交易成本（单边）
        long_daily_cost = long_turnover * trade_cost_rate

        # 空头交易成本（双边，因为做空需要借券）
        short_daily_cost = short_turnover * trade_cost_rate * 2

        # 净收益计算：仅对非 None/NaN 的收益做算术运算，否则传播 None
        def _safe_net(gross, cost):
            """收益未知 → 净收益也未知，不将 None 伪装为 0"""
            if gross is None or (gross is not None and pd.isna(gross)):
                return None
            return gross - cost

        def _safe_ls_diff(long_ret, short_ret, long_cost, short_cost):
            """多空差值：任一方收益未知 → 差值也未知"""
            if long_ret is None or short_ret is None:
                return None
            if pd.isna(long_ret) or pd.isna(short_ret):
                return None
            return (long_ret - long_cost) - (short_ret - short_cost)

        return {
            "cost_rate": trade_cost_rate,
            "long_turnover": long_turnover,
            "short_turnover": short_turnover,
            "long_daily_cost": long_daily_cost,
            "short_daily_cost": short_daily_cost,
            "long_gross_daily_return": long_daily_ret,
            "long_net_daily_return": _safe_net(long_daily_ret, long_daily_cost),
            "short_gross_daily_return": short_daily_ret,
            "short_net_daily_return": _safe_net(short_daily_ret, short_daily_cost),
            "long_short_gross_daily": _safe_ls_diff(long_daily_ret, short_daily_ret, 0, 0),
            "long_short_net_daily": _safe_ls_diff(long_daily_ret, short_daily_ret, long_daily_cost, short_daily_cost),
        }

    def generate_report(self, result: dict) -> str:
        """生成文本报告"""
        lines = []
        lines.append("=" * 70)
        lines.append("分层回测报告")
        lines.append("=" * 70)
        lines.append("")

        # 元数据
        meta = result["meta"]
        lines.append(f"分层数量: {meta['n_layers']}")
        lines.append(f"因子方向: {'反向因子' if meta['factor_direction'] == 'negative' else '正向因子'}")
        lines.append(f"多头组合: Layer {', '.join(map(str, meta['long_layers']))}")
        lines.append(f"空头组合: Layer {', '.join(map(str, meta['short_layers']))}")
        lines.append(f"回测天数: {meta['n_days_total']}")
        lines.append(f"股票数量: {meta['n_assets_total']}")
        lines.append("")

        # 分层收益统计
        lines.append("-" * 70)
        lines.append("一、分层收益统计")
        lines.append("-" * 70)
        lines.append(f"{'分层':<8} {'股票数':<10} {'日均收益':<12} {'年化收益':<12} {'夏普比':<10} {'换手率':<10}")
        lines.append("-" * 70)

        # 统计有效层数（用于空数据提示）
        valid_layer_count = 0
        for layer_id in range(1, meta["n_layers"] + 1):
            stats = result["layer_stats"].get(f"layer_{layer_id}", {})
            if stats.get("n_stocks_avg", 0) == 0:
                continue

            valid_layer_count += 1
            n_stocks = stats.get("n_stocks_avg", 0)
            daily_ret = stats.get("daily_return_mean")
            annual_ret = stats.get("annual_return")
            sharpe = stats.get("sharpe_ratio")
            turnover = stats.get("turnover_avg")

            # 使用 _format_pct 处理 NaN（v1.6 修正）
            sharpe_str = f"{sharpe:.2f}" if sharpe is not None and not pd.isna(sharpe) else "N/A"
            daily_str = _format_pct(daily_ret, decimals=2)
            annual_str = _format_pct(annual_ret, decimals=2)
            turnover_str = _format_pct(turnover, decimals=1)

            lines.append(
                f"Layer{layer_id:<3} {n_stocks:<10.0f} {daily_str:>10} {annual_str:>10} {sharpe_str:<10} {turnover_str:>8}"
            )

        # 空数据提示（所有层都无效时）
        if valid_layer_count == 0:
            lines.append("⚠ 无有效分层数据：所有日期数据量均不足 min_stocks_per_layer")
            lines.append("  建议：检查数据范围或降低 min_stocks_per_layer 参数")

        lines.append("-" * 70)
        lines.append("")

        # 多空组合表现
        lines.append("-" * 70)
        lines.append("二、多空组合表现")
        lines.append("-" * 70)

        ls_stats = result.get("long_short", {})
        if ls_stats:
            long_daily = ls_stats.get("long_return_daily")
            long_annual = ls_stats.get("long_return_annual")
            short_daily = ls_stats.get("short_return_daily")
            short_annual = ls_stats.get("short_return_annual")
            ls_daily = ls_stats.get("long_short_return_daily")
            ls_annual = ls_stats.get("long_short_return_annual")

            # 使用 _format_pct 处理 NaN（v1.6 修正）
            lines.append(f"多头日均收益: {_format_pct(long_daily, 4)}")
            lines.append(f"多头年化收益: {_format_pct(long_annual, 2)}")
            lines.append(f"空头日均收益: {_format_pct(short_daily, 4)}")
            lines.append(f"空头年化收益: {_format_pct(short_annual, 2)}")
            lines.append(f"多空日均收益: {_format_pct(ls_daily, 4)}")
            lines.append(f"多空年化收益: {_format_pct(ls_annual, 2)}")
            # 夏普比率可能为 None（volatility=0 时），需单独处理避免 TypeError
            sharpe = ls_stats.get("long_short_sharpe")
            sharpe_str = f"{sharpe:.2f}" if sharpe is not None and not pd.isna(sharpe) else "N/A"
            lines.append(f"多空夏普比率: {sharpe_str}")
        else:
            # 空数据提示
            lines.append("⚠ 无多空组合数据：缺少有效的多空层收益数据")

        lines.append("-" * 70)
        lines.append("")

        # 单调性
        lines.append("-" * 70)
        lines.append("三、单调性检验")
        lines.append("-" * 70)

        mono = result.get("monotonicity", {})
        corr = mono.get("correlation")
        if corr is not None:
            lines.append(f"分层单调性相关系数: {corr:.4f}")
            lines.append(f"单调性质量: {mono.get('quality', 'unknown')}")

            if meta["factor_direction"] == "negative":
                if corr < -0.5:
                    lines.append("✓ 反向因子单调性良好（Layer1 > Layer5）")
                elif corr < 0:
                    lines.append("△ 反向因子单调性一般")
                else:
                    lines.append("✗ 反向因子单调性较差")
            else:  # positive
                if corr > 0.5:
                    lines.append("✓ 正向因子单调性良好（Layer1 < Layer5）")
                elif corr > 0:
                    lines.append("△ 正向因子单调性一般")
                else:
                    lines.append("✗ 正向因子单调性较差")
        else:
            # 空数据提示
            quality = mono.get("quality", "unknown")
            lines.append(f"单调性质量: {quality}")
            if quality == "no_data":
                lines.append("⚠ 无单调性数据：缺少有效的分层收益数据")

        lines.append("-" * 70)
        lines.append("")

        # 交易成本分析
        lines.append("-" * 70)
        lines.append("四、交易成本分析")
        lines.append("-" * 70)

        cost = result.get("trading_cost_analysis", {})
        if cost:
            cost_rate = cost.get("cost_rate")
            long_turnover = cost.get("long_turnover")
            short_turnover = cost.get("short_turnover")
            long_daily_cost = cost.get("long_daily_cost")
            short_daily_cost = cost.get("short_daily_cost")
            ls_gross = cost.get("long_short_gross_daily")
            ls_net = cost.get("long_short_net_daily")
            lines.append(f"单边交易成本率: {_format_pct(cost_rate, 2)}")
            lines.append(f"多头日均换手率: {_format_pct(long_turnover, 2)}")
            lines.append(f"空头日均换手率: {_format_pct(short_turnover, 2)}")
            lines.append(f"多头日均成本: {_format_pct(long_daily_cost, 4)}")
            lines.append(f"空头日均成本: {_format_pct(short_daily_cost, 4)}")
            lines.append(f"多空毛收益: {_format_pct(ls_gross, 4)}")
            lines.append(f"多空净收益: {_format_pct(ls_net, 4)}")
        else:
            # 空数据提示
            lines.append("⚠ 无交易成本数据：缺少有效的多空组合换手率数据")

        lines.append("-" * 70)

        return "\n".join(lines)
