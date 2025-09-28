"""Tool that lists uploaded files for a given tool id."""

from __future__ import annotations

from typing import Any, Mapping, Optional

from pydantic import BaseModel, Field
from openai.types.responses import FunctionToolParam

from .base import ResponseTool, ToolExecutionResult
from .filesystem import (
    DEFAULT_FOLDER_PREFIX,
    VARIATION_METADATA_FILENAME,
    VARIATION_PREFIX,
    ToolFileRecord,
    ToolNotFoundError,
    VariationNotFoundError,
    InvalidFolderPrefixError,
    list_tool_files,
    list_variations,
    normalize_folder_prefix,
    resolve_storage_root,
)
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


def _build_variation_payload(*, filename: str, relative_path: str) -> AvailableInputFile:
    return AvailableInputFile(filename=filename, path=relative_path)


def _resolve_variation_id(folder_prefix: str | None) -> str | None:
    kind, variation_id = normalize_folder_prefix(folder_prefix)
    if kind == DEFAULT_FOLDER_PREFIX:
        return None
    return variation_id


def _list_variation_files(tool_id: int, variation_id: str) -> list[AvailableInputFile]:
    records = list_variations(tool_id)
    target = next((item for item in records if item.id == variation_id), None)
    if target is None:
        raise VariationNotFoundError(f"Variation '{variation_id}' not found for tool {tool_id}")

    files: list[AvailableInputFile] = []
    seen: set[str] = set()
    for entry in target.files:
        files.append(
            _build_variation_payload(
                filename=entry.original_filename,
                relative_path=entry.original_filename,
            )
        )
        seen.add(entry.stored_filename)

    base_dir = resolve_storage_root(tool_id, f"{VARIATION_PREFIX}/{variation_id}")
    for child in base_dir.iterdir():
        if child.is_dir():
            continue
        if child.name == VARIATION_METADATA_FILENAME:
            continue
        if child.name in seen:
            continue
        files.append(
            _build_variation_payload(
                filename=child.name,
                relative_path=child.name,
            )
        )

    files.sort(key=lambda item: item.filename.lower())
    return files


async def _execute_get_available_input_files(
    *,
    tool_id: int,
    arguments: Optional[Mapping[str, Any]] = None,
    folder_prefix: str | None = None,
) -> ToolExecutionResult:
    _args = GetAvailableInputFilesArgs.model_validate(arguments or {})

    try:
        variation_id = _resolve_variation_id(folder_prefix)
        if variation_id is None:
            records = list_tool_files(tool_id)
            payload_files = [_build_file_payload(record) for record in records]
        else:
            payload_files = _list_variation_files(tool_id, variation_id)
    except ToolNotFoundError as exc:
        return ToolExecutionResult(success=False, output="{}", error=str(exc))
    except (VariationNotFoundError, InvalidFolderPrefixError) as exc:
        return ToolExecutionResult(success=False, output="{}", error=str(exc))

    payload = GetAvailableInputFilesResult(
        tool_id=tool_id,
        files=payload_files,
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
