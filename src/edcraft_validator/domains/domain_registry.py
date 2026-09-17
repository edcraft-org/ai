"""Registry of available question domains."""

from collections.abc import Callable

from edcraft_validator.domains.code.code_domain import CodeDomain
from edcraft_validator.domains.domain_contract import DomainModule

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
