"""
原语集模块
定义遗传规划可用的操作符和函数
"""

import numpy as np
from typing import List, Callable, Dict, Any, Optional, Tuple
import warnings

# gplearn imports
try:
    from gplearn.functions import make_function
    from gplearn.fitness import make_fitness
    GPLEARN_AVAILABLE = True
except ImportError:
    GPLEARN_AVAILABLE = False
    warnings.warn("gplearn not installed. Run: pip install gplearn")


# ============ 保护函数 ============

def protected_division(x1: np.ndarray, x2: np.ndarray) -> np.ndarray:
    """
    保护除法：避免除以零
    
    Args:
        x1: 被除数
        x2: 除数
        
    Returns:
        x1 / x2，除数接近零时返回1
    """
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return np.where(np.abs(x2) > 1e-10, np.divide(x1, x2), 1.0)


def protected_sqrt(x: np.ndarray) -> np.ndarray:
    """
    保护平方根：负数返回sqrt(abs(x))
    
    Args:
        x: 输入数组
        
    Returns:
        sqrt(|x|) * sign(x)
    """
    return np.sqrt(np.abs(x))


def protected_log(x: np.ndarray) -> np.ndarray:
    """
    保护对数：对零或负数返回log(|x| + 1)
    
    Args:
        x: 输入数组
        
    Returns:
        log(|x| + 1)
    """
    return np.log1p(np.abs(x))


def protected_inverse(x: np.ndarray) -> np.ndarray:
    """
    保护倒数：避免除以零
    
    Args:
        x: 输入数组
        
    Returns:
        1/x，x接近零时返回1
    """
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return np.where(np.abs(x) > 1e-10, 1.0 / x, 1.0)


def protected_power(x1: np.ndarray, x2: np.ndarray) -> np.ndarray:
    """
    保护幂运算：限制结果范围
    
    Args:
        x1: 底数
        x2: 指数
        
    Returns:
        x1 ^ x2，限制在合理范围
    """
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        # 限制指数范围
        x2_clipped = np.clip(x2, -10, 10)
        # 对负底数取绝对值
        x1_safe = np.abs(x1) + 1e-10
        result = np.power(x1_safe, x2_clipped)
        # 限制结果范围
        return np.clip(result, -1e10, 1e10)


# ============ 数学函数 ============

def sigmoid(x: np.ndarray) -> np.ndarray:
    """Sigmoid函数"""
    return 1.0 / (1.0 + np.exp(-np.clip(x, -100, 100)))


def tanh_safe(x: np.ndarray) -> np.ndarray:
    """安全的tanh函数"""
    return np.tanh(np.clip(x, -100, 100))


def relu(x: np.ndarray) -> np.ndarray:
    """ReLU函数"""
    return np.maximum(0, x)


def leaky_relu(x: np.ndarray, alpha: float = 0.01) -> np.ndarray:
    """Leaky ReLU函数"""
    return np.where(x > 0, x, alpha * x)


# ============ 时序操作 ============

def ts_rank(x: np.ndarray, window: int = 5) -> np.ndarray:
    """
    时序排名
    
    Args:
        x: 输入序列
        window: 窗口大小
        
    Returns:
        排名值（归一化到0-1）
    """
    # 注意：这里假设x是一维时序数据
    # 在实际使用中需要根据数据结构调整
    x = np.asarray(x).flatten()
    n = len(x)
    result = np.zeros(n)
    
    for i in range(n):
        start = max(0, i - window + 1)
        window_data = x[start:i+1]
        if len(window_data) > 0:
            result[i] = (np.argsort(np.argsort(window_data))[-1] + 1) / len(window_data)
    
    return result


def ts_delta(x: np.ndarray, period: int = 1) -> np.ndarray:
    """
    时序变化
    
    Args:
        x: 输入序列
        period: 周期
        
    Returns:
        x[t] - x[t-period]
    """
    x = np.asarray(x).flatten()
    result = np.zeros_like(x)
    result[:period] = 0
    result[period:] = x[period:] - x[:-period]
    return result


def ts_mean(x: np.ndarray, window: int = 5) -> np.ndarray:
    """
    滚动均值
    
    Args:
        x: 输入序列
        window: 窗口大小
        
    Returns:
        滚动均值
    """
    x = np.asarray(x).flatten()
    n = len(x)
    result = np.zeros(n)
    
    for i in range(n):
        start = max(0, i - window + 1)
        result[i] = np.mean(x[start:i+1])
    
    return result


