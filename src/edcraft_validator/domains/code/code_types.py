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


Difficulty = Literal["beginner", "intermediate", "advanced"]


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


ParameterValue = int | bool | str | list[int]
