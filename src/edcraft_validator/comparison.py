import math
from typing import Any


def equivalent(left: Any, right: Any, *, tolerance: float = 1e-9) -> bool:
    """Compare JSON-like answers without treating booleans as integers."""
    if isinstance(left, bool) or isinstance(right, bool):
        return type(left) is type(right) and left == right

    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        if not (math.isfinite(float(left)) and math.isfinite(float(right))):
            return False
        return math.isclose(
            float(left), float(right), rel_tol=tolerance, abs_tol=tolerance
        )

    if isinstance(left, list) and isinstance(right, list):
        return len(left) == len(right) and all(
            equivalent(a, b, tolerance=tolerance)
            for a, b in zip(left, right, strict=True)
        )

    if isinstance(left, dict) and isinstance(right, dict):
        return left.keys() == right.keys() and all(
            equivalent(left[key], right[key], tolerance=tolerance) for key in left
        )

    return type(left) is type(right) and left == right
