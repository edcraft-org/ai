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


def test_evaluate_cli_writes_attempts_and_prints_summary(
    monkeypatch, capsys, tmp_path
) -> None:
    captured: dict[str, object] = {}
    output = tmp_path / "attempts.jsonl"

    class Summary:
        failed = 0

        def model_dump_json(self, *, indent: int) -> str:
            assert indent == 2
            return json.dumps({"attempts": 2, "approved": 2, "failed": 0})

    class Report:
        summary = Summary()

        def write_jsonl(self, path):
            captured["output"] = path

    class StubEvaluator:
        def evaluate(self, **kwargs):
            captured.update(kwargs)
            return Report()

    monkeypatch.setattr(template_cli, "TemplateEvaluator", StubEvaluator)
    monkeypatch.setattr(template_cli, "load_dotenv", lambda: None)
    monkeypatch.setattr(
        "sys.argv",
        [
            "edcraft-template",
            "evaluate",
            "--provider",
            "ollama",
            "--model",
            "qwen-test",
            "--topic",
            "loops",
            "--difficulty",
            "beginner",
            "--repetitions",
            "2",
            "--output",
            str(output),
        ],
    )

    exit_code = template_cli.main()

    assert exit_code == 0
    assert captured["provider"] == "ollama"
    assert captured["model"] == "qwen-test"
    assert captured["topics"] == ("loops",)
    assert captured["difficulties"] == ("beginner",)
    assert captured["repetitions"] == 2
    assert captured["output"] == output
    assert json.loads(capsys.readouterr().out) == {
        "attempts": 2,
        "approved": 2,
        "failed": 0,
    }
