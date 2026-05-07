#!/usr/bin/env python3
"""
智能选股回测系统
作者: 云舟
功能: 根据自然语言条件选股并进行回测分析

核心功能:
1. 条件解析（大模型解析）
2. 回测引擎（T+1 开盘买入）
3. 指标计算（涨跌幅、胜率、净值曲线等）

数据格式:
- 使用现有的因子数据缓存（长格式）
- 因子数据: date, asset, open, close, high, low, rsi_6, volume_ratio_5
- 换手率数据: date, asset, turnover_rate
- 收益数据: date, asset, forward_return
- 计算型指标: return_3d, is_limit_up, is_one_word, is_sealed, turnover_surge

支持条件（通过大模型解析）:
- RSI < 30, 量比 > 2
- 换手率 15%~30%（范围表达式）
- 换手率突增 2~5倍（计算型因子）
- 3日涨幅 < 20%
- 布尔条件：涨停、一字涨停、封死涨停
"""

import json
import gzip
import re
import uuid
import threading
import requests
import gc
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field, asdict
import pandas as pd
import numpy as np


# ========== 数据结构 ==========

@dataclass
class BacktestResult:
    """回测结果"""
    task_id: str
    status: str  # pending, running, completed, error
    message: str = ""
    progress: int = 0
    
    # 选股条件
    condition: str = ""
    parsed_condition: Dict = field(default_factory=dict)
    
    # 回测参数
    start_date: str = ""
    end_date: str = ""
    period_days: int = 250  # 默认近1年（约250个交易日）
    
    # 核心指标
    total_trades: int = 0  # 总交易次数
    total_stocks_selected: int = 0  # 选出的股票总数
    avg_forward_return: float = 0.0  # 平均T+1收益率（收盘收益）
    avg_open_return: float = 0.0  # 平均T+1开盘涨幅（相对T日收盘）
    avg_high_return: float = 0.0  # 平均T+1最高收益（相对开盘买入价）
    limit_up_prob: float = 0.0  # 涨停概率（涨幅 >= 9.5%）
    positive_rate: float = 0.0  # 上涨概率
    avg_positive_return: float = 0.0  # 平均正收益
    avg_negative_return: float = 0.0  # 平均负收益
    profit_ratio: float = 0.0  # 盈亏比
    nav_final: float = 1.0  # 最终净值
    
    # 净值曲线
    nav_curve: List[Dict] = field(default_factory=list)
    
    # 交易明细
    trade_details: List[Dict] = field(default_factory=list)
    
    # 时间戳
    created_at: str = ""
    completed_at: str = ""
    error: str = ""


# ========== 大模型条件解析器 ==========

