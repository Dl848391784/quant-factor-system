#!/usr/bin/env python3
"""
策略验证脚本 - 事后验证策略表现(修正版)

核心修正:
1. T+N周期在第N天收盘验证(而非统一7天后验证)
2. 每日检查今日需要验证的各周期推荐
3. 同一天可能验证多个周期(并行验证)

职责:
1. 每日18:00执行
2. 检查今日需要验证的周期(T+1/T+3/T+5)
3. 计算实际收益
4. 更新验证记录和成功率
"""

import json
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
import numpy as np

# ===== 配置常量 =====
BASE_DIR = Path(__file__).parent.parent.parent  # scripts -> v2 -> factor_ic_analyzer(项目根目录)
CACHE_DIR = BASE_DIR / "cache" / "v2"
PRECOMPUTE_DIR = CACHE_DIR / "precompute"

HISTORY_DIR = PRECOMPUTE_DIR / "history"
VALIDATION_FILE = CACHE_DIR / "strategy_validation.json"
COMBO_FILE = CACHE_DIR / "weight_combinations.json"
RATING_FILE = CACHE_DIR / "strategy_rating.json"

# 周期配置
PERIODS = {
    'T+1': {'days': 1, 'desc': '1天持仓'},
    'T+3': {'days': 3, 'desc': '3天持仓'},
    'T+5': {'days': 5, 'desc': '5天持仓'}
}

# 成功阈值(收益率 > 0 即为成功)
SUCCESS_THRESHOLD = 0.0


