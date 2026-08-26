from edcraft_validator.comparison import equivalent


def test_numeric_equivalence_uses_tolerance() -> None:
    # Binary floating-point arithmetic does not represent 0.1 or 0.2 exactly.
    assert equivalent(0.1 + 0.2, 0.3)


def test_bool_is_not_equivalent_to_integer() -> None:
    # Python considers True == 1, but they represent different answer types.
    assert not equivalent(True, 1)


def test_nested_values_are_compared() -> None:
    # Numeric tolerance should apply recursively inside structured answers.
    assert equivalent({"values": [1, 2.0]}, {"values": [1.0, 2]})


def test_different_nested_values_are_not_equivalent() -> None:
    assert not equivalent({"values": [1, 2]}, {"values": [1, 3]})


def test_lists_of_different_lengths_are_not_equivalent() -> None:
    assert not equivalent([1, 2], [1, 2, 3])


def test_non_finite_numbers_are_not_equivalent() -> None:
    # NaN must never validate as a stable, JSON-compatible answer.
    assert not equivalent(float("nan"), float("nan"))


def test_different_scalar_types_are_not_equivalent() -> None:
    assert not equivalent("16", 16)