class LLMConditionParser:
    """
    大模型条件解析器（纯 LLM 版本）
    
    使用大模型将自然语言条件解析成结构化JSON
    支持复杂表达式：范围、倍数、组合等
    
    支持的字段：
    - turnover_rate: 换手率（小数，如 0.15 表示 15%）
    - turnover_surge: 换手率突增倍数
    - return_3d: 3日涨幅
    - return_1d: 1日涨幅
    - is_one_word: 是否一字涨停
    - is_sealed: 是否封死涨停
    - consecutive_limit_up: 连续涨停天数
    - rsi_6: RSI指标
    - volume_ratio_5: 5日量比
    - is_limit_up: 是否涨停
    
    支持的操作符：
    - range: 范围（min, max）
    - lt: 小于
    - gt: 大于
    - lte: 小于等于
    - gte: 大于等于
    - eq: 等于
    """
    
    # 大模型 API 配置
    API_URL = "https://coding.dashscope.aliyuncs.com/v1/chat/completions"
    
    # 支持的字段列表
    VALID_FIELDS = {
        'turnover_rate', 'turnover_surge', 'return_3d', 'return_1d',
        'is_one_word', 'is_sealed', 'consecutive_limit_up',
        'rsi_6', 'volume_ratio_5', 'is_limit_up'
    }
    
    # 支持的操作符
    VALID_OPERATORS = {'range', 'lt', 'gt', 'lte', 'gte', 'eq'}
    
    def __init__(self, api_key: str = None):
        self.api_key = api_key or self._get_api_key()
    
    def _get_api_key(self) -> str:
        """
        获取 API Key
        
        优先级：
        1. 环境变量 DASHSCOPE_API_KEY
        2. openclaw.json 配置文件中的 dashscope-coding provider apiKey
        3. 本地 .api_key 文件
        """
        import os
        
        # 1. 尝试从环境变量获取
        key = os.environ.get('DASHSCOPE_API_KEY', '').strip()
        if key:
            return key
        
        # 2. 尝试从 openclaw.json 配置文件获取
        openclaw_config_path = Path.home() / '.openclaw' / 'openclaw.json'
        if openclaw_config_path.exists():
            try:
                with open(openclaw_config_path, 'r') as f:
                    config = json.load(f)
                providers = config.get('models', {}).get('providers', {})
                dashscope_coding = providers.get('dashscope-coding', {})
                key = dashscope_coding.get('apiKey', '').strip()
                if key:
                    return key
            except Exception as e:
                print(f"读取 openclaw.json 失败: {e}")
        
        # 3. 尝试从本地配置文件获取
        config_file = Path(__file__).parent / '.api_key'
        if config_file.exists():
            return config_file.read_text().strip()
        
        return ""
    
    def parse(self, condition_text: str) -> Dict:
        """
        解析自然语言条件（纯 LLM 版本）
        
        Args:
            condition_text: 自然语言条件文本
            
        Returns:
            Dict: 解析后的结构化条件
        """
        result = {
            'raw_text': condition_text,
            'rules': [],
            'logic': 'and',
            'valid': True,
            'error': '',
            'source': 'llm'
        }
        
        if not self.api_key:
            result['valid'] = False
            result['error'] = '未配置 API Key'
            return result
        
        try:
            # 调用大模型解析
            parsed = self._call_llm(condition_text)
            if parsed:
                # 校验解析结果
                validated = self._validate_parsed_result(parsed)
                if validated['valid']:
                    result.update(validated)
                else:
                    result['valid'] = False
                    result['error'] = validated.get('error', '解析结果校验失败')
            else:
                result['valid'] = False
                result['error'] = '大模型解析返回空结果'
        except Exception as e:
            result['valid'] = False
            result['error'] = f'大模型解析异常: {str(e)}'
        
        return result
    
    def _validate_parsed_result(self, parsed: Dict) -> Dict:
        """
        校验大模型解析结果
        
        Args:
            parsed: 大模型返回的解析结果
            
        Returns:
            Dict: 校验后的结果
        """
        result = {
            'logic': parsed.get('logic', 'and'),
            'rules': [],
            'valid': True,
            'error': ''
        }
        
        # 校验 logic
        if result['logic'] not in ('and', 'or'):
            result['logic'] = 'and'
        
        # 校验 rules
        rules = parsed.get('rules', [])
        if not isinstance(rules, list):
            result['valid'] = False
            result['error'] = 'rules 不是列表'
            return result
        
        validated_rules = []
        for i, rule in enumerate(rules):
            if not isinstance(rule, dict):
                continue
            
            field = rule.get('field') or rule.get('factor')  # 兼容两种字段名
            op = rule.get('op') or rule.get('operator')  # 兼容两种操作符名
            value = rule.get('value')
            
            # 校验字段名
            if field not in self.VALID_FIELDS:
                # 尝试映射常见别名
                field_mapping = {
                    '换手率': 'turnover_rate',
                    '换手率突增': 'turnover_surge',
                    '3日涨幅': 'return_3d',
                    '1日涨幅': 'return_1d',
                    '一字涨停': 'is_one_word',
                    '封死涨停': 'is_sealed',
                    '封板': 'is_sealed',
                    '涨停': 'is_limit_up',
                    'RSI': 'rsi_6',
                    '量比': 'volume_ratio_5',
                }
                field = field_mapping.get(field)
                if not field:
                    continue  # 跳过无效字段
            
            # 校验操作符
            if op not in self.VALID_OPERATORS:
                # 兼容旧格式操作符
                op_mapping = {
                    '<': 'lt',
                    '>': 'gt',
                    '<=': 'lte',
                    '>=': 'gte',
                    '==': 'eq',
                    '=': 'eq',
                    'range': 'range',
                }
                op = op_mapping.get(op)
                if not op:
                    continue  # 跳过无效操作符
            
            # 校验值
            if op == 'range':
                # 范围操作符需要 [min, max] 数组
                if isinstance(value, list) and len(value) == 2:
                    try:
                        min_val = float(value[0])
                        max_val = float(value[1])
                        value = [min_val, max_val]
                    except (ValueError, TypeError):
                        continue
                elif isinstance(value, dict):
                    # 兼容 {"min": x, "max": y} 格式
                    try:
                        min_val = float(value.get('min', 0))
                        max_val = float(value.get('max', 0))
                        value = [min_val, max_val]
                    except (ValueError, TypeError):
                        continue
                else:
                    continue
            elif field in ('is_one_word', 'is_sealed', 'is_limit_up'):
                # 布尔字段
                if isinstance(value, str):
                    value = value.lower() in ('true', '1', 'yes', '是')
                else:
                    value = bool(value)
            else:
                # 数值字段
                try:
                    value = float(value)
                except (ValueError, TypeError):
                    continue
            
            validated_rules.append({
                'factor': field,
                'operator': op,
                'value': value
            })
        
        if not validated_rules:
            result['valid'] = False
            result['error'] = '无有效规则'
            return result
        
        result['rules'] = validated_rules
        return result
    
    def _call_llm(self, condition_text: str) -> Optional[Dict]:
        """调用大模型解析条件（带 few-shot examples）"""
        
        system_prompt = """你是一个选股条件解析器，负责将自然语言条件解析成标准JSON格式。

## 支持的字段（field）
- turnover_rate: 换手率（小数，如 0.15 表示 15%）
- turnover_surge: 换手率突增倍数（当日换手率 / 过去5日均值，如 2.0 表示2倍）
- return_3d: 3日涨幅（小数，如 0.2 表示 20%）
- return_1d: 1日涨幅（小数）
- is_one_word: 是否一字涨停（布尔值）
- is_sealed: 是否封死涨停（布尔值）
- consecutive_limit_up: 连续涨停天数（整数，0表示无连续涨停）
- rsi_6: RSI指标（0-100）
- volume_ratio_5: 5日量比
- is_limit_up: 当日是否涨停（布尔值）

## 重要字段区分说明
- is_limit_up: 当日是否涨停（布尔值，true/false）
- consecutive_limit_up: 连续涨停天数（整数，0表示未连续涨停，1表示涨停1天，2表示连涨2天...）
- is_one_word: 是否一字涨停（布尔值）
- is_sealed: 是否封死涨停（布尔值）

## 支持的操作符（op）
- range: 范围条件，value 为 [min, max]
- lt: 小于
- gt: 大于
- lte: 小于等于
- gte: 大于等于
- eq: 等于

## 输出格式
```json
{
  "conditions": [
    {"field": "字段名", "op": "操作符", "value": 值或[min,max]},
    ...
  ]
}
```

## 示例（few-shot）

### 示例1: 换手率范围（"在"字句式）
输入: "换手率在 15%~30%"
输出:
```json
{
  "conditions": [
    {"field": "turnover_rate", "op": "range", "value": [0.15, 0.30]}
  ]
}
```

### 示例2: 换手率突增（完整表达式）
输入: "换手率较过去5日均值突增 2~5 倍"
输出:
```json
{
  "conditions": [
    {"field": "turnover_surge", "op": "range", "value": [2.0, 5.0]}
  ]
}
```

### 示例3: 换手率突增（简写形式）
输入: "换手率突增 2~5 倍"
输出:
```json
{
  "conditions": [
    {"field": "turnover_surge", "op": "range", "value": [2.0, 5.0]}
  ]
}
```

### 示例4: 逗号分隔多条件
输入: "换手率突增 2~5 倍, 换手率 15%~30%, 3日涨幅小于20%"
输出:
```json
{
  "conditions": [
    {"field": "turnover_surge", "op": "range", "value": [2.0, 5.0]},
    {"field": "turnover_rate", "op": "range", "value": [0.15, 0.30]},
    {"field": "return_3d", "op": "lt", "value": 0.2}
  ]
}
```

### 示例5: "且"连接多条件
输入: "换手率突增 2~5 倍 且 换手率 15%~30% 且 3日涨幅小于20%"
输出:
```json
{
  "conditions": [
    {"field": "turnover_surge", "op": "range", "value": [2.0, 5.0]},
    {"field": "turnover_rate", "op": "range", "value": [0.15, 0.30]},
    {"field": "return_3d", "op": "lt", "value": 0.2}
  ]
}
```

### 示例6: 否定条件（一字涨停、封死涨停）
输入: "非一字涨停 且 未封死涨停"
输出:
```json
{
  "conditions": [
    {"field": "is_one_word", "op": "eq", "value": false},
    {"field": "is_sealed", "op": "eq", "value": false}
  ]
}
```

### 示例7: 未连续涨停（关键！）
输入: "未连续涨停"
输出:
```json
{
  "conditions": [
    {"field": "consecutive_limit_up", "op": "eq", "value": 0}
  ]
}
```

### 示例8: 连续涨停天数条件
输入: "连续涨停2天以上"
输出:
```json
{
  "conditions": [
    {"field": "consecutive_limit_up", "op": "gte", "value": 2}
  ]
}
```

### 示例9: 当日涨停条件
输入: "今日涨停"
输出:
```json
{
  "conditions": [
    {"field": "is_limit_up", "op": "eq", "value": true}
  ]
}
```

### 示例10: 大于/小于条件
输入: "换手率大于5% 且 量比大于2"
输出:
```json
{
  "conditions": [
    {"field": "turnover_rate", "op": "gt", "value": 0.05},
    {"field": "volume_ratio_5", "op": "gt", "value": 2.0}
  ]
}
```

### 示例11: RSI条件
输入: "RSI小于30"
输出:
```json
{
  "conditions": [
    {"field": "rsi_6", "op": "lt", "value": 30}
  ]
}
```

### 示例12: 中文逗号分隔
输入: "换手率在15%到30%之间，换手率突增2到5倍，非一字涨停"
输出:
```json
{
  "conditions": [
    {"field": "turnover_rate", "op": "range", "value": [0.15, 0.30]},
    {"field": "turnover_surge", "op": "range", "value": [2.0, 5.0]},
    {"field": "is_one_word", "op": "eq", "value": false}
  ]
}
```

### 示例13: 复杂组合条件（完整示例）
输入: "换手率较过去5日均值突增 2~5 倍，且当前换手在 15%~30%，3日涨幅 < 20%，未连续涨停，非一字涨停，T日未封死涨停"
输出:
```json
{
  "conditions": [
    {"field": "turnover_surge", "op": "range", "value": [2.0, 5.0]},
    {"field": "turnover_rate", "op": "range", "value": [0.15, 0.30]},
    {"field": "return_3d", "op": "lt", "value": 0.2},
    {"field": "consecutive_limit_up", "op": "eq", "value": 0},
    {"field": "is_one_word", "op": "eq", "value": false},
    {"field": "is_sealed", "op": "eq", "value": false}
  ]
}
```

### 示例14: "到"/"至"连接范围
输入: "换手率15%至30%"
输出:
```json
{
  "conditions": [
    {"field": "turnover_rate", "op": "range", "value": [0.15, 0.30]}
  ]
}
```

## 重要规则
1. 百分比换手率必须转换成小数（如 15% → 0.15）
2. 3日涨幅、1日涨幅也要转换成小数（如 20% → 0.2）
3. 布尔字段（is_one_word, is_sealed, is_limit_up）使用 true/false
4. 范围条件使用 "range" 操作符，value 为 [min, max] 数组
5. 只输出 JSON，不要任何其他文字说明
6. 多个条件之间默认为"且"逻辑，全部满足
7. 【关键】"未连续涨停" → consecutive_limit_up = 0（不是 is_limit_up！）
8. 【关键】"换手率较过去5日均值突增 X~Y 倍" → turnover_surge, range, [X, Y]"""

        user_prompt = f"请解析以下选股条件，输出标准JSON格式：\n{condition_text}"
        
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        }
        
        payload = {
            "model": "glm-5",  # 使用 glm-5 模型
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "temperature": 0.1,
            "max_tokens": 500
        }
        
        try:
            response = requests.post(
                self.API_URL,
                headers=headers,
                json=payload,
                timeout=120
            )
            
            if response.status_code == 200:
                resp_data = response.json()
                content = resp_data.get('choices', [{}])[0].get('message', {}).get('content', '')
                
                # 提取JSON
                json_match = re.search(r'\{[\s\S]*\}', content)
                if json_match:
                    parsed = json.loads(json_match.group())
                    # 转换格式
                    return self._convert_llm_output(parsed)
            else:
                print(f"LLM调用失败: HTTP {response.status_code}")
        except Exception as e:
            print(f"LLM调用异常: {e}")
        
        return None
    
    def _convert_llm_output(self, parsed: Dict) -> Dict:
        """
        将 LLM 输出转换为内部格式
        
        Args:
            parsed: LLM 返回的 JSON
            
        Returns:
            Dict: 内部格式的条件
        """
        conditions = parsed.get('conditions', [])
        rules = []
        
        for cond in conditions:
            field = cond.get('field')
            op = cond.get('op')
            value = cond.get('value')
            
            if not field or not op:
                continue
            
            # 构建规则（格式与 ConditionParser 一致）
            rule = {
                'factor': field,
                'operator': op,
                'value': value
            }
            rules.append(rule)
        
        return {
            'logic': parsed.get('logic', 'and'),
            'rules': rules
        }


