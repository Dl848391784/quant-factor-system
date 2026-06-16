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


class SummaryLogError(Exception):
    """摘要日志层失败（H12 R20 + R17 联动）

    用途：log_factor_summary 在 main() 内失败时，main() 不能直接 sys.exit(3)
    （会杀单元测试宿主进程，issue 2），改为 raise SummaryLogError 让 __main__
    块统一处理退出码（exit 3 = 辅助层失败，主结果产物可用）。

    典型触发场景：
    - log_factor_summary 内部 dict 字段访问异常（理论上其契约 L40-44 不抛，
      但本异常作为防御性兜底，一旦未来回归打破契约可立即定位）
    - logger 子系统故障（如 disk full、handler 异常）

    捕获约定：
    - main() 内 try/except log_factor_summary → raise SummaryLogError(...) from e
    - CLI 入口 __main__ 块 except SummaryLogError → logger.exception + sys.exit(3)
    - 与 DataSchemaError / FactorCalcError 并列：本异常表示"主结果可用，仅 sidecar
      失败"，exit 3 与业务失败 exit 4/5 严格区分（H12 R17/R18/R19 退出码档）
    """

    pass


__all__ = ["FactorCalcError", "DataSchemaError", "SummaryLogError"]
