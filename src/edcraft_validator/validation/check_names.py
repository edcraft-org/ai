"""Stable identifiers for checks shared across question domains.

A shared check is offered to a domain through a capability tag rather than a
``domain:`` tag. The identifier lives here so domains, tools and the application
can refer to it without importing one another.
"""

TEMPLATE_RELEVANCE_CAPABILITY = "template-relevance"
TEMPLATE_RELEVANCE_CHECK = "assess_template_relevance"
