#!/usr/bin/env python3
"""
因子数据合并脚本

功能：
1. 加载主数据源 factor_data.json.gz
2. 加载所有 parquet 因子文件
3. 数据对齐（基于 date + asset）
4. 命名统一（使用 parquet 文件名作为因子名）
5. 生成合并后数据

使用方法：
    python summary/merge_factors.py                     # 使用默认因子列表
    python summary/merge_factors.py --factors A_FA_N0112 B_atr_pct  # 指定因子
    python summary/merge_factors.py --list-factors      # 列出可用因子
    python summary/merge_factors.py --output ./output   # 指定输出目录

版本历史：
    v1.0: 基础版本（硬编码路径）
    v1.1: 2026-05-28 符合研发规范：添加版本常量、setup_logger、返回类型注解、异常处理、pytest测试
    v1.2: 2026-05-28 第二轮深度审查：精确化异常处理、删除未使用变量、函数拆分、argparse支持、流程文档
"""

__version__ = '1.2'
__author__ = 'factor_ic_analyzer'

# 标准库导入
import argparse
import gzip
import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# 第三方库导入
import pandas as pd


# 项目根目录
PROJECT_ROOT = Path(__file__).parent.parent.resolve()

# 数据路径配置
DATA_PATHS = {
    'factor_data': 'data_fetchers/result',
    'factors': 'data_fetchers/result/factors',
}

# 14个新因子列表（默认值，可通过命令行覆盖）
DEFAULT_FACTORS = [
    'A_FA_N0112', 'A_FA_N0322', 'A_FA_N0340',
    'B_atr_pct', 'B_bollinger_width_20', 'B_cci_overbought',
    'B_keltner_position', 'B_ma_trend', 'B_mfi_overbought',
    'B_plus_di_14', 'B_rsi_24', 'B_trend_strength',
    'B_volatility_ratio', 'C_genetic_combo'
]

# 输出文件名常量
OUTPUT_FILES = {
    'json': 'factor_data_merged.json.gz',
    'metadata': 'factor_data_merged_metadata.json',
    'parquet': 'factor_data_merged.parquet',
}

# 必需列名（用于数据对齐）
REQUIRED_COLUMNS = ['date', 'asset']

# 预期因子值列名（按优先级排序）
FACTOR_VALUE_COLUMNS = ['factor_value', 'value', 'val']


def setup_logger(name: str = 'merge_factors') -> logging.Logger:
    """配置日志记录器
    
    Args:
        name: 日志记录器名称
        
    Returns:
        配置好的 Logger 对象
    """
    logger = logging.getLogger(name)
    
    if not logger.handlers:
        # 日志文件路径
        log_dir = PROJECT_ROOT / 'summary' / 'logs'
        log_dir.mkdir(parents=True, exist_ok=True)
        
        log_file = log_dir / f'merge_factors_{datetime.now().strftime("%Y-%m-%d")}.log'
        
        # 文件处理器
        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        file_handler.setLevel(logging.DEBUG)
        
        # 控制台处理器
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        
        # 日志格式
        formatter = logging.Formatter('%(asctime)s | %(levelname)-8s | %(name)s | %(message)s')
        file_handler.setFormatter(formatter)
        console_handler.setFormatter(formatter)
        
        logger.addHandler(file_handler)
        logger.addHandler(console_handler)
        logger.setLevel(logging.DEBUG)
    
    return logger


def load_main_data(logger: logging.Logger) -> Optional[pd.DataFrame]:
    """加载主数据源
    
    Args:
        logger: 日志记录器
        
    Returns:
        主数据 DataFrame，或 None（加载失败）
    """
    main_data_file = PROJECT_ROOT / DATA_PATHS['factor_data'] / 'factor_data.json.gz'
    
    if not main_data_file.exists():
        logger.warning(f"主数据源文件不存在: {main_data_file}")
        return None
    
    logger.info(f"加载主数据源: {main_data_file}")
    
    try:
        with gzip.open(main_data_file, 'rt', encoding='utf-8') as f:
            data = json.load(f).get('data', [])
        df = pd.DataFrame(data)
        logger.info(f"主数据源加载完成: {len(df)} 条记录, {len(df.columns)} 列")
        logger.debug(f"主数据列: {df.columns.tolist()}")
        return df
    except gzip.BadGzipFile as e:
        logger.error(f"主数据源 gzip 格式错误: {e}")
        return None
    except json.JSONDecodeError as e:
        logger.error(f"主数据源 JSON 解析失败: {e}")
        return None
    except OSError as e:
        logger.error(f"主数据源文件读取失败: {e}")
        return None


