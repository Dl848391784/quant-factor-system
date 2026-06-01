"""
集成测试：历史教训对应测试
对应 PROJECT.md 历史教训 → 集成测试
"""

import pytest


class TestPathMigration:
    """路径迁移未同步教训测试"""

    def test_no_legacy_path_in_loader(self):
        """data_loader 不允许硬编码旧路径（如 cache/）"""
        # TODO: 检查所有 data_loader.py 不包含 "cache/" 字面量
        pass

    def test_paths_module_importable(self):
        """paths.py 必须可导入"""
        from paths import FACTOR_IC_DATA, FACTOR_IC_RESULT
        assert FACTOR_IC_DATA is not None
        assert FACTOR_IC_RESULT is not None


class TestRedundantFields:
    """字段冗余设计教训测试"""

    def test_no_legacy_additional_factor_files(self):
        """禁止保留 additional_factor_files 冗余读取逻辑"""
        # TODO: 检查 factor_generator.py 不包含 additional_factor_files 参数
        pass


class TestReturnDataSource:
    """收益数据获取教训测试"""

    def test_return_data_from_factor_ic_data(self):
        """forward_return 必须从 factor_ic_data.json.gz 获取"""
        from paths import FACTOR_IC_DATA
        # TODO: 验证收益数据列存在
        pass

    def test_no_return_data_backup_as_source(self):
        """禁止从 return_data.json.gz 获取收益数据"""
        # TODO: grep 检查代码不引用 RETURN_DATA_BACKUP 作为运行时数据源
        pass


class TestChangeSync:
    """变更同步遗漏教训测试"""

    def test_project_md_updated_on_path_change(self):
        """路径变更后 PROJECT.md 路径表必须更新"""
        # TODO: 检查 paths.py 与 PROJECT.md 路径表一致
        pass


class TestBackwardCompat:
    """向后兼容假设教训测试"""

    def test_no_assumption_on_old_columns(self):
        """禁止假设数据列在旧文件中"""
        # TODO: 检查不存在 fallback 读取旧文件的逻辑
        pass


class TestDocLayer:
    """文档层级写错教训测试"""

    def test_module_md_for_module_specific(self):
        """模块特定规范在 MODULE.md"""
        # TODO: 检查 PROJECT.md 不包含 factor_ic/backtest 特定规范
        pass
