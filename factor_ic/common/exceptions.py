#!/usr/bin/env python3
"""
factor_ic 模块共享业务异常类型

设计意图（解决跨脚本异常类型分裂）：
原本 20 个 factor_ic/ic_*.py 入口脚本各自定义同名 FactorCalcError，
上层 pipeline 跨文件 except FactorCalcError 时拿到的是哪个版本取决于
触发来源，且需 import 具体脚本，违反"异常类应定义在被捕获侧上游"的惯例。

本模块作为 single source of truth：
- 所有因子 IC 入口脚本统一 from factor_ic.common.exceptions import FactorCalcError
- 上层 pipeline 只需 import 一次，可捕获所有因子脚本抛出的业务异常

迁移状态（2026-06-15）：
- ✅ ic_capital_flow_ratio_trend_1d.py（本次落地）
- ⏳ 其余 19 个 ic_*.py 在后续维护中逐步迁移（独立任务）

作者: 云瑶
创建日期: 2026-06-15
版本历史:
  v1.0 (2026-06-15): 落地 FactorCalcError 公共定义
"""

from __future__ import annotations


class FactorCalcError(Exception):
    """因子计算业务异常

    用途：因子 IC 入口脚本中显式抛出的业务级失败信号，区别于程序 bug
    （后者由裸 Exception 捕获并以 CRITICAL 级别告警）。

    典型触发场景：
    - 公共模块返回 None / 非 dict
    - 公共模块返回结构不完整（缺关键字段如 ic_metrics）
    - 关键字段类型异常（如 ic_metrics 不是 dict）

    捕获约定：
    - CLI 入口 __main__ 块 except FactorCalcError → logger.error(exc_info=True)
    - 上层 pipeline 应自行捕获并决定 retry / skip / 上报告警
    """

    pass


class DataSchemaError(Exception):
    """因子数据 schema 校验失败

    用途：FactorSpec 声明的 required_columns 与实际数据列不匹配时抛出。
    含因子名 + 缺失列 + 可用列，便于运维精确定位。

    典型触发场景：
    - 上游 data_fetchers 改了列名，消费者 FactorSpec 的 required_columns 未同步
    - 新增因子但 factor_ic_data.json.gz 未重跑，缺扩展因子列
    - required_columns 含拼写错误的列名

    捕获约定：
    - factor_ic_runner.run_factor_ic() 内部捕获并 logger.error 后 raise
    - CLI 入口 __main__ 块 except DataSchemaError → logger.error + sys.exit(1)
    - 与 FactorCalcError 并列，上层 pipeline 可分别捕获处理
    """

    factor_name: str
    missing_columns: list[str]
    available_columns: list[str]

    def __init__(
        self,
        factor_name: str,
        missing: list[str],
        available: list[str],
    ) -> None:
        self.factor_name = factor_name
        self.missing_columns = missing
        self.available_columns = available
        super().__init__(f"因子 {factor_name} 数据 schema 校验失败: 缺失列 {missing}, 可用列(前20): {available[:20]}")


__all__ = ["FactorCalcError", "DataSchemaError"]
