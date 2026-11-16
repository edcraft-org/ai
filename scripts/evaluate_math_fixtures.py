"""Run the frozen mathematics fixtures through the production checks offline.

Every fixture is a complete math template candidate with a small header that
declares its category and expected outcome. The runner applies the same
deterministic checks the application uses: the item spec, the option checks,
prose anchors and equivalence, and the answer form for factor and expand goals.
It uses the production sampling budget and seed 0, writes one JSONL record per
fixture, and refuses to pass when a fixture differs from its expectation.

No model, MCP server or network call is made. For prose templates the blind
parse back model is replaced by an identity reconstruction, so only the
deterministic anchor and equivalence path is exercised.
"""

from __future__ import annotations

import argparse
import json
import socket
import time
from collections import Counter
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from pydantic import ValidationError

from edcraft_validator.application.fidelity import engine as fidelity_engine
from edcraft_validator.domains.math.candidate_builder import build_math_candidate
from edcraft_validator.domains.math.fidelity import math_fidelity_plugin
from edcraft_validator.domains.math.ir.instantiate import representative_item
from edcraft_validator.domains.math.ir.schema import (
    MathItemSpec,
    MathReconstruction,
    MathTemplateSpec,
)
from edcraft_validator.domains.math.math_schemas import (
    MathTemplateCandidate,
    MathTemplateContent,
    MathTemplateRequest,
    MathValidationSummary,
    ValidatedMathTemplate,
)
from edcraft_validator.domains.math.math_types import (
    FORM_SENSITIVE_GOALS,
    MAX_IR_VARIANTS,
)
from edcraft_validator.domains.math.question_generator import generate_math_question
from edcraft_validator.domains.math.validation.harness import (
    HarnessReport,
    validate_template,
)
from edcraft_validator.llm import judging
from edcraft_validator.mcp import math_tools
from edcraft_validator.tools import isolated_process
from edcraft_validator.validation.validation_contracts import ValidationEvidence

FIXTURES_DIR = (
    Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "math_eval"
)
DEFAULT_OUTPUT = Path(".artifacts/math-fixtures.jsonl")
DETERMINISM_SEEDS = (0, 1, 42)

HEADER_FIELDS = ("id", "category", "expected", "expected_code", "note")
CATEGORIES = ("correct", "incorrect", "equivalent", "unsupported")
EXPECTATIONS = ("pass", "reject")

Category = Literal["correct", "incorrect", "equivalent", "unsupported"]
Expectation = Literal["pass", "reject"]


@dataclass(frozen=True)
class Fixture:
    """One frozen template plus the header that states its expectation."""

    path: Path
    id: str
    category: Category
    expected: Expectation
    expected_code: str | None
    note: str
    template: MathTemplateSpec | None
    schema_error: str | None = None


@dataclass
class FixtureResult:
    """One fixture's observed outcome and the checks that produced it."""

    fixture: Fixture
    actual: Expectation
    matched: bool
    codes: list[str]
    checks: dict[str, dict[str, Any]]
    findings: list[str]
    examples_checked: int
    declared_domain_size: int
    runtime_ms: float
    determinism: dict[str, Any] | None = None
    mismatch_reasons: list[str] = field(default_factory=list)

    def to_record(self) -> dict[str, Any]:
        return {
            "id": self.fixture.id,
            "category": self.fixture.category,
            "expected": self.fixture.expected,
            "expected_code": self.fixture.expected_code,
            "note": self.fixture.note,
            "actual": self.actual,
            "matched": self.matched,
            "codes": self.codes,
            "checks": self.checks,
            "findings": self.findings[:20],
            "examples_checked": self.examples_checked,
            "declared_domain_size": self.declared_domain_size,
            "runtime_ms": round(self.runtime_ms, 3),
            "determinism": self.determinism,
            "mismatch_reasons": self.mismatch_reasons,
        }

    def mismatch_record(self) -> dict[str, Any]:
        return {
            "id": self.fixture.id,
            "category": self.fixture.category,
            "expected": self.fixture.expected,
            "actual": self.actual,
            "expected_code": self.fixture.expected_code,
            "codes": self.codes,
            "reasons": self.mismatch_reasons,
        }


def load_fixtures(directory: Path = FIXTURES_DIR) -> list[Fixture]:
    """Load every JSON fixture in declaration order."""
    paths = sorted(Path(directory).glob("*.json"))
    if not paths:
        raise ValueError(f"no mathematics fixtures found in {directory}")
    return [load_fixture(path) for path in paths]


