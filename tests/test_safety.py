import pytest

from edcraft_validator.safety import check_code_safety


def test_accepts_simple_function() -> None:
    result = check_code_safety("def double(x):\n    return x * 2", "double")
    assert result.is_safe


def test_rejects_import_and_attribute_access() -> None:
    # Both the import and os.getcwd attribute call violate the supported subset.
    result = check_code_safety(
        "import os\ndef bad():\n    return os.getcwd()",
        "bad",
    )
    assert not result.is_safe
    assert any("Import" in error for error in result.errors)
    assert any("Attribute" in error for error in result.errors)


def test_rejects_missing_entry_function() -> None:
    result = check_code_safety("def other():\n    return 1", "main")
    assert not result.is_safe
    assert any("not defined" in error for error in result.errors)


def test_rejects_recursion() -> None:
    result = check_code_safety(
        "def countdown(n):\n    return 0 if n == 0 else countdown(n - 1)",
        "countdown",
    )
    assert not result.is_safe
    assert any("Recursion" in error for error in result.errors)


def test_accepts_helpers_conditionals_and_for_loops() -> None:
    # Helper functions and bounded for-loops are expected AI-generation patterns.
    code = (
        "def adjust(value):\n"
        "    if value < 0:\n"
        "        return 0\n"
        "    return value\n\n"
        "def total(values):\n"
        "    result = 0\n"
        "    for value in values:\n"
        "        result += adjust(value)\n"
        "    return result"
    )
    assert check_code_safety(code, "total").is_safe


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        ("def main():\n    while True:\n        pass", "While"),
        ("def main():\n    return [x for x in range(3)]", "ListComp"),
        ("def main():\n    return lambda x: x", "Lambda"),
        ("print('side effect')\ndef main():\n    return 1", "Top-level Expr"),
        ("def main():\n    return unknown()", "Call to 'unknown'"),
    ],
)
def test_rejects_unsupported_constructs(code: str, expected: str) -> None:
    # Each case represents syntax outside the deliberately narrow safe subset.
    result = check_code_safety(code, "main")
    assert not result.is_safe
    assert any(expected in error for error in result.errors)


def test_rejects_decorated_functions() -> None:
    result = check_code_safety("@staticmethod\ndef main():\n    return 1", "main")
    assert not result.is_safe
    assert any("Decorators" in error for error in result.errors)
