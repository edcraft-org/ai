"""Domain-neutral difficulty rubric records and their registry.

A domain owns its rubric document, prompt components and dimensions model. The
record keeps those parts together so the shared judging cascade can build the
same decision and reasoning requests for every domain. Domains register their
record when their tools are registered, and the shared MCP tool looks it up by
identifier.
"""

import hashlib
import re
from dataclasses import dataclass
from importlib import import_module
from importlib.resources import files
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, StringConstraints

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class DifficultyRecord(BaseModel):
    """Closed, strict base shared by every difficulty response model."""

    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class DimensionAssessment(DifficultyRecord):
    rating: Literal["low", "moderate", "high", "unknown"]
    reason: Text


@dataclass(frozen=True)
class DifficultyRubric:
    """One domain's rubric document together with its prompt components.

    ``reference`` is the rubric text the judge sees: the dimension and level
    tables plus the worked anchors, extracted by the owning domain. ``text`` is
    the unchanged document, so ``sha256`` identifies the reviewed file.
    """

    rubric_id: str
    text: str
    version: str
    assessment_conditions_version: str
    scope: str
    reasoning_procedure: str
    reference: str
    dimensions_model: type[BaseModel]
    reasoning_prompt_version: str
    decision_prompt_version: str
    reasoning_schema_name: str
    decision_schema_name: str

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.text.encode()).hexdigest()


_RUBRIC_ID = re.compile(r"^[a-z][a-z0-9.-]*$")
_VERSION = re.compile(r"^Rubric version: `([^`]+)`", re.MULTILINE)
_CONDITIONS = re.compile(
    r"^Assessment conditions version: `([^`]+)`",
    re.MULTILINE,
)
_RUBRICS: dict[str, DifficultyRubric] = {}


def register_difficulty_rubric(rubric: DifficultyRubric) -> None:
    """Register one domain rubric for the shared difficulty cascade."""
    if not _RUBRIC_ID.fullmatch(rubric.rubric_id):
        raise ValueError(f"Invalid difficulty rubric id {rubric.rubric_id!r}.")
    existing = _RUBRICS.get(rubric.rubric_id)
    if existing is not None:
        if existing != rubric:
            raise ValueError(
                f"A different difficulty rubric is already registered as "
                f"{rubric.rubric_id!r}."
            )
        return

    _RUBRICS[rubric.rubric_id] = rubric


def ensure_difficulty_rubric(rubric_id: str) -> None:
    """Load a domain's rubric on demand when no server registered it yet."""
    if rubric_id in _RUBRICS or not _RUBRIC_ID.fullmatch(rubric_id):
        return

    module_name = f"edcraft_validator.domains.{rubric_id}.difficulty"
    function_name = f"load_{rubric_id.replace('-', '_')}_difficulty_rubric"
    try:
        loader = getattr(import_module(module_name), function_name)
    except (ImportError, AttributeError):
        return
    register_difficulty_rubric(loader())


def difficulty_rubric(rubric_id: str) -> DifficultyRubric:
    ensure_difficulty_rubric(rubric_id)
    try:
        return _RUBRICS[rubric_id]
    except KeyError as exc:
        supported = ", ".join(available_difficulty_rubrics()) or "none"
        raise ValueError(
            f"Unsupported difficulty rubric {rubric_id!r}. Registered: {supported}"
        ) from exc


def available_difficulty_rubrics() -> tuple[str, ...]:
    """Return the registered rubric identifiers in registration order."""
    return tuple(_RUBRICS)


def load_rubric_document(
    *,
    package: str,
    bundled_name: str,
    source: Path,
) -> tuple[str, str, str]:
    """Read a rubric document and its declared versions.

    The wheel bundles the same document used for source-tree review records, so
    the packaged copy is preferred and the source checkout is the fallback.
    """
    resource = files(package).joinpath(bundled_name)
    if resource.is_file():
        text = resource.read_bytes().decode("utf-8")
    else:
        text = source.read_bytes().decode("utf-8")

    version = _VERSION.search(text)
    conditions = _CONDITIONS.search(text)
    if version is None or conditions is None:
        raise ValueError("rubric must declare versions")
    return text, version[1], conditions[1]


def format_rubric_reference(
    *,
    dimensions: str,
    levels: str,
    anchors: tuple[tuple[str, str], ...],
) -> str:
    """Render the rubric extracts in the order the judge prompts expect."""
    return (
        "Dimensions (unchanged):\n| Dimension | Low | Moderate | High |\n"
        + dimensions
        + "\n\nLevels (unchanged):\n| Level | Anchor description |\n"
        + levels
        + "\n\nExisting worked anchors, training material only:\n\n"
        + "\n\n".join(f"### {level}\n{anchor}" for level, anchor in anchors)
    )
