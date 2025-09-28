"""Helpers for invoking the OpenAI Responses API."""

from __future__ import annotations

import json
import re
from typing import Any, List, Sequence

from openai import AsyncOpenAI
from openai.types.responses import (
    FunctionToolParam,
    Response,
    ResponseInputItemParam,
    ResponseOutputMessage,
    ResponseOutputText,
    ResponseUsage,
    ResponseFunctionToolCallParam,
)

from ..misc.typeguards import is_any_list
from ..tools.base import ResponseTool, ToolExecutionResult
from ..tools.registry import registry as tool_registry

async def call_openai_responses(
    *,
    tool_id: int,
    api_key: str,
    system_prompt: str,
    messages: list[ResponseInputItemParam],
    model_name: str,
    tool_names: list[str] | None = None,
    max_tool_iterations: int = 3,
    parse_structured_tags: bool = True,
    folder_prefix: str | None = None,
) -> tuple[
    Response,
    str,
    str | None,
    list[str],
    list[dict[str, Any]],
    list[dict[str, Any]],
    bool,
    bool,
    int | None,
    int | None,
    int | None,
    str,
    list[ToolExecutionResult],
]:
    """Call the Responses API and return raw/parsed artefacts.

    The returned tuple contains:
        - the raw Response object
        - display text with code/pip tags removed
        - latest code block (or None)
        - list of pip packages
        - prompt token usage (if reported)
        - completion token usage (if reported)
        - total token usage (if reported)
        - executed tool call details (if any were triggered)
    Raises:
        KeyError: If a requested tool name is not registered.
    """

    client = AsyncOpenAI(api_key=api_key)
    history = messages

    available_tools: list[FunctionToolParam] = []
    tool_handlers: dict[str, ResponseTool] = {}

    if tool_names:
        seen: set[str] = set()
        for name in tool_names:
            if name in seen:
                continue
            seen.add(name)
            tool = tool_registry.get(name)
            available_tools.append(tool.definition)
            tool_handlers[tool.name] = tool

    executed_tools: list[ToolExecutionResult] = []

    response: Response | None = None

    for _iteration in range(max(max_tool_iterations, 0) + 1):
        response = await client.responses.create(
            model=model_name,
            instructions=system_prompt,
            input=history,
            tools=available_tools,
        )

        tool_calls = [output for output in response.output if output.type == "function_call"]
        if not tool_calls:
            history.append({
                "role": "assistant",
                "content": response.output_text
            })
            break # Finished tool calling iterations, proceed to parsing output

        for call in tool_calls:
            
            tool = tool_handlers.get(call.name)
            if tool is None:
                msg = f"No executor registered for tool '{call.name}'"
                raise KeyError(msg)

            arguments_raw = call.arguments
            arguments = json.loads(arguments_raw)

            execution = await tool.invoke(
                tool_id=tool_id,
                arguments=arguments,
                folder_prefix=folder_prefix,
            )
            if not execution.success:
                print(f"Tool '{tool.name}' execution failed: {execution.error}")

            history.append(ResponseFunctionToolCallParam(**call.model_dump()))
            history.append({
                "type": "function_call_output",
                "call_id": call.call_id,
                "output": str(execution),
            })

            executed_tools.append(execution)
    else:  # pragma: no cover - defensive guard for runaway tool loops
        msg = "Exceeded maximum tool iterations without completing the response"
        raise RuntimeError(msg)

    if response is None:  # pyright: ignore[reportUnnecessaryComparison]
        raise RuntimeError("Failed to obtain a response from OpenAI")

    raw_text = _extract_text(response)

    if parse_structured_tags:
        code_blocks = _extract_tagged_blocks(raw_text, "CodeOutput")
        pip_blocks = _extract_tagged_blocks(raw_text, "Pip")
        params_blocks = _extract_tagged_blocks(raw_text, "Params")
        file_blocks = _extract_tagged_blocks(raw_text, "FileList")

        code = code_blocks[-1] if code_blocks else None
        pip_packages = _split_packages(pip_blocks)
        params_present = bool(params_blocks)
        file_present = bool(file_blocks)
        params_model = _parse_json_array(params_blocks[-1] if params_blocks else None)
        file_requirements = _parse_json_array(file_blocks[-1] if file_blocks else None)
        display_text = _strip_tags(raw_text, ("CodeOutput", "Pip", "Params", "FileList"))
    else:
        code = None
        pip_packages: list[str] = []
        params_present = False
        file_present = False
        params_model: list[dict[str, Any]] = []
        file_requirements: list[dict[str, Any]] = []
        display_text = raw_text.strip()

    usage: ResponseUsage | None = response.usage
    prompt_tokens = usage.input_tokens if usage else None
    completion_tokens = usage.output_tokens if usage else None
    total_tokens = usage.total_tokens if usage else None

    return (
        response,
        display_text,
        code,
        pip_packages,
        params_model,
        file_requirements,
        params_present,
        file_present,
        prompt_tokens,
        completion_tokens,
        total_tokens,
        raw_text,
        executed_tools,
    )

def _extract_text(response: Response) -> str:
    segments: List[str] = []
    for item in response.output or []:
        if isinstance(item, ResponseOutputMessage):
            for content in item.content:
                if isinstance(content, ResponseOutputText):
                    segments.append(content.text)
    if segments:
        return "".join(segments)
    raise ValueError("OpenAI response did not include textual content")


def _extract_tagged_blocks(text: str, tag: str) -> list[str]:
    pattern = re.compile(rf"<{tag}>(.*?)</{tag}>", re.IGNORECASE | re.DOTALL)
    return [match.group(1).strip() for match in pattern.finditer(text)]


def _split_packages(blocks: Sequence[str]) -> list[str]:
    packages: list[str] = []
    for block in blocks:
        for line in block.splitlines():
            pkg = line.strip()
            if pkg:
                packages.append(pkg)
    return packages


def _parse_json_array(block: str | None) -> list[dict[str, Any]]:
    if not block:
        return []
    try:
        data = json.loads(block)
    except json.JSONDecodeError:
        return []
    if is_any_list(data):
        return [item for item in data if isinstance(item, dict)]
    return []


def _strip_tags(text: str, tags: Sequence[str]) -> str:
    cleaned = text
    for tag in tags:
        cleaned = re.sub(rf"<{tag}>.*?</{tag}>", "", cleaned, flags=re.IGNORECASE | re.DOTALL)
    return cleaned.strip()
