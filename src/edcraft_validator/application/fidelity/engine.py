"""Domain-neutral orchestration of anchor checks and blind parse-back.

The engine only sequences plugin-owned operations. It cannot approve text on its
own: every model parse is compared by the plugin's ``equivalent`` method and
every operational failure is ``inconclusive`` rather than ``passed``.
"""

from __future__ import annotations

import hashlib
import json
from collections import OrderedDict
from typing import Any

from pydantic import BaseModel

from edcraft_validator.application.fidelity.contracts import (
    EvidenceStrength,
    FidelityPlugin,
    FidelityReport,
    FidelityStatus,
    FidelityVerdict,
)
from edcraft_validator.llm.judging import JudgeProviderFactory, run_judge
from edcraft_validator.llm.llm_contracts import StructuredGenerationRequest
from edcraft_validator.llm.usage import ModelUsageSummary

DEFAULT_CACHE_SIZE = 256


class FidelityCache:
    """A small bounded, least-recently-used cache of blind reconstructions.

    Only successful parse-back artifacts belong here. Verdicts are deliberately
    not cached, so a cached reconstruction is always re-checked against the
    expected artifact by the plugin.
    """

    def __init__(self, max_entries: int = DEFAULT_CACHE_SIZE) -> None:
        if max_entries < 1:
            raise ValueError("cache size must be at least one entry")
        self.max_entries = max_entries
        self._entries: OrderedDict[str, BaseModel] = OrderedDict()

    def get(self, key: str) -> BaseModel | None:
        artifact = self._entries.get(key)
        if artifact is None:
            return None
        self._entries.move_to_end(key)
        return artifact

    def put(self, key: str, artifact: BaseModel) -> None:
        self._entries[key] = artifact
        self._entries.move_to_end(key)
        while len(self._entries) > self.max_entries:
            self._entries.popitem(last=False)

    def clear(self) -> None:
        self._entries.clear()

    def __len__(self) -> int:
        return len(self._entries)


_DEFAULT_CACHE = FidelityCache()


def default_cache() -> FidelityCache:
    """Return the shared cache used when the caller does not supply one."""
    return _DEFAULT_CACHE


async def verify_text_fidelity(
    plugin: FidelityPlugin,
    expected: BaseModel,
    text: str,
    *,
    provider_factory: JudgeProviderFactory,
    timeout_seconds: float = 60.0,
    cache: FidelityCache | None = None,
) -> FidelityReport:
    """Check rendered text against the artifact that was supposed to produce it."""
    if not isinstance(expected, plugin.artifact_model):
        raise TypeError(
            f"{plugin.domain!r} fidelity expects {plugin.artifact_model.__name__}"
        )
    request = plugin.reconstruction_request(text)
    request_sha256 = _request_sha256(request)

    if not plugin.requires_check(expected):
        return _report(
            domain=plugin.domain,
            evidence_strength=plugin.evidence_strength,
            status="passed",
            verdict=FidelityVerdict(
                status="passed",
                reasons=["constrained realization; no blind parse-back required"],
            ),
            prompt_version=request.prompt_version,
            request_sha256=request_sha256,
        )

    anchor_verdict, anchor_error = _safe_anchor_check(plugin, expected, text)
    if anchor_verdict.status != "passed":
        return _report(
            domain=plugin.domain,
            evidence_strength=plugin.evidence_strength,
            status=anchor_verdict.status,
            verdict=anchor_verdict,
            prompt_version=request.prompt_version,
            request_sha256=request_sha256,
            error_code=anchor_error,
        )

    canonical = plugin.canonicalize(expected)
    active_cache = cache if cache is not None else _DEFAULT_CACHE
    key = _cache_key(plugin.domain, text, canonical.digest)
    cached_artifact = active_cache.get(key)
    if cached_artifact is not None:
        verdict = _equivalent(plugin, expected, cached_artifact)
        return _report(
            domain=plugin.domain,
            evidence_strength=plugin.evidence_strength,
            status=verdict.status,
            verdict=verdict,
            prompt_version=request.prompt_version,
            request_sha256=request_sha256,
            reconstruction=cached_artifact.model_dump(mode="json"),
            cached=True,
        )

    run = await run_judge(
        request,
        provider_factory=provider_factory,
        timeout_seconds=timeout_seconds,
    )
    if run.status != "completed" or run.assessment is None:
        code = run.error_code or "JUDGE_INVALID_RESPONSE"
        verdict = FidelityVerdict(
            status="inconclusive",
            reasons=[f"blind parse-back failed: {code}"],
            evidence={
                "judge_error_code": code,
                "validation_errors": [
                    finding.model_dump(mode="json") for finding in run.validation_errors
                ],
            },
        )
        return _report(
            domain=plugin.domain,
            evidence_strength=plugin.evidence_strength,
            status="inconclusive",
            verdict=verdict,
            prompt_version=run.prompt_version,
            request_sha256=run.request_sha256,
            error_code=code,
            provider=run.provider,
            model=run.model,
            usage=run.usage,
        )

    reconstruction = run.assessment
    active_cache.put(key, reconstruction)
    verdict = _equivalent(plugin, expected, reconstruction)
    return _report(
        domain=plugin.domain,
        evidence_strength=plugin.evidence_strength,
        status=verdict.status,
        verdict=verdict,
        prompt_version=run.prompt_version,
        request_sha256=run.request_sha256,
        reconstruction=reconstruction.model_dump(mode="json"),
        provider=run.provider,
        model=run.model,
        usage=run.usage,
    )


