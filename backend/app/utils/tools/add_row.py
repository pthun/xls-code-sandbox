"""Edit tool that inserts or appends a row."""

from __future__ import annotations

from typing import Mapping, Optional

from openai.types.responses import FunctionToolParam
from pydantic import BaseModel, Field

from .base import ResponseTool, ToolExecutionResult
from .excel_common import (
    Result,
    get_required_sheet,
    normalize_row,
    open_workbook_for_write,
    resolve_workbook_record,
    result_from_exception,
    save_workbook_atomic,
    serialize_result,
)
from .registry import registry


class AddRowParams(BaseModel):
    path: str = Field(..., description="Path (relative to tool uploads) to the workbook.")
    sheet: str = Field(..., description="Name of the target sheet.")
    values: list[object | None] = Field(default_factory=list, description="Values for the row.")
    index: int | None = Field(None, ge=1, description="Optional 1-based index to insert before. Append when omitted.")


class AddRowData(BaseModel):
    rows_total: int
    inserted_at: int


ADD_ROW_NAME = "add_row"

ADD_ROW_DEFINITION = FunctionToolParam(
    type="function",
    name=ADD_ROW_NAME,
    description="Insert or append a row in a worksheet.",
    parameters=AddRowParams.model_json_schema(),
    strict=False,
)


async def _execute_add_row(
    *,
    tool_id: int,
    arguments: Optional[Mapping[str, object]] = None,
    folder_prefix: str | None = None,
) -> ToolExecutionResult:
    args = AddRowParams.model_validate(arguments or {})

    try:
        record = resolve_workbook_record(tool_id, args.path, folder_prefix=folder_prefix)
        with open_workbook_for_write(record.path) as workbook:
            sheet = get_required_sheet(workbook, args.sheet)
            if args.index is None:
                sheet.append(list(args.values))
                inserted_at = sheet.max_row
            else:
                inserted_at = normalize_row(args.index)
                sheet.insert_rows(inserted_at)
                for offset, value in enumerate(args.values, start=1):
                    sheet.cell(row=inserted_at, column=offset).value = value
            rows_total = sheet.max_row
            save_workbook_atomic(workbook, record.path)
        data = AddRowData(rows_total=rows_total, inserted_at=inserted_at)
        result: Result[AddRowData] = Result[AddRowData].ok(data)
        return ToolExecutionResult(success=True, output=serialize_result(result))
    except Exception as exc:  # pragma: no cover - defensive umbrella
        error_result = result_from_exception(exc)
        return ToolExecutionResult(
            success=False,
            output=serialize_result(error_result),
            error=error_result.message,
        )


add_row_tool = ResponseTool(
    name=ADD_ROW_NAME,
    definition=ADD_ROW_DEFINITION,
    executor=_execute_add_row,
)

registry.register(add_row_tool)

__all__ = [
    "ADD_ROW_NAME",
    "ADD_ROW_DEFINITION",
    "AddRowData",
    "add_row_tool",
]
