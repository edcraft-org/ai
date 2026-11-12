"""Public application facade for the private reusable-check pilot."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Literal

from edcraft_validator.application.check_pilot.authoring import (
    author_template_flow,
    find_applicable_check,
)
from edcraft_validator.application.check_pilot.errors import (
    PilotConflict,
    PilotInputError,
)
from edcraft_validator.application.check_pilot.generation import (
    MAX_QUANTITY,
    generate_batch,
)
from edcraft_validator.application.check_pilot.models import (
    CheckRecord,
    PilotBatch,
    PilotQualificationSettings,
    PilotTemplateRecord,
)
from edcraft_validator.application.check_pilot.storage import (
    PilotStore,
    template_record_sha256,
)
from edcraft_validator.llm.llm_contracts import ModelProvider

_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _validate_owner(owner_id: str) -> None:
    if (
        not isinstance(owner_id, str)
        or not owner_id.strip()
        or len(owner_id) > 200
        or "\x00" in owner_id
    ):
        raise PilotInputError("owner id is invalid")


class CheckPilotApplication:
    """Private, owner-scoped authoring and deterministic generation."""

    def __init__(
        self,
        root: Path,
        *,
        qualification_settings: PilotQualificationSettings | None = None,
    ) -> None:
        self.store = PilotStore(root)
        self.qualification_settings = (
            qualification_settings or PilotQualificationSettings()
        )

    def author_template(
        self,
        owner_id: str,
        *,
        prompt: str,
        provider: ModelProvider,
        num_distractors: int = 3,
    ) -> PilotTemplateRecord:
        _validate_owner(owner_id)
        if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 4000:
            raise PilotInputError("prompt must be 1 to 4000 non-blank characters")
        if type(num_distractors) is not int or not 1 <= num_distractors <= 5:
            raise PilotInputError("num_distractors must be an integer from 1 to 5")
        if not callable(getattr(provider, "generate", None)):
            raise PilotInputError("a structured model provider is required")
        return author_template_flow(
            self.store,
            owner_id,
            prompt=prompt,
            provider=provider,
            num_distractors=num_distractors,
            settings=self.qualification_settings,
        )

    def list_checks(self, owner_id: str) -> list[CheckRecord]:
        return self.store.list_checks(owner_id)

    def get_check(self, owner_id: str, check_id: str) -> CheckRecord:
        return self.store.get_check(owner_id, check_id)

    def list_templates(self, owner_id: str) -> list[PilotTemplateRecord]:
        return self.store.list_templates(owner_id)

    def get_template(self, owner_id: str, template_id: str) -> PilotTemplateRecord:
        return self.store.get_template(owner_id, template_id)

    def decide(
        self,
        owner_id: str,
        template_id: str,
        *,
        template_sha256: str,
        check_sha256: str,
        decision: Literal["approved", "rejected"],
    ) -> PilotTemplateRecord:
        _validate_owner(owner_id)
        if decision not in {"approved", "rejected"}:
            raise PilotInputError("decision must be approved or rejected")
        if not isinstance(template_sha256, str) or not _SHA256.fullmatch(
            template_sha256
        ):
            raise PilotInputError("template_sha256 must be a lowercase sha256")
        if not isinstance(check_sha256, str) or not _SHA256.fullmatch(check_sha256):
            raise PilotInputError("check_sha256 must be a lowercase sha256")
        record = self.store.get_template(owner_id, template_id)
        if record.check is None:
            raise PilotConflict("this template has no qualified check to approve")
        if record.template_sha256 != template_sha256:
            raise PilotConflict("template changed; reload before deciding")
        if record.check.check_ref.sha256 != check_sha256:
            raise PilotConflict("check changed; reload before deciding")
        if decision == "approved":
            if (
                record.status != "ready"
                or record.qualification is None
                or record.qualification.status != "passed"
                or record.check.qualification.status != "passed"
            ):
                raise PilotConflict(
                    "only a ready template with passed check and template "
                    "qualification can be approved"
                )
        updated = record.model_copy(update={"approval": decision})
        return self.store.replace_template(
            owner_id,
            updated,
            expected_record_sha256=template_record_sha256(record),
        )

    def generate(
        self, owner_id: str, template_id: str, *, seed: int, quantity: int
    ) -> PilotBatch:
        _validate_owner(owner_id)
        if type(seed) is not int or seed < 0:
            raise PilotInputError("seed must be a non-negative integer")
        if type(quantity) is not int or not 1 <= quantity <= MAX_QUANTITY:
            raise PilotInputError(
                f"quantity must be an integer from 1 to {MAX_QUANTITY}"
            )
        return generate_batch(
            self.store, owner_id, template_id, seed=seed, quantity=quantity
        )


__all__ = ["CheckPilotApplication", "find_applicable_check"]
