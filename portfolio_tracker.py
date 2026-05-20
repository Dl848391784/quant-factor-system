#!/usr/bin/env python3
"""
虚拟持仓跟踪模块 - Portfolio Tracker
作者: 云舟
功能: 管理虚拟账户、计算净值、记录交易、跟踪策略表现

v1.0 - P0 核心功能
- 虚拟账户初始化（100万资金）
- 每日预计算结果存储
- 调仓逻辑（买入/卖出）
- 每日净值计算
- 累计净值曲线生成
- 核心指标计算（累计收益、最大回撤、夏普比率）
- 交易记录查询

v1.1 - P1 功能增强
- 调仓建议生成
- 手动触发调仓
- 权重偏离阈值可配置
- 停牌/涨跌停特殊处理
- 调仓原因记录
- 历史调仓效果统计
- 与沪深300对比曲线

v1.2 - P2 高级功能
- 多策略并行跟踪
- 策略组合（多策略加权）
- 导出交易记录（Excel）
- 自定义初始资金
- 考虑交易成本（手续费、滑点）
"""

import json
import os
import gc
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any
import logging
import numpy as np
import pandas as pd

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ========== 常量配置 ==========

# 让 API 从定时任务写入的目录读取数据
# 定时任务写入路径: stock_strategy/data/daily_positions.json
BASE_DIR = Path('/home/admin/.openclaw/workspace/stock_strategy/data')
CACHE_DIR = BASE_DIR
PRECOMPUTE_DIR = BASE_DIR  # 预计算结果也在同一目录

# 数据文件路径
PREDICTIONS_FILE = CACHE_DIR / 'predictions.json'
HOLDINGS_FILE = CACHE_DIR / 'daily_positions.json'
TRADES_FILE = CACHE_DIR / 'daily_rotation_logs.json'
NET_VALUES_FILE = CACHE_DIR / 'daily_net_values.json'
CONFIG_FILE = CACHE_DIR / 'daily_rotation_config.json'

# 默认参数
DEFAULT_INITIAL_CAPITAL = 1_000_000  # 100万初始资金
DEFAULT_REBALANCE_THRESHOLD = 0.10   # 权重偏离10%触发调仓
DEFAULT_MAX_POSITIONS = 10           # 最大持仓数量
DEFAULT_TOP_N = 5                    # 默认持仓股票数量
DEFAULT_TRADE_COST = 0.002           # 默认交易成本（0.2%双边）
DEFAULT_SLIPPAGE = 0.001             # 默认滑点（0.1%）
RISK_FREE_RATE = 0.03                # 无风险利率（年化3%）

# ========== 数据管理工具 ==========

