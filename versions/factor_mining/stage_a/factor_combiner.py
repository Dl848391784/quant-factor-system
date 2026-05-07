"""
因子组合生成器模块

基于现有因子进行数学组合生成新因子
"""

import numpy as np
import pandas as pd
from typing import List, Dict, Tuple, Optional, Callable, Union
from itertools import combinations, permutations
import re
import warnings

from .safe_math import SafeMath

warnings.filterwarnings('ignore')


class FactorCombiner:
    """
    因子组合引擎
    
    支持的操作：
    - 四则运算：+, -, *, /
    - 比率运算：ratio(a, b) = a / b
    - 数学函数：log, sqrt, abs, power
    - 统计函数：rank, zscore, delta
    """
    
    # 基础因子列表
    BASE_FACTORS = [
        'rsi',
        'kdj_j',
        'bollinger_pb',
        'volume_ratio',
        'turnover_surge',
        'main_inflow_ratio'
    ]
    
    # 操作符配置
    BINARY_OPERATORS = {
        '+': lambda a, b: a + b,
        '-': lambda a, b: a - b,
        '*': lambda a, b: a * b,
        '/': lambda a, b: SafeMath.safe_divide(a, b),
        'max': lambda a, b: np.maximum(a, b),
        'min': lambda a, b: np.minimum(a, b),
    }
    
    UNARY_OPERATORS = {
        'log': lambda a: SafeMath.safe_log(a),
        'sqrt': lambda a: SafeMath.safe_sqrt(a),
        'abs': lambda a: np.abs(a),
        'neg': lambda a: -a,
        'rank': lambda a: SafeMath.safe_rank(a),
        'zscore': lambda a: SafeMath.safe_zscore(a),
    }
    
    TIME_OPERATORS = {
        'delta': lambda a, p=1: SafeMath.safe_delta(a, period=p),
    }
    
    def __init__(
        self,
        base_factors: Optional[List[str]] = None,
        max_combination_depth: int = 2,
        include_unary: bool = True,
        include_time_ops: bool = True
    ):
        """
        初始化组合器
        
        Args:
            base_factors: 基础因子列表，None则使用默认
            max_combination_depth: 最大组合深度
            include_unary: 是否包含一元操作符
            include_time_ops: 是否包含时序操作符
        """
        self.base_factors = base_factors or self.BASE_FACTORS.copy()
        self.max_depth = max_combination_depth
        self.include_unary = include_unary
        self.include_time_ops = include_time_ops
        
        # 存储生成的表达式
        self.expressions: List[Dict] = []
    
    def generate_binary_combinations(
        self,
        factor_data: Dict[str, pd.Series]
    ) -> List[Dict]:
        """
        生成二元组合因子
        
        Args:
            factor_data: 因子数据字典 {factor_name: series}
            
        Returns:
            组合因子列表
        """
        combinations_list = []
        expr_id = 0
        
        # 遍历所有因子对
        for f1, f2 in combinations(self.base_factors, 2):
            if f1 not in factor_data or f2 not in factor_data:
                continue
                
            s1 = factor_data[f1]
            s2 = factor_data[f2]
            
            # 四则运算
            for op_name, op_func in self.BINARY_OPERATORS.items():
                try:
                    result = op_func(s1, s2)
                    
                    # 验证结果有效性
                    if self._validate_result(result):
                        expr_id += 1
                        expr_str = f"({f1} {op_name} {f2})"
                        
                        combinations_list.append({
                            'expr_id': f'FA_{expr_id:04d}',
                            'expression': expr_str,
                            'factors': [f1, f2],
                            'operator': op_name,
                            'type': 'binary',
                            'data': result
                        })
                except Exception as e:
                    continue
        
        return combinations_list
    
    def generate_unary_combinations(
        self,
        factor_data: Dict[str, pd.Series]
    ) -> List[Dict]:
        """
        生成一元组合因子（对单个因子应用数学函数）
        
        Args:
            factor_data: 因子数据字典
            
        Returns:
            组合因子列表
        """
        combinations_list = []
        expr_id = 0
        
        if not self.include_unary:
            return combinations_list
        
        for factor in self.base_factors:
            if factor not in factor_data:
                continue
            
            s = factor_data[factor]
            
            for op_name, op_func in self.UNARY_OPERATORS.items():
                try:
                    result = op_func(s)
                    
                    if self._validate_result(result):
                        expr_id += 1
                        expr_str = f"{op_name}({factor})"
                        
                        combinations_list.append({
                            'expr_id': f'FA_U{expr_id:04d}',
                            'expression': expr_str,
                            'factors': [factor],
                            'operator': op_name,
                            'type': 'unary',
                            'data': result
                        })
                except Exception as e:
                    continue
        
        return combinations_list
    
    def generate_rank_combinations(
        self,
        factor_data: Dict[str, pd.Series]
    ) -> List[Dict]:
        """
        生成排名组合因子
        
        对因子进行排名后进行组合
        
        Args:
            factor_data: 因子数据字典
            
        Returns:
            排名组合因子列表
        """
        combinations_list = []
        expr_id = 0
        
        # 先对所有因子计算排名
        ranked_data = {}
        for factor in self.base_factors:
            if factor in factor_data:
                ranked_data[f'rank_{factor}'] = SafeMath.safe_rank(factor_data[factor])
        
        # 排名后的因子进行组合
        for f1, f2 in combinations(ranked_data.keys(), 2):
            s1 = ranked_data[f1]
            s2 = ranked_data[f2]
            
            # 排名的加减乘除
            for op_name, op_func in self.BINARY_OPERATORS.items():
                try:
                    result = op_func(s1, s2)
                    
                    if self._validate_result(result):
                        expr_id += 1
                        expr_str = f"(rank({f1.replace('rank_', '')}) {op_name} rank({f2.replace('rank_', '')}))"
                        
                        combinations_list.append({
                            'expr_id': f'FA_R{expr_id:04d}',
                            'expression': expr_str,
                            'factors': [f1.replace('rank_', ''), f2.replace('rank_', '')],
                            'operator': f'rank_{op_name}',
                            'type': 'rank_binary',
                            'data': result
                        })
                except Exception as e:
                    continue
        
        return combinations_list
    
    def generate_ratio_combinations(
        self,
        factor_data: Dict[str, pd.Series]
    ) -> List[Dict]:
        """
        生成比率因子
        
        特殊的除法组合，用于生成交叉比率
        
        Args:
            factor_data: 因子数据字典
            
        Returns:
            比率因子列表
        """
        combinations_list = []
        expr_id = 0
        
        for f1, f2 in permutations(self.base_factors, 2):
            if f1 not in factor_data or f2 not in factor_data:
                continue
            
            s1 = factor_data[f1]
            s2 = factor_data[f2]
            
            # 比率 a / b
            try:
                result = SafeMath.safe_ratio(s1, s2)
                
                if self._validate_result(result):
                    expr_id += 1
                    expr_str = f"ratio({f1}, {f2})"
                    
                    combinations_list.append({
                        'expr_id': f'FA_RT{expr_id:04d}',
                        'expression': expr_str,
                        'factors': [f1, f2],
                        'operator': 'ratio',
                        'type': 'ratio',
                        'data': result
                    })
            except Exception as e:
                continue
        
        return combinations_list
    
    def generate_nested_combinations(
        self,
        factor_data: Dict[str, pd.Series],
        depth: int = 2
    ) -> List[Dict]:
        """
        生成嵌套组合因子
        
        例如：log(rsi * kdj_j)、rank(rsi - kdj_j)
        
        Args:
            factor_data: 因子数据字典
            depth: 嵌套深度
            
        Returns:
            嵌套组合因子列表
        """
        combinations_list = []
        expr_id = 0
        
        if depth < 2:
            return combinations_list
        
        # 生成二元组合，然后应用一元操作
        binary_combos = self.generate_binary_combinations(factor_data)
        
        for combo in binary_combos:
            for op_name, op_func in self.UNARY_OPERATORS.items():
                try:
                    result = op_func(combo['data'])
                    
                    if self._validate_result(result):
                        expr_id += 1
                        inner_expr = combo['expression']
                        expr_str = f"{op_name}({inner_expr})"
                        
                        combinations_list.append({
                            'expr_id': f'FA_N{expr_id:04d}',
                            'expression': expr_str,
                            'factors': combo['factors'],
                            'operator': f"{op_name}({combo['operator']})",
                            'type': 'nested',
                            'data': result
                        })
                except Exception as e:
                    continue
        
        return combinations_list
    
    def generate_all(
        self,
        factor_data: Dict[str, pd.Series],
        include_nested: bool = True
    ) -> List[Dict]:
        """
        生成所有类型的组合因子
        
        Args:
            factor_data: 因子数据字典
            include_nested: 是否包含嵌套组合
            
        Returns:
            所有组合因子列表
        """
        all_combinations = []
        
        # 二元组合
        binary = self.generate_binary_combinations(factor_data)
        all_combinations.extend(binary)
        
        # 一元组合
        unary = self.generate_unary_combinations(factor_data)
        all_combinations.extend(unary)
        
        # 排名组合
        rank_combos = self.generate_rank_combinations(factor_data)
        all_combinations.extend(rank_combos)
        
        # 比率组合
        ratio_combos = self.generate_ratio_combinations(factor_data)
        all_combinations.extend(ratio_combos)
        
        # 嵌套组合
        if include_nested:
            nested = self.generate_nested_combinations(factor_data)
            all_combinations.extend(nested)
        
        # 清理数据，移除data字段（减少内存占用）
        for combo in all_combinations:
            combo.pop('data', None)
        
        self.expressions = all_combinations
        
        return all_combinations
    
    def compute_expression(
        self,
        expression: str,
        factor_data: Dict[str, pd.Series]
    ) -> pd.Series:
        """
        根据表达式字符串计算因子值
        
        Args:
            expression: 表达式字符串，如 "rsi + kdj_j"
            factor_data: 因子数据字典
            
        Returns:
            计算结果Series
        """
        # 解析表达式
        expr = expression.strip()
        
        # 处理 ratio(f1, f2) 格式
        ratio_match = re.match(r'^ratio\s*\(\s*([^,]+)\s*,\s*([^)]+)\s*\)$', expr)
        if ratio_match:
            f1 = ratio_match.group(1).strip()
            f2 = ratio_match.group(2).strip()
            s1 = self._get_factor_value(f1, factor_data)
            s2 = self._get_factor_value(f2, factor_data)
            if s1 is None or s2 is None:
                raise ValueError(f"因子不存在: {f1} 或 {f2}")
            return SafeMath.safe_divide(s1, s2)
        
        # 处理括号外的二元操作（支持嵌套表达式如 rank(rsi) + rank(kdj_j)）
        binary_ops = [' + ', ' - ', ' * ', ' / ', ' max ', ' min ']
        outer_result = self._try_parse_outer_binary(expr, factor_data, binary_ops)
        if outer_result is not None:
            return outer_result
        
        # 处理嵌套函数（一元函数包裹）
        if '(' in expr and ')' in expr:
            return self._parse_nested_expression(expr, factor_data)
        
        # 单个因子
        if expr in factor_data:
            return factor_data[expr]
        
        raise ValueError(f"无法解析表达式: {expression}")
    
    def _get_factor_value(self, factor_name: str, factor_data: Dict[str, pd.Series]) -> Optional[pd.Series]:
        """
        获取因子值，支持递归解析
        """
        factor_name = factor_name.strip()
        # 直接查找
        if factor_name in factor_data:
            return factor_data[factor_name]
        # 尝试去掉括号
        stripped = factor_name.strip('()')
        if stripped in factor_data:
            return factor_data[stripped]
        # 尝试递归解析
        if '(' in factor_name or any(op in factor_name for op in ['+', '-', '*', '/', 'max', 'min']):
            try:
                return self.compute_expression(factor_name, factor_data)
            except:
                pass
        return None
    
    def _try_parse_outer_binary(
        self,
        expr: str,
        factor_data: Dict[str, pd.Series],
        binary_ops: List[str]
    ) -> Optional[pd.Series]:
        """
        尝试解析括号外的二元操作
        
        支持嵌套表达式如: rank(rsi) + rank(kdj_j)
        """
        for op in binary_ops:
            # 找到操作符的位置，但需要确保它在最外层（不在括号内）
            pos = self._find_outermost_operator(expr, op)
            if pos != -1:
                left = expr[:pos].strip()
                right = expr[pos + len(op):].strip()
                
                if left and right:
                    s1 = self._get_factor_value(left, factor_data)
                    s2 = self._get_factor_value(right, factor_data)
                    
                    if s1 is not None and s2 is not None:
                        op_key = op.strip()
                        if op_key in self.BINARY_OPERATORS:
                            return self.BINARY_OPERATORS[op_key](s1, s2)
        
        return None
    
    def _find_outermost_operator(self, expr: str, op: str) -> int:
        """
        找到最外层（不在括号内）的操作符位置
        """
        paren_depth = 0
        i = 0
        while i < len(expr):
            if expr[i] == '(':
                paren_depth += 1
            elif expr[i] == ')':
                paren_depth -= 1
            elif paren_depth == 0 and expr[i:i+len(op)] == op:
                return i
            i += 1
        return -1
    
    def _parse_nested_expression(
        self,
        expr: str,
        factor_data: Dict[str, pd.Series]
    ) -> pd.Series:
        """
        解析嵌套表达式
        """
        # 处理括号包裹的表达式 (expr)
        if expr.startswith('(') and expr.endswith(')'):
            # 检查这对括号是否匹配
            if self._is_matching_parens(expr):
                return self.compute_expression(expr[1:-1], factor_data)
        
        # 找到最外层函数 func(args)
        match = re.match(r'^(\w+)\s*\((.+)\)$', expr)
        if match:
            func_name = match.group(1)
            inner_expr = match.group(2)
            
            # 处理一元函数
            if func_name in self.UNARY_OPERATORS:
                inner_result = self.compute_expression(inner_expr, factor_data)
                return self.UNARY_OPERATORS[func_name](inner_result)
            
            # 处理 ratio 函数（如果到达这里）
            if func_name == 'ratio':
                # 解析逗号分隔的两个参数
                parts = self._split_by_comma(inner_expr)
                if len(parts) == 2:
                    f1, f2 = parts[0].strip(), parts[1].strip()
                    s1 = self._get_factor_value(f1, factor_data)
                    s2 = self._get_factor_value(f2, factor_data)
                    if s1 is not None and s2 is not None:
                        return SafeMath.safe_divide(s1, s2)
        
        raise ValueError(f"无法解析嵌套表达式: {expr}")
    
    def _is_matching_parens(self, expr: str) -> bool:
        """检查首尾括号是否匹配"""
        depth = 0
        for i, c in enumerate(expr):
            if c == '(':
                depth += 1
            elif c == ')':
                depth -= 1
            if depth == 0 and i < len(expr) - 1:
                # 在非结尾位置深度归零，说明首尾括号不匹配
                return False
        return depth == 0
    
    def _split_by_comma(self, s: str) -> List[str]:
        """按逗号分割，忽略括号内的逗号"""
        parts = []
        current = []
        depth = 0
        for c in s:
            if c == '(':
                depth += 1
                current.append(c)
            elif c == ')':
                depth -= 1
                current.append(c)
            elif c == ',' and depth == 0:
                parts.append(''.join(current))
                current = []
            else:
                current.append(c)
        if current:
            parts.append(''.join(current))
        return parts
    
    def _validate_result(self, result: pd.Series) -> bool:
        """
        验证结果有效性
        
        Args:
            result: 计算结果
            
        Returns:
            是否有效
        """
        if result is None:
            return False
        
        # 检查有效值比例
        valid_ratio = (~result.isna()).sum() / len(result)
        if valid_ratio < 0.5:
            return False
        
        # 检查是否有足够的方差
        if result.std() < 1e-10:
            return False
        
        # 检查是否全是inf
        if np.isinf(result).sum() > len(result) * 0.5:
            return False
        
        return True
    
    def get_expression_count(self) -> Dict[str, int]:
        """
        获取各类表达式数量统计
        
        Returns:
            统计字典
        """
        stats = {
            'binary': 0,
            'unary': 0,
            'rank_binary': 0,
            'ratio': 0,
            'nested': 0
        }
        
        for expr in self.expressions:
            expr_type = expr.get('type', 'unknown')
            if expr_type in stats:
                stats[expr_type] += 1
        
        stats['total'] = len(self.expressions)
        return stats