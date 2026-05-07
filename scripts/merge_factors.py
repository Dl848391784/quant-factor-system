#!/usr/bin/env python3
"""
合并新因子到主数据源
作者: 云舟 🛠️
功能: 将14个新因子parquet文件合并到factor_data.json.gz

执行步骤:
1. 加载主数据源factor_data.json.gz
2. 加载所有parquet因子文件
3. 数据对齐（基于date+asset）
4. 命名统一（使用parquet文件名作为因子名）
5. 生成合并后数据
"""

import gzip
import json
import pandas as pd
from pathlib import Path
import logging
from datetime import datetime

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# 路径设置
ROOT_DIR = Path(__file__).parent.parent
CACHE_DIR = ROOT_DIR / 'cache' / 'factor_data'
MAIN_DATA_FILE = CACHE_DIR / 'factor_data.json.gz'
FACTORS_DIR = CACHE_DIR / 'factors'
OUTPUT_FILE = CACHE_DIR / 'factor_data_merged.json.gz'

# 14个新因子列表
NEW_FACTORS = [
    'A_FA_N0112', 'A_FA_N0322', 'A_FA_N0340',
    'B_atr_pct', 'B_bollinger_width_20', 'B_cci_overbought',
    'B_keltner_position', 'B_ma_trend', 'B_mfi_overbought',
    'B_plus_di_14', 'B_rsi_24', 'B_trend_strength',
    'B_volatility_ratio', 'C_genetic_combo'
]

def load_main_data():
    """加载主数据源"""
    logger.info(f"加载主数据源: {MAIN_DATA_FILE}")
    with gzip.open(MAIN_DATA_FILE, 'rt', encoding='utf-8') as f:
        data = json.load(f).get('data', [])
    df = pd.DataFrame(data)
    logger.info(f"主数据源加载完成: {len(df)} 条记录, {len(df.columns)} 列")
    logger.info(f"主数据列: {df.columns.tolist()}")
    return df

def load_parquet_factor(factor_name):
    """加载单个parquet因子文件"""
    filepath = FACTORS_DIR / f"{factor_name}.parquet"
    if not filepath.exists():
        logger.warning(f"因子文件不存在: {filepath}")
        return None
    
    df = pd.read_parquet(filepath)
    logger.info(f"加载因子 {factor_name}: {len(df)} 条记录")
    return df

def merge_factors():
    """合并所有因子"""
    logger.info("=" * 60)
    logger.info("开始合并因子数据")
    logger.info("=" * 60)
    
    # 1. 加载主数据源
    main_df = load_main_data()
    
    # 2. 加载所有新因子
    logger.info(f"\n开始加载 {len(NEW_FACTORS)} 个新因子...")
    factor_dfs = {}
    for factor_name in NEW_FACTORS:
        df = load_parquet_factor(factor_name)
        if df is not None:
            factor_dfs[factor_name] = df
    
    logger.info(f"\n成功加载 {len(factor_dfs)} 个因子")
    
    # 3. 逐个合并因子
    merged_df = main_df.copy()
    logger.info(f"\n开始合并因子到主数据...")
    
    for factor_name, factor_df in factor_dfs.items():
        # 检查必需列
        if 'date' not in factor_df.columns or 'asset' not in factor_df.columns:
            logger.error(f"因子 {factor_name} 缺少 date 或 asset 列")
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
    logger.info("\n" + "=" * 60)
    logger.info("合并完成统计:")
    logger.info(f"  原始列数: {len(main_df.columns)}")
    logger.info(f"  合并后列数: {len(merged_df.columns)}")
    logger.info(f"  新增因子数: {len(merged_df.columns) - len(main_df.columns)}")
    logger.info(f"  总记录数: {len(merged_df):,}")
    logger.info(f"  所有列: {merged_df.columns.tolist()}")
    
    # 5. 保存合并后的数据（使用parquet格式，更高效）
    logger.info(f"\n保存合并数据到: {OUTPUT_FILE}")
    output_parquet = CACHE_DIR / 'factor_data_merged.parquet'
    merged_df.to_parquet(output_parquet, index=False, compression='gzip')
    
    # 同时保存元数据
    metadata_file = CACHE_DIR / 'factor_data_merged_metadata.json'
    with open(metadata_file, 'w', encoding='utf-8') as f:
        json.dump({
            'created_at': datetime.now().isoformat(),
            'total_records': len(merged_df),
            'total_factors': len(merged_df.columns) - 2,
            'factors': merged_df.columns.tolist(),
            'source': 'factor_data.json.gz + 14 new factors'
        }, f, indent=2, ensure_ascii=False)
    
    logger.info(f"✓ 保存完成:")
    logger.info(f"  Parquet文件: {output_parquet}")
    logger.info(f"  文件大小: {output_parquet.stat().st_size / 1024 / 1024:.2f} MB")
    logger.info(f"  元数据文件: {metadata_file}")
    
    return merged_df

if __name__ == '__main__':
    merged_df = merge_factors()
    logger.info("\n" + "=" * 60)
    logger.info("✓ 因子合并流程完成")
    logger.info("=" * 60)