class StrategyValidator:
    """策略验证器(修正版)"""

    def __init__(self):
        self.today = datetime.now()
        self.validation_data = self._load_validation_data()
        self.combo_data = self._load_combo_data()
        self.rating_data = self._load_rating_data()
        self._return_data_cache = None  # 本地收益率数据缓存

    def _load_return_data(self) -> Dict:
        """
        加载本地收益率数据(return_data.json.gz)

        数据格式:
        {
          "meta": {...},
          "data": [{"date": "2024-01-23", "asset": "002309", "forward_return_1d": 0.022, ...}]
        }

        返回:
          {"2024-01-23_002309": {"forward_return_1d": 0.022, ...}, ...}
        """
        # 使用缓存
        if self._return_data_cache is not None:
            return self._return_data_cache

        import gzip

        return_file = BASE_DIR / "cache" / "factor_data" / "return_data.json.gz"

        if not return_file.exists():
            print(f"  ⚠ 本地收益率数据文件不存在: {return_file}")
            return {}

        try:
            with gzip.open(return_file, 'rt', encoding='utf-8') as f:
                raw_data = json.load(f)

            # 构建索引:{date}_{asset} -> {forward_return_1d, ...}
            data_index = {}
            for item in raw_data.get('data', []):
                key = f"{item['date']}_{item['asset']}"
                data_index[key] = {
                    'forward_return_1d': item.get('forward_return_1d'),
                    'forward_return_3d': item.get('forward_return_3d'),
                    'forward_return_5d': item.get('forward_return_5d')
                }

            self._return_data_cache = data_index
            print(f"  ✓ 本地收益率数据已加载: {len(data_index)} 条记录")
            return data_index

        except Exception as e:
            print(f"  ⚠ 加载本地收益率数据失败: {e}")
            return {}

    # ===== 数据加载 =====

    def _load_validation_data(self) -> Dict:
        """加载验证数据(strategy_validation.json)"""
        if VALIDATION_FILE.exists():
            with open(VALIDATION_FILE, encoding='utf-8') as f:
                return json.load(f)

        # 初始化新文件
        return {
            'meta': {
                'generated_at': datetime.now().isoformat(),
                'data_version': '1.0',
                'last_run': None
            },
            'validations': [],
            'summary': {}
        }

    def _load_combo_data(self) -> Dict:
        """加载权重组合数据(weight_combinations.json)"""
        if COMBO_FILE.exists():
            with open(COMBO_FILE, encoding='utf-8') as f:
                return json.load(f)

        # 初始化新文件
        return {
            'meta': {
                'generated_at': datetime.now().isoformat(),
                'data_version': '1.0'
            },
            'combinations': {},
            'by_period': {}
        }

    def _load_rating_data(self) -> Dict:
        """加载评分数据(strategy_rating.json)"""
        if RATING_FILE.exists():
            with open(RATING_FILE, encoding='utf-8') as f:
                return json.load(f)

        return {'ratings': {}}

    # ===== 核心逻辑1:获取今日需要验证的预测 =====

    def get_predictions_to_validate_today(self) -> List[Dict]:
        """
        核心逻辑:获取今日需要验证的预测

        云柏修正后的方案:
        验证日 = T-1(本地数据的截止日期)
        推荐日 = 验证日 - 周期天数

        示例(今天是28号,数据截止27号):
        - T+1验证:推荐日26号,使用26号的forward_return_1d
        - T+3验证:推荐日24号,使用24号的forward_return_3d
        - T+5验证:推荐日22号,使用22号的forward_return_5d
        """
        predictions_today = []

        # 获取数据截止日期(T-1)
        data_end_date = self._get_data_end_date()
        if data_end_date is None:
            print("  ⚠ 无法获取数据截止日期")
            return []

        validation_date_str = data_end_date.strftime('%Y-%m-%d')
        print(f"  验证日期(数据截止):{validation_date_str}")

        # 遍历三个周期
        for period, config in PERIODS.items():
            period_days = config['days']

            # 核心修正:推荐日期 = 验证日期 - 周期天数
            prediction_date = data_end_date - timedelta(days=period_days)
            prediction_date_str = prediction_date.strftime('%Y-%m-%d')

            # 验证ID = "val_{推荐日期}_{周期}"
            validation_id = f"val_{prediction_date_str}_{period}"

            # 检查是否已验证过
            if self._is_already_validated(validation_id):
                print(f"  ⊙ {period} 已验证过(推荐日期:{prediction_date_str}),跳过")
                continue

            # 加载推荐日的策略数据
            # 云汐修正：优先读取 optimization_summary.json，兼容 optimization_result_multi_period.json
            history_file = HISTORY_DIR / prediction_date_str / "optimization_summary.json"
            fallback_file = HISTORY_DIR / prediction_date_str / "optimization_result_multi_period.json"
            
            if history_file.exists():
                data_file = history_file
            elif fallback_file.exists():
                data_file = fallback_file
            else:
                print(f"  ⚠ {period} 找不到推荐日数据（{prediction_date_str}），跳过")
                continue

            with open(data_file, encoding='utf-8') as f:
                strategy_data = json.load(f)

            # 提取策略信息
            period_data = strategy_data.get('periods', {}).get(period, {})
            if not period_data:
                print(f"  ⚠ {period} 推荐日数据无此周期（{prediction_date_str}），跳过")
                continue

            # 云汐修正：weights 在 metrics.weights，兼容顶层 weights
            metrics_data = period_data.get('metrics', {})
            weights = metrics_data.get('weights', period_data.get('weights', {}))
            combo_id = self._identify_weight_combo(period, weights)

            # 云汐修正：stocks 是完整对象数组，需要提取 code 字段
            stocks_raw = period_data.get('stocks', [])
            if isinstance(stocks_raw, list) and len(stocks_raw) > 0:
                # 如果第一个元素是对象（有 code 字段），提取 code
                if isinstance(stocks_raw[0], dict) and 'code' in stocks_raw[0]:
                    stocks = [s.get('code') for s in stocks_raw if s.get('code')]
                else:
                    # 已经是简单代码数组
                    stocks = stocks_raw
            else:
                # 兼容 top_stocks 或 recommended_stocks
                stocks = period_data.get('top_stocks', period_data.get('recommended_stocks', []))

            # 构建预测对象
            prediction = {
                'validation_id': validation_id,
                'prediction_date': prediction_date_str,
                'period': period,
                'period_days': period_days,
                'validation_date': validation_date_str,
                'stocks': stocks,
                'weights': weights,
                'combo_id': combo_id,
                'metrics': metrics_data
            }

            predictions_today.append(prediction)
            print(f"  ✓ {period} 待验证(推荐日期:{prediction_date_str} → 验证日期:{validation_date_str})")

        return predictions_today

    def _get_data_end_date(self) -> Optional[datetime]:
        """
        获取本地数据的截止日期(T-1)

        从 return_data.json.gz 的 meta.date_range.end 获取
        """
        import gzip

        return_file = BASE_DIR / "cache" / "factor_data" / "return_data.json.gz"

        if not return_file.exists():
            return None

        try:
            with gzip.open(return_file, 'rt', encoding='utf-8') as f:
                raw_data = json.load(f)

            date_range = raw_data.get('meta', {}).get('date_range', {})
            end_date_str = date_range.get('end')

            if end_date_str:
                return datetime.strptime(end_date_str, '%Y-%m-%d')
            return None

        except Exception as e:
            print(f"  ⚠ 获取数据截止日期失败: {e}")
            return None

    def _is_already_validated(self, validation_id: str) -> bool:
        """检查是否已验证过"""
        validations = self.validation_data.get('validations', [])
        return any(v.get('validation_id') == validation_id for v in validations)

    def _identify_weight_combo(self, period: str, weights: Dict) -> str:
        """
        识别权重组合ID

        算法:
        1. 使用数值比较匹配已有组合(允许±0.05差异)
        2. 在 weight_combinations.json 中查找匹配的组合
        3. 如果找不到,生成新的combo_id
        """
        # 查找已有组合(数值比较)
        combos = self.combo_data.get('combinations', {})
        for combo_id, combo in combos.items():
            if combo.get('period') == period and self._match_weight_signature(weights, combo):
                return combo_id

        # 新组合,生成ID
        new_combo_id = f"combo_{len(combos) + 1:03d}"
        return new_combo_id

    def _match_weight_signature(self, weights: Dict, existing_combo: Dict) -> bool:
        """
        权重签名匹配(允许±0.05差异)

        Args:
            weights: 当前权重
            existing_combo: 已有组合数据

        Returns:
            是否匹配
        """
        combo_weights = existing_combo.get('weights', {})
        for factor in ['rsi', 'bollinger_pb', 'volume_ratio', 'turnover_surge', 'return_3d']:
            w1 = weights.get(factor, 0)
            w2 = combo_weights.get(factor, 0)
            if abs(w1 - w2) > 0.05:  # 允许±0.05差异
                return False
        return True

    def _generate_weight_signature(self, weights: Dict) -> str:
        """
        生成权重签名

        格式:-0.4_-0.3_-0.4_-0.3_0.1(按顺序:rsi, bollinger_pb, volume_ratio, turnover_surge, return_3d)

        注意:四舍五入到小数点后1位,允许±0.05的微小差异
        """
        factors = ['rsi', 'bollinger_pb', 'volume_ratio', 'turnover_surge', 'return_3d']

        signature_parts = []
        for factor in factors:
            value = weights.get(factor, 0)
            rounded = round(value, 1)  # 四舍五入到小数点后1位
            signature_parts.append(f"{rounded:.1f}")

        return '_'.join(signature_parts)

    # ===== 核心逻辑2:计算实际收益 =====

    def calculate_actual_returns(
        self,
        stocks: List[str],
        weights: Dict,
        prediction_date: str,
        validation_date: str,
        period_days: int
    ) -> Tuple[Dict[str, float], float, float]:
        """
        核心逻辑:计算实际收益(使用本地数据)

        云柏修正后的方案:
        直接从本地数据读取 forward_return_Nd

        Args:
            stocks: 推荐股票列表
            weights: 权重
            prediction_date: 推荐日期
            validation_date: 验证日期
            period_days: 周期天数(1/3/5)

        Returns:
            (个股收益字典, 组合收益, 基准收益)
        """
        # 加载本地收益率数据
        return_data = self._load_return_data()

        # 根据周期天数选择字段
        field = f"forward_return_{period_days}d"

        actual_returns = {}
        for stock in stocks:
            # 构建索引 key
            key = f"{prediction_date}_{stock}"

            # 查找数据
            stock_return = return_data.get(key, {}).get(field)

            if stock_return is None:
                print(f"    ⚠ {stock}: 无收益率数据(key: {key}, field: {field})")
                actual_returns[stock] = None
            else:
                actual_returns[stock] = round(stock_return, 4)
                print(f"    ✓ {stock}: 收益率 {stock_return:.2%}")

        # 计算组合收益(按权重加权平均)
        portfolio_return = self._calculate_portfolio_return(actual_returns, weights)

        # 基准收益:暂用0,后续可从本地数据获取沪深300收益
        benchmark_return = 0.0

        return actual_returns, portfolio_return, benchmark_return

    # ===== 组合收益计算 =====

    def _calculate_portfolio_return(
        self,
        actual_returns: Dict[str, float],
        weights: Dict
    ) -> float:
        """
        计算组合收益

        注意:
        1. 只计算有效收益率(非None)
        2. 按权重加权平均
        """
        valid_returns = {k: v for k, v in actual_returns.items() if v is not None}

        if not valid_returns:
            return 0.0

        # 按权重加权平均(这里简化为等权重,实际需要传入具体权重)
        total_weight = 0.0
        weighted_sum = 0.0

        for stock, ret in valid_returns.items():
            weight = 1.0 / len(valid_returns)  # 等权重作为默认
            total_weight += weight
            weighted_sum += weight * ret

        return round(weighted_sum / total_weight if total_weight > 0 else 0.0, 4)

    # ===== 核心逻辑3:验证单个预测 =====

    def validate_prediction(self, prediction: Dict) -> Dict:
        """
        核心逻辑:验证单个预测

        流程:
        1. 计算实际收益
        2. 判断是否成功(portfolio_return > 0)
        3. 构建验证记录
        """
        print(f"\n  → 验证 {prediction['validation_id']}...")

        # 计算收益(传递 period_days)
        actual_returns, portfolio_return, benchmark_return = self.calculate_actual_returns(
            prediction['stocks'],
            prediction['weights'],
            prediction['prediction_date'],
            prediction['validation_date'],
            prediction['period_days']  # 新增参数
        )

        # 计算超额收益
        excess_return = portfolio_return - benchmark_return

        # 判断是否成功
        success = portfolio_return > SUCCESS_THRESHOLD

        # 构建验证记录
        validation_record = {
            'validation_id': prediction['validation_id'],
            'prediction_date': prediction['prediction_date'],
            'period': prediction['period'],
            'period_days': prediction['period_days'],
            'validation_date': prediction['validation_date'],
            'predicted_stocks': prediction['stocks'],
            'predicted_weights': prediction['weights'],
            'weight_combo_id': prediction['combo_id'],
            'actual_returns': {k: v for k, v in actual_returns.items() if v is not None},
            'portfolio_return': round(portfolio_return, 4),
            'benchmark_return': round(benchmark_return, 4),
            'excess_return': round(excess_return, 4),
            'success': success,
            'success_threshold': SUCCESS_THRESHOLD,
            'created_at': datetime.now().isoformat()
        }

        # 打印结果
        status = "✓ 成功" if success else "✗ 失败"
        print(f"    {status}: 组合收益 {portfolio_return:.2%}, 超额收益 {excess_return:.2%}")

        return validation_record

    # ===== 核心逻辑4:更新成功率 =====

    def update_success_rates(self, validations: List[Dict]):
        """
        核心逻辑:更新成功率

        流程:
        1. 更新 strategy_validation.json 的 summary
        2. 更新 weight_combinations.json 的成功率
        """
        print("\n  → 更新成功率...")

        # 更新 strategy_validation.json
        self._update_validation_summary(validations)

        # 更新 weight_combinations.json
        self._update_combo_success_rates(validations)

    def _update_validation_summary(self, validations: List[Dict]):
        """更新验证汇总统计"""
        # 添加新验证记录
        self.validation_data['validations'].extend(validations)

        # 计算汇总统计
        all_validations = self.validation_data['validations']
        total = len(all_validations)
        successful = sum(1 for v in all_validations if v.get('success', False))

        # 按周期统计
        by_period = {}
        for v in all_validations:
            period = v.get('period', 'unknown')
            if period not in by_period:
                by_period[period] = {'total': 0, 'successful': 0, 'avg_return': 0.0, 'avg_excess_return': 0.0}

            by_period[period]['total'] += 1
            if v.get('success', False):
                by_period[period]['successful'] += 1

            by_period[period]['avg_return'] += v.get('portfolio_return', 0)
            by_period[period]['avg_excess_return'] += v.get('excess_return', 0)

        # 计算平均值和成功率
        for period, stats in by_period.items():
            stats['success_rate'] = round(stats['successful'] / stats['total'], 4) if stats['total'] > 0 else 0
            stats['avg_return'] = round(stats['avg_return'] / stats['total'], 4) if stats['total'] > 0 else 0
            stats['avg_excess_return'] = round(stats['avg_excess_return'] / stats['total'], 4) if stats['total'] > 0 else 0

        # 按组合统计
        by_combo = {}
        for v in all_validations:
            combo_id = v.get('weight_combo_id', 'unknown')
            if combo_id not in by_combo:
                by_combo[combo_id] = {'total': 0, 'successful': 0, 'avg_return': 0.0}

            by_combo[combo_id]['total'] += 1
            if v.get('success', False):
                by_combo[combo_id]['successful'] += 1

            by_combo[combo_id]['avg_return'] += v.get('portfolio_return', 0)

        # 计算平均值和成功率
        for combo_id, stats in by_combo.items():
            stats['success_rate'] = round(stats['successful'] / stats['total'], 4) if stats['total'] > 0 else 0
            stats['avg_return'] = round(stats['avg_return'] / stats['total'], 4) if stats['total'] > 0 else 0

        # 更新汇总
        self.validation_data['summary'] = {
            'total_validations': total,
            'successful_validations': successful,
            'overall_success_rate': round(successful / total, 4) if total > 0 else 0,
            'by_period': by_period,
            'by_combo': by_combo,
            'last_updated': datetime.now().isoformat()
        }

        print(f"    ✓ 验证汇总已更新:总数 {total}, 成功 {successful}")

    def _update_combo_success_rates(self, validations: List[Dict]):
        """
        更新权重组合成功率

        注意:
        1. 对于新组合,创建新的组合记录
        2. 对于已有组合,更新成功率
        """
        combos = self.combo_data.get('combinations', {})

        for v in validations:
            combo_id = v.get('weight_combo_id')
            period = v.get('period')
            weights = v.get('predicted_weights', {})
            success = v.get('success', False)
            portfolio_return = v.get('portfolio_return', 0)
            prediction_date = v.get('prediction_date')

            # 如果是新组合,创建记录
            if combo_id not in combos:
                combos[combo_id] = {
                    'combo_id': combo_id,
                    'period': period,
                    'weights': weights,
                    'weight_signature': self._generate_weight_signature(weights),
                    'appearances': 1,
                    'successes': 1 if success else 0,
                    'success_rate': 1.0 if success else 0.0,
                    'avg_return': portfolio_return,
                    'max_return': portfolio_return,
                    'min_return': portfolio_return,
                    'first_seen': prediction_date,
                    'last_seen': prediction_date,
                    'recent_5_success_rate': 1.0 if success else 0.0,
                    'trend': 'new'
                }
                print(f"    ✓ 新组合 {combo_id} 已创建")
            else:
                # 已有组合,更新数据
                combo = combos[combo_id]
                combo['appearances'] += 1
                if success:
                    combo['successes'] += 1

                combo['success_rate'] = round(combo['successes'] / combo['appearances'], 4)
                combo['avg_return'] = round((combo['avg_return'] * (combo['appearances'] - 1) + portfolio_return) / combo['appearances'], 4)
                combo['max_return'] = max(combo['max_return'], portfolio_return)
                combo['min_return'] = min(combo['min_return'], portfolio_return)
                combo['last_seen'] = prediction_date
                combo['recent_5_success_rate'] = combo['success_rate']
                combo['trend'] = self._determine_trend(combo['success_rate'], combo['recent_5_success_rate'])
                print(f"    ✓ 组合 {combo_id} 已更新:成功率 {combo['success_rate']:.2%}")

        # 更新按周期统计
        self._update_by_period_stats()

    def _determine_trend(self, overall_rate: float, recent_5_rate: float) -> str:
        """判断趋势"""
        if recent_5_rate > overall_rate * 1.1:
            return 'rising'
        elif recent_5_rate < overall_rate * 0.9:
            return 'declining'
        else:
            return 'stable'

    def _update_by_period_stats(self):
        """更新按周期统计"""
        combos = self.combo_data.get('combinations', {})
        by_period = {}

        for combo_id, combo in combos.items():
            period = combo.get('period', 'unknown')

            if period not in by_period:
                by_period[period] = {'total_combos': 0, 'successful_combos': 0, 'best_combo_id': None, 'best_combo_success_rate': 0.0}

            by_period[period]['total_combos'] += 1
            if combo['success_rate'] >= 0.6:
                by_period[period]['successful_combos'] += 1

            if combo['success_rate'] > by_period[period]['best_combo_success_rate']:
                by_period[period]['best_combo_id'] = combo_id
                by_period[period]['best_combo_success_rate'] = combo['success_rate']

        self.combo_data['by_period'] = by_period

    # ===== 数据保存 =====

    def _save_validation_data(self):
        """保存验证数据"""
        self.validation_data['meta']['last_run'] = datetime.now().isoformat()
        VALIDATION_FILE.parent.mkdir(parents=True, exist_ok=True)

        with open(VALIDATION_FILE, 'w', encoding='utf-8') as f:
            json.dump(self.validation_data, f, indent=2, ensure_ascii=False)

        print(f"  ✓ 验证数据已保存:{VALIDATION_FILE}")

    def _save_combo_data(self):
        """保存权重组合数据"""
        self.combo_data['meta']['generated_at'] = datetime.now().isoformat()
        COMBO_FILE.parent.mkdir(parents=True, exist_ok=True)

        with open(COMBO_FILE, 'w', encoding='utf-8') as f:
            json.dump(self.combo_data, f, indent=2, ensure_ascii=False)

        print(f"  ✓ 权重组合数据已保存:{COMBO_FILE}")

    # ===== 主流程 =====

    def run(self):
        """
        主流程

        步骤:
        1. 获取今日需要验证的预测
        2. 逐个验证
        3. 更新成功率
        4. 保存数据
        5. 打印摘要
        """
        print("=" * 60)
        print("🔍 策略验证开始(修正版)")
        print(f"  今日日期: {self.today.strftime('%Y-%m-%d')}")
        print("=" * 60)

        # 1. 获取今日需要验证的预测
        predictions = self.get_predictions_to_validate_today()

        if not predictions:
            print("\n  ⊙ 今日无待验证预测")
            return

        print(f"\n  → 找到 {len(predictions)} 个待验证预测")

        # 2. 逐个验证
        validations = []
        for prediction in predictions:
            result = self.validate_prediction(prediction)
            if result:
                validations.append(result)

        if not validations:
            print("\n  ✗ 无有效验证结果")
            return

        # 3. 更新成功率
        self.update_success_rates(validations)

        # 4. 保存数据
        self._save_validation_data()
        self._save_combo_data()

        # 5. 打印摘要
        self._print_summary()

        print("=" * 60)
        print("✓ 策略验证完成")
        print("=" * 60)

    def _print_summary(self):
        """打印摘要"""
        summary = self.validation_data.get('summary', {})

        print("\n📊 验证统计摘要:")
        print(f"  总验证数: {summary.get('total_validations', 0)}")
        print(f"  成功数: {summary.get('successful_validations', 0)}")
        overall_rate = summary.get('overall_success_rate', 0)
        print(f"  整体成功率: {overall_rate:.2%}")

        print("\n  按周期统计:")
        for period, stats in summary.get('by_period', {}).items():
            sr = stats['success_rate']
            ar = stats['avg_return']
            print(f"    {period}: 成功率 {sr:.2%} ({stats['successful']}/{stats['total']}), 平均收益 {ar:.2%}")

        print("\n  按组合统计:")
        for combo_id, stats in summary.get('by_combo', {}).items():
            sr = stats['success_rate']
            ar = stats['avg_return']
            print(f"    {combo_id}: 成功率 {sr:.2%} ({stats['successful']}/{stats['total']}), 平均收益 {ar:.2%}")


# ===== 入口 =====
if __name__ == '__main__':
    validator = StrategyValidator()
    validator.run()