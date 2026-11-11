"""Domain-neutral fidelity engine tests with a synthetic, non-math plugin."""

from __future__ import annotations

import hashlib
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from edcraft_validator.application.fidelity.contracts import (
    CanonicalArtifact,
    EvidenceStrength,
    FidelityVerdict,
)
from edcraft_validator.application.fidelity.engine import (
    FidelityCache,
    verify_text_fidelity,
)
from edcraft_validator.llm.llm_contracts import StructuredGenerationRequest
from edcraft_validator.llm.usage import TokenUsage

AnchorStatus = Literal["passed", "failed", "inconclusive"]


class DemoArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: int
    checked: bool = True


class DemoReconstruction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: int
    ambiguous: bool = False


class DemoPlugin:
    domain: str = "demo"
    artifact_model: type[BaseModel] = DemoArtifact
    evidence_strength: EvidenceStrength = "deterministic"

    def __init__(self, anchor_status: AnchorStatus = "passed") -> None:
        self.anchor_status = anchor_status
        self.equivalence_calls = 0

    def requires_check(self, artifact: BaseModel) -> bool:
        return _artifact(artifact).checked

    def reconstruction_request(self, text: str) -> StructuredGenerationRequest[Any]:
        return StructuredGenerationRequest(
            messages=[{"role": "user", "content": text}],
            response_model=DemoReconstruction,
            schema_name="demo_reconstruction",
            prompt_version="demo/1",
        )

    def canonicalize(self, artifact: BaseModel) -> CanonicalArtifact:
        value = _artifact(artifact).value
        payload = {"value": value}
        return CanonicalArtifact(
            domain=self.domain,
            payload=payload,
            digest=hashlib.sha256(f"demo|{value}".encode()).hexdigest(),
        )

    def check_anchors(self, artifact: BaseModel, text: str) -> FidelityVerdict:
        if self.anchor_status == "passed":
            return FidelityVerdict(status="passed")
        return FidelityVerdict(
            status=self.anchor_status,
            reasons=[f"anchor status is {self.anchor_status}"],
        )

    def equivalent(
        self, expected: BaseModel, reconstructed: BaseModel
    ) -> FidelityVerdict:
        self.equivalence_calls += 1
        parse = _reconstruction(reconstructed)
        if parse.ambiguous:
            return FidelityVerdict(
                status="inconclusive", reasons=["ambiguous demo parse"]
            )
        if parse.value == _artifact(expected).value:
            return FidelityVerdict(status="passed")
        return FidelityVerdict(status="failed", reasons=["values differ"])


class DemoProvider:
    provider = "scripted"
    model = "demo-parser"

    def __init__(self, response: Any) -> None:
        self.response = response
        self.calls = 0

    def generation_settings(self) -> dict[str, Any]:
        return {"mode": "scripted"}

    def generate(self, request: StructuredGenerationRequest[Any]) -> Any:
        self.calls += 1
        self.last_usage = TokenUsage(input_tokens=5, output_tokens=2)
        if isinstance(self.response, Exception):
            raise self.response
        if isinstance(self.response, BaseModel):
            return request.response_model.model_validate(self.response.model_dump())
        return self.response


def _artifact(artifact: BaseModel) -> DemoArtifact:
    if not isinstance(artifact, DemoArtifact):
        raise TypeError("expected DemoArtifact")
    return artifact


def _reconstruction(artifact: BaseModel) -> DemoReconstruction:
    if not isinstance(artifact, DemoReconstruction):
        raise TypeError("expected DemoReconstruction")
    return artifact


def _item(value: int = 3, *, checked: bool = True) -> DemoArtifact:
    return DemoArtifact(value=value, checked=checked)


async def test_plugin_can_skip_blind_parse_back() -> None:
    provider = DemoProvider(DemoReconstruction(value=3))
    report = await verify_text_fidelity(
        DemoPlugin(),
        _item(checked=False),
        "demo text",
        provider_factory=lambda: provider,
        cache=FidelityCache(),
    )
    assert report.status == "passed"
    assert provider.calls == 0
    assert report.reconstruction is None


async def test_inconclusive_anchors_skip_the_model() -> None:
    provider = DemoProvider(DemoReconstruction(value=3))
    report = await verify_text_fidelity(
        DemoPlugin(anchor_status="inconclusive"),
        _item(),
        "demo text",
        provider_factory=lambda: provider,
        cache=FidelityCache(),
    )
    assert report.status == "inconclusive"
    assert provider.calls == 0


async def test_judge_error_is_inconclusive_and_not_cached() -> None:
    cache = FidelityCache()
    broken = DemoProvider(object())
    first = await verify_text_fidelity(
        DemoPlugin(),
        _item(),
        "demo text",
        provider_factory=lambda: broken,
        cache=cache,
    )
    assert first.status == "inconclusive"
    assert first.error_code == "JUDGE_INVALID_RESPONSE"

    provider = DemoProvider(DemoReconstruction(value=3))
    second = await verify_text_fidelity(
        DemoPlugin(),
        _item(),
        "demo text",
        provider_factory=lambda: provider,
        cache=cache,
    )
    assert second.status == "passed"
    assert second.cached is False
    assert provider.calls == 1


async def test_cached_reconstruction_is_rechecked_not_reused_as_verdict() -> None:
    cache = FidelityCache()
    plugin = DemoPlugin()
    provider = DemoProvider(DemoReconstruction(value=3))
    first = await verify_text_fidelity(
        plugin,
        _item(),
        "demo text",
        provider_factory=lambda: provider,
        cache=cache,
    )
    second = await verify_text_fidelity(
        plugin,
        _item(),
        "demo text",
        provider_factory=lambda: provider,
        cache=cache,
    )
    assert first.cached is False
    assert second.cached is True
    assert second.status == "passed"
    assert provider.calls == 1
    assert plugin.equivalence_calls == 2


async def test_ambiguous_parse_is_never_passed() -> None:
    provider = DemoProvider(DemoReconstruction(value=3, ambiguous=True))
    report = await verify_text_fidelity(
        DemoPlugin(),
        _item(),
        "demo text",
        provider_factory=lambda: provider,
        cache=FidelityCache(),
    )
    assert report.status == "inconclusive"
    assert report.status != "passed"
