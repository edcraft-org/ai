"""Owner-scoped, hash-validated pilot persistence.

Checks are content-addressed and immutable. Templates are mutable only through
a compare-and-swap approval update. Writes use an atomic link/replace so a
crash or concurrent request can never expose a partial record.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

from edcraft_validator.application.check_pilot.errors import (
    PilotConflict,
    PilotInputError,
    PilotNotFound,
)
from edcraft_validator.application.check_pilot.models import (
    CHECK_SCHEMA_VERSION,
    CheckRecipeDefinition,
    CheckRecord,
    PilotTemplateDefinition,
    PilotTemplateRecord,
    PolynomialScope,
)

_CHECK_ID = re.compile(r"^chk_[0-9a-f]{16,64}$")
_TEMPLATE_ID = re.compile(r"^tpl_[0-9a-f]{16,64}$")
_SENSITIVE_KEYS = {
    "api_key",
    "apikey",
    "authorization",
    "credential",
    "credentials",
    "password",
    "secret",
    "token",
}
NULL_TEMPLATE_SHA256 = hashlib.sha256(
    json.dumps(
        {"contract": CHECK_SCHEMA_VERSION, "template": None},
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
).hexdigest()


def _canonical_sha256(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode()
    ).hexdigest()


def check_content_sha256(
    *,
    title: str,
    description: str,
    scope: dict[str, Any],
    definition: dict[str, Any],
) -> str:
    return _canonical_sha256(
        {
            "contract": CHECK_SCHEMA_VERSION,
            "title": title,
            "description": description,
            "scope": scope,
            "definition": definition,
        }
    )


def template_definition_sha256(
    definition: PilotTemplateDefinition | dict[str, Any],
) -> str:
    value = (
        definition.model_dump(mode="json", exclude_none=True)
        if isinstance(definition, PilotTemplateDefinition)
        else definition
    )
    return _canonical_sha256(value)


def template_record_sha256(record: PilotTemplateRecord) -> str:
    # ``exclude_none`` keeps the frozen v1 bytes (and its compare-and-swap hash)
    # stable after additive optional diagnostics were introduced. Legacy records
    # only contain non-null values for the fields they actually stored.
    return _canonical_sha256(record.model_dump(mode="json", exclude_none=True))


def _validate_owner(owner_id: str) -> str:
    if (
        not isinstance(owner_id, str)
        or not owner_id.strip()
        or len(owner_id) > 200
        or "\x00" in owner_id
    ):
        raise PilotInputError("owner id is invalid")
    return owner_id


def _validate_id(value: str, pattern: re.Pattern[str], kind: str) -> str:
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        raise PilotNotFound(f"{kind} was not found")
    return value


def _validate_created_at(value: str) -> None:
    try:
        datetime.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise PilotConflict("stored record has an invalid timestamp") from exc


def _scan_for_secrets(value: Any) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if isinstance(key, str) and key.lower() in _SENSITIVE_KEYS:
                raise PilotInputError("provenance must not contain credentials")
            _scan_for_secrets(item)
    elif isinstance(value, list):
        for item in value:
            _scan_for_secrets(item)


def _validate_check_record(record: CheckRecord) -> None:
    _validate_created_at(record.created_at)
    _scan_for_secrets(record.provenance)
    if record.qualification.status != "passed":
        raise PilotInputError("only a passed qualification can be stored")
    if record.check_ref.version != "1":
        raise PilotConflict("unsupported stored check version")
    try:
        scope = PolynomialScope.model_validate(record.scope)
        CheckRecipeDefinition.model_validate(record.definition)
    except ValueError as exc:
        raise PilotConflict("stored check is outside the pilot scope") from exc
    digest = check_content_sha256(
        title=record.title,
        description=record.description,
        scope=scope.model_dump(mode="json"),
        definition=record.definition,
    )
    if digest != record.check_ref.sha256:
        raise PilotConflict("stored check failed integrity validation")


def _validate_template_record(record: PilotTemplateRecord) -> None:
    _validate_created_at(record.created_at)
    _scan_for_secrets(record.provenance or {})
    if record.template is None:
        if record.template_sha256 != NULL_TEMPLATE_SHA256:
            raise PilotConflict("stored template failed integrity validation")
    else:
        try:
            definition = PilotTemplateDefinition.model_validate(record.template)
        except ValueError as exc:
            raise PilotConflict("stored template is outside the pilot scope") from exc
        if template_definition_sha256(definition) != record.template_sha256:
            raise PilotConflict("stored template failed integrity validation")
    if record.check is not None:
        _validate_check_record(record.check)
    if record.status == "ready" and (
        record.check is None
        or record.template is None
        or record.qualification is None
        or record.qualification.status != "passed"
    ):
        raise PilotConflict("a ready template requires qualified evidence")


class PilotStore:
    """Filesystem store rooted at an application-owned data directory."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def _owner_dir(self, owner_id: str) -> Path:
        token = hashlib.sha256(owner_id.encode()).hexdigest()
        return self.root / "owners" / token

    def _under_root(self, path: Path) -> bool:
        root = self.root.resolve()
        resolved = path.resolve()
        return resolved == root or root in resolved.parents

    def _existing_path(self, path: Path, kind: str) -> Path:
        try:
            resolved = path.resolve(strict=True)
        except FileNotFoundError as exc:
            raise PilotNotFound(f"{kind} was not found") from exc
        if not self._under_root(resolved):
            raise PilotNotFound(f"{kind} was not found")
        return resolved

    def _check_path(self, owner_id: str, check_id: str) -> Path:
        return self._owner_dir(owner_id) / "checks" / check_id / "v1.json"

    def _template_path(self, owner_id: str, template_id: str) -> Path:
        return self._owner_dir(owner_id) / "templates" / template_id / "template.json"

    def _read_envelope(self, path: Path, owner_id: str, kind: str) -> dict[str, Any]:
        resolved = self._existing_path(path, kind)
        try:
            raw = json.loads(resolved.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            raise PilotConflict(f"stored {kind} failed integrity validation") from exc
        if not isinstance(raw, dict) or raw.get("owner_id") != owner_id:
            raise PilotNotFound(f"{kind} was not found")
        record = raw.get("record")
        if not isinstance(record, dict):
            raise PilotConflict(f"stored {kind} failed integrity validation")
        if raw.get("record_sha256") != _canonical_sha256(record):
            raise PilotConflict(f"stored {kind} failed integrity validation")
        return record

    def _write_immutable(self, path: Path, envelope: dict[str, Any]) -> bool:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        descriptor, temporary_name = tempfile.mkstemp(prefix=".tmp-", dir=path.parent)
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(envelope, handle, allow_nan=False)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temporary, 0o600)
            try:
                os.link(temporary, path)
            except FileExistsError:
                return False
            return True
        finally:
            temporary.unlink(missing_ok=True)

    def _atomic_replace(self, path: Path, envelope: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        descriptor, temporary_name = tempfile.mkstemp(prefix=".tmp-", dir=path.parent)
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(envelope, handle, allow_nan=False)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temporary, 0o600)
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)

    def _envelope(self, owner_id: str, record: Any) -> dict[str, Any]:
        payload = record.model_dump(mode="json")
        return {
            "owner_id": owner_id,
            "record_sha256": _canonical_sha256(payload),
            "record": payload,
        }

    def _read_check(self, owner_id: str, check_id: str) -> CheckRecord:
        record = self._read_envelope(
            self._check_path(owner_id, check_id), owner_id, "check"
        )
        try:
            parsed = CheckRecord.model_validate(record)
        except ValueError as exc:
            raise PilotConflict("stored check failed integrity validation") from exc
        if parsed.check_ref.check_id != check_id:
            raise PilotConflict("stored check failed integrity validation")
        _validate_check_record(parsed)
        return parsed

    def _read_template(self, owner_id: str, template_id: str) -> PilotTemplateRecord:
        record = self._read_envelope(
            self._template_path(owner_id, template_id), owner_id, "template"
        )
        try:
            parsed = PilotTemplateRecord.model_validate(record)
        except ValueError as exc:
            raise PilotConflict("stored template failed integrity validation") from exc
        if parsed.template_id != template_id:
            raise PilotConflict("stored template failed integrity validation")
        _validate_template_record(parsed)
        return parsed

    def save_check(self, owner_id: str, record: CheckRecord) -> CheckRecord:
        owner = _validate_owner(owner_id)
        _validate_id(record.check_ref.check_id, _CHECK_ID, "check")
        _validate_check_record(record)
        path = self._check_path(owner, record.check_ref.check_id)
        if self._write_immutable(path, self._envelope(owner, record)):
            return record
        existing = self._read_check(owner, record.check_ref.check_id)
        if existing.check_ref.sha256 != record.check_ref.sha256:
            raise PilotConflict("an immutable check version already exists")
        return existing

    def get_check(self, owner_id: str, check_id: str) -> CheckRecord:
        owner = _validate_owner(owner_id)
        validated = _validate_id(check_id, _CHECK_ID, "check")
        return self._read_check(owner, validated)

    def list_checks(self, owner_id: str) -> list[CheckRecord]:
        owner = _validate_owner(owner_id)
        directory = self._owner_dir(owner) / "checks"
        if not directory.is_dir():
            return []
        records = []
        for child in directory.iterdir():
            if child.is_dir() and _CHECK_ID.fullmatch(child.name):
                records.append(self._read_check(owner, child.name))
        return sorted(
            records, key=lambda item: (item.created_at, item.check_ref.check_id)
        )

    def save_template(
        self, owner_id: str, record: PilotTemplateRecord
    ) -> PilotTemplateRecord:
        owner = _validate_owner(owner_id)
        _validate_id(record.template_id, _TEMPLATE_ID, "template")
        _validate_template_record(record)
        path = self._template_path(owner, record.template_id)
        if self._write_immutable(path, self._envelope(owner, record)):
            return record
        existing = self._read_template(owner, record.template_id)
        if existing != record:
            raise PilotConflict("an immutable template record already exists")
        return existing

    def get_template(self, owner_id: str, template_id: str) -> PilotTemplateRecord:
        owner = _validate_owner(owner_id)
        validated = _validate_id(template_id, _TEMPLATE_ID, "template")
        return self._read_template(owner, validated)

    def list_templates(self, owner_id: str) -> list[PilotTemplateRecord]:
        owner = _validate_owner(owner_id)
        directory = self._owner_dir(owner) / "templates"
        if not directory.is_dir():
            return []
        records = []
        for child in directory.iterdir():
            if child.is_dir() and _TEMPLATE_ID.fullmatch(child.name):
                records.append(self._read_template(owner, child.name))
        return sorted(records, key=lambda item: (item.created_at, item.template_id))

    def replace_template(
        self,
        owner_id: str,
        record: PilotTemplateRecord,
        *,
        expected_record_sha256: str,
    ) -> PilotTemplateRecord:
        owner = _validate_owner(owner_id)
        _validate_id(record.template_id, _TEMPLATE_ID, "template")
        _validate_template_record(record)
        path = self._template_path(owner, record.template_id)
        lock_directory = self._owner_dir(owner) / "template-locks"
        lock_directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        lock_path = lock_directory / f"{record.template_id}.lock"
        with lock_path.open("a+") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            try:
                current = self._read_template(owner, record.template_id)
                if template_record_sha256(current) != expected_record_sha256:
                    raise PilotConflict("template changed; reload before updating")
                if (
                    current.template_sha256 != record.template_sha256
                    or current.check != record.check
                    or current.template != record.template
                    or current.qualification != record.qualification
                    or current.status != record.status
                    or current.reused_check != record.reused_check
                ):
                    raise PilotConflict("an approval may only change the decision")
                self._atomic_replace(path, self._envelope(owner, record))
                return record
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


__all__ = [
    "NULL_TEMPLATE_SHA256",
    "PilotStore",
    "check_content_sha256",
    "template_definition_sha256",
    "template_record_sha256",
]
