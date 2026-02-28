#!/usr/bin/env python3
"""Quick test for watermark cleaning in parser._clean_text()."""

import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from emmc_copilot.ingestion.parser import _clean_text


# Test cases
TEST_CASES = [
    # (input, expected_output_substring, description)
    (
        "Downloaded by ru yi (ry_lang@outlook.com)",
        "",
        "完整下载声明"
    ),
    (
        "Some text here\nDownloaded by R (ry_lang@outlook.com)\nMore text",
        "Some text here",
        "下载声明在文本中间"
    ),
    (
        "ry_lang@outlook.com some text",
        "some text",
        "单独的邮箱"
    ),
    (
        "This is ry_lang and some text",
        "This is and some text",
        "水印用户名 ry_lang"
    ),
    (
        "Downloaded by A (xxx@xxx.com)\nNormal paragraph",
        "Normal paragraph",
        "通用下载声明模式"
    ),
    (
        "Valid text with ry yi inside",
        "Valid text with inside",
        "带空格的水印名"
    ),
    (
        "Normal text without watermarks",
        "Normal text without watermarks",
        "无水印文本应保持不变"
    ),
    (
        "Text\n\n\n\nMultiple newlines",
        "Text\n\nMultiple newlines",
        "多余换行符应被清理"
    ),
    (
        "Multiple    spaces   and\t\ttabs",
        "Multiple spaces and tabs",
        "多余空白符应被清理"
    ),
]


def run_tests():
    """Run watermark cleaning tests."""
    passed = 0
    failed = 0

    print("=" * 60)
    print("水印清洗测试")
    print("=" * 60)

    for i, (input_text, expected, description) in enumerate(TEST_CASES, 1):
        result = _clean_text(input_text)
        # Check if expected substring is in result
        success = expected in result if expected else result == ""

        status = "✓ PASS" if success else "✗ FAIL"
        print(f"\n测试 {i}: {description}")
        print(f"  输入:   {repr(input_text)}")
        print(f"  期望包含: {repr(expected)}")
        print(f"  实际结果: {repr(result)}")
        print(f"  {status}")

        if success:
            passed += 1
        else:
            failed += 1

    print("\n" + "=" * 60)
    print(f"结果: {passed} 通过, {failed} 失败")
    print("=" * 60)

    return failed == 0


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
