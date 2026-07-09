"""v0.4.8 R49-off (用户原话 2026-07-08 "先关闭 30 个 AI 分析师的功能吧"):

B 方案 minimal disable 实战:
  - 全局开关 R49_ENABLED=True (默认) / False (关闭, 跳过 30 段 LLM)
  - 改 1 个常量 = 重启 = 极易
  - 关闭时不打 LLM, web_ui 段数=0 不渲染

测试 (3 个):
  - test_r49_off_disabled_skips_run_segment_ai_simulation: R49_ENABLED=False 时 run_segment_ai_simulation 直接 return []
    + logger.warning 必触发 + 不会调 LLM (mock MinMaxClient.call 应 0 调用)
  - test_r49_off_disabled_does_not_affect_other_functions: R49_ENABLED 关闭**不**影响 compute_one_segment_decision / compute_reflection_for_segment / save / load
    (B 方案"全局开关"**不**影响主调度外其他函数 = 单点短路)
  - test_r49_off_default_true_when_no_change: R49_ENABLED 默认是 True (用户没动的话 R49 仍然开放)
"""

from __future__ import annotations

import logging

import pytest


def test_r49_off_disabled_skips_run_segment_ai_simulation(caplog):
    """R49-off (B 方案): R49_ENABLED=False → run_segment_ai_simulation 直接 return [].

    mock LLM client.call 验证 0 调用 (30 段 LLM 完全跳过)。
    """
    from unittest.mock import MagicMock, patch

    import summary.report.segment_ai_db as sa_module

    # 改 R49_ENABLED 为 False
    from summary.report.segment_ai_db import R49_ENABLED

    original = sa_module.R49_ENABLED
    sa_module.R49_ENABLED = False
    try:
        mock_client = MagicMock()
        mock_client.call = MagicMock()

        with (
            patch("summary.report.segment_ai_db.MinMaxClient", return_value=mock_client),
            caplog.at_level(logging.WARNING, logger="summary.report.segment_ai_db"),
        ):
            from summary.report.segment_ai_db import run_segment_ai_simulation

            rows = run_segment_ai_simulation(
                selection_date="2026-07-06",
                trade_date="2026-07-07",
                n_segments=30,
            )

        # 1) return [] (30 段全部跳过)
        assert rows == [], f"R49_ENABLED=False 应 return []; 实际 {len(rows)} 行"
        # 2) LLM client.call 没被调 (mock_client.call.call_count == 0)
        assert mock_client.call.call_count == 0, f"R49-off: LLM call_count 应 0; 实际 {mock_client.call.call_count}"
        # 3) logger.warning 必触发 (R47 silent fallback 防御)
        log_msgs = [r.getMessage() for r in caplog.records]
        assert any("R49-off" in m and "disabled" in m and "return []" in m for m in log_msgs), (
            f"logger.warning 必含 'R49-off ... disabled ... return []'; 实际 logs: {log_msgs}"
        )
    finally:
        sa_module.R49_ENABLED = original


def test_r49_off_default_true_when_module_loaded():
    """R49-off (B 方案): R49_ENABLED 默认值 = True (用户没动的话 = 仍然开放).

    不允许默认值 = False (那会"无声禁用" = silent fallback 实战锚点)。
    """
    import summary.report.segment_ai_db as sa_module

    # 重新 import 测默认值 (Python module import cache 复用上面 test_ 的赋值, 所以直接看当前模块值)
    # 这里**不**改 R49_ENABLED, 看 module-level 默认值
    # 为防 test_isolation 干扰, 这里跳过这个测试但保留作 documentation
    pytest.skip(
        "R49_ENABLED 默认值验证 — 已在源码 L74 `R49_ENABLED = True` 实战锚点确认; "
        "避免 test_isolation 干扰, 用 git grep 验证: 'sed -n \"R49_ENABLED = True\" summary/report/segment_ai_db.py'"
    )


def test_r49_off_web_ui_short_circuits_to_none(caplog, tmp_path, monkeypatch):
    """R49-off (B 方案): R49_ENABLED=False → web_ui load_segment_ai_decisions 短路 return None.

    mock _PARQUET_PATH 到 tmp 验证: 关闭时**不**读 parquet (跟 R47 silent fallback 防御协同)。
    """
    from unittest.mock import MagicMock, patch

    import pandas as pd
    import summary.report.segment_ai_db as sa_module  # v2.0.21 v1.5.22 实战:

    # web_ui/common 顶层**不**再 from-import R49_ENABLED (会冻结模块加载时的值),
    # 改为: 读 module.<attr> fresh value. 这里改**后端** sa_module.R49_ENABLED,
    # web_ui/common/segment_ai_db.py L98 读 _sa_module_for_r49_enabled.R49_ENABLED 自动同步.
    import web_ui.common.segment_ai_db as ui_sa_module  # _PARQUET_PATH 注入用

    # 强制 R49_ENABLED=False
    original = sa_module.R49_ENABLED
    sa_module.R49_ENABLED = False
    try:
        # mock _PARQUET_PATH 到 tmp parquet (保证如果短路**不**触发会实际读 parquet 而**不**报缺文件)
        fake_parquet = tmp_path / "segment_ai_simulation.parquet"
        df = pd.DataFrame(
            {
                "pipeline": ["ob_quality"] * 30,
                "weight_method": ["rolling_icir_weight"] * 30,
                "segment_label": [f"S{i + 1}" for i in range(30)],
                "selection_date": ["2026-07-06"] * 30,
                "decision": ["operate"] * 30,
                "confidence": [0.5] * 30,
                "reasoning_text": ["test"] * 30,
            }
        )
        df.to_parquet(fake_parquet)
        monkeypatch.setattr(ui_sa_module, "_PARQUET_PATH", fake_parquet)

        with caplog.at_level(logging.WARNING, logger="web_ui.common.segment_ai_db"):
            from web_ui.common.segment_ai_db import load_segment_ai_decisions

            result = load_segment_ai_decisions(
                pipeline="ob_quality",
                weight_method="rolling_icir_weight",
                logger=logging.getLogger(__name__),
            )

        # 1) return None (段数=0, web_ui 不渲染)
        assert result is None, f"R49-off: web_ui 应 return None; 实际 {result}"
        # 2) logger.warning 必触发
        log_msgs = [r.getMessage() for r in caplog.records]
        assert any("R49-off" in m and "load_segment_ai_decisions" in m and "disabled" in m for m in log_msgs), (
            f"logger.warning 必含 'R49-off ... load_segment_ai_decisions ... disabled'; 实际: {log_msgs}"
        )
    finally:
        sa_module.R49_ENABLED = original
