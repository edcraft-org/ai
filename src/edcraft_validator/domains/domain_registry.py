"""Registry of available question domains."""

import re
from collections.abc import Callable

from edcraft_validator.domains.code.code_domain import CodeDomain
from edcraft_validator.domains.domain_contract import DomainModule

DomainFactory = Callable[[], DomainModule]

_DOMAIN_NAME = re.compile(r"^[a-z][a-z0-9_-]*$")
_DOMAIN_FACTORIES: dict[str, DomainFactory] = {"code": CodeDomain}


def available_domains() -> tuple[str, ...]:
    """Return the registered domain names in registration order."""
    return tuple(_DOMAIN_FACTORIES)


def register_domain(name: str, factory: DomainFactory) -> None:
    """Register a domain factory.

    Used by applications and tests that add an out-of-tree domain. Registration
    is explicit so shared orchestration never has to know domain names.
    """
    if not _DOMAIN_NAME.fullmatch(name):
        raise ValueError(f"Invalid domain name {name!r}.")
    if name in _DOMAIN_FACTORIES:
        raise ValueError(f"Domain {name!r} is already registered.")
    _DOMAIN_FACTORIES[name] = factory


def unregister_domain(name: str) -> None:
    """Remove a previously registered domain factory."""
    try:
        del _DOMAIN_FACTORIES[name]
    except KeyError as exc:
        raise ValueError(f"Domain {name!r} is not registered.") from exc


def create_domain(name: str) -> DomainModule:
    try:
        factory = _DOMAIN_FACTORIES[name]
    except KeyError as exc:
        supported = ", ".join(available_domains())
        raise ValueError(
            f"Unsupported domain {name!r}; choose one of: {supported}"
        ) from exc
    return factory()
