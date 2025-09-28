"""Hello World tool scaffold for the Responses tool framework."""

from __future__ import annotations

import json
from typing import Any, cast
from uuid import uuid4

from openai.types.responses import (
    FunctionToolParam,
    ResponseFunctionToolCallParam,
    ResponseInputItemParam,
)

from .base import ResponseTool, ToolExecutionResult
from .registry import registry


HELLO_WORLD_DEFINITION: FunctionToolParam = cast(
    FunctionToolParam,
    {
        "type": "function",
        "function": {
            "name": "hello_world",
            "description": "Return a static greeting so the tool pipeline can be smoke-tested.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
)
"""JSON-schema definition for the hello world tool."""


async def _execute_hello_world(
    *, arguments: dict[str, Any] | None = None
) -> ToolExecutionResult:
    """Return a greeting encoded as a Responses tool result."""

    payload = arguments or {}
    call_id = f"hello_world_{uuid4().hex}"

    tool_call = cast(
        ResponseFunctionToolCallParam,
        {
            "type": "function",
            "id": call_id,
            "function": {
                "name": HELLO_WORLD_DEFINITION["function"]["name"],
                "arguments": json.dumps(payload, separators=(",", ":")),
            },
        },
    )

    output = cast(
        ResponseInputItemParam,
        {
            "type": "tool_result",
            "tool_call_id": call_id,
            "role": "tool",
            "content": [
                {
                    "type": "output_text",
                    "text": "hello world",
                }
            ],
        },
    )

    return ToolExecutionResult(tool_call=tool_call, output=output)


hello_world_tool = ResponseTool(
    name="hello_world",
    definition=HELLO_WORLD_DEFINITION,
    executor=_execute_hello_world,
)
"""Convenience handle for the hello world tool."""

registry.register(hello_world_tool)
"""Register the hello world tool on import."""
