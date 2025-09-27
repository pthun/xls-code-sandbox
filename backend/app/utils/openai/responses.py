"""Helpers for invoking the OpenAI Responses API."""

from __future__ import annotations

import re
from typing import List, Literal, Sequence

from openai import OpenAI
from openai.types.responses import (
    Response,
    ResponseInputItemParam,
    ResponseOutputMessage,
    ResponseOutputText,
    ResponseUsage,
)
from openai.types.responses.easy_input_message_param import EasyInputMessageParam


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

    code = code_blocks[-1] if code_blocks else None
    pip_packages = _split_packages(pip_blocks)
    display_text = _strip_tags(raw_text, ("CodeOutput", "Pip"))

    usage: ResponseUsage | None = response.usage
    prompt_tokens = usage.input_tokens if usage else None
    completion_tokens = usage.output_tokens if usage else None
    total_tokens = usage.total_tokens if usage else None

    return (
        response,
        display_text,
        code,
        pip_packages,
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


def _strip_tags(text: str, tags: Sequence[str]) -> str:
    cleaned = text
    for tag in tags:
        cleaned = re.sub(rf"<{tag}>.*?</{tag}>", "", cleaned, flags=re.IGNORECASE | re.DOTALL)
    return cleaned.strip()