# ========== 智能条件解析器 ==========

class SmartConditionParser:
    """
    智能条件解析器（纯 LLM 版本）
    
    使用大模型解析自然语言条件
    """
    
    def __init__(self, use_llm: bool = True):
        self.llm_parser = LLMConditionParser()
        self.use_llm = use_llm
    
    def parse(self, condition_text: str) -> Dict:
        """
        解析选股条件（纯 LLM 版本）
        
        Args:
            condition_text: 自然语言条件
            
        Returns:
            Dict: 解析后的结构化条件
        """
        result = self.llm_parser.parse(condition_text)
        result['source'] = 'llm'
        return result


# ========== 回测引擎 ==========

class BacktestEngine:
    """
    选股回测引擎
    
    核心逻辑:
    1. 每日收盘后根据条件筛选股票
    2. 计算 forward_return 作为 T+1 收益
    3. 计算各种收益指标
    4. 支持大模型解析复杂条件
    """
    
    CACHE_DIR = Path(__file__).parent / 'cache' / 'factor_data'
    STOCK_LIST_FILE = Path(__file__).parent / 'cache' / 'stock_list.json'
    
    def __init__(self, use_llm: bool = True):
        self.parser = SmartConditionParser(use_llm=use_llm)
        self._factor_df = None
        self._return_df = None
        self._stock_list = None
        self._lock = threading.Lock()
    
    def _load_turnover_rate_data(self) -> Optional[pd.DataFrame]:
        """
        加载换手率数据
        
        Returns:
            DataFrame: date, asset, turnover_rate
        """
        turnover_path = self.CACHE_DIR / 'turnover_rate_data.json.gz'
        
        if not turnover_path.exists():
            print(f"  [提示] 换手率数据文件不存在: {turnover_path}")
            return None
        
        try:
            print(f"  [加载] 换手率数据...")
            
            with gzip.open(turnover_path, 'rt', encoding='utf-8') as f:
                data = json.load(f)
            
            records = [
                {
                    'date': r['date'],
                    'asset': r['asset'],
                    'turnover_rate': r.get('turnover_rate')
                }
                for r in data.get('data', [])
            ]
            
            del data
            gc.collect()
            
            if not records:
                return None
            
            df = pd.DataFrame(records)
            del records
            gc.collect()
            
            df['date'] = df['date'].astype(str)
            df['turnover_rate'] = pd.to_numeric(df['turnover_rate'], errors='coerce')
            df = df.dropna(subset=['turnover_rate'])
            
            print(f"  [完成] 换手率数据: {len(df)} 条记录")
            return df
            
        except Exception as e:
            print(f"  [错误] 加载换手率数据失败: {e}")
            return None
    
    def _load_return_data(self) -> Optional[pd.DataFrame]:
        """
        加载收益数据
        
        Returns:
            DataFrame: date, asset, forward_return
        """
        return_path = self.CACHE_DIR / 'return_data.json.gz'
        
        if not return_path.exists():
            print(f"  [提示] 收益数据文件不存在: {return_path}")
            return None
        
        try:
            print(f"  [加载] 收益数据...")
            
            with gzip.open(return_path, 'rt', encoding='utf-8') as f:
                data = json.load(f)
            
            records = [
                {
                    'date': r['date'],
                    'asset': r['asset'],
                    'forward_return': r.get('forward_return_1d', r.get('forward_return'))
                }
                for r in data.get('data', [])
            ]
            
            del data
            gc.collect()
            
            if not records:
                return None
            
            df = pd.DataFrame(records)
            del records
            gc.collect()
            
            df['date'] = df['date'].astype(str)
            df['forward_return'] = pd.to_numeric(df['forward_return'], errors='coerce')
            df = df.dropna(subset=['forward_return'])
            
            print(f"  [完成] 收益数据: {len(df)} 条记录")
            return df
            
        except Exception as e:
            print(f"  [错误] 加载收益数据失败: {e}")
            return None
    
    def load_data(self) -> Tuple[pd.DataFrame, pd.DataFrame, List]:
        """
        加载数据（包含计算型指标：return_3d, is_limit_up, is_one_word, is_sealed, turnover_surge）
        
        数据源：
        - factor_data.json.gz → close, rsi_6, volume_ratio_5, open, high, low
        - turnover_rate_data.json.gz → turnover_rate
        - return_data.json.gz → forward_return（作为备用数据源）
        
        计算型指标：
        - return_3d: 3日涨幅
        - is_limit_up: 涨停判断
        - is_one_word: 一字涨停
        - is_sealed: 封死涨停
        - turnover_surge: 换手率突增（当日换手率 / 过去5日均值）
        """
        with self._lock:
            if self._factor_df is None:
                # 加载因子数据
                cache_file = self.CACHE_DIR / 'factor_data.json.gz'
                if cache_file.exists():
                    print(f"\n[数据加载] 开始加载多数据源...")
                    
                    with gzip.open(cache_file, 'rt') as f:
                        data = json.load(f)
                    
                    # 数据在 'data' 键下面
                    all_data = data.get('data', [])
                    df = pd.DataFrame(all_data)
                    del data, all_data
                    gc.collect()
                    
                    print(f"  [完成] 因子数据: {len(df)} 条记录")
                    
                    # 检查可用的字段
                    has_open = 'open' in df.columns
                    has_high = 'high' in df.columns
                    has_low = 'low' in df.columns
                    
                    if not has_high:
                        print(f"  [提示] 数据缺少 high/low/open 列，使用简化版涨停判断")
                    
                    # 确保日期为字符串
                    df['date'] = df['date'].astype(str)
                    
                    # ========== 加载换手率数据 ==========
                    turnover_df = self._load_turnover_rate_data()
                    
                    if turnover_df is not None:
                        print(f"  [合并] 因子数据 + 换手率数据...")
                        
                        # 合并换手率数据
                        df = pd.merge(
                            df,
                            turnover_df,
                            on=['date', 'asset'],
                            how='left'
                        )
                        
                        del turnover_df
                        gc.collect()
                        
                        print(f"  [完成] 合并后: {len(df)} 条记录")
                    
                    # ========== 加载收益数据（备用） ==========
                    # 注意：forward_return 会在后面从收盘价计算
                    # return_data.json.gz 用于验证或补充
                    
                    # 按股票和日期排序
                    df = df.sort_values(['asset', 'date'])
                    
                    # ========== 计算型指标 ==========
                    
                    # 1. return_3d: 3日涨幅 = (close - close.shift(3)) / close.shift(3)
                    df['return_3d'] = (df['close'] - df.groupby('asset')['close'].shift(3)) / df.groupby('asset')['close'].shift(3)
                    
                    # 2. is_limit_up: 涨停判断
                    prev_close = df.groupby('asset')['close'].shift(1)
                    
                    if has_high:
                        # 有 high 列：完整涨停判断
                        df['is_limit_up'] = (
                            (df['close'] >= prev_close * 1.095) |  # 涨幅 >= 9.5%
                            (df['high'] >= prev_close * 1.095)     # 最高价触及涨停
                        ).astype(bool)
                    else:
                        # 缺少 high 列：简化涨停判断（仅看收盘涨幅）
                        df['is_limit_up'] = (df['close'] >= prev_close * 1.095).astype(bool)
                    
                    # 3. is_one_word: 一字涨停 = (open == high == close) 且涨停
                    if has_open and has_high and has_low:
                        # 完整判断
                        df['is_one_word'] = (
                            (df['open'] == df['high']) & 
                            (df['high'] == df['low']) & 
                            (df['low'] == df['close']) &
                            df['is_limit_up']
                        ).astype(bool)
                        
                        # 4. is_sealed: 封死涨停 = 收盘价等于最高价，且涨停
                        df['is_sealed'] = (
                            (df['close'] == df['high']) &
                            df['is_limit_up']
                        ).astype(bool)
                    else:
                        # 缺少 open/high/low：无法判断一字涨停和封板，设为 False
                        df['is_one_word'] = False
                        df['is_sealed'] = False
                    
                    # 5. turnover_surge: 换手率突增 = 当日换手率 / 过去5日换手率均值
                    if 'turnover_rate' in df.columns:
                        print(f"  [计算] 换手率突增因子...")
                        
                        # 计算过去5日换手率均值
                        df['turnover_ma'] = df.groupby('asset')['turnover_rate'].transform(
                            lambda x: x.rolling(window=5, min_periods=5).mean()
                        )
                        
                        # 计算换手率突增
                        df['turnover_surge'] = df['turnover_rate'] / df['turnover_ma']
                        
                        # 极端值处理（范围 [0.5, 20]）
                        df['turnover_surge'] = df['turnover_surge'].clip(0.5, 20)
                        
                        valid_count = df['turnover_surge'].notna().sum()
                        print(f"  [完成] 换手率突增因子: {valid_count} 条有效记录")
                    else:
                        print(f"  [提示] 无换手率数据，跳过 turnover_surge 计算")
                    
                    # ========== T+1收益计算 ==========
                    
                    # 计算 forward_return (T+1 收盘收益率，即买入后的收盘收益)
                    df['forward_return'] = df.groupby('asset')['close'].pct_change().shift(-1)
                    
                    # 计算 open_return (T+1 开盘涨幅，相对T日收盘)
                    if has_open:
                        df['open_return'] = (df.groupby('asset')['open'].shift(-1) - df['close']) / df['close']
                    else:
                        # 缺少 open：无法计算开盘涨幅，设为 NaN
                        df['open_return'] = np.nan
                    
                    # 计算 high_return (T+1 最高收益，相对开盘买入价)
                    if has_open and has_high:
                        next_open = df.groupby('asset')['open'].shift(-1)
                        next_high = df.groupby('asset')['high'].shift(-1)
                        df['high_return'] = (next_high - next_open) / next_open
                    elif has_high:
                        # 缺少 open，使用 high/close 估算
                        next_high = df.groupby('asset')['high'].shift(-1)
                        next_close = df.groupby('asset')['close'].shift(-1)
                        df['high_return'] = (next_high - next_close) / next_close
                    else:
                        # 缺少 high：无法计算最高收益，设为 NaN
                        df['high_return'] = np.nan
                    
                    self._factor_df = df
                    self._return_df = df[['date', 'asset', 'forward_return', 'open_return', 'high_return']].dropna()
                    
                    print(f"[数据加载完成] 总记录数: {len(df)}")
                else:
                    raise FileNotFoundError("因子数据缓存不存在")
            
            if self._stock_list is None:
                # 加载股票列表
                if self.STOCK_LIST_FILE.exists():
                    with open(self.STOCK_LIST_FILE, 'r') as f:
                        self._stock_list = json.load(f)
                else:
                    self._stock_list = []
            
            return self._factor_df, self._return_df, self._stock_list
    
    def run_backtest(
        self, 
        condition: str, 
        period_days: int = 250,
        progress_callback=None
    ) -> BacktestResult:
        """
        运行回测
        
        Args:
            condition: 选股条件
            period_days: 回测周期（交易日）
            progress_callback: 进度回调函数
            
        Returns:
            BacktestResult: 回测结果
        """
        task_id = str(uuid.uuid4())[:8]
        result = BacktestResult(
            task_id=task_id,
            status='running',
            condition=condition,
            period_days=period_days,
            created_at=datetime.now().isoformat()
        )
        
        try:
            # 1. 解析条件
            parsed = self.parser.parse(condition)
            result.parsed_condition = parsed
            
            if not parsed['valid']:
                result.status = 'error'
                result.error = parsed['error']
                return result
            
            if progress_callback:
                progress_callback(10, '条件解析完成，加载数据...')
            
            # 2. 加载数据
            factor_df, return_df, stock_list = self.load_data()
            
            if progress_callback:
                progress_callback(20, '数据加载完成，开始回测...')
            
            # 3. 获取日期范围
            dates = sorted(factor_df['date'].unique())
            if len(dates) > period_days:
                dates = dates[-period_days:]
            
            result.start_date = dates[0] if dates else ''
            result.end_date = dates[-1] if dates else ''
            
            # 4. 创建股票名称映射
            stock_names = {s['code']: s['name'] for s in stock_list} if isinstance(stock_list, list) else {}
            
            # 5. 数据已经在 factor_df 中包含了 forward_return
            # 只需要确保数据有效
            merged_df = factor_df.dropna(subset=['forward_return'])
            
            # 6. 执行回测
            all_trades = []
            nav_curve = []
            current_nav = 1.0  # 初始净值
            
            total_days = len(dates)
            
            for i, date in enumerate(dates[:-1]):  # 最后一天没有 forward_return
                # 筛选当天符合条件的股票
                day_data = merged_df[merged_df['date'] == date].copy()
                
                if day_data.empty:
                    continue
                
                # 应用条件筛选
                selected_mask = self._apply_conditions(day_data, parsed['rules'], parsed['logic'])
                selected = day_data[selected_mask].copy()
                
                if selected.empty:
                    continue
                
                # 记录交易（包含 open_return 和 high_return 用于计算新指标）
                for _, row in selected.iterrows():
                    forward_return = row.get('forward_return', None)
                    if forward_return is not None and not np.isnan(forward_return):
                        trade = {
                            'stock_code': row['asset'],
                            'stock_name': stock_names.get(row['asset'], row['asset']),
                            'date': date,
                            'forward_return': round(forward_return * 100, 2),  # 转换为百分比
                            'open_return': round(row.get('open_return', 0) * 100, 2),  # T+1开盘涨幅
                            'high_return': round(row.get('high_return', 0) * 100, 2),  # T+1最高收益
                            'rsi_6': round(row.get('rsi_6', 0), 2),
                            'volume_ratio_5': round(row.get('volume_ratio_5', 0), 2),
                        }
                        all_trades.append(trade)
                
                # 更新净值曲线（等权买入）
                daily_returns = selected['forward_return'].dropna().values
                if len(daily_returns) > 0:
                    avg_return = np.mean(daily_returns)
                    current_nav *= (1 + avg_return)
                    nav_curve.append({
                        'date': date,
                        'nav': round(current_nav, 4),
                        'trades': len(daily_returns),
                        'avg_return': round(avg_return * 100, 2)
                    })
                
                if progress_callback:
                    progress = 20 + int((i + 1) / total_days * 70)
                    progress_callback(progress, f'回测进度: {i+1}/{total_days}')
            
            # 7. 计算统计指标
            if all_trades:
                result = self._calculate_statistics(result, all_trades, nav_curve)
            
            result.status = 'completed'
            result.completed_at = datetime.now().isoformat()
            result.message = f'回测完成，共 {result.total_trades} 笔交易'
            
            if progress_callback:
                progress_callback(100, '回测完成')
            
        except Exception as e:
            result.status = 'error'
            result.error = str(e)
            import traceback
            traceback.print_exc()
        
        return result
    
    def _apply_conditions(
        self, 
        df: pd.DataFrame, 
        rules: List[Dict], 
        logic: str
    ) -> pd.Series:
        """
        应用条件筛选
        
        Args:
            df: 当日数据
            rules: 解析后的规则列表
            logic: 逻辑关系 (and/or)
            
        Returns:
            pd.Series: 布尔掩码
        """
        masks = []
        
        for rule in rules:
            factor = rule['factor']
            op = rule['operator']
            value = rule['value']
            
            if factor not in df.columns:
                # 因子不存在，创建全 False 掩码
                masks.append(pd.Series([False] * len(df)))
                continue
            
            factor_values = df[factor]
            
            # 支持范围条件
            if op == 'range':
                if isinstance(value, list) and len(value) == 2:
                    low, high = value
                    mask = (factor_values >= low) & (factor_values <= high)
                else:
                    mask = pd.Series([False] * len(df))
            # 支持布尔值条件
            elif isinstance(value, bool):
                if op in ('==', 'eq'):
                    mask = factor_values == value
                elif op == '!=':
                    mask = factor_values != value
                else:
                    # 布尔值不支持其他运算符
                    mask = pd.Series([False] * len(df))
            # 支持新操作符格式（来自 LLM）
            elif op == 'lt' or op == '<':
                mask = factor_values < value
            elif op == 'gt' or op == '>':
                mask = factor_values > value
            elif op == 'lte' or op == '<=':
                mask = factor_values <= value
            elif op == 'gte' or op == '>=':
                mask = factor_values >= value
            elif op in ('eq', '=', '=='):
                mask = factor_values == value
            else:
                mask = pd.Series([False] * len(df))
            
            masks.append(mask)
        
        if not masks:
            return pd.Series([False] * len(df))
        
        if logic == 'and':
            return pd.concat(masks, axis=1).all(axis=1)
        else:  # or
            return pd.concat(masks, axis=1).any(axis=1)
    
    def _calculate_statistics(
        self, 
        result: BacktestResult, 
        trades: List[Dict], 
        nav_curve: List[Dict]
    ) -> BacktestResult:
        """计算统计指标（包含 T+1 开盘涨幅、最高收益、涨停概率）"""
        result.total_trades = len(trades)
        result.trade_details = trades[:100]  # 只保留前100条明细
        
        # 统计选出的股票数（去重）
        unique_stocks = set(t['stock_code'] for t in trades)
        result.total_stocks_selected = len(unique_stocks)
        
        # 收益统计（forward_return 是 T+1 收盘收益）
        returns = [t['forward_return'] for t in trades]
        
        # 平均收益率
        result.avg_forward_return = round(np.mean(returns), 2) if returns else 0
        
        # === 新增指标 ===
        
        # T+1 开盘涨幅（相对T日收盘）
        # 公式：(T+1开盘价 - T日收盘价) / T日收盘价 × 100%
        open_returns = [t.get('open_return', 0) for t in trades]
        result.avg_open_return = round(np.mean(open_returns), 2) if open_returns else 0
        
        # T+1 最高收益（从开盘买入后的日内最大收益）
        # 公式：(T+1最高价 - T+1开盘价) / T+1开盘价 × 100%
        high_returns = [t.get('high_return', 0) for t in trades]
        result.avg_high_return = round(np.mean(high_returns), 2) if high_returns else 0
        
        # 涨停概率（次日涨停的可能性，涨幅 >= 9.5%）
        # 公式：涨停次数 / 总交易次数 × 100%
        limit_up_count = sum(1 for r in returns if r >= 9.5)
        result.limit_up_prob = round(limit_up_count / len(returns) * 100, 2) if returns else 0
        
        # === 原有指标 ===
        
        # 上涨概率
        positive_returns = [r for r in returns if r > 0]
        result.positive_rate = round(len(positive_returns) / len(returns) * 100, 2) if returns else 0
        
        # 平均正收益和负收益
        negative_returns = [r for r in returns if r <= 0]
        result.avg_positive_return = round(np.mean(positive_returns), 2) if positive_returns else 0
        result.avg_negative_return = round(np.mean(negative_returns), 2) if negative_returns else 0
        
        # 盈亏比
        if result.avg_negative_return != 0:
            result.profit_ratio = round(abs(result.avg_positive_return / result.avg_negative_return), 2)
        else:
            result.profit_ratio = 0
        
        # 最终净值
        if nav_curve:
            result.nav_final = round(nav_curve[-1]['nav'], 4)
        else:
            result.nav_final = 1.0
        
        # 净值曲线
        result.nav_curve = nav_curve
        
        return result


