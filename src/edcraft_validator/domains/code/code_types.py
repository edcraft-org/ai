"""Small type aliases and supported topic names for the code domain."""

from __future__ import annotations

from typing import Literal, get_args

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


Difficulty = Literal["easy", "medium", "hard"]


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


CODE_DIFFICULTIES: tuple[Difficulty, ...] = get_args(Difficulty)


# Learner-facing choice count is distractors + 1. The default keeps the familiar
# four choices, while authors may request any supported count.
MIN_DISTRACTORS = 1
DEFAULT_DISTRACTORS = 3
MAX_DISTRACTORS = 10
MIN_CHOICES = MIN_DISTRACTORS + 1
MAX_CHOICES = MAX_DISTRACTORS + 1

# Models may propose spare candidates so selection can skip collisions. Keep
# enough headroom for the largest supported request plus a couple of spares.
MAX_DISTRACTOR_CANDIDATES = 12

# Domain-owned advisory identities. Application policy never derives this from
# untrusted tool evidence or model arguments.
CODE_ADVISORY_CHECK_NAMES = frozenset(
    {"code_assess_template_difficulty", "code_assess_template_relevance"}
)


ParameterValue = int | bool | str | list[int]
