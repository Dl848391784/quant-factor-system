#!/usr/bin/env python3
"""
factor_ic.common.exceptions 单元测试

测试覆盖：
- FactorCalcError 是 Exception 子类
- 可正常 raise/catch
- 异常链 (raise ... from e) 正常工作
- 通过 factor_ic.common 命名空间也能导入（防止 __init__.py 漏导出）
"""

import pytest

from factor_ic.common.exceptions import FactorCalcError


class TestFactorCalcError:
    def test_is_exception_subclass(self):
        assert issubclass(FactorCalcError, Exception)

    def test_raise_and_catch(self):
        with pytest.raises(FactorCalcError, match="测试消息"):
            raise FactorCalcError("测试消息")

    def test_exception_chain_preserved(self):
        """raise ... from e 必须保留原始异常上下文"""
        original = ValueError("原始错误")
        try:
            try:
                raise original
            except ValueError as e:
                raise FactorCalcError("业务异常") from e
        except FactorCalcError as caught:
            assert caught.__cause__ is original
            assert isinstance(caught.__cause__, ValueError)

    def test_namespace_export(self):
        """从 factor_ic.common 顶层 import 也应能拿到同一个类（防 __init__ 漏导出）"""
        from factor_ic.common import FactorCalcError as NamespaceImported

        assert NamespaceImported is FactorCalcError

    def test_no_args_construction(self):
        """允许无参构造"""
        err = FactorCalcError()
        assert isinstance(err, Exception)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
