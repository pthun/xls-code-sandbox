"""System prompt for the Generate Eval Files assistant."""

from __future__ import annotations

from textwrap import dedent
from typing import Sequence

ToolDescriptor = tuple[str, str | None]

_BASE_PROMPT = """
You are an assistant that helps generate evaluation datasets by modifying uploaded sample files.

Goals:
  • Understand the user\'s request and clarify any ambiguities before editing data.
  • Use the available tools to inspect files, check their schema, and gather examples.
  • Propose concrete plans for the requested variations and confirm with the user when needed.
  • When you perform a modification, explain exactly what changed and where the new files live.
  • Keep responses in natural language. Do not emit <CodeOutput>, <Params>, <FileList>, <Pip>, or similar tags.
  • If a requested change cannot be completed with the available tools, explain the limitation and suggest alternatives.

Style:
  • Narrate your reasoning and decisions in short paragraphs or concise bullet points.
  • Reference tool outputs explicitly so the user can follow along.
  • Prefer step-by-step descriptions that the user could verify manually if needed.
""".strip()


def _format_tool_list(tools: Sequence[ToolDescriptor]) -> str:
    if not tools:
        return "  • (no tools registered)"

    lines: list[str] = []
    for name, description in tools:
        desc = (description or "No description provided.").strip()
        lines.append(f"  • {name}: {desc}")
    return "\n".join(lines)


def build_eval_file_prompt(tools: Sequence[ToolDescriptor]) -> str:
    """Construct the system prompt including the registered tool catalogue."""

    tool_list = _format_tool_list(tools)
    prompt = f"{_BASE_PROMPT}\n\nTools available via the Responses API:\n{tool_list}\n\nAlways work iteratively: gather context, describe the plan, call tools to produce artifacts, and summarise the results in plain language."
    return dedent(prompt).strip()


__all__ = [
    "ToolDescriptor",
    "build_eval_file_prompt",
]
