import pytest

from edcraft_validator.tools.python_analysis import analyze_python_subset


def test_accepts_simple_function() -> None:
    # A basic pure function is the minimum supported safe-code case.
    result = analyze_python_subset("def double(x):\n    return x * 2", "double")
    assert result.is_valid


def test_rejects_import_and_attribute_access() -> None:
    # Both the import and os.getcwd attribute call violate the supported subset.
    result = analyze_python_subset(
        "import os\ndef bad():\n    return os.getcwd()",
        "bad",
    )
    assert not result.is_valid
    assert any("Import" in error for error in result.errors)
    assert any("Attribute" in error for error in result.errors)


def test_rejects_missing_entry_function() -> None:
    # Execution is unsafe when the requested entry point is absent.
    result = analyze_python_subset("def other():\n    return 1", "main")
    assert not result.is_valid
    assert any("not defined" in error for error in result.errors)


def test_rejects_recursion() -> None:
    # Recursion is blocked to keep generated execution bounded and predictable.
    result = analyze_python_subset(
        "def countdown(n):\n    return 0 if n == 0 else countdown(n - 1)",
        "countdown",
    )
    assert not result.is_valid
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
    assert analyze_python_subset(code, "total").is_valid


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
    result = analyze_python_subset(code, "main")
    assert not result.is_valid
    assert any(expected in error for error in result.errors)


def test_rejects_decorated_functions() -> None:
    # Decorators can alter execution semantics and are outside the safe subset.
    result = analyze_python_subset("@staticmethod\ndef main():\n    return 1", "main")
    assert not result.is_valid
    assert any("Decorators" in error for error in result.errors)


def test_rejects_oversized_integer_literals() -> None:
    result = analyze_python_subset(
        "def allocate():\n    return [0] * 100000000", "allocate"
    )

    assert not result.is_valid
    assert any("Integer literal exceeds" in error for error in result.errors)