def atomic_write_json(filepath: Path, data: dict):
    """
    原子写入 JSON 文件
    防止写入中断导致文件截断
    """
    import tempfile
    import shutil
    
    temp_fd, temp_path = tempfile.mkstemp(
        dir=filepath.parent,
        prefix='.tmp_',
        suffix='.json'
    )
    
    try:
        with os.fdopen(temp_fd, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        shutil.move(temp_path, str(filepath))
    except Exception as e:
        if os.path.exists(temp_path):
            os.unlink(temp_path)
        raise e


def load_json_file(filepath: Path, default: Any = None) -> Any:
    """
    安全加载 JSON 文件
    如果文件不存在或损坏，返回默认值
    """
    if not filepath.exists():
        return default
    
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        logger.warning(f"加载文件失败 {filepath}: {e}")
        return default


def convert_to_native_types(obj):
    """
    递归转换 numpy 类型为 Python 原生类型
    """
    if isinstance(obj, dict):
        return {k: convert_to_native_types(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [convert_to_native_types(v) for v in obj]
    elif isinstance(obj, (np.integer, np.int64, np.int32)):
        return int(obj)
    elif isinstance(obj, (np.floating, np.float64, np.float32)):
        return float(obj)
    elif isinstance(obj, np.bool_):
        return bool(obj)
    elif isinstance(obj, np.ndarray):
        return obj.tolist()
    elif isinstance(obj, pd.Series):
        return obj.tolist()
    elif pd.isna(obj):
        return None
    else:
        return obj


# ========== 虚拟账户类 ==========

class VirtualAccount:
    """
    虚拟账户管理
    
    功能：
    - 初始化账户（100万资金）
    - 持仓管理（买入/卖出）
    - 现金管理
    - 净值计算
    """
    
    def __init__(
        self,
        strategy_name: str = 'multi_factor_v1',
        initial_capital: float = DEFAULT_INITIAL_CAPITAL,
        rebalance_threshold: float = DEFAULT_REBALANCE_THRESHOLD,
        max_positions: int = DEFAULT_MAX_POSITIONS,
        top_n: int = DEFAULT_TOP_N,
        trade_cost: float = DEFAULT_TRADE_COST,
        slippage: float = DEFAULT_SLIPPAGE
    ):
        self.strategy_name = strategy_name
        self.initial_capital = initial_capital
        self.rebalance_threshold = rebalance_threshold
        self.max_positions = max_positions
        self.top_n = top_n
        self.trade_cost = trade_cost
        self.slippage = slippage
        
        # 初始化账户状态
        self.cash_balance = initial_capital
        self.holdings: Dict[str, Dict] = {}  # {stock_code: {shares, cost_price, weight, ...}}
        self.total_market_value = 0.0
        self.net_value = 1.0
        self.daily_return = 0.0
        
        # 初始化日期（首次建仓日期）
        self.init_date = None
        
        # 加载历史数据（如果存在）
        self._load_from_disk()
    
    def _load_from_disk(self):
        """从磁盘加载账户数据（兼容新旧格式）"""
        holdings_data = load_json_file(HOLDINGS_FILE)
        config_data = load_json_file(CONFIG_FILE)
        
        if config_data:
            # 旧格式：strategy_name
            if config_data.get('strategy_name') == self.strategy_name:
                # 恢复账户配置
                self.initial_capital = config_data.get('initial_capital', self.initial_capital)
                self.cash_balance = config_data.get('cash_balance', self.initial_capital)
                self.init_date = config_data.get('init_date')
                self.net_value = config_data.get('net_value', 1.0)
                self.trade_cost = config_data.get('trade_cost', self.trade_cost)
                self.slippage = config_data.get('slippage', self.slippage)
                
                # 恢复持仓（旧格式：holdings 字典）
                if holdings_data and holdings_data.get('strategy_name') == self.strategy_name:
                    self.holdings = holdings_data.get('holdings', {})
                    logger.info(f"已加载历史持仓（旧格式）: {len(self.holdings)} 只股票")
            
            # 新格式：account_id（定时任务生成）
            elif config_data.get('account_id'):
                # 恢复账户配置
                self.initial_capital = config_data.get('initial_capital', self.initial_capital)
                self.cash_balance = config_data.get('available_cash', config_data.get('cash_balance', self.initial_capital))
                self.init_date = config_data.get('init_date')
                self.net_value = config_data.get('net_value', 1.0)
                
                # 从 rotation_strategy 读取配置
                rotation_strategy = config_data.get('rotation_strategy', {})
                self.trade_cost = rotation_strategy.get('trade_cost_pct', self.trade_cost)
                self.slippage = rotation_strategy.get('slippage_pct', self.slippage)
                
                # 恢复持仓（新格式：positions 数组）
                if holdings_data and holdings_data.get('account_id'):
                    positions = holdings_data.get('positions', [])
                    # 转换 positions 数组为 holdings 字典格式
                    # positions 中使用 'code' 字段，需要映射到 'stock_code'
                    self.holdings = {}
                    for p in positions:
                        stock_code = p.get('code') or p.get('stock_code')
                        if stock_code:
                            self.holdings[stock_code] = {
                                'shares': p.get('shares', 0),
                                'cost_price': p.get('buy_price', 0),
                                'current_price': p.get('buy_price', 0),
                                'target_weight': p.get('weight_target', 0),
                                'market_value': p.get('shares', 0) * p.get('buy_price', 0),
                                'status': 'holding',
                                'buy_date': p.get('buy_date'),
                                'name': p.get('name', '')
                            }
                    logger.info(f"已加载历史持仓（新格式）: {len(self.holdings)} 只股票")
    
    def _save_to_disk(self):
        """保存账户数据到磁盘"""
        # 保存配置
        config_data = {
            'strategy_name': self.strategy_name,
            'initial_capital': self.initial_capital,
            'cash_balance': self.cash_balance,
            'net_value': self.net_value,
            'init_date': self.init_date,
            'rebalance_threshold': self.rebalance_threshold,
            'max_positions': self.max_positions,
            'top_n': self.top_n,
            'trade_cost': self.trade_cost,
            'slippage': self.slippage,
            'last_updated': datetime.now().isoformat()
        }
        atomic_write_json(CONFIG_FILE, config_data)
        
        # 保存持仓
        holdings_data = {
            'strategy_name': self.strategy_name,
            'holdings': self.holdings,
            'last_updated': datetime.now().isoformat()
        }
        atomic_write_json(HOLDINGS_FILE, holdings_data)
        
        logger.info(f"账户数据已保存: 净值={self.net_value:.4f}, 现金={self.cash_balance:.2f}")
    
    def initialize(self, date: str, stock_list: List[str], weights: Dict[str, float], prices: Dict[str, float]):
        """
        初始化账户（首次建仓）
        
        Args:
            date: 初始化日期
            stock_list: 推荐股票列表
            weights: 目标权重映射
            prices: 股票收盘价映射
        """
        self.init_date = date
        
        # 清空持仓
        self.holdings = {}
        self.cash_balance = self.initial_capital
        
        # 按权重买入
        for stock_code in stock_list[:self.top_n]:
            target_weight = weights.get(stock_code, 1.0 / self.top_n)
            price = prices.get(stock_code)
            
            if not price:
                logger.warning(f"股票 {stock_code} 价格缺失，跳过")
                continue
            
            # 计算买入金额和数量
            buy_amount = self.initial_capital * target_weight
            buy_shares = int(buy_amount / price / 100) * 100  # 向下取整到100股
            
            if buy_shares <= 0:
                logger.warning(f"股票 {stock_code} 买入金额不足（{buy_amount:.2f}），跳过")
                continue
            
            # 执行买入
            actual_amount = buy_shares * price
            trade_cost_amount = actual_amount * self.trade_cost
            
            self.holdings[stock_code] = {
                'shares': buy_shares,
                'cost_price': price,
                'current_price': price,
                'target_weight': target_weight,
                'actual_weight': actual_amount / self.initial_capital,
                'market_value': actual_amount,
                'status': 'holding',
                'buy_date': date
            }
            
            # 更新现金余额
            self.cash_balance -= (actual_amount + trade_cost_amount)
            
            logger.info(f"买入 {stock_code}: {buy_shares}股, 价格={price:.2f}, 成本={trade_cost_amount:.2f}")
        
        # 计算初始净值
        self._update_market_value(prices)
        self.net_value = 1.0
        
        # 保存到磁盘
        self._save_to_disk()
        
        # 记录交易
        self._record_init_trades(date, prices)
        
        logger.info(f"账户初始化完成: 持仓{len(self.holdings)}只, 现金余额={self.cash_balance:.2f}")
    
    def _record_init_trades(self, date: str, prices: Dict[str, float]):
        """记录初始化交易"""
        trades = load_json_file(TRADES_FILE, {'trades': []})
        
        for stock_code, holding in self.holdings.items():
            trade_record = {
                'strategy_name': self.strategy_name,
                'trade_date': date,
                'stock_code': stock_code,
                'action': 'buy',
                'shares': holding['shares'],
                'price': holding['cost_price'],
                'amount': holding['shares'] * holding['cost_price'],
                'trade_cost': holding['shares'] * holding['cost_price'] * self.trade_cost,
                'reason': 'init_position',
                'new_weight': holding['target_weight'],
                'created_at': datetime.now().isoformat()
            }
            trades['trades'].append(trade_record)
        
        trades['last_updated'] = datetime.now().isoformat()
        atomic_write_json(TRADES_FILE, trades)
    
    def _update_market_value(self, prices: Dict[str, float]):
        """更新持仓市值"""
        self.total_market_value = 0.0
        
        for stock_code, holding in self.holdings.items():
            price = prices.get(stock_code, holding.get('current_price'))
            holding['current_price'] = price
            holding['market_value'] = holding['shares'] * price
            self.total_market_value += holding['market_value']
    
    def calculate_net_value_DISABLED(self, date: str, prices: Dict[str, float]) -> Tuple[float, float]:
        """
        【已禁用】净值计算功能已移除
        
        Args:
            date: 计算日期
            prices: 股票收盘价映射
            
        Returns:
            (net_value, daily_return) - 现在返回固定值 (1.0, 0.0)
        """
        # 仅更新市值，不计算净值和收益率
        self._update_market_value(prices)
        
        # 不再计算净值和收益率
        # prev_net_value = self.net_value
        # self.net_value = (self.total_market_value + self.cash_balance) / self.initial_capital
        # self.daily_return = ...
        
        # 不再记录净值
        # self._record_net_value(date)
        
        # 保存账户状态（仅持仓信息）
        self._save_to_disk()
        
        logger.info(f"市值更新: 日期={date}, 持仓市值={self.total_market_value:.2f}")
        
        # 返回固定值
        return 1.0, 0.0
    
    def _record_net_value_DISABLED(self, date: str):
        """【已禁用】净值记录功能已移除"""
        pass


# ========== 持仓跟踪器 ==========

class PortfolioTracker:
    """
    持仓跟踪器
    
    功能：
    - 每日预计算结果存储
    - 调仓逻辑执行
    - 净值曲线生成
    - 指标计算
    - 交易记录管理
    """
    
    def __init__(self, account: Optional[VirtualAccount] = None):
        self.account = account or VirtualAccount()
        self.predictions: List[Dict] = []  # 预计算结果历史
        
        # 加载历史预计算结果
        self._load_predictions()
    
    def _load_predictions(self):
        """加载历史预计算结果"""
        predictions_data = load_json_file(PREDICTIONS_FILE, {'predictions': []})
        self.predictions = predictions_data.get('predictions', [])
        logger.info(f"已加载 {len(self.predictions)} 条历史预计算结果")
    
    def _save_predictions(self):
        """保存预计算结果"""
        predictions_data = {
            'predictions': self.predictions,
            'last_updated': datetime.now().isoformat()
        }
        atomic_write_json(PREDICTIONS_FILE, predictions_data)
    
    def store_prediction(self, date: str, optimization_result: Dict, top_stocks: List[Dict]):
        """
        存储每日预计算结果
        
        Args:
            date: 预计算日期
            optimization_result: 最优权重组合结果
            top_stocks: 推荐股票列表
        """
        prediction_record = {
            'date': date,
            'strategy_name': self.account.strategy_name,
            'weights': optimization_result.get('best_combination', {}).get('weights', {}),
            'weights_display': optimization_result.get('best_combination', {}).get('weights_display', {}),
            'metrics': optimization_result.get('best_combination', {}).get('metrics', {}),
            'top_stocks': top_stocks[:self.account.top_n],
            'computed_at': optimization_result.get('computed_at'),
            'created_at': datetime.now().isoformat()
        }
        
        # 检查是否已存在
        existing_dates = [p['date'] for p in self.predictions]
        if date in existing_dates:
            # 更新已存在的记录
            for i, p in enumerate(self.predictions):
                if p['date'] == date:
                    self.predictions[i] = prediction_record
                    break
            logger.info(f"更新预计算结果: {date}")
        else:
            # 新增记录
            self.predictions.append(prediction_record)
            logger.info(f"新增预计算结果: {date}")
        
        # 保存
        self._save_predictions()
        
        return prediction_record
    
    def get_latest_prediction(self) -> Optional[Dict]:
        """获取最新预计算结果"""
        if not self.predictions:
            return None
        
        # 按日期排序，返回最新
        sorted_predictions = sorted(self.predictions, key=lambda p: p['date'])
        return sorted_predictions[-1]
    
    def calculate_rebalance(
        self,
        current_holdings: Dict[str, Dict],
        target_weights: Dict[str, float],
        current_prices: Dict[str, float],
        threshold: float = None
    ) -> Dict:
        """
        计算调仓需求
        
        Args:
            current_holdings: 当前持仓
            target_weights: 目标权重
            current_prices: 当前价格
            threshold: 权重偏离阈值
            
        Returns:
            {
                'need_rebalance': bool,
                'to_sell': List[Dict],
                'to_buy': List[Dict],
                'to_adjust': List[Dict],
                'reason': str
            }
        """
        threshold = threshold or self.account.rebalance_threshold
        
        to_sell = []
        to_buy = []
        to_adjust = []
        
        # 计算总市值
        total_value = self.account.total_market_value + self.account.cash_balance
        
        # 计算当前实际权重
        current_actual_weights = {}
        for stock_code, holding in current_holdings.items():
            current_actual_weights[stock_code] = holding['market_value'] / total_value
        
        # 1. 检查需要卖出的股票（不在目标持仓中）
        for stock_code in current_holdings.keys():
            target_weight = target_weights.get(stock_code, 0.0)
            
            if target_weight == 0.0:
                # 目标权重为0，需要卖出
                to_sell.append({
                    'stock_code': stock_code,
                    'shares': current_holdings[stock_code]['shares'],
                    'price': current_prices.get(stock_code),
                    'prev_weight': current_actual_weights[stock_code],
                    'new_weight': 0.0,
                    'reason': 'remove_from_portfolio'
                })
            else:
                # 检查权重偏离
                weight_diff = abs(current_actual_weights[stock_code] - target_weight)
                if weight_diff > threshold:
                    # 权重偏离超过阈值，需要调整
                    to_adjust.append({
                        'stock_code': stock_code,
                        'current_weight': current_actual_weights[stock_code],
                        'target_weight': target_weight,
                        'weight_diff': weight_diff,
                        'reason': 'weight_rebalance'
                    })
        
        # 2. 检查需要买入的股票（新增推荐）
        for stock_code, target_weight in target_weights.items():
            if stock_code not in current_holdings and target_weight > 0:
                # 新增股票
                price = current_prices.get(stock_code)
                if price:
                    buy_amount = total_value * target_weight
                    buy_shares = int(buy_amount / price / 100) * 100
                    
                    to_buy.append({
                        'stock_code': stock_code,
                        'target_weight': target_weight,
                        'buy_shares': buy_shares,
                        'price': price,
                        'reason': 'new_selection'
                    })
        
        # 判断是否需要调仓
        need_rebalance = len(to_sell) > 0 or len(to_buy) > 0 or len(to_adjust) > 0
        
        reason = ''
        if need_rebalance:
            reasons = []
            if len(to_sell) > 0:
                reasons.append(f"移除{len(to_sell)}只股票")
            if len(to_buy) > 0:
                reasons.append(f"新增{len(to_buy)}只股票")
            if len(to_adjust) > 0:
                reasons.append(f"{len(to_adjust)}只股票权重偏离>{threshold:.1%}")
            reason = ', '.join(reasons)
        
        return {
            'need_rebalance': need_rebalance,
            'to_sell': to_sell,
            'to_buy': to_buy,
            'to_adjust': to_adjust,
            'reason': reason,
            'threshold': threshold
        }
    
    def execute_rebalance(
        self,
        date: str,
        rebalance_plan: Dict,
        prices: Dict[str, float]
    ) -> List[Dict]:
        """
        执行调仓
        
        Args:
            date: 调仓日期
            rebalance_plan: 调仓计划
            prices: 价格映射
            
        Returns:
            执行的交易记录列表
        """
        trades = []
        
        # 1. 执行卖出
        for sell_item in rebalance_plan.get('to_sell', []):
            stock_code = sell_item['stock_code']
            shares = sell_item['shares']
            price = sell_item.get('price') or prices.get(stock_code)
            
            if not price:
                logger.warning(f"卖出 {stock_code} 价格缺失，跳过")
                continue
            
            # 计算卖出金额和交易成本
            sell_amount = shares * price
            trade_cost = sell_amount * self.account.trade_cost
            
            # 更新持仓
            if stock_code in self.account.holdings:
                del self.account.holdings[stock_code]
            
            # 更新现金余额
            self.account.cash_balance += (sell_amount - trade_cost)
            
            # 记录交易
            trade_record = {
                'strategy_name': self.account.strategy_name,
                'trade_date': date,
                'stock_code': stock_code,
                'action': 'sell',
                'shares': shares,
                'price': price,
                'amount': sell_amount,
                'trade_cost': trade_cost,
                'reason': sell_item.get('reason', 'weight_rebalance'),
                'prev_weight': sell_item.get('prev_weight'),
                'new_weight': 0.0,
                'created_at': datetime.now().isoformat()
            }
            trades.append(trade_record)
            
            logger.info(f"卖出 {stock_code}: {shares}股, 价格={price:.2f}, 收益={sell_amount:.2f}")
        
        # 2. 执行买入
        for buy_item in rebalance_plan.get('to_buy', []):
            stock_code = buy_item['stock_code']
            buy_shares = buy_item.get('buy_shares')
            price = buy_item.get('price') or prices.get(stock_code)
            target_weight = buy_item.get('target_weight')
            
            if not price or buy_shares <= 0:
                logger.warning(f"买入 {stock_code} 价格缺失或数量为0，跳过")
                continue
            
            # 检查现金余额是否足够
            buy_amount = buy_shares * price
            trade_cost = buy_amount * self.account.trade_cost
            total_cost = buy_amount + trade_cost
            
            if total_cost > self.account.cash_balance:
                # 按比例缩减买入数量
                max_shares = int(self.account.cash_balance / (price * (1 + self.account.trade_cost)) / 100) * 100
                buy_shares = max_shares
                buy_amount = buy_shares * price
                trade_cost = buy_amount * self.account.trade_cost
                total_cost = buy_amount + trade_cost
                logger.warning(f"现金不足，缩减 {stock_code} 买入数量: {buy_shares}股")
            
            # 更新持仓
            self.account.holdings[stock_code] = {
                'shares': buy_shares,
                'cost_price': price,
                'current_price': price,
                'target_weight': target_weight,
                'market_value': buy_amount,
                'status': 'holding',
                'buy_date': date
            }
            
            # 更新现金余额
            self.account.cash_balance -= total_cost
            
            # 记录交易
            trade_record = {
                'strategy_name': self.account.strategy_name,
                'trade_date': date,
                'stock_code': stock_code,
                'action': 'buy',
                'shares': buy_shares,
                'price': price,
                'amount': buy_amount,
                'trade_cost': trade_cost,
                'reason': buy_item.get('reason', 'new_selection'),
                'new_weight': target_weight,
                'created_at': datetime.now().isoformat()
            }
            trades.append(trade_record)
            
            logger.info(f"买入 {stock_code}: {buy_shares}股, 价格={price:.2f}, 成本={trade_cost:.2f}")
        
        # 3. 执行调整（可选，暂不实现细粒度调整）
        # 当前策略：直接卖出+买入来实现权重调整
        
        # 更新市值
        self.account._update_market_value(prices)
        
        # 保存账户状态
        self.account._save_to_disk()
        
        # 记录交易到文件
        self._record_trades(trades)
        
        logger.info(f"调仓执行完成: {len(trades)}笔交易")
        
        return trades
    
    def _record_trades(self, trades: List[Dict]):
        """记录交易到文件"""
        trades_data = load_json_file(TRADES_FILE, {'trades': []})
        trades_data['trades'].extend(trades)
        trades_data['last_updated'] = datetime.now().isoformat()
        atomic_write_json(TRADES_FILE, trades_data)
    
    def get_trade_history(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        stock_code: Optional[str] = None,
        action: Optional[str] = None
    ) -> List[Dict]:
        """
        查询交易记录
        
        Args:
            start_date: 开始日期
            end_date: 结束日期
            stock_code: 股票代码筛选
            action: 操作类型筛选（buy/sell）
            
        Returns:
            交易记录列表
        """
        trades_data = load_json_file(TRADES_FILE, {'trades': []})
        trades = trades_data.get('trades', [])
        
        # 筛选
        filtered_trades = []
        for trade in trades:
            # 策略筛选
            if trade.get('strategy_name') != self.account.strategy_name:
                continue
            
            # 日期筛选
            trade_date = trade.get('trade_date')
            if start_date and trade_date < start_date:
                continue
            if end_date and trade_date > end_date:
                continue
            
            # 股票筛选
            if stock_code and trade.get('stock_code') != stock_code:
                continue
            
            # 操作筛选
            if action and trade.get('action') != action:
                continue
            
            filtered_trades.append(trade)
        
        # 按日期排序
        filtered_trades.sort(key=lambda t: t.get('trade_date', ''), reverse=True)
        
        return filtered_trades
    
    def get_net_value_curve(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None
    ) -> List[Dict]:
        """
        获取净值曲线数据
        
        Args:
            start_date: 开始日期
            end_date: 结束日期
            
        Returns:
            净值曲线数据列表
        """
        net_values_data = load_json_file(NET_VALUES_FILE, {'net_values': []})
        net_values = net_values_data.get('net_values', [])
        
        # 筛选
        filtered_net_values = []
        for nv in net_values:
            # 策略筛选
            if nv.get('strategy_name') != self.account.strategy_name:
                continue
            
            # 日期筛选
            date = nv.get('date')
            if start_date and date < start_date:
                continue
            if end_date and date > end_date:
                continue
            
            filtered_net_values.append(nv)
        
        # 按日期排序
        filtered_net_values.sort(key=lambda n: n.get('date'))
        
        return filtered_net_values
    
    def calculate_performance_metrics_DISABLED(self) -> Dict:
        """
        计算核心指标
        
        Returns:
            {
                'cumulative_return': float,
                'max_drawdown': float,
                'sharpe_ratio': float,
                'win_rate': float,
                'total_trades': int
            }
        """
        net_values = self.get_net_value_curve()
        
        if not net_values:
            return {
                'cumulative_return': 0.0,
                'max_drawdown': 0.0,
                'sharpe_ratio': 0.0,
                'win_rate': 0.0,
                'total_trades': 0,
                'current_net_value': 1.0
            }
        
        # 提取净值序列
        nav_series = [nv['net_value'] for nv in net_values]
        daily_returns = [nv['daily_return'] for nv in net_values]
        
        # 累计收益率
        cumulative_return = (nav_series[-1] - 1.0) * 100
        
        # 最大回撤
        max_drawdown = 0.0
        peak = nav_series[0]
        for nav in nav_series:
            if nav > peak:
                peak = nav
            drawdown = (peak - nav) / peak * 100
            if drawdown > max_drawdown:
                max_drawdown = drawdown
        
        # 夏普比率
        if len(daily_returns) > 1:
            annual_return = (1 + np.mean(daily_returns)) ** 252 - 1
            annual_volatility = np.std(daily_returns) * np.sqrt(252)
            if annual_volatility > 0:
                sharpe_ratio = (annual_return - RISK_FREE_RATE) / annual_volatility
            else:
                sharpe_ratio = 0.0
        else:
            sharpe_ratio = 0.0
        
        # 胜率（正收益天数占比）
        positive_days = sum(1 for r in daily_returns if r > 0)
        win_rate = positive_days / len(daily_returns) * 100 if daily_returns else 0.0
        
        # 总交易次数
        trades = self.get_trade_history()
        total_trades = len(trades)
        
        return {
            'cumulative_return': round(cumulative_return, 2),
            'max_drawdown': round(max_drawdown, 2),
            'sharpe_ratio': round(sharpe_ratio, 2),
            'win_rate': round(win_rate, 2),
            'total_trades': total_trades,
            'current_net_value': round(nav_series[-1], 4) if nav_series else 1.0
        }


# ========== 辅助函数 ==========

def get_stock_prices(stock_codes: List[str], date: str) -> Dict[str, float]:
    """
    获取股票收盘价（多数据源容错）
    
    Args:
        stock_codes: 股票代码列表
        date: 日期
        
    Returns:
        {stock_code: price}
    """
    prices = {}
    
    # 方案 1: 从 scoring_engine 缓存获取
    try:
        from scoring_engine import get_cached_engine
        
        engine = get_cached_engine()
        if engine:
            for stock_code in stock_codes:
                price = engine.get_stock_price(stock_code, date)
                if price:
                    prices[stock_code] = price
            
            if len(prices) == len(stock_codes):
                logger.info(f"从 scoring_engine 缓存获取价格成功: {len(prices)} 只股票")
                return prices
            elif prices:
                logger.info(f"从 scoring_engine 缓存获取部分价格: {len(prices)}/{len(stock_codes)} 只股票")
    except Exception as e:
        logger.warning(f"从 scoring_engine 缓存获取价格失败: {e}")
    
    # 方案 2: 从 akshare 获取实时行情
    try:
        import akshare as ak
        
        # 获取 A 股实时行情
        df = ak.stock_zh_a_spot_em()
        
        for stock_code in stock_codes:
            if stock_code in prices:
                continue  # 已经有价格了，跳过
            
            row = df[df['代码'] == stock_code]
            if len(row) > 0:
                prices[stock_code] = float(row['最新价'].values[0])
        
        if len(prices) == len(stock_codes):
            logger.info(f"从 akshare 获取价格成功: {len(prices)} 只股票")
            return prices
        elif len(prices) > len(prices) - len(stock_codes):
            logger.info(f"从 akshare 获取部分价格: {len(prices)}/{len(stock_codes)} 只股票")
    except Exception as e:
        logger.warning(f"从 akshare 获取价格失败: {e}")
    
    # 方案 3: 从本地价格缓存文件获取
    if len(prices) < len(stock_codes):
        try:
            cache_file = Path(__file__).parent / 'cache' / 'stock_prices_cache.json'
            if cache_file.exists():
                cached_data = {}
                with open(cache_file, 'r', encoding='utf-8') as f:
                    cached_data = json.load(f)
                
                for stock_code in stock_codes:
                    if stock_code not in prices and stock_code in cached_data:
                        prices[stock_code] = cached_data[stock_code]
                
                if prices:
                    logger.info(f"从本地缓存补充价格: 当前有 {len(prices)}/{len(stock_codes)} 只股票")
        except Exception as e:
            logger.warning(f"从本地缓存获取价格失败: {e}")
    
    # 方案 4: 尝试从预计算结果中获取最新价格
    if len(prices) < len(stock_codes):
        try:
            optimization_result, _ = load_precompute_result()
            if optimization_result and 'top_stocks' in optimization_result:
                for stock_data in optimization_result['top_stocks']:
                    stock_code = stock_data.get('code')
                    if stock_code and stock_code not in prices and 'price' in stock_data:
                        prices[stock_code] = stock_data['price']
                
                if prices:
                    logger.info(f"从预计算结果补充价格: 当前有 {len(prices)}/{len(stock_codes)} 只股票")
        except Exception as e:
            logger.warning(f"从预计算结果获取价格失败: {e}")
    
    # 最终返回结果
    if len(prices) < len(stock_codes):
        missing = [code for code in stock_codes if code not in prices]
        logger.warning(f"价格获取不完整，缺少 {len(missing)} 只股票: {missing}")
    else:
        logger.info(f"价格获取完成: {len(prices)} 只股票")
    
    return prices


def load_precompute_result(period: str = 'T1') -> Tuple[Optional[Dict], Optional[List[Dict]]]:
    """
    加载v2优化结果（v3.16 优化：直接读取 optimization_T_*.json）
    
    Args:
        period: 周期类型 T1/T3/T5，默认 T1
        
    Returns:
        (optimization_result, top_stocks)
    """
    # 验证period参数
    if period not in ['T1', 'T3', 'T5']:
        logger.warning(f"不支持的周期类型: {period}，使用默认值 T1")
        period = 'T1'
    
    # v2优化结果路径（直接读取 optimization_T_*.json）
    v2_output_dir = Path('/home/admin/projects/factor_ic_analyzer/versions/v2/output')
    
    # 转换周期格式：T1 -> T_1, T3 -> T_3, T5 -> T_5
    file_period = f"T_{period[1]}"  # T1 -> T_1
    optimization_file = v2_output_dir / f'optimization_{file_period}.json'
    
    if not optimization_file.exists():
        logger.warning(f"优化结果不存在: {optimization_file}")
        return None, None
    
    try:
        with open(optimization_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception as e:
        logger.error(f"读取优化结果失败: {e}")
        return None, None
    
    # 构造optimization_result（从optimization文件提取信息）
    optimization_result = {
        'computed_at': data.get('computed_at', ''),
        'period': data.get('period', f'T+{period[1]}'),
        'date': data.get('date', ''),
        'weights_used': data.get('weights', {}),
        'summary': data.get('metrics', {}),
        'best_combination': {
            'weights': data.get('weights', {}),
            'weights_display': data.get('weights', {}),
            'metrics': data.get('metrics', {})
        }
    }
    
    # 提取股票列表：从 selections 字段读取
    top_stocks = data.get('selections', [])
    
    logger.info(f"加载优化结果: {period}, {len(top_stocks)}只股票, computed_at={data.get('computed_at')}")
    
    return optimization_result, top_stocks


def run_daily_tracking(date: str = None) -> Dict:
    """
    执行每日跟踪流程
    
    Args:
        date: 日期（默认今天）
        
    Returns:
        执行结果
    """
    date = date or datetime.now().strftime('%Y-%m-%d')
    
    # 1. 加载预计算结果
    optimization_result, top_stocks = load_precompute_result()
    
    if not optimization_result or not top_stocks:
        return {
            'success': False,
            'error': '预计算结果不存在'
        }
    
    # 2. 创建跟踪器
    tracker = PortfolioTracker()
    
    # 3. 存储预计算结果
    tracker.store_prediction(date, optimization_result, top_stocks)
    
    # 4. 检查账户是否已初始化
    if not tracker.account.init_date:
        # 首次建仓
        stock_codes = [s['code'] for s in top_stocks]
        weights = {s['code']: 1.0 / tracker.account.top_n for s in top_stocks[:tracker.account.top_n]}
        
        # 获取价格
        prices = get_stock_prices(stock_codes, date)
        
        # 初始化账户
        tracker.account.initialize(date, stock_codes, weights, prices)
        
        return {
            'success': True,
            'action': 'init',
            'message': '账户初始化完成',
            'holdings': len(tracker.account.holdings),
            'net_value': tracker.account.net_value
        }
    
    # 5. 计算调仓需求
    latest_prediction = tracker.get_latest_prediction()
    target_weights = latest_prediction.get('weights', {})
    
    # 获取当前价格
    stock_codes = list(tracker.account.holdings.keys()) + [s['code'] for s in top_stocks]
    prices = get_stock_prices(stock_codes, date)
    
    # 计算净值
    tracker.account.calculate_net_value(date, prices)
    
    # 计算调仓需求
    rebalance_plan = tracker.calculate_rebalance(
        tracker.account.holdings,
        target_weights,
        prices
    )
    
    if rebalance_plan['need_rebalance']:
        # 执行调仓
        trades = tracker.execute_rebalance(date, rebalance_plan, prices)
        
        return {
            'success': True,
            'action': 'rebalance',
            'message': f"调仓执行完成: {len(trades)}笔交易",
            'rebalance_reason': rebalance_plan['reason'],
            'trades': trades,
            'net_value': tracker.account.net_value
        }
    
    # 6. 无需调仓
    return {
        'success': True,
        'action': 'hold',
        'message': '持仓不变，无需调仓',
        'net_value': tracker.account.net_value,
        'daily_return': tracker.account.daily_return
    }


# ========== 主函数（测试） ==========

def main():
    """主函数（测试）"""
    print("=" * 50)
    print("虚拟持仓跟踪模块 - Portfolio Tracker v1.0")
    print("=" * 50)
    
    # 创建跟踪器
    tracker = PortfolioTracker()
    
    # 加载预计算结果
    optimization_result, top_stocks = load_precompute_result()
    
    if optimization_result and top_stocks:
        print(f"\n预计算结果加载成功:")
        print(f"  - 计算时间: {optimization_result.get('computed_at')}")
        print(f"  - 推荐股票: {len(top_stocks)}只")
        print(f"  - Top 5: {[s['code'] for s in top_stocks[:5]]}")
        
        # 存储预计算结果
        date = datetime.now().strftime('%Y-%m-%d')
        tracker.store_prediction(date, optimization_result, top_stocks)
        print(f"\n预计算结果已存储: {date}")
        
        # 获取性能指标
        metrics = tracker.calculate_performance_metrics()
        print(f"\n核心指标:")
        print(f"  - 累计收益: {metrics['cumulative_return']:.2f}%")
        print(f"  - 最大回撤: {metrics['max_drawdown']:.2f}%")
        print(f"  - 夏普比率: {metrics['sharpe_ratio']:.2f}")
        print(f"  - 胜率: {metrics['win_rate']:.2f}%")
        print(f"  - 交易次数: {metrics['total_trades']}")
    else:
        print("\n预计算结果不存在，请先运行预计算任务")
    
    print("\n" + "=" * 50)


if __name__ == '__main__':
    main()