def load_parquet_factor(factor_name: str, logger: logging.Logger) -> Optional[pd.DataFrame]:
    """加载单个 parquet 因子文件
    
    Args:
        factor_name: 因子名称
        logger: 日志记录器
        
    Returns:
        因子 DataFrame，或 None（文件不存在或加载失败）
    """
    factors_dir = PROJECT_ROOT / DATA_PATHS['factors']
    filepath = factors_dir / f"{factor_name}.parquet"
    
    if not filepath.exists():
        logger.warning(f"因子文件不存在: {filepath}")
        return None
    
    try:
        df = pd.read_parquet(filepath)
        logger.info(f"加载因子 {factor_name}: {len(df)} 条记录")
        return df
    except OSError as e:
        logger.error(f"因子 {factor_name} 文件读取错误: {e}")
        return None
    except pd.errors.EmptyDataError as e:
        logger.error(f"因子 {factor_name} 数据为空: {e}")
        return None
    except ValueError as e:
        logger.error(f"因子 {factor_name} 数据格式错误: {e}")
        return None


def detect_value_column(factor_df: pd.DataFrame, factor_name: str, logger: logging.Logger) -> Optional[str]:
    """检测因子值列名
    
    Args:
        factor_df: 因子 DataFrame
        factor_name: 因子名称（用于日志）
        logger: 日志记录器
        
    Returns:
        值列名，或 None（无法确定）
    """
    columns = factor_df.columns.tolist()
    
    # 按优先级检查预期列名
    for col in FACTOR_VALUE_COLUMNS:
        if col in columns:
            return col
    
    # 排除必需列后，取最后一个非必需列
    non_required_cols = [c for c in columns if c not in REQUIRED_COLUMNS]
    
    if non_required_cols:
        value_col = non_required_cols[-1]
        logger.debug(f"因子 {factor_name} 使用推断列名: {value_col}")
        return value_col
    
    logger.error(f"因子 {factor_name} 无法确定值列名，列: {columns}")
    return None


def merge_single_factor(
    merged_df: pd.DataFrame,
    factor_df: pd.DataFrame,
    factor_name: str,
    logger: logging.Logger
) -> pd.DataFrame:
    """合并单个因子到主数据
    
    Args:
        merged_df: 当前合并后的 DataFrame
        factor_df: 因子 DataFrame
        factor_name: 因子名称
        logger: 日志记录器
        
    Returns:
        合并后的 DataFrame
    """
    # 检查必需列
    if not all(col in factor_df.columns for col in REQUIRED_COLUMNS):
        logger.error(f"因子 {factor_name} 缺少必需列 {REQUIRED_COLUMNS}，跳过")
        return merged_df
    
    # 检测值列名
    value_col = detect_value_column(factor_df, factor_name, logger)
    if value_col is None:
        return merged_df
    
    # 重命名因子值列为因子名
    factor_df_renamed = factor_df[REQUIRED_COLUMNS + [value_col]].copy()
    factor_df_renamed.columns = REQUIRED_COLUMNS + [factor_name]
    
    # 合并
    merged_df = merged_df.merge(factor_df_renamed, on=REQUIRED_COLUMNS, how='left')
    
    # 统计有效值
    total_rows = len(merged_df)
    valid_count = merged_df[factor_name].notna().sum()
    coverage_pct = valid_count / total_rows * 100 if total_rows > 0 else 0
    logger.info(f"  ✓ {factor_name}: 有效记录 {valid_count:,} / {total_rows:,} ({coverage_pct:.1f}%)")
    
    return merged_df


