"""The application-facing check interface, independent of the MCP implementation."""

from typing import Any, Protocol, Self


class ToolClient(Protocol):
    def __enter__(self) -> Self: ...

    def __exit__(self, *args: Any) -> None: ...

    def list_tools(self) -> list[dict[str, Any]]: ...

    def call_tool(
        self, name: str, arguments: dict[str, Any], *, version: str | None = None
    ) -> dict[str, Any]: ...
