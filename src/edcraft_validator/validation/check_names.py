"""Stable identifiers for checks shared across question domains.

A shared check is offered to a domain through a capability tag rather than a
``domain:`` tag. The identifier lives here so domains, tools and the application
can refer to it without importing one another.
"""

TEMPLATE_RELEVANCE_CAPABILITY = "template-relevance"
TEMPLATE_RELEVANCE_CHECK = "assess_template_relevance"
TEMPLATE_RELEVANCE_TOOL_VERSION = "1.0.0"

TEMPLATE_DIFFICULTY_CAPABILITY = "difficulty"
TEMPLATE_DIFFICULTY_CHECK = "assess_template_difficulty"
TEMPLATE_DIFFICULTY_TOOL_VERSION = "2.0.0"
