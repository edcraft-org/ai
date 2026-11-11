"""Small constants and type aliases for the linear-equation math domain."""

from __future__ import annotations

from typing import Literal, get_args

from edcraft_validator.validation.check_names import TEMPLATE_RELEVANCE_CHECK

Difficulty = Literal["easy", "medium", "hard"]

MATH_DIFFICULTIES: tuple[Difficulty, ...] = get_args(Difficulty)

MathParameterName = Literal["a", "b", "c"]

MATH_PARAMETER_NAMES: tuple[str, ...] = get_args(MathParameterName)

MATH_VARIABLE_NAME = "x"

MIN_PARAMETER_VALUES = 1
MAX_PARAMETER_VALUES = 6
MIN_PARAMETER_VALUE = -100
MAX_PARAMETER_VALUE = 100

MIN_DISTRACTORS = 1
DEFAULT_DISTRACTORS = 3
# Shared authoring controls advertise one distractor range across domains.
MAX_DISTRACTORS = 10
MAX_DISTRACTOR_CANDIDATES = 12
MIN_CHOICES = MIN_DISTRACTORS + 1
MAX_CHOICES = MAX_DISTRACTORS + 1

MAX_PROMPT_LENGTH = 4000
MAX_EQUATION_TEMPLATE_LENGTH = 500
MAX_QUESTION_TEMPLATE_LENGTH = 2000
MAX_EXPRESSION_LENGTH = 500
MAX_REASON_TEMPLATE_LENGTH = 1000

MATH_STRUCTURE_TOOL = "math_verify_template_structure"
MATH_ANSWERS_TOOL = "math_validate_answers_and_distractors"
MATH_DIFFICULTY_TOOL = "math_assess_template_difficulty"

# Domain-owned advisory identities. Application policy never derives these from
# untrusted tool evidence or model arguments. Relevance is a shared check the
# math domain opts into by capability, so its identifier is imported rather
# than duplicated.
MATH_ADVISORY_CHECK_NAMES = frozenset({MATH_DIFFICULTY_TOOL, TEMPLATE_RELEVANCE_CHECK})

MATH_CHECKING_MODE = "exhaustive_domain"
MATH_VALIDATOR_VERSION = "mcp-math-template-v1"
MATH_TOOL_VERSION = "1.0.0"
MATH_FORMAT_VERSION = "1.0.0"
