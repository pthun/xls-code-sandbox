"""Helpers for invoking the OpenAI Responses API."""

from __future__ import annotations

import json
import re
from typing import List, Literal, Sequence, Any

from openai import OpenAI
from openai.types.responses import (
    Response,
    ResponseInputItemParam,
    ResponseOutputMessage,
    ResponseOutputText,
    ResponseUsage,
)
from openai.types.responses.easy_input_message_param import EasyInputMessageParam
from ..misc.typeguards import is_any_list

RoleLiteral = Literal["user", "assistant", "system", "developer"]


def call_openai_responses(
    *,
    api_key: str,
    system_prompt: str,
    messages: Sequence[tuple[RoleLiteral, str]],
    model_name: str,
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
    """

    client = OpenAI(api_key=api_key)
    prompt = _build_prompt(system_prompt, messages)
    response = client.responses.create(model=model_name, input=prompt)

    raw_text = _extract_text(response)
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
    )


def _build_prompt(
    system_prompt: str, messages: Sequence[tuple[RoleLiteral, str]]
) -> List[ResponseInputItemParam]:
    prompt: List[ResponseInputItemParam] = [
        EasyInputMessageParam(
            role="system",
            content=system_prompt.strip(),
            type="message",
        )
    ]

    for role, content in messages:
        text = content.strip()
        if not text:
            continue
        prompt.append(
            EasyInputMessageParam(
                role=role,
                content=text,
                type="message",
            )
        )

    return prompt

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
