"""Tool that lists uploaded files for a given tool id."""

from __future__ import annotations

from typing import Any, Mapping, Optional

from pydantic import BaseModel, Field
from openai.types.responses import FunctionToolParam

from .base import ResponseTool, ToolExecutionResult
from .filesystem import ToolFileRecord, ToolNotFoundError, UPLOAD_ROOT, list_tool_files
from .registry import registry


class GetAvailableInputFilesArgs(BaseModel):
    """Arguments accepted by the get_available_input_files tool."""

    pass

class AvailableInputFile(BaseModel):
    """Metadata about an uploaded input file."""

    id: int
    path: str = Field(description="Absolute path to the stored file on disk.")
    relative_path: str = Field(
        description="Path to the file relative to the uploads root.")
    original_filename: str
    stored_filename: str
    size_bytes: int
    content_type: str | None
    uploaded_at: str
    exists: bool


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
    base = UPLOAD_ROOT.resolve()
    relative_path = record.path.relative_to(base) if record.path.is_relative_to(base) else record.stored_filename
    return AvailableInputFile(
        id=record.id,
        path=str(record.path),
        relative_path=str(relative_path),
        original_filename=record.original_filename,
        stored_filename=record.stored_filename,
        size_bytes=record.size_bytes,
        content_type=record.content_type,
        uploaded_at=record.uploaded_at.isoformat(),
        exists=record.exists,
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
