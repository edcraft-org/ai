"""Deterministic topic registry: school first, then university."""

from __future__ import annotations

from edcraft_validator.domains.math.topics.base import TopicGenerator, TopicStage
from edcraft_validator.domains.math.topics.derivative import DerivativeTopic
from edcraft_validator.domains.math.topics.determinant import DeterminantTopic
from edcraft_validator.domains.math.topics.linear_system import LinearSystemTopic
from edcraft_validator.domains.math.topics.percentage import PercentageTopic
from edcraft_validator.domains.math.topics.quadratic import QuadraticTopic

_TOPICS: tuple[TopicGenerator, ...] = (
    PercentageTopic(),
    QuadraticTopic(),
    LinearSystemTopic(),
    DerivativeTopic(),
    DeterminantTopic(),
)


def all_topics() -> tuple[TopicGenerator, ...]:
    """Every registered topic in stable display order."""
    return _TOPICS


def get_topic(topic_id: str) -> TopicGenerator:
    """Look up a topic by id. Unknown ids raise ``KeyError``."""
    for topic in _TOPICS:
        if topic.topic_id == topic_id:
            return topic
    raise KeyError(topic_id)


def topics_by_stage(stage: TopicStage) -> tuple[TopicGenerator, ...]:
    """Topics for one curriculum stage, preserving registry order."""
    return tuple(topic for topic in _TOPICS if topic.stage == stage)


def topic_ids() -> tuple[str, ...]:
    """Stable ids in registry order."""
    return tuple(topic.topic_id for topic in _TOPICS)
