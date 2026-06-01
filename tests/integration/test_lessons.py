"""
集成测试：历史教训对应测试
对应 PROJECT.md 历史教训 → 集成测试
"""

import pytest


class TestPathMigrationSync:
    """路径迁移未同步教训测试"""

    def test_paths_module_exists(self):
        """paths.py 必须存在"""
        from paths import FACTOR_IC_DATA, FACTOR_IC_RESULT

        assert FACTOR_IC_DATA is not None
        assert FACTOR_IC_RESULT is not None

    def test_no_hardcoded_paths_in_loader(self):
        """data_loader 不允许硬编码路径"""
        # TODO: 实现实际检查
        pass


class TestNoRedundantFields:
    """字段冗余设计教训测试"""

    def test_single_data_source(self):
        """收益数据必须从 factor_ic_data 获取"""
        from paths import FACTOR_IC_DATA

        # TODO: 验证收益数据在 FACTOR_IC_DATA 中
        pass


class TestReturnDataSource:
    """收益数据获取教训测试"""

    def test_return_data_in_factor_ic_data(self):
        """forward_return 必须在 factor_ic_data.json.gz"""
        # TODO: 实现实际检查
        pass


class TestChangeSync:
    """变更同步遗漏教训测试"""

    def test_project_md_updated_on_path_change(self):
        """路径变更后 PROJECT.md 必须更新"""
        # TODO: 实现实际检查
        pass


class TestBackwardCompatAssumption:
    """向后兼容假设教训测试"""

    def test_no_assumption_on_old_path(self):
        """禁止假设数据在旧路径"""
        # TODO: 实现实际检查
        pass


class TestDocLayer:
    """文档层级写错教训测试"""

    def test_module_md_for_module_specific(self):
        """模块特定规范在 MODULE.md"""
        # TODO: 实现实际检查
        pass