def load_fixture(path: Path) -> Fixture:
    """Load one fixture and validate its header and template separately."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path.name} must contain a JSON object")

    header = _fixture_header(path, payload)
    body = {key: value for key, value in payload.items() if key not in HEADER_FIELDS}

    template: MathTemplateSpec | None = None
    schema_error: str | None = None
    try:
        template = MathTemplateSpec.model_validate(body)
    except (ValidationError, ValueError) as exc:
        schema_error = f"{type(exc).__name__}: {exc}"

    return Fixture(
        path=path,
        template=template,
        schema_error=schema_error,
        **header,
    )


def _fixture_header(path: Path, payload: dict[str, Any]) -> dict[str, Any]:
    missing = [name for name in HEADER_FIELDS if name not in payload]
    if missing:
        raise ValueError(f"{path.name} is missing header fields: {', '.join(missing)}")

    identifier = payload["id"]
    if identifier != path.stem:
        raise ValueError(
            f"{path.name} declares id {identifier!r}, which does not match its name"
        )
    category = payload["category"]
    if category not in CATEGORIES:
        raise ValueError(f"{path.name} has unknown category {category!r}")
    expected = payload["expected"]
    if expected not in EXPECTATIONS:
        raise ValueError(f"{path.name} has unknown expectation {expected!r}")
    expected_code = payload["expected_code"]
    if expected_code is not None and (
        not isinstance(expected_code, str) or not expected_code.strip()
    ):
        raise ValueError(f"{path.name} has an invalid expected_code")
    if expected == "pass" and expected_code is not None:
        raise ValueError(f"{path.name} expects a pass but declares an expected_code")
    note = payload["note"]
    if not isinstance(note, str) or not note.strip():
        raise ValueError(f"{path.name} requires a note")

    return {
        "id": identifier,
        "category": category,
        "expected": expected,
        "expected_code": expected_code,
        "note": note,
    }


def evaluate_fixture(fixture: Fixture) -> FixtureResult:
    """Run every check the application would require for this template."""
    started = time.perf_counter()
    checks: dict[str, dict[str, Any]] = {}
    findings: list[str] = []
    codes: list[str] = []
    examples_checked = 0
    declared_domain_size = 0
    correctness: HarnessReport | None = None

    if fixture.template is None:
        checks["schema"] = {
            "status": "rejected",
            "codes": ["SCHEMA_INVALID"],
            "findings": [fixture.schema_error or "fixture is not schema valid"],
        }
        findings.extend(checks["schema"]["findings"])
        codes.append("SCHEMA_INVALID")
    else:
        template = fixture.template
        correctness = validate_template(
            template,
            max_variants=MAX_IR_VARIANTS,
            seed=0,
        )
        examples_checked = correctness.examples_checked
        declared_domain_size = correctness.declared_domain_size
        checks["item_spec"] = _check_from_report(correctness, "IR_VALIDATION")
        checks["options"] = _options_check(template, correctness)
        if template.body.goal.kind in FORM_SENSITIVE_GOALS:
            form = validate_template(
                template,
                max_variants=MAX_IR_VARIANTS,
                seed=0,
                aspect="form",
            )
            checks["answer_form"] = _check_from_report(form, "IR_VALIDATION")
        else:
            checks["answer_form"] = _skipped_check("not required for this goal")
        if template.body.text.mode == "prose":
            checks["text_fidelity"] = _fidelity_check(template)
        else:
            checks["text_fidelity"] = _skipped_check("symbolic template")

        for name, check in checks.items():
            if check["status"] != "passed":
                codes.extend(code for code in check["codes"] if code not in codes)
                findings.extend(
                    f"{name}: {finding}" for finding in check.get("findings", [])
                )

    actual: Expectation = (
        "pass"
        if all(check["status"] in {"passed", "skipped"} for check in checks.values())
        else "reject"
    )
    determinism = (
        _determinism_check(fixture.template, correctness) if actual == "pass" else None
    )

    reasons: list[str] = []
    if actual != fixture.expected:
        reasons.append(f"expected {fixture.expected}, observed {actual}")
    if fixture.expected_code is not None and fixture.expected_code not in codes:
        reasons.append(
            f"expected code {fixture.expected_code!r}, observed {sorted(set(codes))}"
        )
    if actual == "pass" and not _deterministic(determinism):
        reasons.append("passing fixture did not expand deterministically offline")

    return FixtureResult(
        fixture=fixture,
        actual=actual,
        matched=not reasons,
        codes=codes,
        checks=checks,
        findings=findings,
        examples_checked=examples_checked,
        declared_domain_size=declared_domain_size,
        runtime_ms=(time.perf_counter() - started) * 1000,
        determinism=determinism,
        mismatch_reasons=reasons,
    )


def _check_from_report(report: HarnessReport, prefix: str) -> dict[str, Any]:
    status = report.report.status
    if status == "passed":
        code = ""
    elif status == "inconclusive":
        code = f"{prefix}_INCONCLUSIVE"
    else:
        code = f"{prefix}_FAILED"
    return {
        "status": "passed" if status == "passed" else "rejected",
        "codes": [code] if code else [],
        "findings": list(report.report.findings),
        "examples_checked": report.examples_checked,
        "declared_domain_size": report.declared_domain_size,
    }


def _options_check(template: MathTemplateSpec, report: HarnessReport) -> dict[str, Any]:
    """Mirror the option tool: it fails whenever the sampled report does."""
    if not template.body.distractors:
        return {
            "status": "rejected",
            "codes": ["NO_OPTIONS"],
            "findings": ["the item declares no distractor options"],
        }

    failed = [
        f"option {option.index}: {option.result.reason}"
        for option in report.report.options
        if option.result.status != "passed"
    ]
    passed = report.report.status == "passed" and not failed
    return {
        "status": "passed" if passed else "rejected",
        "codes": [] if passed else ["OPTION_CHECK_FAILED"],
        "findings": failed or ([] if passed else list(report.report.findings)),
    }


def _skipped_check(reason: str) -> dict[str, Any]:
    return {"status": "skipped", "codes": [], "findings": [], "reason": reason}


def _fidelity_check(template: MathTemplateSpec) -> dict[str, Any]:
    """Run the deterministic part of the fidelity gate without a model."""
    plugin = math_fidelity_plugin()
    authored = template.body
    anchors = plugin.check_anchors(authored, authored.text.template)
    if anchors.status != "passed":
        return _fidelity_result(anchors.status, anchors.reasons, "anchors")

    try:
        concrete = representative_item(template)
        reconstruction = _identity_reconstruction(concrete)
        verdict = plugin.equivalent(concrete, reconstruction)
    except Exception as exc:  # noqa: BLE001 - a broken gate must not pass
        return _fidelity_result(
            "inconclusive",
            [f"fidelity comparison failed: {type(exc).__name__}"],
            "equivalence",
        )

    return _fidelity_result(verdict.status, verdict.reasons, "equivalence")


def _identity_reconstruction(item: MathItemSpec) -> MathReconstruction:
    """The offline stand in for a blind parse back model."""
    return MathReconstruction(
        topic=item.topic,
        symbols=item.symbols,
        givens=item.givens,
        goal=item.goal,
    )


def _fidelity_result(status: str, reasons: list[str], stage: str) -> dict[str, Any]:
    if status == "passed":
        return {
            "status": "passed",
            "codes": [],
            "findings": [],
            "mode": "anchors and identity equivalence",
        }
    code = "FIDELITY_MISMATCH" if status == "failed" else "FIDELITY_INCONCLUSIVE"
    return {
        "status": "rejected",
        "codes": [code],
        "findings": list(reasons) or [f"fidelity {stage} did not pass"],
        "mode": "anchors and identity equivalence",
    }


def _determinism_check(
    template: MathTemplateSpec | None, report: HarnessReport | None
) -> dict[str, Any]:
    if template is None or report is None:
        return {
            "seeds": list(DETERMINISM_SEEDS),
            "identical": False,
            "no_external_calls": False,
            "external_calls": [],
            "expansions": [],
            "error": "no checked template to expand",
        }

    calls: list[str] = []
    expansions: list[dict[str, Any]] = []
    error: str | None = None
    try:
        artifact = _validated_artifact(template, report)
        with _offline_guard(calls):
            for seed in DETERMINISM_SEEDS:
                first = generate_math_question(artifact, seed)
                second = generate_math_question(artifact, seed)
                expansions.append(
                    {
                        "seed": seed,
                        "identical": first == second,
                        "answer": first.answer,
                        "choices": first.choices,
                        "correct_index": first.correct_index,
                    }
                )
    except Exception as exc:  # noqa: BLE001 - failure is recorded, never approved
        error = f"{type(exc).__name__}: {exc}"

    identical = bool(expansions) and all(
        expansion["identical"] for expansion in expansions
    )
    return {
        "seeds": list(DETERMINISM_SEEDS),
        "identical": identical,
        "no_external_calls": not calls,
        "external_calls": calls,
        "expansions": expansions,
        "error": error,
    }


def _deterministic(determinism: dict[str, Any] | None) -> bool:
    return bool(
        determinism
        and determinism["identical"]
        and determinism["no_external_calls"]
        and determinism["error"] is None
    )


def _validated_artifact(
    template: MathTemplateSpec, report: HarnessReport
) -> ValidatedMathTemplate:
    request = MathTemplateRequest(
        prompt="Author a frozen mathematics fixture.",
        difficulty="easy",
        num_distractors=len(template.body.distractors),
    )
    candidate: MathTemplateCandidate = build_math_candidate(
        request, MathTemplateContent(item=template)
    )
    summary = MathValidationSummary.model_validate(
        report.model_dump(exclude={"report"})
        | {
            "evidence": [
                ValidationEvidence(check="math_verify_item_spec", status="passed")
            ]
        }
    )
    return ValidatedMathTemplate(template=candidate, validation=summary)


@contextmanager
def _offline_guard(calls: list[str]) -> Iterator[None]:
    """Fail if expansion attempts a model, MCP worker or network call."""
    restores: list[tuple[Any, str, Any]] = []

    def replace(module: Any, name: str, label: str) -> None:
        original = getattr(module, name)

        def blocked(*args: Any, **kwargs: Any) -> Any:
            calls.append(label)
            raise AssertionError(f"{label} is not allowed during expansion")

        setattr(module, name, blocked)
        restores.append((module, name, original))

    replace(socket, "create_connection", "socket.create_connection")
    replace(socket, "getaddrinfo", "socket.getaddrinfo")
    replace(socket, "socket", "socket.socket")
    replace(fidelity_engine, "run_judge", "fidelity.run_judge")
    replace(judging, "run_judge", "judging.run_judge")
    replace(math_tools, "run_isolated", "math_tools.run_isolated")
    replace(isolated_process, "run_json_worker", "isolated_process.run_json_worker")

    try:
        yield
    finally:
        for module, name, original in reversed(restores):
            setattr(module, name, original)


def summarise(results: list[FixtureResult]) -> dict[str, Any]:
    """Count outcomes by category and list every mismatch."""
    categories: dict[str, dict[str, Any]] = {}
    for category in CATEGORIES:
        subset = [result for result in results if result.fixture.category == category]
        expected_counts = Counter(result.fixture.expected for result in subset)
        actual_counts = Counter(result.actual for result in subset)
        categories[category] = {
            "total": len(subset),
            "expected": {
                expectation: expected_counts.get(expectation, 0)
                for expectation in EXPECTATIONS
            },
            "actual": {
                expectation: actual_counts.get(expectation, 0)
                for expectation in EXPECTATIONS
            },
            "matched": sum(result.matched for result in subset),
        }

    expected_vs_actual = {
        expected: {
            actual: sum(
                1
                for result in results
                if result.fixture.expected == expected and result.actual == actual
            )
            for actual in EXPECTATIONS
        }
        for expected in EXPECTATIONS
    }

    determinism = {
        "checked": sum(1 for result in results if result.determinism is not None),
        "identical": sum(
            1
            for result in results
            if result.determinism is not None and result.determinism["identical"]
        ),
        "no_external_calls": sum(
            1
            for result in results
            if result.determinism is not None
            and result.determinism["no_external_calls"]
        ),
    }

    mismatches = [result.mismatch_record() for result in results if not result.matched]
    return {
        "fixture_count": len(results),
        "matched": sum(result.matched for result in results),
        "mismatched": len(mismatches),
        "categories": categories,
        "expected_vs_actual": expected_vs_actual,
        "determinism": determinism,
        "mismatches": mismatches,
    }


def write_results(
    results: list[FixtureResult], output: Path = DEFAULT_OUTPUT
) -> dict[str, Any]:
    """Write the JSONL records and the JSON summary beside them."""
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as stream:
        for result in results:
            stream.write(json.dumps(result.to_record(), ensure_ascii=False) + "\n")

    summary = summarise(results)
    summary_path = output.with_suffix(".summary.json")
    summary_path.write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return summary


def run(
    fixtures_dir: Path = FIXTURES_DIR, output: Path = DEFAULT_OUTPUT
) -> dict[str, Any]:
    """Evaluate every fixture and return the summary."""
    results = [evaluate_fixture(fixture) for fixture in load_fixtures(fixtures_dir)]
    return write_results(results, output)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the frozen mathematics fixtures offline."
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="JSONL path for per fixture records",
    )
    parser.add_argument(
        "--fixtures",
        type=Path,
        default=FIXTURES_DIR,
        help="directory holding the frozen fixture JSON files",
    )
    args = parser.parse_args(argv)

    summary = run(args.fixtures, args.output)
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 1 if summary["mismatched"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
