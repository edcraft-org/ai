from edcraft_validator.comparison import equivalent


def test_numeric_equivalence_uses_tolerance() -> None:
    assert equivalent(0.1 + 0.2, 0.3)


def test_bool_is_not_equivalent_to_integer() -> None:
    assert not equivalent(True, 1)


def test_nested_values_are_compared() -> None:
    assert equivalent({"values": [1, 2.0]}, {"values": [1.0, 2]})

