"""Edit tool applying multiple cell updates in one call."""

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
    parse_column_ref,
    resolve_workbook_record,
    result_from_exception,
    save_workbook_atomic,
    serialize_result,
)
from .registry import registry


class BulkUpdateItem(BaseModel):
    row: int = Field(..., ge=1)
    column: int | str
    value: object | None


class BulkUpdateParams(BaseModel):
    path: str = Field(..., description="Path (relative to tool uploads) to the workbook.")
    sheet: str = Field(..., description="Name of the sheet containing the cells.")
    updates: list[BulkUpdateItem] = Field(..., min_length=1)


class BulkUpdateData(BaseModel):
    count: int


BULK_UPDATE_NAME = "bulk_update"

BULK_UPDATE_DEFINITION = FunctionToolParam(
    type="function",
    name=BULK_UPDATE_NAME,
    description="Apply multiple cell updates in a single operation.",
    parameters=BulkUpdateParams.model_json_schema(),
    strict=False,
)


async def _execute_bulk_update(
    *,
    tool_id: int,
    arguments: Optional[Mapping[str, object]] = None,
    folder_prefix: str | None = None,
) -> ToolExecutionResult:
    args = BulkUpdateParams.model_validate(arguments or {})

    try:
        record = resolve_workbook_record(tool_id, args.path, folder_prefix=folder_prefix)
        with open_workbook_for_write(record.path) as workbook:
            sheet = get_required_sheet(workbook, args.sheet)
            for item in args.updates:
                row_index = normalize_row(item.row)
                column_index = parse_column_ref(item.column)
                sheet.cell(row=row_index, column=column_index).value = item.value
            save_workbook_atomic(workbook, record.path)
        data = BulkUpdateData(count=len(args.updates))
        result: Result[BulkUpdateData] = Result[BulkUpdateData].ok(data)
        return ToolExecutionResult(success=True, output=serialize_result(result))
    except Exception as exc:  # pragma: no cover - defensive umbrella
        error_result = result_from_exception(exc)
        return ToolExecutionResult(
            success=False,
            output=serialize_result(error_result),
            error=error_result.message,
        )


bulk_update_tool = ResponseTool(
    name=BULK_UPDATE_NAME,
    definition=BULK_UPDATE_DEFINITION,
    executor=_execute_bulk_update,
)

registry.register(bulk_update_tool)

__all__ = [
    "BULK_UPDATE_NAME",
    "BULK_UPDATE_DEFINITION",
    "BulkUpdateData",
    "bulk_update_tool",
]