def ts_std(x: np.ndarray, window: int = 5) -> np.ndarray:
    """
    滚动标准差
    
    Args:
        x: 输入序列
        window: 窗口大小
        
    Returns:
        滚动标准差
    """
    x = np.asarray(x).flatten()
    n = len(x)
    result = np.zeros(n)
    
    for i in range(n):
        start = max(0, i - window + 1)
        window_data = x[start:i+1]
        if len(window_data) > 1:
            result[i] = np.std(window_data)
        else:
            result[i] = 0
    
    return result


def ts_max(x: np.ndarray, window: int = 5) -> np.ndarray:
    """滚动最大值"""
    x = np.asarray(x).flatten()
    n = len(x)
    result = np.zeros(n)
    
    for i in range(n):
        start = max(0, i - window + 1)
        result[i] = np.max(x[start:i+1])
    
    return result


def ts_min(x: np.ndarray, window: int = 5) -> np.ndarray:
    """滚动最小值"""
    x = np.asarray(x).flatten()
    n = len(x)
    result = np.zeros(n)
    
    for i in range(n):
        start = max(0, i - window + 1)
        result[i] = np.min(x[start:i+1])
    
    return result


def ts_decay_linear(x: np.ndarray, window: int = 5) -> np.ndarray:
    """
    线性衰减加权平均
    
    Args:
        x: 输入序列
        window: 窗口大小
        
    Returns:
        加权平均值（越近权重越高）
    """
    x = np.asarray(x).flatten()
    n = len(x)
    result = np.zeros(n)
    weights = np.arange(1, window + 1, dtype=float)
    weights = weights / weights.sum()
    
    for i in range(n):
        start = max(0, i - window + 1)
        window_data = x[start:i+1]
        w = weights[-len(window_data):]
        result[i] = np.sum(window_data * w)
    
    return result


# ============ 统计函数 ============

def rank(x: np.ndarray) -> np.ndarray:
    """
    横截面排名（归一化到0-1）
    
    Args:
        x: 输入数组
        
    Returns:
        排名值（归一化）
    """
    x = np.asarray(x)
    return (np.argsort(np.argsort(x)) + 1) / len(x)


def zscore(x: np.ndarray) -> np.ndarray:
    """
    Z-Score标准化
    
    Args:
        x: 输入数组
        
    Returns:
        标准化后的值
    """
    x = np.asarray(x)
    mean = np.mean(x)
    std = np.std(x)
    if std < 1e-10:
        return np.zeros_like(x)
    return (x - mean) / std


def winsorize(x: np.ndarray, limits: Tuple[float, float] = (0.01, 0.01)) -> np.ndarray:
    """
    缩尾处理
    
    Args:
        x: 输入数组
        limits: (下限, 上限) 比例
        
    Returns:
        缩尾后的值
    """
    x = np.asarray(x)
    lower_limit = np.percentile(x, limits[0] * 100)
    upper_limit = np.percentile(x, (1 - limits[1]) * 100)
    return np.clip(x, lower_limit, upper_limit)


# ============ 构建gplearn函数集 ============

def make_function_set(
    include_basic: bool = True,
    include_math: bool = True,
    include_time: bool = True,
    include_stat: bool = True,
    custom_functions: Optional[List] = None
) -> List:
    """
    构建gplearn函数集
    
    Args:
        include_basic: 包含基础运算 (+, -, *, /)
        include_math: 包含数学函数
        include_time: 包含时序函数
        include_stat: 包含统计函数
        custom_functions: 自定义函数列表
        
    Returns:
        函数名列表或make_function对象列表
    """
    function_set = []
    
    if not GPLEARN_AVAILABLE:
        # 返回函数名列表（使用gplearn内置函数）
        if include_basic:
            function_set.extend(['add', 'sub', 'mul'])
        return function_set
    
    # 基础运算
    if include_basic:
        function_set.extend(['add', 'sub', 'mul'])
        
        # 保护除法
        div_func = make_function(function=protected_division, name='div', arity=2)
        function_set.append(div_func)
    
    # 数学函数
    if include_math:
        # 保护平方根
        sqrt_func = make_function(function=protected_sqrt, name='sqrt', arity=1)
        function_set.append(sqrt_func)
        
        # 保护对数
        log_func = make_function(function=protected_log, name='log', arity=1)
        function_set.append(log_func)
        
        # 绝对值
        function_set.append('abs')
        
        # 负值
        function_set.append('neg')
        
        # 保护倒数
        inv_func = make_function(function=protected_inverse, name='inv', arity=1)
        function_set.append(inv_func)
        
        # 最大最小值
        function_set.extend(['max', 'min'])
    
    # 时序函数 - 使用内置函数名，因为gplearn的make_function需要严格匹配签名
    # 为了简化，暂时不使用自定义时序函数
    # 统计函数同样处理
    
    # 自定义函数
    if custom_functions:
        function_set.extend(custom_functions)
    
    return function_set


