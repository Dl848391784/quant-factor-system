#!/usr/bin/env python3
"""
run_pipeline._plan_batches 批次切分逻辑单元测试。

测试覆盖：
1. parallel=1 → 每脚本一批（全串行）
2. parallel=2 且全部在 stage 2 → 按 2 切分
3. parallel=2 且余数处理 → 最后一批 < N
4. 混合 stage（0/1/2/3/4）→ stage 边界处切断，stage 0/1/4 强制串行
5. start_script 跨入 parallelizable stage 中间 → 剩余脚本仍按批分配
6. 空列表 → 空批次列表

设计文档：designs/run_pipeline_parallel_design.md §5.1
"""

import sys
from pathlib import Path


# 项目根目录加入 sys.path（run_pipeline.py 在项目根）
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from run_pipeline import (  # noqa: E402
    PARALLELIZABLE_STAGES,
    ScriptTask,
    _plan_batches,
)


def _make_task(name: str, stage: int) -> ScriptTask:
    """快捷构造（args/timeout 用默认值）"""
    return ScriptTask(name=name, script=f"{name}.py", stage=stage, args=[])


# ============================================================================
# 测试用例
# ============================================================================


def test_parallel_1_all_serial():
    """parallel=1 时所有脚本退化为单元素批（全串行）"""
    tasks = [_make_task(f"ic_{i}", 2) for i in range(5)]
    batches = _plan_batches(tasks, parallel=1)

    assert len(batches) == 5
    for b in batches:
        assert len(b) == 1


def test_parallel_2_stage2_even_split():
    """parallel=2 + stage 2 全部 4 个 → 2 批 × 2"""
    tasks = [_make_task(f"ic_{i}", 2) for i in range(4)]
    batches = _plan_batches(tasks, parallel=2)

    assert len(batches) == 2
    assert [t.name for t in batches[0]] == ["ic_0", "ic_1"]
    assert [t.name for t in batches[1]] == ["ic_2", "ic_3"]


def test_parallel_2_stage2_with_remainder():
    """parallel=2 + 5 个 stage 2 脚本 → 3 批（2/2/1）"""
    tasks = [_make_task(f"ic_{i}", 2) for i in range(5)]
    batches = _plan_batches(tasks, parallel=2)

    assert len(batches) == 3
    assert len(batches[0]) == 2
    assert len(batches[1]) == 2
    assert len(batches[2]) == 1
    assert batches[2][0].name == "ic_4"


def test_parallel_3_stage2():
    """parallel=3 + 7 个 stage 2 脚本 → 3 批（3/3/1）"""
    tasks = [_make_task(f"ic_{i}", 2) for i in range(7)]
    batches = _plan_batches(tasks, parallel=3)

    assert len(batches) == 3
    assert len(batches[0]) == 3
    assert len(batches[1]) == 3
    assert len(batches[2]) == 1


def test_mixed_stages_serial_boundary():
    """混合 stage 时 stage 0/1/4 强制串行，stage 2/3 按 N 并行"""
    tasks = [
        _make_task("fetch_a", 0),
        _make_task("fetch_b", 0),
        _make_task("factor_gen", 1),
        _make_task("ic_a", 2),
        _make_task("ic_b", 2),
        _make_task("ic_c", 2),
        _make_task("bt_a", 3),
        _make_task("bt_b", 3),
        _make_task("composite", 4),
        _make_task("summary", 7),
    ]
    batches = _plan_batches(tasks, parallel=2)

    # 期望:
    # [fetch_a], [fetch_b], [factor_gen]       (stage 0/1 串行)
    # [ic_a, ic_b], [ic_c]                     (stage 2 按 2 分)
    # [bt_a, bt_b]                             (stage 3 按 2 分)
    # [composite]                              (stage 4 单脚本)
    # [summary]                                (stage 7 单脚本)
    expected = [
        ["fetch_a"],
        ["fetch_b"],
        ["factor_gen"],
        ["ic_a", "ic_b"],
        ["ic_c"],
        ["bt_a", "bt_b"],
        ["composite"],
        ["summary"],
    ]
    actual = [[t.name for t in b] for b in batches]
    assert actual == expected, f"批次切分不符:\n期望 {expected}\n实际 {actual}"


def test_stage_boundary_not_crossed():
    """Q3=A 决策：批不跨 stage 边界，即使 parallel=N 允许"""
    # 2 个 stage 2 + 2 个 stage 3，parallel=4 不应该把它们拼成一批
    tasks = [
        _make_task("ic_a", 2),
        _make_task("ic_b", 2),
        _make_task("bt_a", 3),
        _make_task("bt_b", 3),
    ]
    batches = _plan_batches(tasks, parallel=4)

    # 期望: [ic_a, ic_b], [bt_a, bt_b] —— 不能 [ic_a, ic_b, bt_a, bt_b]
    assert len(batches) == 2
    assert [t.stage for t in batches[0]] == [2, 2]
    assert [t.stage for t in batches[1]] == [3, 3]


def test_start_script_into_middle_of_stage2():
    """从 stage 2 中间脚本开始（模拟 --start-script ic_c）→ 剩余 stage 2 脚本仍按 N 分批"""
    # 模拟 --start-script ic_c 已经过滤掉 ic_a / ic_b
    tasks = [
        _make_task("ic_c", 2),
        _make_task("ic_d", 2),
        _make_task("ic_e", 2),
        _make_task("bt_a", 3),
    ]
    batches = _plan_batches(tasks, parallel=2)

    expected = [["ic_c", "ic_d"], ["ic_e"], ["bt_a"]]
    actual = [[t.name for t in b] for b in batches]
    assert actual == expected


def test_empty_scripts():
    """空列表 → 空批次列表"""
    assert _plan_batches([], parallel=2) == []
    assert _plan_batches([], parallel=1) == []


def test_parallel_n_equals_stage_size():
    """parallel == stage 大小 → 整 stage 一批跑完"""
    tasks = [_make_task(f"ic_{i}", 2) for i in range(3)]
    batches = _plan_batches(tasks, parallel=3)

    assert len(batches) == 1
    assert len(batches[0]) == 3


def test_parallel_n_larger_than_stage_size():
    """parallel > stage 大小 → 单批含全部脚本"""
    tasks = [_make_task(f"ic_{i}", 2) for i in range(2)]
    batches = _plan_batches(tasks, parallel=10)

    assert len(batches) == 1
    assert len(batches[0]) == 2


def test_parallelizable_stages_config():
    """PARALLELIZABLE_STAGES 配置正确（用户决策 Q1=A：仅 stage 2/3）"""
    assert frozenset({2, 3}) == PARALLELIZABLE_STAGES


def test_custom_parallelizable_stages():
    """允许通过参数覆盖 PARALLELIZABLE_STAGES（便于扩展，例如未来 stage 4 也并行）"""
    tasks = [
        _make_task("composite_a", 4),
        _make_task("composite_b", 4),
        _make_task("composite_c", 4),
    ]
    # 默认 stage 4 不并行
    default_batches = _plan_batches(tasks, parallel=2)
    assert [len(b) for b in default_batches] == [1, 1, 1]

    # 显式允许 stage 4 并行
    custom_batches = _plan_batches(tasks, parallel=2, parallelizable_stages=frozenset({2, 3, 4}))
    assert [len(b) for b in custom_batches] == [2, 1]


if __name__ == "__main__":
    # 允许直接运行
    import pytest

    sys.exit(pytest.main([__file__, "-v"]))
