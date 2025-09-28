"""Shared scaffolding for OpenAI Responses-compatible tools."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from openai.types.responses import (
    FunctionToolParam,
)


class ToolExecutor(Protocol):
    """Protocol for async callables that execute a tool."""

    async def __call__(
        self, *, arguments: dict[str, Any] | None = None
    ) -> "ToolExecutionResult":
        """Execute the tool with optional arguments and return a structured result."""


@dataclass(slots=True)
class ToolExecutionResult:
    """Outcome produced by running a tool handler."""
    success: bool
    output: str
    error: str | None = None

@dataclass(slots=True)
class ResponseTool:
    """Container bundling the tool definition and execution handler."""

    name: str
    definition: FunctionToolParam
    executor: ToolExecutor

    async def invoke(self, *, arguments: dict[str, Any] | None = None) -> ToolExecutionResult:
        """Execute the tool and return the captured result."""

        payload = arguments or {}
        result = await self.executor(arguments=payload)
        return result

    def as_param(self) -> FunctionToolParam:
        """Expose the OpenAI Responses-compatible tool definition."""

        return self.definition
