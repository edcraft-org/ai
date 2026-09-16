import json

import pytest

from edcraft_validator import cli as template_cli
from edcraft_validator.domains.code.module import CodeDomain


@pytest.mark.parametrize("command", ["validate", "generate"])
def test_local_cli_commands_pass_domain_without_creating_provider(
    command, monkeypatch, tmp_path, capsys
):
    from types import SimpleNamespace

    parsed = object()
    calls = []
    source = tmp_path / "template.json"
    source.write_text('{"value": 7}')

    class Model:
        @staticmethod
        def model_validate_json(content):
            assert json.loads(content) == {"value": 7}
            return parsed

    domain = SimpleNamespace(candidate_model=Model, validated_model=Model)

    class Result:
        def model_dump(self, *, mode):
            return {"success": True}

    class Application:
        def validate_template(self, candidate, *, domain):
            calls.append((candidate, domain))
            return Result()

        def generate_question(self, validated, *, domain, seed):
            assert seed == 7
            calls.append((validated, domain))
            return Result()

    def unexpected_provider(*args):
        pytest.fail("Local template commands must not create a model provider")

    monkeypatch.setattr(template_cli, "create_domain", lambda name: domain)
    monkeypatch.setattr(template_cli, "create_model_provider", unexpected_provider)
    monkeypatch.setattr(template_cli, "TemplateApplication", Application)
    monkeypatch.setattr(template_cli, "load_dotenv", lambda: None)
    args = ["edcraft-template", command, "--domain", "code", str(source)]
    if command == "generate":
        args += ["--seed", "7"]
    monkeypatch.setattr("sys.argv", args)

    assert template_cli.main() == 0
    assert calls == [(parsed, domain)]
    assert json.loads(capsys.readouterr().out) == {"success": True}


def test_author_cli_passes_explicit_provider_and_model(monkeypatch, capsys) -> None:
    captured: dict[str, object] = {}

    class Result:
        def model_dump(self, *, mode: str) -> dict[str, bool]:
            assert mode == "json"
            return {"validated": True}

    class StubApplication:
        def create_validated_template(self, request, *, domain, provider):
            captured.update(request=request, domain=domain, provider=provider)
            return Result()

    provider = object()

    def create_provider(selection):
        captured["selection"] = selection
        return provider

    monkeypatch.setattr(template_cli, "create_model_provider", create_provider)
    monkeypatch.setattr(template_cli, "TemplateApplication", StubApplication)
    monkeypatch.setattr(template_cli, "load_dotenv", lambda: None)
    monkeypatch.setattr(
        "sys.argv",
        [
            "edcraft-template",
            "author",
            "--domain",
            "code",
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
    assert captured["provider"] is provider
    assert isinstance(captured["domain"], CodeDomain)
    assert captured["selection"].provider == "ollama"
    assert captured["selection"].model == "qwen-test"
    request = captured["request"]
    assert request.topic == "loops"
    assert request.difficulty == "advanced"
    assert json.loads(capsys.readouterr().out) == {"validated": True}


def test_evaluate_cli_writes_attempts_and_prints_summary(
    monkeypatch, capsys, tmp_path
) -> None:
    captured: dict[str, object] = {}
    output = tmp_path / "attempts.jsonl"

    class Summary:
        failed = 0

        def model_dump_json(self, *, indent: int) -> str:
            assert indent == 2
            return json.dumps({"attempts": 2, "validated": 2, "failed": 0})

    class Report:
        summary = Summary()

    class Attempt:
        attempt = 1
        status = "validated"
        total_duration_ms = 1250.0

        class Request:
            topic = "loops"
            difficulty = "beginner"

        request = Request()

        def model_dump_json(self):
            return json.dumps({"attempt": self.attempt, "status": "validated"})

    class StubEvaluator:
        def evaluate(self, **kwargs):
            captured.update(kwargs)
            for number in range(1, kwargs["repetitions"] + 1):
                attempt = Attempt()
                attempt.attempt = number
                kwargs["on_attempt"](attempt)
            return Report()

    monkeypatch.setattr(template_cli, "TemplateEvaluator", StubEvaluator)
    monkeypatch.setattr(template_cli, "load_dotenv", lambda: None)
    monkeypatch.setattr(
        "sys.argv",
        [
            "edcraft-template",
            "evaluate",
            "--domain",
            "code",
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
    assert [json.loads(line) for line in output.read_text().splitlines()] == [
        {"attempt": 1, "status": "validated"},
        {"attempt": 2, "status": "validated"},
    ]
    captured_output = capsys.readouterr()
    assert "[1] loops/beginner: validated (1.2s)" in captured_output.err
    assert "[2] loops/beginner: validated (1.2s)" in captured_output.err
    assert json.loads(captured_output.out) == {
        "attempts": 2,
        "validated": 2,
        "failed": 0,
    }
