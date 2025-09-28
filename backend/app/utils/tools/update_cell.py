"""Edit tool for updating a single cell."""

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
    to_a1,
)
from .registry import registry


class UpdateCellParams(BaseModel):
    path: str = Field(..., description="Path (relative to tool uploads) to the workbook.")
    sheet: str = Field(..., description="Name of the sheet containing the cell.")
    row: int = Field(..., ge=1, description="1-based row index of the cell.")
    column: int | str = Field(..., description="1-based column index or Excel column letter.")
    value: object | None = Field(..., description="The value to write. Strings starting with '=' become formulas.")


class UpdateCellData(BaseModel):
    cell: str


UPDATE_CELL_NAME = "update_cell"

UPDATE_CELL_DEFINITION = FunctionToolParam(
    type="function",
    name=UPDATE_CELL_NAME,
    description="Update the value of a single cell.",
    parameters=UpdateCellParams.model_json_schema(),
    strict=False,
)


async def _execute_update_cell(
    *,
    tool_id: int,
    arguments: Optional[Mapping[str, object]] = None,
    folder_prefix: str | None = None,
) -> ToolExecutionResult:
    args = UpdateCellParams.model_validate(arguments or {})

    try:
        record = resolve_workbook_record(tool_id, args.path, folder_prefix=folder_prefix)
        column_index = parse_column_ref(args.column)
        row_index = normalize_row(args.row)
        coord = to_a1(row_index, column_index)
        with open_workbook_for_write(record.path) as workbook:
            sheet = get_required_sheet(workbook, args.sheet)
            sheet.cell(row=row_index, column=column_index).value = args.value
            save_workbook_atomic(workbook, record.path)
        data = UpdateCellData(cell=coord)
        result: Result[UpdateCellData] = Result[UpdateCellData].ok(data)
        return ToolExecutionResult(success=True, output=serialize_result(result))
    except Exception as exc:  # pragma: no cover - defensive umbrella
        error_result = result_from_exception(exc)
        return ToolExecutionResult(
            success=False,
            output=serialize_result(error_result),
            error=error_result.message,
        )


update_cell_tool = ResponseTool(
    name=UPDATE_CELL_NAME,
    definition=UPDATE_CELL_DEFINITION,
    executor=_execute_update_cell,
)

registry.register(update_cell_tool)

__all__ = [
    "UPDATE_CELL_NAME",
    "UPDATE_CELL_DEFINITION",
    "UpdateCellData",
    "update_cell_tool",
]
