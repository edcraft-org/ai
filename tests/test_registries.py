import pytest

from edcraft_validator.domains import domain_registry
from edcraft_validator.domains.code.code_domain import CodeDomain
from edcraft_validator.domains.domain_registry import available_domains, create_domain
from edcraft_validator.llm.llm_contracts import TemplateProviderSelection
from edcraft_validator.llm.provider_registry import (
    available_model_providers,
    create_model_provider,
)
from edcraft_validator.mcp.catalogue import resolve_domain_tools
from edcraft_validator.mcp.client import FastMcpToolClient


def test_registry_exposes_builtin_template_providers() -> None:
    assert {"openai", "ollama", "soclaas"} <= set(available_model_providers())
    selection = TemplateProviderSelection(provider="ollama")
    assert create_model_provider(selection).provider == "ollama"


def test_registry_passes_explicit_model_to_provider() -> None:
    selection = TemplateProviderSelection(provider="ollama", model="qwen-test")

    generator = create_model_provider(selection)

    assert generator.model == "qwen-test"


def test_registry_rejects_unknown_model_provider() -> None:
    with pytest.raises(ValueError, match="Unsupported model provider"):
        create_model_provider(TemplateProviderSelection(provider="missing"))


def test_domain_registry_exposes_code_without_changing_the_application() -> None:
    assert "code" in available_domains()
    domain = create_domain("code")
    assert isinstance(domain, CodeDomain)
    assert domain.request_model is not None
    assert domain.candidate_model is not None
    assert domain.validated_model is not None
    assert domain.question_model is not None
    assert domain.template_language == "python"


def test_domain_registry_can_register_and_unregister_a_domain() -> None:
    class StubDomain(CodeDomain):
        name = "stub"

    assert "stub" not in available_domains()
    domain_registry.register_domain("stub", StubDomain)

    assert "stub" in available_domains()
    assert isinstance(create_domain("stub"), StubDomain)

    domain_registry.unregister_domain("stub")

    assert "stub" not in available_domains()


def test_domain_registry_rejects_invalid_or_duplicate_registrations() -> None:
    class StubDomain(CodeDomain):
        name = "stub"

    with pytest.raises(ValueError, match="Invalid domain name"):
        domain_registry.register_domain("Stub Domain", StubDomain)
    with pytest.raises(ValueError, match="already registered"):
        domain_registry.register_domain("code", StubDomain)
    with pytest.raises(ValueError, match="is not registered"):
        domain_registry.unregister_domain("missing-test-domain")


def test_domain_registry_rejects_unknown_domain() -> None:
    with pytest.raises(ValueError, match="Unsupported domain"):
        create_domain("unregistered-test-domain")


def test_domain_factory_key_error_is_not_reported_as_unknown_domain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def broken_factory():
        raise KeyError("internal factory failure")

    monkeypatch.setitem(domain_registry._DOMAIN_FACTORIES, "broken", broken_factory)

    with pytest.raises(KeyError, match="internal factory failure"):
        create_domain("broken")


@pytest.mark.parametrize("domain_name", available_domains())
def test_every_registered_domain_has_tagged_mcp_tools(domain_name: str) -> None:
    with FastMcpToolClient() as client:
        tools = resolve_domain_tools(domain_name, client)

    assert tools