def _safe_anchor_check(
    plugin: FidelityPlugin, expected: BaseModel, text: str
) -> tuple[FidelityVerdict, str | None]:
    try:
        return plugin.check_anchors(expected, text), None
    except Exception as exc:  # noqa: BLE001 - a broken gate must not pass text
        return (
            FidelityVerdict(
                status="inconclusive",
                reasons=[f"anchor check failed: {type(exc).__name__}"],
                evidence={"plugin_error_code": "FIDELITY_ANCHOR_ERROR"},
            ),
            "FIDELITY_ANCHOR_ERROR",
        )


def _equivalent(
    plugin: FidelityPlugin, expected: BaseModel, reconstructed: BaseModel
) -> FidelityVerdict:
    try:
        return plugin.equivalent(expected, reconstructed)
    except Exception as exc:  # noqa: BLE001 - comparison failure is not approval
        return FidelityVerdict(
            status="inconclusive",
            reasons=[f"equivalence check failed: {type(exc).__name__}"],
            evidence={"plugin_error_code": "FIDELITY_EQUIVALENT_ERROR"},
        )


def _cache_key(domain: str, text: str, expected_digest: str) -> str:
    return hashlib.sha256(f"{domain}|{text}|{expected_digest}".encode()).hexdigest()


def _request_sha256(request: StructuredGenerationRequest[Any]) -> str:
    # Keep no-model reports consistent with run_judge's request identity. The
    # expected artifact is never part of this payload.
    return hashlib.sha256(
        json.dumps(
            {
                "messages": request.messages,
                "schema": request.response_model.model_json_schema(),
                "schema_name": request.schema_name,
                "prompt_version": request.prompt_version,
                "reasoning_effort": request.reasoning_effort,
            },
            sort_keys=True,
            allow_nan=False,
        ).encode()
    ).hexdigest()


def _report(
    *,
    domain: str,
    evidence_strength: EvidenceStrength,
    status: FidelityStatus,
    verdict: FidelityVerdict,
    prompt_version: str,
    request_sha256: str,
    reconstruction: dict[str, Any] | None = None,
    cached: bool = False,
    error_code: str | None = None,
    provider: str | None = None,
    model: str | None = None,
    usage: ModelUsageSummary | None = None,
) -> FidelityReport:
    return FidelityReport(
        status=status,
        domain=domain,
        evidence_strength=evidence_strength,
        reconstruction=reconstruction,
        verdict=verdict,
        prompt_version=prompt_version,
        request_sha256=request_sha256,
        cached=cached,
        error_code=error_code,
        provider=provider,
        model=model,
        usage=usage or ModelUsageSummary(),
    )
