"""Safe pilot exceptions mapped by the backend to HTTP 404/409/422."""

from __future__ import annotations


class PilotError(Exception):
    """Base class for pilot failures with a safe, user-facing message."""


class PilotNotFound(PilotError):
    """The owner-scoped artifact does not exist, or belongs to another owner."""


class PilotConflict(PilotError):
    """The request conflicts with immutable state or an approval requirement."""


class PilotInputError(PilotError):
    """The request or provider proposal is outside the supported pilot scope."""


__all__ = ["PilotConflict", "PilotError", "PilotInputError", "PilotNotFound"]
