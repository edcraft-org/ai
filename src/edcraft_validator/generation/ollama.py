import json
import os
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from pydantic import BaseModel

from edcraft_validator.domains.code.templates import (
    CODE_TEMPLATE_SYSTEM_PROMPT,
    CodeTemplateProposal,
    build_template_prompt,
    parse_code_template_proposal,
)
from edcraft_validator.generation.base import GenerationError
from edcraft_validator.generation.models import TemplateAuthoringRequest


class OllamaTemplateGenerator:
    """Author reusable templates through Ollama's native structured endpoint."""

    def __init__(
        self, client: object | None = None, *, model: str | None = None
    ) -> None:
        self.provider = "ollama"
        self.client = client
        self.model = model or os.getenv("OLLAMA_MODEL") or "qwen2.5"

    def generate_proposal(
        self, request: TemplateAuthoringRequest
    ) -> CodeTemplateProposal:
        try:
            content = self._ollama_request(
                [
                    {"role": "system", "content": CODE_TEMPLATE_SYSTEM_PROMPT},
                    {"role": "user", "content": build_template_prompt(request)},
                ],
                CodeTemplateProposal,
            )
            if not content:
                raise ValueError("empty response")
            return parse_code_template_proposal(content)
        except Exception as exc:
            raise GenerationError(
                f"ollama returned invalid question template JSON: {exc}"
            ) from exc

    def _ollama_request(
        self, messages: list[dict[str, str]], schema: type[BaseModel]
    ) -> str:
        base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1")
        native_url = base_url.removesuffix("/v1").rstrip("/") + "/api/chat"
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "format": schema.model_json_schema(),
            "options": {"temperature": float(os.getenv("OLLAMA_TEMPERATURE", "0.2"))},
        }
        request = Request(
            native_url,
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            timeout = float(os.getenv("OLLAMA_TIMEOUT_SECONDS", "300"))
            with urlopen(request, timeout=timeout) as response:
                body = json.load(response)
            return body["message"]["content"]
        except (HTTPError, URLError, KeyError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"Ollama request failed: {exc}") from exc
