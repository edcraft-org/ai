"""Deterministic seed derivation for coefficient-based pilot cases."""

from __future__ import annotations


def coefficient_seed(
    seed: int,
    coefficients: tuple[int, ...],
    *,
    salt: int = 0,
) -> int:
    """Derive a stable case seed from an assignment without hashing strings."""
    value = (seed + salt) & 0x7FFF_FFFF
    for coefficient in coefficients:
        value = (value * 131 + coefficient + 10_007) & 0xFFFF_FFFF_FFFF_FFFF
    return value


__all__ = ["coefficient_seed"]
