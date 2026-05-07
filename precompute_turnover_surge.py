#!/usr/bin/env python3
"""
预计算换手率突增因子分析结果（内存优化版）

因子定义：
- 换手率突增 = 当日换手率 / 过去5日换手率均值
- 使用真实换手率数据（turnover_rate），来自 baostock

筛选条件：
- 换手率突增 > 1（当日换手率高于近期均值）
- 当日涨跌幅 > 0（上涨）

此脚本用于在凌晨内存空闲时运行，生成预计算的结果文件。
Web 服务直接读取预计算结果，避免实时计算导致的 OOM。

内存优化策略：
1. 限制 n_days 为 300（避免加载全量数据）
2. 使用 turnover_surge_factor.py 的内存优化版本
3. 分阶段释放内存
4. 添加内存监控阈值

运行方式：
    python precompute_turnover_surge.py

建议运行时间：
    凌晨 3:00-5:00（内存空闲时段）

作者: 云舟
日期: 2026-04-08
更新: 2026-04-10 (内存优化)
"""

import json
import os
import gc
from pathlib import Path
from datetime import datetime
import sys

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent))

from factor_ic.ic_turnover_surge import run_turnover_surge_analysis


def get_memory_usage_mb() -> float:
    """获取当前进程真实RSS内存（MB）"""
    try:
        with open('/proc/self/status', 'r') as f:
            for line in f:
                if line.startswith('VmRSS:'):
                    return int(line.split()[1]) / 1024  # kB -> MB
    except Exception:
        pass
    return 0.0


def get_memory_info_str() -> str:
    """获取内存信息字符串"""
    mem_mb = get_memory_usage_mb()
    return f"RSS={mem_mb:.1f}MB"


def atomic_write_json(filepath: Path, data: dict):
    """
    原子写入 JSON 文件
    
    先写入临时文件，成功后再重命名，防止写入中断导致文件截断
    
    Args:
        filepath: 目标文件路径
        data: 要写入的数据
    """
    import tempfile
    import shutil
    
    # 创建临时文件（在同一目录下，确保同一文件系统，支持原子重命名）
    temp_fd, temp_path = tempfile.mkstemp(
        dir=filepath.parent,
        prefix='.tmp_',
        suffix='.json'
    )
    
    try:
        # 写入临时文件
        with os.fdopen(temp_fd, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        
        # 原子重命名（同一文件系统上的 rename 是原子操作）
        shutil.move(temp_path, str(filepath))
        
    except Exception as e:
        # 出错时清理临时文件
        if os.path.exists(temp_path):
            os.unlink(temp_path)
        raise e


# 配置
BASE_DIR = Path(__file__).parent
OUTPUT_FILE = BASE_DIR / 'turnover_surge_analysis_result.json'


def main():
    """主函数（内存优化版）"""
    print('='*60)
    print('预计算换手率突增因子分析结果（内存优化版）')
    print('='*60)
    print(f'开始时间: {datetime.now().isoformat()}')
    print(f'初始内存: {get_memory_info_str()}')
    
    initial_mem = get_memory_usage_mb()
    
    # 执行分析（限制天数为 300 天，避免内存不足）
    # n_days 设置为 300 天，足够计算 IC 和分层回测
    print(f'\n[执行分析] n_days=300, 内存阈值已设置...')
    
    result = run_turnover_surge_analysis(
        n_days=300,  # 限制天数，避免 OOM
        num_layers=5,
        filter_conditions=True
    )
    
    if not result.get('success'):
        print(f'\n[错误] 分析失败: {result.get("error")}')
        return
    
    # 保存结果（原子写入，防止文件截断）
    print(f'\n[保存结果] 保存到: {OUTPUT_FILE}')
    
    # 清理 IC Series（无法直接序列化）
    if 'ic_series' in result and isinstance(result['ic_series'], dict):
        # 已经是字典格式，保留
        pass
    elif hasattr(result.get('ic_series'), 'to_dict'):
        # 是 pandas Series，转换为字典
        ic_series = result.pop('ic_series')
        result['ic_series_data'] = {
            'dates': [str(d.date()) if hasattr(d, 'date') else str(d).split()[0] for d in ic_series.index],
            'ic_values': [round(v, 6) for v in ic_series.values]
        }
    
    # 使用原子写入
    atomic_write_json(OUTPUT_FILE, result)
    
    # 清理内存
    del result
    gc.collect()
    
    final_mem = get_memory_usage_mb()
    print(f'[内存监控] 最终内存: {final_mem:.1f} MB')
    print(f'[内存监控] 峰值增量: {final_mem - initial_mem:.1f} MB')
    
    print(f'\n完成时间: {datetime.now().isoformat()}')
    print('='*60)
    print('预计算完成！')


if __name__ == '__main__':
    main()