# ========== 任务管理 ==========

class BacktestTaskManager:
    """回测任务管理器"""
    
    def __init__(self):
        self.tasks: Dict[str, BacktestResult] = {}
        self.lock = threading.Lock()
        self.engine = BacktestEngine()
    
    def submit_task(self, condition: str, period_days: int = 250) -> str:
        """
        提交回测任务
        
        Args:
            condition: 选股条件
            period_days: 回测周期
            
        Returns:
            str: 任务ID
        """
        task_id = str(uuid.uuid4())[:8]
        
        # 提交时就解析条件，这样运行过程中可以看到解析结果
        parsed = self.engine.parser.parse(condition)
        
        with self.lock:
            result = BacktestResult(
                task_id=task_id,
                status='pending',
                condition=condition,
                parsed_condition=parsed,  # 预先填充解析结果
                period_days=period_days,
                created_at=datetime.now().isoformat()
            )
            self.tasks[task_id] = result
        
        # 异步执行
        thread = threading.Thread(
            target=self._run_task,
            args=(task_id, condition, period_days)
        )
        thread.daemon = True
        thread.start()
        
        return task_id
    
    def _run_task(self, task_id: str, condition: str, period_days: int):
        """执行任务"""
        def progress_callback(progress: int, message: str):
            with self.lock:
                if task_id in self.tasks:
                    self.tasks[task_id].progress = progress
                    self.tasks[task_id].message = message
        
        result = self.engine.run_backtest(condition, period_days, progress_callback)
        
        with self.lock:
            self.tasks[task_id] = result
    
    def get_result(self, task_id: str) -> Optional[BacktestResult]:
        """获取任务结果"""
        with self.lock:
            return self.tasks.get(task_id)