def make_terminal_set(
    feature_names: List[str],
    const_range: Tuple[float, float] = (-1.0, 1.0)
) -> Dict[str, Any]:
    """
    构建终端集（变量和常量）
    
    Args:
        feature_names: 特征名称列表
        const_range: 常量范围
        
    Returns:
        终端集配置字典
    """
    return {
        'feature_names': feature_names,
        'const_range': const_range
    }


# ============ 预定义函数集 ============

def get_basic_function_set() -> List:
    """获取基础函数集（四则运算）"""
    return make_function_set(
        include_basic=True,
        include_math=False,
        include_time=False,
        include_stat=False
    )


def get_standard_function_set() -> List:
    """获取标准函数集（基础+数学）"""
    return make_function_set(
        include_basic=True,
        include_math=True,
        include_time=False,
        include_stat=False
    )


def get_full_function_set() -> List:
    """获取完整函数集"""
    return make_function_set(
        include_basic=True,
        include_math=True,
        include_time=True,
        include_stat=True
    )


# ============ 因子操作符 ============

class FactorOperators:
    """因子操作符集合"""
    
    @staticmethod
    def signed_power(x: np.ndarray, power: float = 2.0) -> np.ndarray:
        """保留符号的幂运算"""
        sign = np.sign(x)
        return sign * np.power(np.abs(x), power)
    
    @staticmethod
    def normalize(x: np.ndarray) -> np.ndarray:
        """归一化到[0, 1]"""
        x_min, x_max = np.min(x), np.max(x)
        if x_max - x_min < 1e-10:
            return np.zeros_like(x)
        return (x - x_min) / (x_max - x_min)
    
    @staticmethod
    def standardize(x: np.ndarray) -> np.ndarray:
        """标准化"""
        return zscore(x)
    
    @staticmethod
    def orthogonalize(x: np.ndarray, y: np.ndarray) -> np.ndarray:
        """
        正交化：去除x对y的线性影响
        
        Args:
            x: 待正交化的因子
            y: 参考因子
            
        Returns:
            正交化后的x
        """
        # 简单的线性回归残差
        x = np.asarray(x).flatten()
        y = np.asarray(y).flatten()
        
        valid_mask = ~(np.isnan(x) | np.isnan(y))
        x_valid, y_valid = x[valid_mask], y[valid_mask]
        
        if len(x_valid) < 10:
            return x
        
        # 计算 beta
        beta = np.cov(x_valid, y_valid)[0, 1] / (np.var(y_valid) + 1e-10)
        
        # 残差
        residual = x - beta * y
        
        return residual


# ============ 工具函数 ============

def print_function_info():
    """打印可用函数信息"""
    print("=== 遗传规划可用函数集 ===\n")
    
    print("【基础运算】")
    print("  add(x1, x2)    - 加法")
    print("  sub(x1, x2)    - 减法")
    print("  mul(x1, x2)    - 乘法")
    print("  div(x1, x2)    - 保护除法\n")
    
    print("【数学函数】")
    print("  sqrt(x)       - 保护平方根")
    print("  log(x)        - 保护对数")
    print("  abs(x)        - 绝对值")
    print("  neg(x)        - 取负")
    print("  inv(x)        - 保护倒数")
    print("  max(x1, x2)   - 最大值")
    print("  min(x1, x2)   - 最小值\n")
    
    print("【时序函数】")
    print("  ts_rank(x)    - 时序排名")
    print("  ts_delta(x)   - 时序变化")
    print("  ts_mean(x)    - 滚动均值")
    print("  ts_std(x)     - 滚动标准差")
    print("  ts_max(x)     - 滚动最大值")
    print("  ts_min(x)     - 滚动最小值\n")
    
    print("【统计函数】")
    print("  rank(x)       - 横截面排名")
    print("  zscore(x)     - Z-Score标准化\n")


if __name__ == "__main__":
    print_function_info()