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
    python summary/merge_factors.py

版本历史：
    v1.0: 基础版本（硬编码路径）
    v1.1: 2026-05-28 符合研发规范：添加版本常量、setup_logger、返回类型注解、异常处理、pytest测试
"""

__version__ = '1.1'
__author__ = 'factor_ic_analyzer'

# 标准库导入
import gzip
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

# 第三方库导入
import pandas as pd


# 项目根目录
PROJECT_ROOT = Path(__file__).parent.parent.resolve()

# 数据路径配置
DATA_PATHS = {
    'factor_data': 'data_fetchers/result',
    'factors': 'data_fetchers/result/factors',
}

# 14个新因子列表（可从配置文件读取）
NEW_FACTORS = [
    'A_FA_N0112', 'A_FA_N0322', 'A_FA_N0340',
    'B_atr_pct', 'B_bollinger_width_20', 'B_cci_overbought',
    'B_keltner_position', 'B_ma_trend', 'B_mfi_overbought',
    'B_plus_di_14', 'B_rsi_24', 'B_trend_strength',
    'B_volatility_ratio', 'C_genetic_combo'
]

# 输出文件名常量
OUTPUT_FILENAME = 'factor_data_merged.json.gz'
METADATA_FILENAME = 'factor_data_merged_metadata.json'
PARQUET_FILENAME = 'factor_data_merged.parquet'


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
    except (gzip.BadGzipFile, json.JSONDecodeError, OSError) as e:
        logger.error(f"主数据源加载失败: {type(e).__name__}: {e}")
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
    except Exception as e:
        logger.error(f"因子 {factor_name} 加载失败: {type(e).__name__}: {e}")
        return None


def merge_factors(logger: logging.Logger) -> Optional[pd.DataFrame]:
    """合并所有因子
    
    Args:
        logger: 日志记录器
        
    Returns:
        合并后的 DataFrame，或 None（合并失败）
    """
    logger.info("=" * 60)
    logger.info(f"开始合并因子数据 (版本 {__version__})")
    logger.info("=" * 60)
    
    # 1. 加载主数据源
    main_df = load_main_data(logger)
    if main_df is None:
        logger.error("主数据源加载失败，无法继续合并")
        return None
    
    # 2. 加载所有新因子
    logger.info(f"开始加载 {len(NEW_FACTORS)} 个新因子...")
    factor_dfs: Dict[str, pd.DataFrame] = {}
    
    for factor_name in NEW_FACTORS:
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
        # 检查必需列
        if 'date' not in factor_df.columns or 'asset' not in factor_df.columns:
            logger.error(f"因子 {factor_name} 缺少 date 或 asset 列，跳过")
            continue
        
        # 确定因子值列名
        value_col = 'factor_value' if 'factor_value' in factor_df.columns else factor_df.columns[-1]
        
        # 重命名因子值列为因子名
        factor_df_renamed = factor_df[['date', 'asset', value_col]].copy()
        factor_df_renamed.columns = ['date', 'asset', factor_name]
        
        # 合并
        before_rows = len(merged_df)
        merged_df = merged_df.merge(factor_df_renamed, on=['date', 'asset'], how='left')
        after_rows = len(merged_df)
        
        # 统计有效值
        valid_count = merged_df[factor_name].notna().sum()
        logger.info(f"  ✓ {factor_name}: 有效记录 {valid_count:,} / {after_rows:,} ({valid_count/after_rows*100:.1f}%)")
    
    # 4. 汇总统计
    logger.info("=" * 60)
    logger.info("合并完成统计:")
    logger.info(f"  原始列数: {len(main_df.columns)}")
    logger.info(f"  合并后列数: {len(merged_df.columns)}")
    # 魔法数字说明：减2是因为 date 和 asset 不是因子列
    logger.info(f"  新增因子数: {len(merged_df.columns) - len(main_df.columns)}")
    logger.info(f"  总记录数: {len(merged_df):,}")
    logger.debug(f"  所有列: {merged_df.columns.tolist()}")
    
    # 5. 保存合并后的数据
    output_dir = PROJECT_ROOT / DATA_PATHS['factor_data']
    output_dir.mkdir(parents=True, exist_ok=True)
    
    output_json = output_dir / OUTPUT_FILENAME
    output_parquet = output_dir / PARQUET_FILENAME
    metadata_file = output_dir / METADATA_FILENAME
    
    logger.info(f"保存合并数据到: {output_dir}")
    
    try:
        # 保存 Parquet 文件
        merged_df.to_parquet(output_parquet, index=False, compression='gzip')
        logger.info(f"  Parquet文件: {output_parquet}")
        logger.info(f"  文件大小: {output_parquet.stat().st_size / 1024 / 1024:.2f} MB")
        
        # 保存元数据
        # 魔法数字说明：减2是因为 date 和 asset 不是因子列
        total_factors = len(merged_df.columns) - 2
        
        with open(metadata_file, 'w', encoding='utf-8') as f:
            json.dump({
                'created_at': datetime.now().isoformat(),
                'total_records': len(merged_df),
                'total_factors': total_factors,
                'factors': merged_df.columns.tolist(),
                'source': 'factor_data.json.gz + new factors',
                'script_version': __version__,
            }, f, indent=2, ensure_ascii=False)
        logger.info(f"  元数据文件: {metadata_file}")
        
    except Exception as e:
        logger.error(f"保存数据失败: {type(e).__name__}: {e}")
        return merged_df
    
    logger.info("✓ 保存完成")
    
    return merged_df


def main() -> None:
    """主函数"""
    logger = setup_logger('merge_factors')
    
    merged_df = merge_factors(logger)
    
    if merged_df is not None:
        logger.info("=" * 60)
        logger.info("✓ 因子合并流程完成")
        logger.info("=" * 60)
    else:
        logger.error("因子合并流程失败")


if __name__ == '__main__':
    main()