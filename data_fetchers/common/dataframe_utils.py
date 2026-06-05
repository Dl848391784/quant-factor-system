#!/usr/bin/env python3
"""
DataFrame 工具模块

提供 DataFrame 验证和数据处理工具函数。

遵循 PROJECT.md 规范：
- 使用 Python 标准库 logging 模块
- 公共模块函数接收 logger 参数（遵循 PROJECT.md 第783-857行规范）
- 错误信息包含可用列（遵循 MODULE.md 约束 #61：DataFrame 列名校验）

作者: 云瑶
创建日期: 2026-05-27
版本历史:
- v1.0 (2026-05-27): 首次创建，validate_dataframe_columns 函数
- v1.1 (2026-05-27): logger 参数化，错误信息包含可用列
- v1.2 (2026-05-27): 导入顺序PEP8规范化，删除未使用导入，添加边界处理
- v1.3 (2026-05-27): docstring Example 完善，正常+异常场景分离
- v1.4 (2026-05-27): MODULE.md 版本历史同步，测试边界完善
- v1.5 (2026-05-27): __all__ 放置位置PEP8规范化，df_name 边界校验，docstring 完善
- v1.6 (2026-05-27): 模块级常量定义，错误信息优化，文件末尾换行符
- v1.7 (2026-05-27): df 类型检查改用 isinstance，删除冗余日志，优化 debug 输出
"""

# 标准库导入
import logging

# 第三方库导入
import pandas as pd


# 模块公共 API
__all__ = ['validate_dataframe_columns']

# 模块级常量
_DEFAULT_DF_NAME = "<未命名DataFrame>"


def validate_dataframe_columns(
    df: pd.DataFrame,
    required_cols: list[str],
    df_name: str | None = None,
    logger: logging.Logger | None = None
) -> None:
    """
    验证 DataFrame 是否包含必需列
    
    防御性编程：API 返回列名可能变化，需校验必需列存在。
    错误信息包含可用列，便于用户定位问题。
    
    Args:
        df: DataFrame 对象（必须是 pandas.DataFrame 类型）
        required_cols: 必需列名列表（不能为空）
        df_name: DataFrame 名称（用于错误消息，可选，默认使用模块常量）
        logger: 日志记录器（可选，遵循 PROJECT.md 第783-857行规范）
    
    Raises:
        TypeError: df 参数不是 pandas.DataFrame 类型
        ValueError: required_cols 为空列表，或 DataFrame 缺少必需列
    
    Example:
        >>> import pandas as pd
        >>> from data_fetchers.common.dataframe_utils import validate_dataframe_columns
        >>> 
        >>> # 正常场景：所有必需列存在
        >>> df = pd.DataFrame({'date': ['2024-01-01'], 'close': [100.0], 'volume': [1000]})
        >>> validate_dataframe_columns(df, ['date', 'close', 'volume'], 'stock_data')
        >>> 
        >>> # 正常场景：使用自定义 logger
        >>> import logging
        >>> logger = logging.getLogger('my_module')
        >>> validate_dataframe_columns(df, ['date', 'close'], 'stock_data', logger=logger)
        >>> 
        >>> # 异常场景：缺少必需列（预期抛出 ValueError）
        >>> df_missing = pd.DataFrame({'date': ['2024-01-01'], 'close': [100.0]})
        >>> validate_dataframe_columns(df_missing, ['date', 'close', 'volume'], 'stock_data')
        ValueError: stock_data 缺少必需列: ['volume']
                    可用列: ['date', 'close']
        >>> 
        >>> # 异常场景：df 不是 DataFrame（预期抛出 TypeError）
        >>> validate_dataframe_columns('invalid', ['date'], 'test')
        TypeError: test 参数必须是 pandas.DataFrame 类型
    
    Note:
        日志记录缺失列信息，便于后续审计追溯。
        遵循 MODULE.md 约束 #61（DataFrame 列名校验）。
    """
    # logger 参数化（遵循 PROJECT.md 规范）
    if logger is None:
        logger = logging.getLogger(__name__)

    # 边界处理：df_name 参数校验（优先处理，确保后续错误信息友好）
    if df_name is None:
        df_name = _DEFAULT_DF_NAME

    # 边界处理：df 参数类型校验（使用 isinstance 确保类型正确）
    if not isinstance(df, pd.DataFrame):
        logger.error(f"DataFrame 参数类型错误: {df_name}, 实际类型: {type(df).__name__}")
        raise TypeError(f"{df_name} 参数必须是 pandas.DataFrame 类型")

    # 边界处理：required_cols 参数校验
    if not required_cols:
        logger.error(f"required_cols 参数为空列表: {df_name}")
        raise ValueError(f"{df_name} 的 required_cols 不能为空列表")

    # 验证必需列存在（使用列表推导式保持原始顺序）
    missing_cols = [col for col in required_cols if col not in df.columns]

    if missing_cols:
        # 构建友好错误信息（包含可用列）
        available_cols = list(df.columns)
        error_msg = (
            f"{df_name} 缺少必需列: {missing_cols}\n"
            f"可用列: {available_cols}"
        )

        # 日志记录（便于审计追溯）
        logger.error(f"DataFrame 列名校验失败: {df_name}, 缺失: {missing_cols}, 可用: {available_cols}")

        raise ValueError(error_msg)

    # 验证通过日志（只记录关键信息，避免冗长输出）
    logger.debug(f"{df_name} 列名校验通过，共 {len(required_cols)} 列")
