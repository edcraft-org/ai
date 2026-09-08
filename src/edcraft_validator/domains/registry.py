"""Registry of available question domains."""

from collections.abc import Callable

from edcraft_validator.domains.base import DomainModule
from edcraft_validator.domains.code.module import CodeDomain

DomainFactory = Callable[[], DomainModule]

_DOMAIN_FACTORIES: dict[str, DomainFactory] = {"code": CodeDomain}


def available_domains() -> tuple[str, ...]:
    return tuple(_DOMAIN_FACTORIES)


def create_domain(name: str) -> DomainModule:
    try:
        return _DOMAIN_FACTORIES[name]()
    except KeyError as exc:
        supported = ", ".join(available_domains())
        raise ValueError(
            f"Unsupported domain {name!r}; choose one of: {supported}"
        ) from exc
