#!/usr/bin/env python3
"""
因子数据缓存拉取脚本
定时任务：周二至周六凌晨4点执行

拉取近2年（500个交易日）的主板股票数据，缓存到本地。
"""

import sys
import os
from datetime import datetime
from pathlib import Path

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent))

from real_data_loader import RealDataLoader

def main():
    print("=" * 60)
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 开始拉取因子数据")
    print("=" * 60)
    print("参数: n_days=500, max_stocks=0（全部主板股票）")
    print()
    
    # 创建数据加载器
    loader = RealDataLoader(
        use_mock=False,
        use_local=False,
        enable_cache=True
    )
    
    try:
        # 拉取数据（会自动缓存）
        factor_df, return_df = loader.load_data_multithreaded(
            n_days=500,
            max_stocks=0,
            enable_complement=True
        )
        
        print()
        print("=" * 60)
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 因子数据拉取完成")
        print("=" * 60)
        print(f"因子数据: {len(factor_df)} 行")
        print(f"收益数据: {len(return_df)} 行")
        print(f"股票数量: {factor_df['asset'].nunique()}")
        print(f"交易日数: {factor_df['date'].nunique()}")
        
        return True
        
    except Exception as e:
        print(f"\n❌ 拉取失败: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == '__main__':
    success = main()
    sys.exit(0 if success else 1)
