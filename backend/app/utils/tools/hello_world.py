"""Hello World tool scaffold using Pydantic models for params and output.

Key changes:
- Params and output are Pydantic `BaseModel`s.
- `FunctionToolParam.parameters` is derived from `HelloWorldArgs.model_json_schema()` (Pydantic v2).
- Execution parses with `.model_validate()` and emits output with `.model_dump_json()`.
"""
from __future__ import annotations

from typing import Any, Mapping, Optional

from pydantic import BaseModel, Field
from openai.types.responses import (
    FunctionToolParam,
)

from .base import ResponseTool, ToolExecutionResult
from .registry import registry

# ——————————————————————————————————————————————————————————————
# Pydantic models (params & result)
# ——————————————————————————————————————————————————————————————
class HelloWorldArgs(BaseModel):
    """Arguments accepted by the hello_world tool.

    Add fields as needed; keeping one optional field here to demo parsing.
    """

    name: Optional[str] = Field(
        default=None,
        description="Optional name to greet (defaults to 'world').",
    )


class HelloWorldResult(BaseModel):
    """JSON-serializable result returned from the tool."""

    message: str = Field(description="Greeting message produced by the tool.")


# ——————————————————————————————————————————————————————————————
# Constants & schema (derived from Pydantic)
# ——————————————————————————————————————————————————————————————
HELLO_WORLD_NAME: str = "hello_world"

HELLO_WORLD_DEFINITION: FunctionToolParam = FunctionToolParam(
    type="function",
    name=HELLO_WORLD_NAME,
    description=(
        "Return a static greeting so the tool pipeline can be smoke-tested."
    ),
    # IMPORTANT: parameters come directly from the Pydantic model schema
    parameters=HelloWorldArgs.model_json_schema(),
    strict=False,
)
"""JSON Schema definition for the hello_world tool (via Pydantic)."""


# ——————————————————————————————————————————————————————————————
# Executor
# ——————————————————————————————————————————————————————————————
async def _execute_hello_world(*, arguments: Optional[Mapping[str, Any]] = None) -> ToolExecutionResult:
    """Execute the hello_world tool and produce a Responses-compliant result.

    Steps:
      1) Parse/validate `arguments` with Pydantic
      2) Perform the work (execution body)
      3) Package a tool_call + tool_output for the Responses API
    """

    # 1) Parse/validate with Pydantic
    _args = HelloWorldArgs.model_validate(arguments or {})

    # 2) ———— EXECUTION BODY (put your business logic here) ————
    who = _args.name.strip() if _args.name else "world"
    result = HelloWorldResult(message=f"hello {who}")
    # ————————————————————————————————————————————————————————————

    return ToolExecutionResult(
        success=True,
        output=result.model_dump_json(),
    )


# ——————————————————————————————————————————————————————————————
# Tool handle & registration
# ——————————————————————————————————————————————————————————————
hello_world_tool: ResponseTool = ResponseTool(
    name=HELLO_WORLD_NAME,
    definition=HELLO_WORLD_DEFINITION,
    executor=_execute_hello_world,
)

# Register on import
registry.register(hello_world_tool)

__all__ = [
    "HELLO_WORLD_NAME",
    "HELLO_WORLD_DEFINITION",
    "HelloWorldArgs",
    "HelloWorldResult",
    "hello_world_tool",
]
