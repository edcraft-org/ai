"""End-to-end pilot application flow with a stubbed structured provider."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from edcraft_validator.application.check_pilot import (
    CheckPilotApplication,
    PilotConflict,
    PilotInputError,
    PilotNotFound,
)
from edcraft_validator.application.check_pilot.models import (
    CheckAuthorProposal,
    CheckRecipeDefinition,
    CoefficientDomain,
    PilotQualificationSettings,
    PolynomialFamily,
    Qualification,
    RecipeArgument,
    RecipeStep,
    TemplateAuthorProposal,
)


def input_arg(name: str) -> RecipeArgument:
    return RecipeArgument(source="input", name=name)


def step_arg(name: str) -> RecipeArgument:
    return RecipeArgument(source="step", name=name)


def valid_recipe() -> CheckRecipeDefinition:
    return CheckRecipeDefinition(
        steps=[
            RecipeStep(
                id="d1",
                operation="poly.differentiate",
                version="1",
                arguments={"polynomial": input_arg("problem")},
            ),
            RecipeStep(
                id="out",
                operation="poly.equivalent",
                version="1",
                arguments={
                    "expected": step_arg("d1"),
                    "actual": input_arg("candidate"),
                },
            ),
        ],
        output="out",
    )


def wrong_recipe() -> CheckRecipeDefinition:
    return CheckRecipeDefinition(
        steps=[
            RecipeStep(
                id="d1",
                operation="poly.differentiate",
                version="1",
                arguments={"polynomial": input_arg("problem")},
            ),
            RecipeStep(
                id="d2",
                operation="poly.differentiate",
                version="1",
                arguments={"polynomial": step_arg("d1")},
            ),
            RecipeStep(
                id="out",
                operation="poly.equivalent",
                version="1",
                arguments={
                    "expected": step_arg("d2"),
                    "actual": input_arg("candidate"),
                },
            ),
        ],
        output="out",
    )


def valid_check_proposal() -> CheckAuthorProposal:
    return CheckAuthorProposal(
        title="Differentiate a bounded polynomial",
        description=(
            "Checks a candidate derivative by comparing it with an independently "
            "derived polynomial over all coefficients."
        ),
        recipe=valid_recipe(),
    )


def family(
    *,
    degree: int = 2,
    constants: list[int] | None = None,
    leading: list[int] | None = None,
) -> PolynomialFamily:
    constants = constants or [-3, -1, 0, 2]
    leading = leading or [1, 2, 3]
    return PolynomialFamily(
        degree=degree,
        coefficients=[
            CoefficientDomain(exponent=0, values=constants),
            *[
                CoefficientDomain(exponent=exponent, values=[-2, 0, 1, 2])
                for exponent in range(1, degree)
            ],
            CoefficientDomain(exponent=degree, values=leading),
        ],
        num_distractors=3,
    )


def valid_template_proposal(
    *,
    degree: int = 2,
    constants: list[int] | None = None,
    leading: list[int] | None = None,
) -> TemplateAuthorProposal:
    return TemplateAuthorProposal(
        family=family(degree=degree, constants=constants, leading=leading)
    )


class ScriptedProvider:
    provider = "stub"
    model = "stub-structured"

    def __init__(
        self,
        *,
        check=None,
        template=None,
        check_errors: int = 0,
        template_errors: int = 0,
    ) -> None:
        self.check = check or valid_check_proposal()
        self.template = template or valid_template_proposal()
        self.check_errors = check_errors
        self.template_errors = template_errors
        self.calls: list[dict] = []

    def generation_settings(self):
        return {"mode": "scripted", "reasoning_effort": "none"}

    def generate(self, request):
        role = (
            "check-author"
            if request.prompt_version.startswith("check-author")
            else "template-author"
        )
        self.calls.append(
            {
                "role": role,
                "prompt_version": request.prompt_version,
                "schema": request.schema_name,
                "messages": request.messages,
            }
        )
        if role == "check-author":
            if self.check_errors:
                self.check_errors -= 1
                raise RuntimeError("scripted check author transport failure")
            return self.check() if callable(self.check) else self.check
        if self.template_errors:
            self.template_errors -= 1
            raise RuntimeError("scripted template author transport failure")
        return self.template() if callable(self.template) else self.template


def app(tmp_path: Path, *, max_examples: int = 8) -> CheckPilotApplication:
    return CheckPilotApplication(
        tmp_path,
        qualification_settings=PilotQualificationSettings(
            max_examples=max_examples,
            max_execution_calls=800,
            timeout_seconds=30.0,
        ),
    )


def author(
    application,
    provider,
    owner="owner",
    prompt="Author a polynomial derivative check",
    *,
    num_distractors=3,
):
    return application.author_template(
        owner, prompt=prompt, provider=provider, num_distractors=num_distractors
    )


def test_end_to_end_author_approve_generate_and_restart(tmp_path: Path):
    application = app(tmp_path)
    provider = ScriptedProvider()
    record = author(application, provider)

    assert record.status == "ready"
    assert record.approval == "unreviewed"
    assert record.reused_check is False
    assert record.check is not None
    assert record.check.qualification.status == "passed"
    assert record.qualification is not None and record.qualification.status == "passed"
    assert record.check_qualification is not None
    assert record.check_qualification.status == "passed"
    assert [call["role"] for call in provider.calls] == [
        "check-author",
        "template-author",
    ]
    assert len({call["prompt_version"] for call in provider.calls}) == 2
    assert len(application.list_checks("owner")) == 1
    assert len(application.list_templates("owner")) == 1

    with pytest.raises(PilotConflict):
        application.generate("owner", record.template_id, seed=1, quantity=2)
    with pytest.raises(PilotConflict):
        application.decide(
            "owner",
            record.template_id,
            template_sha256="0" * 64,
            check_sha256=record.check.check_ref.sha256,
            decision="approved",
        )
    with pytest.raises(PilotConflict):
        application.decide(
            "owner",
            record.template_id,
            template_sha256=record.template_sha256,
            check_sha256="f" * 64,
            decision="approved",
        )

    approved = application.decide(
        "owner",
        record.template_id,
        template_sha256=record.template_sha256,
        check_sha256=record.check.check_ref.sha256,
        decision="approved",
    )
    assert approved.approval == "approved"
    batch = application.generate("owner", record.template_id, seed=42, quantity=5)
    assert batch.requested_quantity == 5
    assert len(provider.calls) == 2
    assert batch.shortfall == 0
    assert len(batch.questions) == 5
    assert len({question.expression for question in batch.questions}) == 5
    for question in batch.questions:
        assert len(question.choices) == 4
        assert question.choices[question.correct_index] == question.answer
        assert len(set(question.choices)) == 4
        assert question.check_ref == record.check.check_ref
        assert question.expression in question.question
    assert (
        application.generate("owner", record.template_id, seed=42, quantity=5) == batch
    )

    restarted = app(tmp_path)
    assert restarted.get_check("owner", record.check.check_ref.check_id).check_ref == (
        record.check.check_ref
    )
    assert restarted.get_template("owner", record.template_id).approval == "approved"
    assert restarted.generate("owner", record.template_id, seed=42, quantity=5) == batch


def test_second_template_reuses_check_without_check_author_call(tmp_path: Path):
    application = app(tmp_path)
    first = author(application, ScriptedProvider())
    second_provider = ScriptedProvider()
    second = author(
        application,
        second_provider,
        prompt="Author a different polynomial derivative template",
    )

    assert second.reused_check is True
    assert second.check is not None and first.check is not None
    assert second.check.check_ref == first.check.check_ref
    assert [call["role"] for call in second_provider.calls] == ["template-author"]
    assert len(application.list_checks("owner")) == 1

    with pytest.raises(PilotNotFound):
        application.get_check("other-owner", first.check.check_ref.check_id)
    with pytest.raises(PilotNotFound):
        application.get_template("other-owner", first.template_id)
    with pytest.raises(PilotNotFound):
        application.decide(
            "other-owner",
            first.template_id,
            template_sha256=first.template_sha256,
            check_sha256=first.check.check_ref.sha256,
            decision="approved",
        )
    with pytest.raises(PilotNotFound):
        application.generate("other-owner", first.template_id, seed=1, quantity=1)

    other_provider = ScriptedProvider(
        check=CheckAuthorProposal(
            title="Differentiate a different bounded polynomial",
            description=(
                "A separate check definition so this owner's private library "
                "does not share the first owner's content hash."
            ),
            recipe=valid_recipe(),
        )
    )
    other = author(application, other_provider, owner="other-owner")
    assert other.reused_check is False
    assert other.check is not None
    assert other.check.check_ref != first.check.check_ref
    assert [call["role"] for call in other_provider.calls] == [
        "check-author",
        "template-author",
    ]
    assert application.list_checks("other-owner")[0].check_ref == other.check.check_ref


def test_repair_exhaustion_preserves_counterexample_and_no_usable_check(
    tmp_path: Path,
):
    provider = ScriptedProvider(
        check=CheckAuthorProposal(
            title="Wrong derivative",
            description="This recipe differentiates twice.",
            recipe=wrong_recipe(),
        )
    )
    application = app(tmp_path)
    record = author(application, provider)

    assert record.status == "needs_review"
    assert record.check is None
    assert record.template is None
    assert record.check_qualification is not None
    assert record.check_qualification.status == "failed"
    assert any("counterexample" in finding for finding in record.findings)
    assert [call["role"] for call in provider.calls] == ["check-author"] * 3
    assert "counterexample" in provider.calls[1]["messages"][1]["content"]
    assert "counterexample" in provider.calls[2]["messages"][1]["content"]
    assert application.list_checks("owner") == []
    assert [item.status for item in application.list_templates("owner")] == [
        "needs_review"
    ]
    with pytest.raises(PilotConflict):
        application.generate("owner", record.template_id, seed=1, quantity=1)


def test_provider_error_leaves_error_record_and_no_usable_check(tmp_path: Path):
    provider = ScriptedProvider(check_errors=1)
    application = app(tmp_path)
    record = author(application, provider)

    assert record.status == "error"
    assert record.check is None
    assert record.check_qualification is None
    assert record.findings
    assert [call["role"] for call in provider.calls] == ["check-author"]
    assert application.list_checks("owner") == []
    assert [item.status for item in application.list_templates("owner")] == ["error"]
    with pytest.raises(PilotConflict):
        application.generate("owner", record.template_id, seed=1, quantity=1)


def test_unsupported_check_capability_is_development_needed(tmp_path: Path):
    provider = ScriptedProvider(
        check=CheckAuthorProposal(
            supported=False,
            development_needed="Polynomial integration is not supported in this pilot.",
        )
    )
    record = author(app(tmp_path), provider)
    assert record.status == "needs_review"
    assert record.check is None
    assert any("Development needed" in finding for finding in record.findings)
    assert [call["role"] for call in provider.calls] == ["check-author"]


def test_unsupported_template_keeps_qualified_check_but_blocks_approval(
    tmp_path: Path,
):
    provider = ScriptedProvider(
        template=TemplateAuthorProposal(
            supported=False,
            development_needed=(
                "This family is not representable as coefficient domains."
            ),
        )
    )
    application = app(tmp_path)
    record = author(application, provider)
    assert record.status == "needs_review"
    assert record.template is None
    assert record.check is not None
    assert record.check.qualification.status == "passed"
    assert len(application.list_checks("owner")) == 1
    with pytest.raises(PilotConflict):
        application.decide(
            "owner",
            record.template_id,
            template_sha256=record.template_sha256,
            check_sha256=record.check.check_ref.sha256,
            decision="approved",
        )


def test_template_provider_error_keeps_qualified_check_but_no_template(
    tmp_path: Path,
):
    provider = ScriptedProvider(template_errors=1)
    application = app(tmp_path)
    record = author(application, provider)
    assert record.status == "error"
    assert record.template is None
    assert record.qualification is None
    assert record.check is not None
    assert record.check.qualification.status == "passed"
    assert [call["role"] for call in provider.calls] == [
        "check-author",
        "template-author",
    ]
    assert len(application.list_checks("owner")) == 1
    with pytest.raises(PilotConflict):
        application.generate("owner", record.template_id, seed=1, quantity=1)


def test_template_qualification_failure_is_separate_evidence(
    tmp_path: Path, monkeypatch
):
    from edcraft_validator.application.check_pilot import authoring as module

    def failed_template(*args, **kwargs):
        return Qualification(
            status="failed",
            accepted_cases=4,
            execution_calls=12,
            seed=1,
            max_examples=8,
            max_execution_calls=800,
            timeout_seconds=30.0,
            counterexample={"reason": "pinned recipe accepted a distractor"},
            findings=["counterexample: pinned recipe accepted a distractor"],
            versions={"question_builder": "polynomial-mcq/1"},
        )

    monkeypatch.setattr(module, "qualify_template", failed_template)
    application = app(tmp_path)
    record = author(application, ScriptedProvider())
    assert record.status == "needs_review"
    assert record.check is not None
    assert record.check.qualification.status == "passed"
    assert record.qualification is not None
    assert record.qualification.status == "failed"
    assert record.template is not None
    assert any("counterexample" in finding for finding in record.findings)
    assert len(application.list_checks("owner")) == 1
    with pytest.raises(PilotConflict):
        application.generate("owner", record.template_id, seed=1, quantity=1)


def test_rejection_is_distinct_from_check_qualification(tmp_path: Path):
    application = app(tmp_path)
    record = author(application, ScriptedProvider())
    rejected = application.decide(
        "owner",
        record.template_id,
        template_sha256=record.template_sha256,
        check_sha256=record.check.check_ref.sha256,
        decision="rejected",
    )
    assert rejected.approval == "rejected"
    assert rejected.check is not None
    assert rejected.check.qualification.status == "passed"
    with pytest.raises(PilotConflict):
        application.generate("owner", record.template_id, seed=1, quantity=1)


def test_generation_shortfall_does_not_claim_domain_exhaustion(tmp_path: Path):
    application = app(tmp_path)
    provider = ScriptedProvider(
        template=valid_template_proposal(degree=1, constants=[0, 1], leading=[1])
    )
    record = author(application, provider)
    application.decide(
        "owner",
        record.template_id,
        template_sha256=record.template_sha256,
        check_sha256=record.check.check_ref.sha256,
        decision="approved",
    )
    batch = application.generate("owner", record.template_id, seed=7, quantity=3)
    assert len(batch.questions) == 2
    assert batch.shortfall == 1
    joined = " ".join(batch.findings)
    assert "bounded sampling" in joined
    assert "No claim" in joined
    assert "exhausted" not in joined.lower()


@pytest.mark.parametrize("num_distractors", [3, 5])
def test_max_supported_generation_batch_completes(tmp_path: Path, num_distractors: int):
    application = app(tmp_path)
    provider = ScriptedProvider(
        template=valid_template_proposal(
            degree=2, constants=list(range(-4, 4)), leading=[1, 2, 3]
        )
    )
    record = author(application, provider, num_distractors=num_distractors)
    assert record.status == "ready"
    application.decide(
        "owner",
        record.template_id,
        template_sha256=record.template_sha256,
        check_sha256=record.check.check_ref.sha256,
        decision="approved",
    )
    batch = application.generate("owner", record.template_id, seed=42, quantity=50)
    assert len(batch.questions) == 50
    assert batch.shortfall == 0
    assert all(
        len(question.choices) == num_distractors + 1 for question in batch.questions
    )
    assert len(provider.calls) == 2


def test_input_validation_and_unapproved_owner_operations(tmp_path: Path):
    application = app(tmp_path)
    provider = ScriptedProvider()
    with pytest.raises(PilotInputError):
        author(application, provider, prompt="")
    with pytest.raises(PilotInputError):
        application.author_template(
            "owner", prompt="valid", provider=provider, num_distractors=99
        )
    assert provider.calls == []
    with pytest.raises(PilotNotFound):
        application.get_template("owner", "tpl_" + "a" * 24)
    with pytest.raises(PilotInputError):
        application.decide(
            "owner",
            "tpl_" + "a" * 24,
            template_sha256="0" * 64,
            check_sha256="0" * 64,
            decision="maybe",
        )
    assert datetime.now(UTC).year >= 2026
