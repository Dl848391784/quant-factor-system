#!/usr/bin/env python3
"""
校验输出文件 JSON Schema
对应 PROJECT.md 输出结构校验规范
"""

import json
import sys
from pathlib import Path


try:
    from jsonschema import ValidationError, validate
except ImportError:
    print("请安装 jsonschema: pip install jsonschema")
    sys.exit(1)


SCHEMA_DIR = Path(__file__).parent.parent / "schemas"
RESULT_DIRS = [
    Path(__file__).parent.parent / "factor_ic" / "result",
    Path(__file__).parent.parent / "backtest" / "result",
    Path(__file__).parent.parent / "comprehensive_factor" / "result",
    Path(__file__).parent.parent / "data_fetchers" / "result",
    Path(__file__).parent.parent / "summary" / "result",
]


def validate_output_schemas() -> int:
    """校验所有输出文件符合 JSON Schema"""
    errors = []

    for result_dir in RESULT_DIRS:
        if not result_dir.exists():
            continue

        for json_file in result_dir.glob("*.json"):
            # 查找对应 schema
            module = result_dir.parent.name
            schema_file = result_dir.parent / "schemas" / f"{json_file.stem}.schema.json"

            if not schema_file.exists():
                # 尝试通用 schema
                schema_file = SCHEMA_DIR / f"{module}.schema.json"

            if not schema_file.exists():
                continue

            try:
                with open(json_file) as f:
                    data = json.load(f)
                with open(schema_file) as f:
                    schema = json.load(f)

                validate(data, schema)
                print(f"✓ {json_file.name} schema 校验通过")
            except ValidationError as e:
                errors.append(f"{json_file}: {e.message}")
            except json.JSONDecodeError as e:
                errors.append(f"{json_file}: JSON 解析失败 {e}")

    if errors:
        print("❌ Schema 校验失败：")
        for e in errors:
            print(f"   {e}")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(validate_output_schemas())