# 全局任务管理器
task_manager = BacktestTaskManager()


# ========== 测试代码 ==========

def test_condition_parser():
    """测试条件解析器（纯 LLM 版本）"""
    print("\n" + "="*60)
    print("测试 LLM 条件解析器")
    print("="*60)
    
    parser = LLMConditionParser()
    
    test_conditions = [
        "换手率突增 2~5 倍",
        "换手率在 15%~30%",
        "换手率突增 2~5 倍, 换手率 15%~30%, 3日涨幅小于20%",
        "非一字涨停 且 未封死涨停",
        "换手率突增 2~5 倍 且 换手率 15%~30% 且 3日涨幅 < 20% 且 非一字涨停 且 未封死涨停",
    ]
    
    for condition in test_conditions:
        print(f"\n条件: {condition}")
        result = parser.parse(condition)
        print(f"  有效: {result['valid']}")
        print(f"  来源: {result['source']}")
        if result['valid']:
            print(f"  规则数: {len(result['rules'])}")
            for rule in result['rules']:
                print(f"    - {rule}")
        else:
            print(f"  错误: {result['error']}")
    
    print("\n" + "="*60)


def test_backtest():
    """测试回测引擎（纯 LLM 版本）"""
    print("\n" + "="*60)
    print("测试回测引擎")
    print("="*60)
    
    # 测试条件：换手率突增 2~5 倍 且 换手率 15%~30% 且 3日涨幅 < 20% 且 非一字涨停 且 未封死涨停
    condition = "换手率突增 2~5 倍 且 换手率 15%~30% 且 3日涨幅 < 20% 且 非一字涨停 且 未封死涨停"
    
    print(f"测试条件: {condition}")
    
    engine = BacktestEngine(use_llm=True)  # 使用 LLM 解析
    
    # 运行回测
    result = engine.run_backtest(condition, period_days=250)
    
    print(f"\n结果:")
    print(f"  状态: {result.status}")
    print(f"  错误: {result.error if result.error else '无'}")
    
    if result.status == 'completed':
        print(f"  总交易数: {result.total_trades}")
        print(f"  选出股票数: {result.total_stocks_selected}")
        print(f"  平均T+1收益率: {result.avg_forward_return}%")
        print(f"  平均T+1开盘涨幅: {result.avg_open_return}%")
        print(f"  平均T+1最高收益: {result.avg_high_return}%")
        print(f"  涨停概率: {result.limit_up_prob}%")
        print(f"  上涨概率: {result.positive_rate}%")
        print(f"  盈亏比: {result.profit_ratio}")
        print(f"  最终净值: {result.nav_final}")
        
        # 显示前10条交易明细
        if result.trade_details:
            print(f"\n前10条交易明细:")
            for i, trade in enumerate(result.trade_details[:10]):
                print(f"  {i+1}. {trade['date']} {trade['stock_code']} {trade['stock_name']}: {trade['forward_return']}%")
    
    print("\n" + "="*60)


if __name__ == '__main__':
    """测试选股回测系统"""
    
    # 测试条件解析器
    test_condition_parser()
    
    # 测试回测引擎
    test_backtest()