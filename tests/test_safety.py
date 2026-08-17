from edcraft_validator.safety import check_code_safety


def test_accepts_simple_function() -> None:
    result = check_code_safety("def double(x):\n    return x * 2", "double")
    assert result.is_safe


def test_rejects_import_and_attribute_access() -> None:
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

