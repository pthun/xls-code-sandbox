"""Tool that lists uploaded files for a given tool id."""

from __future__ import annotations

from typing import Any, Mapping, Optional

from pydantic import BaseModel, Field
from openai.types.responses import FunctionToolParam

from .base import ResponseTool, ToolExecutionResult
from .filesystem import ToolFileRecord, ToolNotFoundError, list_tool_files
from .registry import registry


class GetAvailableInputFilesArgs(BaseModel):
    """Arguments accepted by the get_available_input_files tool."""

    pass

class AvailableInputFile(BaseModel):
    """Minimal metadata describing an uploaded input file."""

    filename: str = Field(description="Human-readable name of the uploaded file.")
    path: str = Field(
        description=(
            "Path to use when referencing the file within this tool's uploads directory."
        )
    )


class GetAvailableInputFilesResult(BaseModel):
    """JSON-serialisable result payload for the tool."""

    tool_id: int
    files: list[AvailableInputFile]


GET_AVAILABLE_INPUT_FILES_NAME = "get_available_input_files"

GET_AVAILABLE_INPUT_FILES_DEFINITION = FunctionToolParam(
    type="function",
    name=GET_AVAILABLE_INPUT_FILES_NAME,
    description=(
        "List uploaded input files for a tool and provide their filesystem paths."
    ),
    parameters=GetAvailableInputFilesArgs.model_json_schema(),
    strict=False,
)


def _build_file_payload(record: ToolFileRecord) -> AvailableInputFile:
    human_path = record.original_filename
    return AvailableInputFile(
        filename=record.original_filename,
        path=human_path,
    )


async def _execute_get_available_input_files(
    *, tool_id: int, arguments: Optional[Mapping[str, Any]] = None
) -> ToolExecutionResult:
    _args = GetAvailableInputFilesArgs.model_validate(arguments or {})

    try:
        records = list_tool_files(tool_id)
    except ToolNotFoundError as exc:
        return ToolExecutionResult(success=False, output="{}", error=str(exc))

    payload = GetAvailableInputFilesResult(
        tool_id=tool_id,
        files=[_build_file_payload(record) for record in records],
    )

    return ToolExecutionResult(
        success=True,
        output=payload.model_dump_json(),
    )


get_available_input_files_tool = ResponseTool(
    name=GET_AVAILABLE_INPUT_FILES_NAME,
    definition=GET_AVAILABLE_INPUT_FILES_DEFINITION,
    executor=_execute_get_available_input_files,
)

registry.register(get_available_input_files_tool)

__all__ = [
    "GET_AVAILABLE_INPUT_FILES_NAME",
    "GET_AVAILABLE_INPUT_FILES_DEFINITION",
    "GetAvailableInputFilesArgs",
    "GetAvailableInputFilesResult",
    "get_available_input_files_tool",
]
