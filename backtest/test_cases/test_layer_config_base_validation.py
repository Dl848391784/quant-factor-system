"""LayerConfigBase __init_subclass__ 类定义期校验测试

覆盖：
- layer_names 长度 < 2 → 类加载即抛 ValueError
- layer_descriptions 与 layer_names 长度不一致 → 类加载即抛 ValueError
- layer_descriptions 为空（合法回退）→ 通过
- 长度一致 → 通过

设计动机：文档"percentile 5 层"等模式描述与实现的硬契约校验，
防止 layer_names_dict 静默回退到英文标签而出现"日志少了中文描述但程序仍能跑"
的退化场景（详见 LayerConfigBase docstring）。
"""

from collections.abc import Sequence
from typing import ClassVar

import pytest

from backtest.common.layered_backtest_runner import LayerConfigBase


class TestLayerConfigBaseInitSubclassValidation:
    """__init_subclass__ 类定义期长度校验"""

    def test_layer_names_too_few_raises(self) -> None:
        """layer_names 长度 < 2 → 类加载期抛 ValueError"""
        with pytest.raises(ValueError, match="layer_names 至少需要 2 层"):

            class _BadOneLayer(LayerConfigBase):
                factor_name: ClassVar[str] = "bad_one"
                layer_names: ClassVar[Sequence[str]] = ("only_one",)

    def test_descriptions_length_mismatch_raises(self) -> None:
        """layer_descriptions 与 layer_names 长度不一致 → 类加载期抛 ValueError"""
        with pytest.raises(ValueError, match="layer_descriptions 长度"):

            class _BadMismatch(LayerConfigBase):
                factor_name: ClassVar[str] = "bad_mismatch"
                layer_names: ClassVar[Sequence[str]] = ("a", "b", "c")
                layer_descriptions: ClassVar[Sequence[str]] = ("一", "二")  # 长度2 vs 3

    def test_empty_descriptions_allowed(self) -> None:
        """layer_descriptions 为空 → 合法（layer_names_dict 回退到 layer_names）"""

        class _OkEmpty(LayerConfigBase):
            factor_name: ClassVar[str] = "ok_empty"
            layer_names: ClassVar[Sequence[str]] = ("low", "high")
            # 不声明 layer_descriptions，使用基类默认空元组

        assert _OkEmpty.layer_names == ("low", "high")
        assert _OkEmpty.layer_descriptions == ()

    def test_matching_lengths_passes(self) -> None:
        """长度一致 → 类正常加载"""

        class _OkMatch(LayerConfigBase):
            factor_name: ClassVar[str] = "ok_match"
            layer_names: ClassVar[Sequence[str]] = ("low", "mid", "high")
            layer_descriptions: ClassVar[Sequence[str]] = ("低", "中", "高")

        assert len(_OkMatch.layer_names) == len(_OkMatch.layer_descriptions) == 3

    def test_error_message_contains_class_name(self) -> None:
        """错误消息必须含子类名，便于定位违规脚本"""
        with pytest.raises(ValueError, match="_NamedBad"):

            class _NamedBad(LayerConfigBase):
                factor_name: ClassVar[str] = "named_bad"
                layer_names: ClassVar[Sequence[str]] = ("a", "b")
                layer_descriptions: ClassVar[Sequence[str]] = ("一",)
