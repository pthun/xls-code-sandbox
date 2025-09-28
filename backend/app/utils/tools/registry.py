"""Simple in-memory registry for response-compatible tools."""

from __future__ import annotations

from typing import Iterable, Sequence

from openai.types.responses import FunctionToolParam

from .base import ResponseTool


class ToolRegistry:
    """Registry that stores tools by name and exposes their definitions."""

    def __init__(self) -> None:
        self._tools: dict[str, ResponseTool] = {}

    def register(self, tool: ResponseTool) -> None:
        """Add a tool to the registry, enforcing unique names."""

        if tool.name in self._tools:
            msg = f"tool '{tool.name}' is already registered"
            raise ValueError(msg)
        self._tools[tool.name] = tool

    def get(self, name: str) -> ResponseTool:
        """Fetch a tool by name."""

        if name not in self._tools:
            msg = f"tool '{name}' is not registered"
            raise KeyError(msg)
        return self._tools[name]

    def get_many(self, names: Sequence[str]) -> list[ResponseTool]:
        """Fetch multiple tools, preserving the requested order."""

        tools: list[ResponseTool] = []
        for name in names:
            tools.append(self.get(name))
        return tools

    def values(self) -> Iterable[ResponseTool]:
        """Iterate over registered tools."""

        return self._tools.values()

    def definitions(self, names: Sequence[str] | None = None) -> list[FunctionToolParam]:
        """Return tool definitions, optionally filtered by name."""

        if names is not None:
            return [tool.as_param() for tool in self.get_many(names)]

        return [tool.as_param() for tool in self._tools.values()]


registry = ToolRegistry()
"""Global registry used by the application."""
