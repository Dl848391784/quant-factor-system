#!/usr/bin/env python3
"""
策略追踪脚本 - 计算历史评分（v2.0版本）

v2.0 核心变更：
- 成功率维度：历史成功率 → 权重组合成功率
- 稳定性维度：权重稳定性 → 权重相似度

评分算法（v2.0）：
- 权重组合成功率（40%）：匹配历史组合的成功率
- 权重相似度（30%）：与历史成功组合的相似程度
- ICIR稳定性（30%）：ICIR随时间的变化程度

作者：云舟
版本：v2.0
"""

import json
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
import sys
import os
import math

# 添加项目根目录到 sys.path
PROJECT_ROOT = Path(__file__).parent.parent.parent  # scripts -> v2 -> factor_ic_analyzer（项目根目录）
sys.path.insert(0, str(PROJECT_ROOT))

# 配置路径
HISTORY_DIR = PROJECT_ROOT / "cache" / "v2" / "precompute" / "history"
OUTPUT_FILE = PROJECT_ROOT / "cache" / "v2" / "strategy_rating.json"
COMBINATIONS_FILE = PROJECT_ROOT / "cache" / "v2" / "weight_combinations.json"
CURRENT_RESULT_FILE = PROJECT_ROOT / "v2" / "output" / "optimization_result_multi_period.json"
ANALYSIS_DAYS = 30  # 分析最近30天数据

# 权重因子列表（固定顺序）
WEIGHT_FACTORS = ['rsi', 'bollinger_pb', 'volume_ratio', 'turnover_surge', 'return_3d']

# 尝试导入 numpy（可选）
try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False


