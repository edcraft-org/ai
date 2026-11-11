"""Small constants and type aliases for the linear-equation math domain."""

from __future__ import annotations

from typing import Literal, get_args

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

MathParameterName = Literal["a", "b", "c"]

MATH_PARAMETER_NAMES: tuple[str, ...] = get_args(MathParameterName)

MATH_VARIABLE_NAME = "x"

MIN_PARAMETER_VALUES = 1
MAX_PARAMETER_VALUES = 6
MIN_PARAMETER_VALUE = -100
MAX_PARAMETER_VALUE = 100

MAX_PROMPT_LENGTH = 4000
MAX_EQUATION_TEMPLATE_LENGTH = 500
MAX_QUESTION_TEMPLATE_LENGTH = 2000
MAX_EXPRESSION_LENGTH = 500
MAX_REASON_TEMPLATE_LENGTH = 1000

MATH_STRUCTURE_TOOL = "math_verify_template_structure"
MATH_ANSWERS_TOOL = "math_validate_answers_and_distractors"
MATH_DIFFICULTY_TOOL = "math_assess_template_difficulty"
MATH_ITEM_SPEC_TOOL = "math_verify_item_spec"
MATH_OPTIONS_TOOL = "math_validate_options"
MATH_FIDELITY_TOOL = "math_verify_text_fidelity"

# Domain-owned advisory identities. Application policy never derives these from
# untrusted tool evidence or model arguments. Relevance is a shared check the
# math domain opts into by capability, so its identifier is imported rather
# than duplicated.
MATH_ADVISORY_CHECK_NAMES = frozenset({MATH_DIFFICULTY_TOOL, TEMPLATE_RELEVANCE_CHECK})

MATH_CHECKING_MODE = "exhaustive_domain"
MATH_VALIDATOR_VERSION = "mcp-math-template-v1"
MATH_TOOL_VERSION = "1.0.0"
MATH_IR_TOOL_VERSION = "1.1.0"
MATH_FORMAT_VERSION = "1.0.0"
