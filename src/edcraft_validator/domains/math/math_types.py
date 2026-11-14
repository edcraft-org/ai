"""Small constants and type aliases for the math domain."""

from __future__ import annotations

from typing import Literal

# Explicit re-exports: these names remain importable from this module even
# though the single definition now lives in the shared vocabulary module.
from edcraft_validator.domain_types import (
    DEFAULT_DISTRACTORS as DEFAULT_DISTRACTORS,
)
from edcraft_validator.domain_types import (
    DIFFICULTIES as DIFFICULTIES,
)
from edcraft_validator.domain_types import (
    MAX_CHOICES as MAX_CHOICES,
)
from edcraft_validator.domain_types import (
    MAX_DISTRACTOR_CANDIDATES as MAX_DISTRACTOR_CANDIDATES,
)
from edcraft_validator.domain_types import (
    MAX_DISTRACTORS as MAX_DISTRACTORS,
)
from edcraft_validator.domain_types import (
    MIN_CHOICES as MIN_CHOICES,
)
from edcraft_validator.domain_types import (
    MIN_DISTRACTORS as MIN_DISTRACTORS,
)
from edcraft_validator.domain_types import (
    Difficulty as Difficulty,
)
from edcraft_validator.validation.check_names import TEMPLATE_RELEVANCE_CHECK

MATH_DIFFICULTIES: tuple[Difficulty, ...] = DIFFICULTIES

MAX_PROMPT_LENGTH = 4000

# Sample budget for bounded property-based validation of a template's declared
# parameter domain. The schema does not cap the domain itself; only this many
# deterministic variants (boundary cases plus generated examples) are graded.
MAX_IR_VARIANTS = 100

MATH_DIFFICULTY_TOOL = "math_assess_template_difficulty"
MATH_ITEM_SPEC_TOOL = "math_verify_item_spec"
MATH_OPTIONS_TOOL = "math_validate_options"
MATH_FIDELITY_TOOL = "math_verify_text_fidelity"

# Domain-owned advisory identities. Application policy never derives these from
# untrusted tool evidence or model arguments. Relevance is a shared check the
# math domain opts into by capability, so its identifier is imported rather
# than duplicated.
MATH_ADVISORY_CHECK_NAMES = frozenset({MATH_DIFFICULTY_TOOL, TEMPLATE_RELEVANCE_CHECK})

MATH_CHECKING_MODE: Literal["property_based"] = "property_based"
MATH_VALIDATOR_VERSION: Literal["mcp-math-template-v1"] = "mcp-math-template-v1"
MATH_TOOL_VERSION = "1.0.0"
MATH_IR_TOOL_VERSION = "1.1.0"
MATH_FORMAT_VERSION: Literal["1.0.0"] = "1.0.0"

# Retired public identifier, retained as a constant alias so downstream imports
# keep working. It is read-compatibility only; new evidence uses the shared
# relevance check name.
LEGACY_MATH_RELEVANCE_TOOL = "math_assess_template_relevance"
