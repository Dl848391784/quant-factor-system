#!/usr/bin/env python3
"""
路径管理模块

统一项目路径获取方式，避免硬编码绝对路径。

作者: 云瑶
日期: 2026-05-24
"""

from pathlib import Path


# 项目根目录（相对于本模块位置）
_PROJECT_ROOT: Path | None = None


def get_project_root() -> Path:
    """
    获取项目根目录
    
    使用相对于本模块的位置计算，避免硬编码绝对路径。
    
    Returns:
        Path: 项目根目录路径
    """
    global _PROJECT_ROOT
    if _PROJECT_ROOT is None:
        # data_fetchers/common/paths.py → data_fetchers/ → factor_ic_analyzer/
        _PROJECT_ROOT = Path(__file__).parent.parent.parent
    return _PROJECT_ROOT


def get_cache_dir() -> Path:
    """
    获取缓存目录
    
    Returns:
        Path: cache/ 目录路径
    """
    return get_project_root() / 'cache'


def get_factor_data_dir() -> Path:
    """
    获取因子数据目录
    
    Returns:
        Path: cache/factor_data/ 目录路径
    """
    return get_cache_dir() / 'factor_data'


def get_stock_list_file() -> Path:
    """
    获取股票列表缓存文件路径
    
    Returns:
        Path: cache/stock_list.json 文件路径
    """
    return get_cache_dir() / 'stock_list.json'


def get_logs_dir() -> Path:
    """
    获取项目级日志目录
    
    Returns:
        Path: logs/ 目录路径
    """
    return get_project_root() / 'logs'


def get_module_logs_dir() -> Path:
    """
    获取模块级日志目录（data_fetchers/logs）
    
    Returns:
        Path: data_fetchers/logs/ 目录路径
    """
    return Path(__file__).parent.parent / 'logs'


def get_module_result_dir() -> Path:
    """
    获取模块级结果目录（data_fetchers/result）
    
    Returns:
        Path: data_fetchers/result/ 目录路径
    """
    return Path(__file__).parent.parent / 'result'


def ensure_dir(dir_path: Path) -> Path:
    """
    确保目录存在，不存在则创建
    
    Args:
        dir_path: 目录路径
        
    Returns:
        Path: 目录路径
    """
    dir_path.mkdir(parents=True, exist_ok=True)
    return dir_path


# 常用路径常量（延迟计算）
class Paths:
    """路径常量类（便于静态引用）"""
    
    @property
    def project_root(self) -> Path:
        return get_project_root()
    
    @property
    def cache_dir(self) -> Path:
        return get_cache_dir()
    
    @property
    def factor_data_dir(self) -> Path:
        return get_factor_data_dir()
    
    @property
    def stock_list_file(self) -> Path:
        return get_stock_list_file()
    
    @property
    def logs_dir(self) -> Path:
        return get_logs_dir()


# 全局路径实例
paths = Paths()


if __name__ == '__main__':
    # 测试路径获取
    # 注意：作为独立脚本运行时，路径计算会不同
    print("项目根目录:", Path(__file__).parent.parent.parent)
    print("缓存目录:", Path(__file__).parent.parent.parent / 'cache')
    print("因子数据目录:", Path(__file__).parent.parent.parent / 'cache' / 'factor_data')
    print("股票列表文件:", Path(__file__).parent.parent.parent / 'cache' / 'stock_list.json')
    print("日志目录:", Path(__file__).parent.parent.parent / 'logs')
    print("模块日志目录:", Path(__file__).parent.parent / 'logs')