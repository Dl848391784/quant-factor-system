#!/usr/bin/env python
"""
factor_generator.py 测试脚本

位置: data_fetchers/test_cases/test_factor_generator.py
创建时间: 2026-05-25
用途: 独立测试脚本，与 CLI 入口分离

测试内容：
1. 函数定义验证
2. get_module_logger 验证
3. generate_all_factors 验证（真实数据）
4. 返回字段验证
5. 因子列验证
6. 有效记录数验证
"""

import logging
import sys
from pathlib import Path


# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from data_fetchers.common.logger_config import setup_logger
from data_fetchers.factor_generator import generate_all_factors, get_module_logger


def test_factor_generator():
    """测试 factor_generator.py 核心功能"""

    # 设置测试 logger
    test_logger = setup_logger('data_fetchers.factor_generator', level=logging.INFO)

    test_logger.info("=" * 40)
    test_logger.info("factor_generator.py 测试脚本")
    test_logger.info("=" * 40)

    try:
        # 测试 1: 函数定义验证
        test_logger.info("\n[测试 1] 函数定义验证...")
        test_logger.info("  generate_all_factors 已定义")
        test_logger.info("  get_module_logger 已定义")

        # 测试 2: get_module_logger 验证
        test_logger.info("\n[测试 2] get_module_logger 验证...")
        module_logger = get_module_logger()
        test_logger.info("  模块 logger 名称: %s", module_logger.name)
        assert module_logger.name == 'data_fetchers.factor_generator', "logger 名称不正确"
        test_logger.info("  logger 名称验证通过")

        # 测试 3: generate_all_factors 验证（使用真实数据）
        test_logger.info("\n[测试 3] generate_all_factors 验证...")
        test_logger.info("  使用真实数据进行测试...")

        metadata = generate_all_factors(logger=test_logger)

        # 测试 4: 返回字段验证
        test_logger.info("\n[测试 4] 返回字段验证...")
        required_fields = [
            'generated_at', 'elapsed_seconds', 'total_records',
            'valid_records', 'valid_records_percent', 'factor_columns',
            'input_sources', 'output_path'
        ]
        for field in required_fields:
            assert field in metadata, f"缺少必需字段: {field}"
            test_logger.info("  字段 %s 存在: %s", field, metadata[field])

        # 测试 5: 因子列验证
        test_logger.info("\n[测试 5] 因子列验证...")
        expected_factors = ['bollinger_pb', 'kdj_j', 'turnover_surge']
        assert metadata['factor_columns'] == expected_factors, "因子列不正确"
        test_logger.info("  因子列验证通过: %s", metadata['factor_columns'])

        # 测试 6: 有效记录数验证
        test_logger.info("\n[测试 6] 有效记录数验证...")
        for factor, count in metadata['valid_records'].items():
            test_logger.info("  %s 有效记录数: %d", factor, count)
            assert count > 0, f"{factor} 有效记录数为 0"

        test_logger.info("\n" + "=" * 40)
        test_logger.info("所有测试通过")
        test_logger.info("运行耗时: %.2f 秒", metadata['elapsed_seconds'])
        test_logger.info("=" * 40)

        return 0

    except Exception as e:
        test_logger.error("测试失败: %s", str(e))
        raise
    finally:
        # 清理测试 logger 处理器
        for handler in list(test_logger.handlers):
            handler.close()
            test_logger.removeHandler(handler)


if __name__ == '__main__':
    sys.exit(test_factor_generator())
