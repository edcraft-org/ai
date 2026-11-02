"""Structured-only providers used by authoring integration tests."""

from edcraft_validator.domains.code.code_schemas import (
    CodeTemplateCandidate,
    CodeTemplateProposal,
)
from edcraft_validator.llm.llm_contracts import (
    PlannedGenerationResponse,
)


class RequestPendingTools:
    def generation_settings(self):
        return {"mode": "scripted"}


def proposal_for(candidate: CodeTemplateCandidate) -> CodeTemplateProposal:
    """Turn authored template content into the proposal a model would return."""
    return CodeTemplateProposal.model_validate(
        candidate.model_dump(
            include={
                "question_template",
                "code",
                "entry_function",
                "parameters",
                "answer_target",
                "answer_expression",
                "distractors",
            }
        )
    )


class CandidateProposalProvider(RequestPendingTools):
    """Deterministic authoring fixture that proposes known template content."""

    provider = "stub"
    model = "stub-proposal"

    def __init__(self, proposal, checks=("code_validate_answers_and_distractors",)):
        self.proposal = proposal
        self.checks = checks

    def generate(self, request):
        assert issubclass(request.response_model, PlannedGenerationResponse)
        return PlannedGenerationResponse(
            proposal=self.proposal,
            checks=[{"name": name, "arguments": {}} for name in self.checks],
        )
