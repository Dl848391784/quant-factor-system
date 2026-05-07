"""
可视化模块
生成IC时序图和统计图表
"""

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from typing import Dict, List, Optional, Tuple
from pathlib import Path
import warnings


# 使用英文标签避免字体问题
plt.rcParams['font.family'] = 'DejaVu Sans'
plt.rcParams['axes.unicode_minus'] = False


class ICVisualizer:
    """IC可视化器 - 生成IC相关的图表"""
    
    def __init__(self, output_dir: str = './output'):
        """
        初始化可视化器
        
        Args:
            output_dir: 输出目录
        """
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
    def plot_ic_series(
        self,
        ic_series: pd.Series,
        factor_name: str,
        ma_window: int = 20,
        save_path: Optional[str] = None,
        show: bool = False
    ) -> str:
        """
        绘制单个因子的IC时序图
        
        Args:
            ic_series: IC序列 (index: 日期)
            factor_name: 因子名称
            ma_window: 移动平均窗口
            save_path: 保存路径，如果为None则自动生成
            show: 是否显示图表
            
        Returns:
            保存的图片路径
        """
        fig, ax = plt.subplots(figsize=(14, 6))
        
        # 绘制IC序列
        dates = ic_series.index
        ic_values = ic_series.values
        
        # IC柱状图（正值绿色，负值红色）
        colors = ['#2ecc71' if v >= 0 else '#e74c3c' for v in ic_values]
        ax.bar(dates, ic_values, color=colors, alpha=0.6, width=1.0, label='Daily IC')
        
        # 移动平均线
        ic_ma = ic_series.rolling(window=ma_window, min_periods=1).mean()
        ax.plot(dates, ic_ma.values, color='#3498db', linewidth=2, 
                label=f'{ma_window}-day MA')
        
        # 零线
        ax.axhline(y=0, color='black', linewidth=1, linestyle='-', alpha=0.5)
        
        # ±0.05阈值线
        ax.axhline(y=0.05, color='#27ae60', linewidth=1, linestyle='--', alpha=0.5, label='IC=±0.05')
        ax.axhline(y=-0.05, color='#27ae60', linewidth=1, linestyle='--', alpha=0.5)
        
        # 设置标题和标签
        ax.set_title(f'{factor_name} - IC Time Series', fontsize=14, fontweight='bold')
        ax.set_xlabel('Date', fontsize=11)
        ax.set_ylabel('Rank IC', fontsize=11)
        
        # 设置x轴日期格式
        ax.xaxis.set_major_locator(mdates.MonthLocator(interval=3))
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
        plt.xticks(rotation=45)
        
        # 添加图例
        ax.legend(loc='upper right')
        
        # 添加网格
        ax.grid(True, alpha=0.3)
        
        # 添加统计信息文本框
        valid_ic = ic_series.dropna()
        if len(valid_ic) > 0:
            stats_text = (
                f"IC Mean: {valid_ic.mean():.4f}\n"
                f"IC Std: {valid_ic.std():.4f}\n"
                f"ICIR: {valid_ic.mean() / valid_ic.std():.4f}\n"
                f"IC>0 Ratio: {(valid_ic > 0).sum() / len(valid_ic):.1%}"
            )
            ax.text(0.02, 0.98, stats_text, transform=ax.transAxes, fontsize=10,
                   verticalalignment='top', bbox=dict(boxstyle='round', 
                   facecolor='wheat', alpha=0.8))
        
        plt.tight_layout()
        
        # 保存图片
        if save_path is None:
            save_path = self.output_dir / f'{factor_name}_ic_series.png'
        else:
            save_path = Path(save_path)
            
        plt.savefig(save_path, dpi=150, bbox_inches='tight')
        
        if show:
            plt.show()
        else:
            plt.close()
        
        print(f"✓ IC时序图已保存: {save_path}")
        return str(save_path)
    
    def plot_ic_comparison(
        self,
        ic_results: Dict[str, Dict],
        save_path: Optional[str] = None,
        show: bool = False
    ) -> str:
        """
        绘制多因子IC对比图
        
        Args:
            ic_results: IC分析结果字典
            save_path: 保存路径
            show: 是否显示图表
            
        Returns:
            保存的图片路径
        """
        n_factors = len(ic_results)
        if n_factors == 0:
            print("警告: 没有因子数据可绘制")
            return ""
        
        # 创建子图
        fig, axes = plt.subplots(n_factors, 1, figsize=(14, 4 * n_factors))
        if n_factors == 1:
            axes = [axes]
        
        colors = ['#3498db', '#e74c3c', '#2ecc71', '#f39c12', '#9b59b6']
        
        for idx, (factor_name, result) in enumerate(ic_results.items()):
            ax = axes[idx]
            ic_series = result['ic_series']
            
            dates = ic_series.index
            ic_values = ic_series.values
            
            # 绘制IC序列
            bar_colors = ['#2ecc71' if v >= 0 else '#e74c3c' for v in ic_values]
            ax.bar(dates, ic_values, color=bar_colors, alpha=0.6, width=1.0)
            
            # 移动平均线
            ic_ma = ic_series.rolling(window=20, min_periods=1).mean()
            ax.plot(dates, ic_ma.values, color=colors[idx % len(colors)], 
                   linewidth=2, label='20日MA')
            
            # 零线
            ax.axhline(y=0, color='black', linewidth=1, linestyle='-', alpha=0.5)
            
            # 标题和标签
            stats = result['statistics']
            title = f'{factor_name}'
            if stats:
                title += f" (IC均值:{stats['ic_mean']:.4f}, ICIR:{stats['icir']:.4f})"
            ax.set_title(title, fontsize=12, fontweight='bold')
            ax.set_ylabel('Rank IC', fontsize=10)
            
            # x轴格式
            ax.xaxis.set_major_locator(mdates.MonthLocator(interval=6))
            ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
            
            ax.legend(loc='upper right')
            ax.grid(True, alpha=0.3)
        
        plt.xlabel('Date', fontsize=11)
        plt.tight_layout()
        
        # 保存
        if save_path is None:
            save_path = self.output_dir / 'factors_ic_comparison.png'
        else:
            save_path = Path(save_path)
            
        plt.savefig(save_path, dpi=150, bbox_inches='tight')
        
        if show:
            plt.show()
        else:
            plt.close()
        
        print(f"✓ 多因子IC对比图已保存: {save_path}")
        return str(save_path)
    
    def plot_ic_distribution(
        self,
        ic_series: pd.Series,
        factor_name: str,
        save_path: Optional[str] = None,
        show: bool = False
    ) -> str:
        """
        绘制IC分布直方图
        
        Args:
            ic_series: IC序列
            factor_name: 因子名称
            save_path: 保存路径
            show: 是否显示图表
            
        Returns:
            保存的图片路径
        """
        fig, ax = plt.subplots(figsize=(10, 6))
        
        # 剔除NaN
        ic_valid = ic_series.dropna()
        
        # 绘制直方图
        n, bins, patches = ax.hist(ic_valid, bins=50, color='#3498db', 
                                   alpha=0.7, edgecolor='white', density=True)
        
        # 添加核密度估计曲线
        try:
            from scipy.stats import gaussian_kde
            kde = gaussian_kde(ic_valid)
            x_range = np.linspace(ic_valid.min(), ic_valid.max(), 200)
            ax.plot(x_range, kde(x_range), color='#e74c3c', linewidth=2, label='核密度估计')
        except:
            pass
        
        # 均值线
        ic_mean = ic_valid.mean()
        ax.axvline(x=ic_mean, color='#27ae60', linewidth=2, 
                  linestyle='--', label=f'Mean: {ic_mean:.4f}')
        
        # 零线
        ax.axvline(x=0, color='black', linewidth=1, linestyle='-', alpha=0.5)
        
        ax.set_title(f'{factor_name} - IC Distribution', fontsize=14, fontweight='bold')
        ax.set_xlabel('IC Value', fontsize=11)
        ax.set_ylabel('Density', fontsize=11)
        ax.legend()
        ax.grid(True, alpha=0.3)
        
        plt.tight_layout()
        
        # 保存
        if save_path is None:
            save_path = self.output_dir / f'{factor_name}_ic_distribution.png'
        else:
            save_path = Path(save_path)
            
        plt.savefig(save_path, dpi=150, bbox_inches='tight')
        
        if show:
            plt.show()
        else:
            plt.close()
        
        print(f"✓ IC分布图已保存: {save_path}")
        return str(save_path)
    
    def generate_report(
        self,
        ic_results: Dict[str, Dict],
        show: bool = False
    ) -> List[str]:
        """
        生成完整的可视化报告
        
        Args:
            ic_results: IC分析结果
            show: 是否显示图表
            
        Returns:
            生成的图片路径列表
        """
        saved_paths = []
        
        print("\n生成可视化报告...")
        
        # 1. 生成各因子的IC时序图
        for factor_name, result in ic_results.items():
            path = self.plot_ic_series(
                result['ic_series'], 
                factor_name,
                show=show
            )
            saved_paths.append(path)
        
        # 2. 生成多因子对比图
        path = self.plot_ic_comparison(ic_results, show=show)
        saved_paths.append(path)
        
        # 3. 生成IC分布图
        for factor_name, result in ic_results.items():
            path = self.plot_ic_distribution(
                result['ic_series'],
                factor_name,
                show=show
            )
            saved_paths.append(path)
        
        return saved_paths