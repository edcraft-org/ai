import json

from edcraft_validator import template as template_cli


def test_author_cli_passes_explicit_provider_and_model(monkeypatch, capsys) -> None:
    captured: dict[str, object] = {}

    class Result:
        def model_dump(self, *, mode: str) -> dict[str, bool]:
            assert mode == "json"
            return {"approved": True}

    class StubApplication:
        def author(self, request, *, provider, model):
            captured.update(request=request, provider=provider, model=model)
            return Result()

    monkeypatch.setattr(template_cli, "QuestionTemplateApplication", StubApplication)
    monkeypatch.setattr(template_cli, "load_dotenv", lambda: None)
    monkeypatch.setattr(
        "sys.argv",
        [
            "edcraft-template",
            "author",
            "--provider",
            "ollama",
            "--model",
            "qwen-test",
            "--topic",
            "loops",
            "--difficulty",
            "advanced",
        ],
    )

    exit_code = template_cli.main()

    assert exit_code == 0
    assert captured["provider"] == "ollama"
    assert captured["model"] == "qwen-test"
    request = captured["request"]
    assert request.topic == "loops"
    assert request.difficulty == "advanced"
    assert json.loads(capsys.readouterr().out) == {"approved": True}
