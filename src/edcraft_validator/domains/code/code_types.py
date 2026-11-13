"""Small type aliases and supported topic names for the code domain."""

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

AnswerTarget = Literal[
    "return_value",
    "loop_iterations",
    "loop_executions",
    "branch_executions",
    "function_calls",
]


ProgrammingTopic = Literal[
    "arithmetic",
    "conditionals",
    "loops",
    "functions",
    "lists",
]


ParameterKind = Literal["integer", "boolean", "string", "integer_list"]


AnswerKind = Literal["number", "integer", "integer_list"]


CodeFeature = Literal[
    "arithmetic",
    "conditional",
    "early_return",
    "helper_function",
    "list_aggregate",
    "list_index",
    "list_sort",
    "loop",
    "nested_conditional",
    "nested_helper",
    "nested_loop",
    "sequential_conditionals",
    "sequential_loops",
]


CODE_TOPICS: tuple[ProgrammingTopic, ...] = get_args(ProgrammingTopic)


CODE_DIFFICULTIES: tuple[Difficulty, ...] = DIFFICULTIES


# Concrete MCQs use the fixed A-D option schema, so they support only the
# three- and four-choice forms. Template authoring has the wider range above.
MIN_CONCRETE_DISTRACTORS = 2
MAX_CONCRETE_DISTRACTORS = 3

# Domain-owned advisory identities. Application policy never derives this from
# untrusted tool evidence or model arguments.
CODE_ADVISORY_CHECK_NAMES = frozenset(
    {"code_assess_template_difficulty", "code_assess_template_relevance"}
)


ParameterValue = int | bool | str | list[int]
