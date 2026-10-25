"""Code-specific revision scopes and shared difficulty definitions for authors."""

from edcraft_validator.domains.code.difficulty import load_code_difficulty_rubric
from edcraft_validator.domains.code.proposal_response import (
    CodeDistractorRevision,
    CodeProposalResponse,
)
from edcraft_validator.llm.llm_errors import GenerationSchemaError


def author_difficulty_guidance() -> str:
    rubric = load_code_difficulty_rubric()
    levels = (
        rubric.text.split("| Level | Anchor description |", 1)[1]
        .split("Choose the closest worked anchor", 1)[0]
        .strip()
    )
    return (
        "Difficulty definitions shared with the checker, without worked examples:\n"
        "| Level | Anchor description |\n" + levels + "\n"
        "Apply these to the typical instance across independent, uniformly chosen "
        "parameter values, under manual untimed tracing with scratch paper. "
        "Consider execution burden, changing state, conceptual interaction and "
        "answer discrimination together. Account for shortcuts and irrelevant code. "
        "Extra syntax or larger loop bounds alone do not establish hard difficulty."
    )


def revision_contract(proposal, attempt):
    failed = [item for item in attempt.executions if not item.passed]
    findings = [
        finding
        for item in failed
        if item.evidence is not None
        for finding in item.evidence.findings
    ]
    distractors_only = (
        isinstance(proposal, CodeProposalResponse)
        and bool(failed)
        and all(item.error is None and item.evidence is not None for item in failed)
        and bool(findings)
        and all(finding.code == "DISTRACTOR_SELECTION_FAILED" for finding in findings)
    )
    names = [parameter.name for parameter in proposal.parameters]
    guidance = {
        "scope": "distractors_and_parameter_values" if distractors_only else "proposal",
        "parameter_names": names,
        "entry_signature": f"def {proposal.entry_function}({', '.join(names)}):",
        "instructions": (
            "Fix the smallest failed part; preserve previously valid fields where "
            "possible. Use only one to three parameters. If a full revision changes "
            "parameter names or order, update the entry function signature, body, "
            "question placeholders, answer and distractor expressions together. "
            "Define called helper functions at module level. For a difficulty "
            "mismatch, address the judge's deciding reasoning demands and shortcuts; "
            "increasing repetition alone may not address the mismatch."
        ),
    }
    if distractors_only:
        guidance["instructions"] = (
            "Return only parameters and distractors. Keep parameter names, kinds "
            "and order unchanged; only their listed values may change, consistent "
            "with the original request. Fix every reported collision across the "
            "sampled domain. Code, entry function, question wording, answer recipe, "
            "answer target are preserved by the application. "
            "Do not invent fallback distractors."
        )
    return CodeDistractorRevision if distractors_only else type(proposal), guidance


def merge_revision(proposal, revised):
    if isinstance(revised, CodeDistractorRevision):
        if [(p.name, p.kind) for p in revised.parameters] != [
            (p.name, p.kind) for p in proposal.parameters
        ]:
            raise GenerationSchemaError(
                "Distractor revision must preserve parameter names, kinds and order"
            )
        return type(proposal).model_validate(
            proposal.model_dump() | revised.model_dump()
        )
    if not isinstance(revised, type(proposal)):
        raise GenerationSchemaError("Revision must return only the proposal")
    return revised