def save_merged_data(
    merged_df: pd.DataFrame,
    output_dir: Path,
    logger: logging.Logger
) -> bool:
    """保存合并后的数据
    
    Args:
        merged_df: 合并后的 DataFrame
        output_dir: 输出目录
        logger: 日志记录器
        
    Returns:
        是否保存成功
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    
    output_parquet = output_dir / OUTPUT_FILES['parquet']
    metadata_file = output_dir / OUTPUT_FILES['metadata']
    
    logger.info(f"保存合并数据到: {output_dir}")
    
    try:
        # 保存 Parquet 文件
        merged_df.to_parquet(output_parquet, index=False, compression='gzip')
        file_size_mb = output_parquet.stat().st_size / 1024 / 1024
        logger.info(f"  Parquet文件: {output_parquet}")
        logger.info(f"  文件大小: {file_size_mb:.2f} MB")
        
        # 保存元数据
        # 减2是因为 date 和 asset 不是因子列
        total_factors = len(merged_df.columns) - len(REQUIRED_COLUMNS)
        
        metadata = {
            'created_at': datetime.now().isoformat(),
            'total_records': len(merged_df),
            'total_factors': total_factors,
            'factors': merged_df.columns.tolist(),
            'source': 'factor_data.json.gz + new factors',
            'script_version': __version__,
        }
        
        with open(metadata_file, 'w', encoding='utf-8') as f:
            json.dump(metadata, f, indent=2, ensure_ascii=False)
        logger.info(f"  元数据文件: {metadata_file}")
        
        return True
        
    except OSError as e:
        logger.error(f"保存数据文件系统错误: {e}")
        return False
    except ValueError as e:
        logger.error(f"保存数据格式错误: {e}")
        return False


def merge_factors(
    logger: logging.Logger,
    factor_list: Optional[List[str]] = None,
    output_dir: Optional[Path] = None
) -> Optional[pd.DataFrame]:
    """合并所有因子
    
    Args:
        logger: 日志记录器
        factor_list: 因子列表（None 则使用默认列表）
        output_dir: 输出目录（None 则使用默认目录）
        
    Returns:
        合并后的 DataFrame，或 None（合并失败）
    """
    # 使用默认值
    factors = factor_list if factor_list is not None else DEFAULT_FACTORS
    out_dir = output_dir if output_dir is not None else PROJECT_ROOT / DATA_PATHS['factor_data']
    
    logger.info("=" * 60)
    logger.info(f"开始合并因子数据 (版本 {__version__})")
    logger.info("=" * 60)
    
    # 1. 加载主数据源
    main_df = load_main_data(logger)
    if main_df is None:
        logger.error("主数据源加载失败，无法继续合并")
        return None
    
    # 2. 加载所有新因子
    logger.info(f"开始加载 {len(factors)} 个新因子...")
    factor_dfs: Dict[str, pd.DataFrame] = {}
    
    for factor_name in factors:
        df = load_parquet_factor(factor_name, logger)
        if df is not None:
            factor_dfs[factor_name] = df
    
    logger.info(f"成功加载 {len(factor_dfs)} 个因子")
    
    if not factor_dfs:
        logger.warning("没有成功加载任何因子，返回原始主数据")
        return main_df
    
    # 3. 逐个合并因子
    merged_df = main_df.copy()
    logger.info("开始合并因子到主数据...")
    
    for factor_name, factor_df in factor_dfs.items():
        merged_df = merge_single_factor(merged_df, factor_df, factor_name, logger)
    
    # 4. 汇总统计
    logger.info("=" * 60)
    logger.info("合并完成统计:")
    logger.info(f"  原始列数: {len(main_df.columns)}")
    logger.info(f"  合并后列数: {len(merged_df.columns)}")
    logger.info(f"  新增因子数: {len(merged_df.columns) - len(main_df.columns)}")
    logger.info(f"  总记录数: {len(merged_df):,}")
    logger.debug(f"  所有列: {merged_df.columns.tolist()}")
    
    # 5. 保存合并后的数据
    if save_merged_data(merged_df, out_dir, logger):
        logger.info("✓ 保存完成")
    else:
        logger.warning("保存失败，但合并数据仍可用")
    
    return merged_df


def list_available_factors(logger: logging.Logger) -> List[str]:
    """列出可用的因子文件
    
    Args:
        logger: 日志记录器
        
    Returns:
        可用因子名称列表
    """
    factors_dir = PROJECT_ROOT / DATA_PATHS['factors']
    
    if not factors_dir.exists():
        logger.warning(f"因子目录不存在: {factors_dir}")
        return []
    
    available = [f.stem for f in factors_dir.glob('*.parquet')]
    logger.info(f"可用因子 ({len(available)} 个):")
    for factor in sorted(available):
        logger.info(f"  - {factor}")
    
    return available


def parse_args() -> argparse.Namespace:
    """解析命令行参数
    
    Returns:
        解析后的参数对象
    """
    parser = argparse.ArgumentParser(
        description='合并因子数据到主数据源',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python summary/merge_factors.py                        # 使用默认因子列表
  python summary/merge_factors.py --factors A_FA_N0112 B_atr_pct  # 指定因子
  python summary/merge_factors.py --list-factors         # 列出可用因子
  python summary/merge_factors.py --output ./output      # 指定输出目录
        """
    )
    
    parser.add_argument(
        '--factors', '-f',
        nargs='+',
        default=None,
        help='指定要合并的因子列表（默认使用内置14个因子）'
    )
    
    parser.add_argument(
        '--output', '-o',
        type=Path,
        default=None,
        help='指定输出目录（默认: data_fetchers/result）'
    )
    
    parser.add_argument(
        '--list-factors', '-l',
        action='store_true',
        help='列出因子目录中所有可用的因子文件'
    )
    
    parser.add_argument(
        '--version', '-v',
        action='version',
        version=f'merge_factors {__version__}'
    )
    
    return parser.parse_args()


def main() -> None:
    """主函数"""
    args = parse_args()
    logger = setup_logger('merge_factors')
    
    # 列出可用因子
    if args.list_factors:
        list_available_factors(logger)
        sys.exit(0)
    
    # 合并因子
    merged_df = merge_factors(
        logger,
        factor_list=args.factors,
        output_dir=args.output
    )
    
    if merged_df is not None:
        logger.info("=" * 60)
        logger.info("✓ 因子合并流程完成")
        logger.info("=" * 60)
    else:
        logger.error("因子合并流程失败")
        sys.exit(1)


if __name__ == '__main__':
    main()