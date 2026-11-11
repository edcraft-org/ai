"""Deterministic school and university math topic generators."""

from edcraft_validator.domains.math.topics.base import TopicGenerator, TopicStage
from edcraft_validator.domains.math.topics.derivative import DerivativeTopic
from edcraft_validator.domains.math.topics.determinant import DeterminantTopic
from edcraft_validator.domains.math.topics.linear_system import LinearSystemTopic
from edcraft_validator.domains.math.topics.percentage import PercentageTopic
from edcraft_validator.domains.math.topics.quadratic import QuadraticTopic
from edcraft_validator.domains.math.topics.registry import (
    all_topics,
    get_topic,
    topic_ids,
    topics_by_stage,
)

__all__ = [
    "DerivativeTopic",
    "DeterminantTopic",
    "LinearSystemTopic",
    "PercentageTopic",
    "QuadraticTopic",
    "TopicGenerator",
    "TopicStage",
    "all_topics",
    "get_topic",
    "topic_ids",
    "topics_by_stage",
]