class StrategyTracker:
    """策略追踪器 v2.0"""
    
    def __init__(self):
        self.history_data: List[Dict] = []
        self.current_result: Optional[Dict] = None
        self.weight_combinations: Dict = {}
    
    # ========== 数据加载 ==========
    
    def load_history_data(self) -> List[Dict]:
        """加载历史数据"""
        history = []
        cutoff_date = datetime.now() - timedelta(days=ANALYSIS_DAYS)
        
        if not HISTORY_DIR.exists():
            print(f"  ⚠ 历史数据目录不存在: {HISTORY_DIR}")
            return history
        
        for date_dir in sorted(HISTORY_DIR.iterdir()):
            if not date_dir.is_dir():
                continue
            
            try:
                date = datetime.strptime(date_dir.name, "%Y-%m-%d")
                if date < cutoff_date:
                    continue
                
                # 尝试加载多种格式的历史数据
                summary_file = date_dir / "optimization_summary.json"
                result_file = date_dir / "optimization_result_multi_period.json"
                
                if summary_file.exists():
                    with open(summary_file, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                        data['date'] = date_dir.name
                        history.append(data)
                elif result_file.exists():
                    with open(result_file, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                        data['date'] = date_dir.name
                        history.append(data)
            except ValueError:
                continue
            except Exception as e:
                print(f"  ⚠ 加载 {date_dir.name} 数据失败: {e}")
                continue
        
        self.history_data = history
        return history
    
    def load_current_result(self) -> Optional[Dict]:
        """加载当前优化结果"""
        if CURRENT_RESULT_FILE.exists():
            with open(CURRENT_RESULT_FILE, 'r', encoding='utf-8') as f:
                self.current_result = json.load(f)
        else:
            print(f"  ⚠ 当前优化结果不存在: {CURRENT_RESULT_FILE}")
        return self.current_result
    
    def load_weight_combinations(self) -> Dict:
        """加载权重组合历史数据"""
        if COMBINATIONS_FILE.exists():
            with open(COMBINATIONS_FILE, 'r', encoding='utf-8') as f:
                self.weight_combinations = json.load(f)
        else:
            print(f"  ⚠ 权重组合数据不存在: {COMBINATIONS_FILE}")
            self.weight_combinations = {'combinations': {}, 'by_period': {}}
        return self.weight_combinations
    
    # ========== v2.0 核心方法：权重组合识别 ==========
    
    def generate_weight_signature(self, weights: Dict) -> str:
        """
        生成权重签名（用于识别组合）
        
        签名规则：将权重四舍五入到小数点后1位，用 '_' 连接
        
        Args:
            weights: 权重字典 {'rsi': -0.4, 'bollinger_pb': -0.25, ...}
        
        Returns:
            签名字符串 "-0.4_-0.3_-0.4_-0.3_0.1"
        """
        values = []
        for factor in WEIGHT_FACTORS:
            weight = weights.get(factor, 0)
            # 四舍五入到小数点后1位
            rounded = round(weight, 1)
            values.append(str(rounded))
        return '_'.join(values)
    
    def calculate_cosine_similarity(self, weights1: Dict, weights2: Dict) -> float:
        """
        计算权重组合的余弦相似度
        
        Args:
            weights1: 第一个权重组合
            weights2: 第二个权重组合
        
        Returns:
            相似度值 [0, 1]
        """
        # 提取权重向量（按固定顺序）
        v1 = [weights1.get(f, 0) for f in WEIGHT_FACTORS]
        v2 = [weights2.get(f, 0) for f in WEIGHT_FACTORS]
        
        # 计算余弦相似度
        dot_product = sum(a * b for a, b in zip(v1, v2))
        norm1 = math.sqrt(sum(a * a for a in v1))
        norm2 = math.sqrt(sum(b * b for b in v2))
        
        if norm1 == 0 or norm2 == 0:
            return 0.0
        
        cos_sim = dot_product / (norm1 * norm2)
        
        # 映射到 [0, 1] 范围（余弦相似度范围是 [-1, 1]）
        similarity = (cos_sim + 1) / 2
        
        return similarity
    
    def identify_weight_combination(self, period: str, current_weights: Dict) -> Dict:
        """
        识别当前权重组合
        
        Args:
            period: 周期（T+1, T+3, T+5）
            current_weights: 当前权重
        
        Returns:
            组合信息字典
        """
        current_signature = self.generate_weight_signature(current_weights)
        
        # 查找历史组合
        combinations = self.weight_combinations.get('combinations', {})
        
        matched_combos = []
        for combo_id, combo_data in combinations.items():
            # 只匹配同周期的组合
            if combo_data.get('period') != period:
                continue
            
            # 计算与当前权重的相似度
            historical_weights = combo_data.get('weights', {})
            similarity = self.calculate_cosine_similarity(current_weights, historical_weights)
            
            if similarity >= 0.95:  # 高度相似，视为同一组合
                matched_combos.append({
                    'combo_id': combo_id,
                    'similarity': similarity,
                    'data': combo_data,
                    'is_exact_match': True
                })
            elif similarity >= 0.80:  # 相似但不是同一组合
                matched_combos.append({
                    'combo_id': combo_id,
                    'similarity': similarity,
                    'data': combo_data,
                    'is_exact_match': False
                })
        
        # 找出最佳匹配
        if matched_combos:
            best_match = max(matched_combos, key=lambda x: x['similarity'])
            return {
                'combo_id': best_match['combo_id'] if best_match['is_exact_match'] else 'new_' + current_signature,
                'signature': current_signature,
                'is_new_combo': not best_match['is_exact_match'],
                'best_match': best_match,
                'matched_combos': matched_combos,
                'first_seen': best_match['data'].get('first_seen', datetime.now().strftime('%Y-%m-%d')),
                'appearances': best_match['data'].get('appearances', 1) if best_match['is_exact_match'] else 1,
                'successes': best_match['data'].get('successes', 0) if best_match['is_exact_match'] else 0
            }
        
        # 没有匹配的历史组合，是新组合
        return {
            'combo_id': 'new_' + current_signature,
            'signature': current_signature,
            'is_new_combo': True,
            'best_match': None,
            'matched_combos': [],
            'first_seen': datetime.now().strftime('%Y-%m-%d'),
            'appearances': 1,
            'successes': 0
        }
    
    # ========== v2.0 评分维度计算 ==========
    
    def calculate_weight_combination_success_rate(self, period: str, current_weights: Dict) -> Dict:
        """
        v2.0: 计算权重组合成功率
        
        定义：当前权重组合与历史成功组合的匹配成功率
        
        评分逻辑：
        - 如果是已知组合：分数 = 历史成功率 × 100
        - 如果是相似组合：分数 = (相似度 × 0.5 + 历史成功率 × 0.5) × 100
        - 如果是新组合：分数 = 30（默认低分，风险高）
        """
        combo_info = self.identify_weight_combination(period, current_weights)
        
        # 获取匹配的历史组合
        matched_combos = combo_info.get('matched_combos', [])
        
        if not matched_combos:
            # 新组合，无历史数据
            return {
                'score': 30,
                'rating': 'D',
                'details': {
                    'current_combo_id': combo_info['combo_id'],
                    'combo_similarity': 0,
                    'matched_historical_combos': 0,
                    'total_predictions': 0,
                    'successful_predictions': 0,
                    'success_rate': None,
                    'avg_return_on_success': None,
                    'avg_return_on_fail': None,
                    'note': '新权重组合，无历史数据'
                }
            }
        
        # 取最佳匹配计算成功率
        best_match = combo_info.get('best_match', matched_combos[0])
        best_combo = best_match['data']
        similarity = best_match['similarity']
        
        # 计算加权成功率
        # 如果是完全匹配（相似度>=95%），直接使用历史成功率
        # 如果是相似匹配，使用相似度加权
        historical_success_rate = best_combo.get('success_rate', 0)
        
        if best_match['is_exact_match']:
            weighted_success_rate = historical_success_rate
        else:
            # 相似组合：相似度 × 0.5 + 历史成功率 × 0.5
            weighted_success_rate = (similarity * 0.5 + historical_success_rate * 0.5)
        
        score = int(weighted_success_rate * 100)
        
        # 统计所有匹配组合的数据
        total_predictions = sum(c['data'].get('appearances', 0) for c in matched_combos)
        successful_predictions = sum(c['data'].get('successes', 0) for c in matched_combos)
        
        return {
            'score': score,
            'rating': self._score_to_rating(score),
            'details': {
                'current_combo_id': combo_info['combo_id'],
                'combo_similarity': round(similarity, 4),
                'matched_historical_combos': len(matched_combos),
                'total_predictions': total_predictions,
                'successful_predictions': successful_predictions,
                'success_rate': round(successful_predictions / total_predictions, 4) if total_predictions > 0 else None,
                'avg_return_on_success': best_combo.get('avg_return'),
                'avg_return_on_fail': best_combo.get('min_return'),
                'historical_combo_id': best_match['combo_id']
            }
        }
    
    def calculate_weight_similarity_score(self, period: str, current_weights: Dict) -> Dict:
        """
        v2.0: 计算权重相似度评分
        
        定义：当前组合与历史成功组合的相似程度
        
        评分逻辑：
        - 找出历史成功率 >= 60% 的成功组合
        - 计算当前组合与所有成功组合的相似度
        - 分数 = 最佳相似度 × 70 + 匹配数量 × 3（最多+30）
        
        风险级别：
        - 相似度 >= 80%：低风险
        - 相似度 50%-80%：中风险
        - 相似度 < 50%：高风险
        """
        # 获取同周期的成功组合（成功率 >= 60%）
        combinations = self.weight_combinations.get('combinations', {})
        successful_combos = [
            c for c_id, c in combinations.items()
            if c.get('period') == period and c.get('success_rate', 0) >= 0.6
        ]
        
        if not successful_combos:
            # 没有成功组合可参考
            return {
                'score': 35,
                'rating': 'D',
                'details': {
                    'similarity_to_best_combo': 0,
                    'similarity_to_avg_success': 0,
                    'matched_combo_count': 0,
                    'is_new_combo': True,
                    'risk_level': 'high'
                }
            }
        
        # 计算与每个成功组合的相似度
        similarities = []
        for combo in successful_combos:
            historical_weights = combo.get('weights', {})
            sim = self.calculate_cosine_similarity(current_weights, historical_weights)
            similarities.append({
                'combo_id': combo.get('combo_id'),
                'similarity': sim,
                'success_rate': combo.get('success_rate')
            })
        
        # 按相似度排序
        similarities.sort(key=lambda x: x['similarity'], reverse=True)
        
        # 最佳相似度
        best_similarity = similarities[0]['similarity'] if similarities else 0
        
        # 匹配数量（相似度 >= 80% 的组合）
        matched_count = len([s for s in similarities if s['similarity'] >= 0.80])
        
        # 平均相似度
        avg_similarity = sum(s['similarity'] for s in similarities) / len(similarities) if similarities else 0
        
        # 计算分数
        base_score = best_similarity * 70  # 最高 70 分
        match_bonus = min(matched_count * 3, 30)  # 匹配数量加分，最高 30 分
        score = int(base_score + match_bonus)
        
        # 确定风险级别
        if best_similarity >= 0.80:
            risk_level = 'low'
        elif best_similarity >= 0.50:
            risk_level = 'medium'
        else:
            risk_level = 'high'
        
        return {
            'score': score,
            'rating': self._score_to_rating(score),
            'details': {
                'similarity_to_best_combo': round(best_similarity, 4),
                'similarity_to_avg_success': round(avg_similarity, 4),
                'matched_combo_count': matched_count,
                'is_new_combo': best_similarity < 0.80,
                'risk_level': risk_level,
                'best_match_combo': similarities[0] if similarities else None
            }
        }
    
    def calculate_icir_stability(self, period: str) -> Dict:
        """
        计算ICIR稳定性
        
        定义：ICIR随时间的变化程度和趋势
        
        评分逻辑：
        - 分数 = 50 + (高于阈值比例×30) + 趋势加分 - 波动扣分
        - 趋势加分：rising=+10, stable=0, declining=-10
        - 波动扣分：ICIR标准差×20
        """
        icir_history = []
        
        # 从历史数据提取 ICIR
        for data in self.history_data:
            icir = None
            
            if 'all_periods' in data:
                period_data = data.get('all_periods', {}).get(period, {})
                icir = period_data.get('icir')
            elif 'icir' in data and data.get('period') == period:
                icir = data.get('icir')
            elif 'best_result' in data:
                icir = data.get('best_result', {}).get('icir')
            
            if icir is not None:
                icir_history.append(icir)
        
        # 如果没有历史数据，使用当前 ICIR
        if not icir_history and self.current_result:
            period_data = self.current_result.get('all_periods', {}).get(period, {})
            icir = period_data.get('icir')
            if icir is not None:
                icir_history.append(icir)
        
        if not icir_history:
            return {
                'score': 50,
                'rating': 'C',
                'details': {'error': '无 ICIR 数据'}
            }
        
        current_icir = icir_history[-1] if icir_history else 0
        
        # 计算统计值
        if HAS_NUMPY:
            icir_mean = float(np.mean(icir_history))
            icir_std = float(np.std(icir_history)) if len(icir_history) > 1 else 0
        else:
            icir_mean = sum(icir_history) / len(icir_history)
            icir_std = 0
            if len(icir_history) > 1:
                variance = sum((x - icir_mean) ** 2 for x in icir_history) / len(icir_history)
                icir_std = variance ** 0.5
        
        # 判断趋势
        if len(icir_history) >= 3:
            recent_count = min(5, len(icir_history))
            recent_mean = sum(icir_history[-recent_count:]) / recent_count
            older_count = max(1, len(icir_history) - recent_count)
            older_mean = sum(icir_history[:-recent_count]) / older_count if older_count > 0 else recent_mean
            
            if recent_mean > older_mean * 1.1:
                trend = "rising"
            elif recent_mean < older_mean * 0.9:
                trend = "declining"
            else:
                trend = "stable"
        else:
            trend = "insufficient_data"
        
        # 计算高于阈值的比例
        threshold = 0.2  # ICIR 阈值
        above_threshold_ratio = sum(1 for icir in icir_history if icir >= threshold) / len(icir_history)
        
        # 计算分数
        score = 50 + int(above_threshold_ratio * 30)
        score += 10 if trend == "rising" else (-10 if trend == "declining" else 0)
        score -= int(icir_std * 20)
        score = max(0, min(100, score))
        
        # 如果只有一天数据，基于当前值评分
        if len(icir_history) == 1:
            if current_icir >= 0.3:
                score = 85
            elif current_icir >= 0.2:
                score = 75
            elif current_icir >= 0.1:
                score = 65
            elif current_icir >= 0:
                score = 50
            else:
                score = 40
        
        return {
            'score': int(score),
            'rating': self._score_to_rating(score),
            'details': {
                'current_icir': round(current_icir, 4),
                'icir_mean_30d': round(icir_mean, 4),
                'icir_std_30d': round(icir_std, 4),
                'icir_trend': trend,
                'icir_above_threshold_ratio': round(above_threshold_ratio, 4),
                'days_analyzed': len(icir_history)
            }
        }
    
    # ========== 综合评级计算 ==========
    
    def calculate_overall_rating(self, dimensions: Dict) -> Tuple[int, str]:
        """
        计算综合评级
        
        v2.0 权重分配：
        - 权重组合成功率: 40%
        - 权重相似度: 30%
        - ICIR稳定性: 30%
        """
        weights = {
            'weight_combination_success_rate': 0.40,
            'weight_similarity': 0.30,
            'icir_stability': 0.30
        }
        
        overall_score = sum(
            dimensions.get(dim, {}).get('score', 50) * weight
            for dim, weight in weights.items()
        )
        
        return int(overall_score), self._score_to_rating(overall_score)
    
    def generate_recommendation(self, overall_score: int, dimensions: Dict, current_weights: Dict, combo_info: Dict) -> Dict:
        """
        v2.0: 生成推荐建议
        
        增加组合匹配信息
        """
        # 获取相似度和成功率
        combo_rate = dimensions.get('weight_combination_success_rate', {})
        weight_sim = dimensions.get('weight_similarity', {})
        
        combo_similarity = combo_rate.get('details', {}).get('combo_similarity', 0)
        success_rate = combo_rate.get('details', {}).get('success_rate')
        matched_combos = combo_rate.get('details', {}).get('matched_historical_combos', 0)
        
        # 根据相似度判断
        if combo_similarity >= 0.80:
            if overall_score >= 85:
                return {
                    'confidence': 'very_high',
                    'action': '强烈推荐',
                    'reason': f'当前权重组合与历史成功组合相似度{combo_similarity:.0%}，历史成功率{success_rate:.0%}（如有）',
                    'combo_match': {
                        'best_match_id': combo_info.get('best_match', {}).get('combo_id'),
                        'similarity': round(combo_similarity, 4),
                        'historical_success_rate': success_rate
                    }
                }
            elif overall_score >= 70:
                return {
                    'confidence': 'high',
                    'action': '建议采纳',
                    'reason': f'当前权重组合与历史成功组合相似度{combo_similarity:.0%}，可参考历史表现',
                    'combo_match': {
                        'best_match_id': combo_info.get('best_match', {}).get('combo_id'),
                        'similarity': round(combo_similarity, 4),
                        'historical_success_rate': success_rate
                    }
                }
        elif combo_similarity >= 0.50:
            return {
                'confidence': 'medium',
                'action': '谨慎参考',
                'reason': f'当前权重组合与历史组合相似度{combo_similarity:.0%}，参考价值有限',
                'combo_match': {
                    'best_match_id': combo_info.get('best_match', {}).get('combo_id'),
                    'similarity': round(combo_similarity, 4),
                    'historical_success_rate': success_rate
                }
            }
        else:
            return {
                'confidence': 'high',
                'action': '不建议采纳',
                'reason': '新权重组合，与历史成功组合相似度低，风险较高',
                'combo_match': None
            }
    
    # ========== 辅助方法 ==========
    
    def _score_to_rating(self, score: float) -> str:
        """分数转评级"""
        if score >= 90:
            return 'A+'
        elif score >= 80:
            return 'A'
        elif score >= 70:
            return 'B+'
        elif score >= 60:
            return 'B'
        elif score >= 50:
            return 'C'
        elif score >= 40:
            return 'D'
        else:
            return 'F'
    
    # ========== 主流程 ==========
    
    def run(self) -> Dict:
        """执行评分计算"""
        print("📊 策略追踪开始（v2.0版本）...")
        
        # 1. 加载所有数据
        print("  → 加载历史数据...")
        self.load_history_data()
        self.load_current_result()
        self.load_weight_combinations()
        
        if not self.current_result:
            print("  ✗ 错误：找不到当前优化结果")
            return {'success': False, 'error': 'No current optimization result found'}
        
        print(f"  ✓ 加载了 {len(self.history_data)} 天历史数据")
        print(f"  ✓ 加载了 {len(self.weight_combinations.get('combinations', {}))} 个权重组合")
        
        # 2. 获取周期列表
        periods = ['T+1', 'T+3', 'T+5']
        
        # 3. 计算每个周期的评分
        ratings = {}
        
        for period in periods:
            print(f"\n  → 计算 {period} 评分...")
            
            period_data = self.current_result.get('all_periods', {}).get(period, {})
            current_weights = period_data.get('weights', {})
            
            if not current_weights:
                print(f"    ⚠ {period} 无权重数据，跳过")
                continue
            
            # v2.0: 使用新的评分维度
            combo_info = self.identify_weight_combination(period, current_weights)
            
            dimensions = {
                'weight_combination_success_rate': self.calculate_weight_combination_success_rate(period, current_weights),
                'weight_similarity': self.calculate_weight_similarity_score(period, current_weights),
                'icir_stability': self.calculate_icir_stability(period)
            }
            
            overall_score, overall_rating = self.calculate_overall_rating(dimensions)
            recommendation = self.generate_recommendation(overall_score, dimensions, current_weights, combo_info)
            
            ratings[period] = {
                'period': period,
                'overall_rating': overall_rating,
                'overall_score': overall_score,
                'dimensions': dimensions,
                'current_weights': current_weights,
                'current_metrics': {
                    'annual_return': period_data.get('metrics', {}).get('annual_return'),
                    'sharpe_ratio': period_data.get('metrics', {}).get('sharpe_ratio'),
                    'max_drawdown': period_data.get('metrics', {}).get('max_drawdown'),
                    'win_rate': period_data.get('metrics', {}).get('win_rate'),
                    'icir': period_data.get('icir')
                },
                'recommendation': recommendation,
                'current_combo': {
                    'combo_id': combo_info.get('combo_id'),
                    'weights': current_weights,
                    'first_seen': combo_info.get('first_seen'),
                    'appearances': combo_info.get('appearances', 1),
                    'successes': combo_info.get('successes', 0)
                },
                'history_stats': {
                    'days_analyzed': len(self.history_data),
                    'data_completeness': 1.0 if self.history_data else 0,
                    'last_updated': datetime.now().strftime('%Y-%m-%d'),
                    'unique_combos_seen': len(self.weight_combinations.get('combinations', {})),
                    'successful_combos': len([c for c_id, c in self.weight_combinations.get('combinations', {}).items() if c.get('success_rate', 0) >= 0.6])
                }
            }
            
            print(f"    综合评级: {overall_rating} ({overall_score}分)")
            print(f"    组合匹配: {combo_info.get('combo_id')} (相似度: {combo_info.get('matched_combos', [{}])[0].get('similarity', 0):.2f})")
        
        # 4. 生成摘要
        summary = self._generate_summary(ratings)
        
        # 5. 构建输出
        result = {
            'meta': {
                'generated_at': datetime.now().isoformat(),
                'data_version': '2.0',
                'source': str(CURRENT_RESULT_FILE),
                'note': 'v2.0: 改用权重组合成功率替代周期成功率'
            },
            'ratings': ratings,
            'weight_combinations': self.weight_combinations.get('combinations', {}),
            'summary': summary
        }
        
        # 6. 保存结果
        OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
            json.dump(result, f, indent=2, ensure_ascii=False)
        
        print(f"\n✓ 评分结果已保存到: {OUTPUT_FILE}")
        
        return {
            'success': True,
            'output_file': str(OUTPUT_FILE),
            'summary': summary,
            'version': '2.0'
        }
    
    def _generate_summary(self, ratings: Dict) -> Dict:
        """生成摘要"""
        if not ratings:
            return {
                'best_period': None,
                'recommended_periods': [],
                'caution_periods': [],
                'overall_assessment': '无有效评分数据'
            }
        
        # 找出最佳周期
        best_period = max(ratings.keys(), key=lambda p: ratings[p]['overall_score'])
        
        # 推荐周期（评分 >= 70）
        recommended = [
            p for p, r in ratings.items() 
            if r['overall_score'] >= 70
        ]
        
        # 需谨慎周期
        caution = [
            p for p, r in ratings.items() 
            if r['overall_score'] < 70
        ]
        
        # 生成综合评估
        best_data = ratings[best_period]
        assessment_parts = [
            f"{best_period}周期策略表现最佳",
            f"综合评分{best_data['overall_score']}分"
        ]
        
        if recommended:
            assessment_parts.append(f"推荐周期：{', '.join(recommended)}")
        if caution:
            assessment_parts.append(f"需谨慎周期：{', '.join(caution)}")
        
        # 添加决策规则说明
        decision_rules = {
            'follow_threshold': 0.80,
            'caution_threshold': 0.50,
            'description': '权重组合相似度>80%→可跟随；相似度<50%→新组合，风险高'
        }
        
        return {
            'best_period': best_period,
            'recommended_periods': recommended,
            'caution_periods': caution,
            'overall_assessment': '；'.join(assessment_parts),
            'decision_rules': decision_rules
        }


def main():
    """主函数"""
    tracker = StrategyTracker()
    result = tracker.run()
    
    if result.get('success'):
        print(f"\n📋 摘要: {result.get('summary', {}).get('overall_assessment', 'N/A')}")
        print(f"版本: {result.get('version', 'N/A')}")
    else:
        print(f"\n❌ 执行失败: {result.get('error', '未知错误')}")
    
    return result


if __name__ == '__main__':
    main()