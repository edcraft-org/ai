"""Shared judge configuration used by every difficulty request."""


def test_judge_provider_and_model_follow_shared_configuration(monkeypatch):
    from edcraft_validator.llm import judge_configuration

    selected = []
    monkeypatch.delenv("EDCRAFT_JUDGE_PROVIDER", raising=False)
    monkeypatch.delenv("EDCRAFT_JUDGE_MODEL", raising=False)
    monkeypatch.setattr(
        judge_configuration,
        "create_model_provider",
        lambda settings: selected.append(settings) or object(),
    )

    judge_configuration.configured_judge_provider()
    assert selected[0].provider == "soclaas"
    assert selected[0].model == "x-test-3"

    for name in ("openai", "ollama"):
        monkeypatch.setenv("EDCRAFT_JUDGE_PROVIDER", name)
        monkeypatch.setenv("EDCRAFT_JUDGE_MODEL", "configured-model")
        judge_configuration.configured_judge_provider()
        assert selected[-1].provider == name
        assert selected[-1].model == "configured-model"
