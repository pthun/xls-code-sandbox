"""Edit tool that writes a rectangular block of values."""

from __future__ import annotations

from typing import Mapping, Optional

from openai.types.responses import FunctionToolParam
from pydantic import BaseModel, Field, model_validator

from .base import ResponseTool, ToolExecutionResult
from .excel_common import (
    Result,
    format_range,
    get_required_sheet,
    open_workbook_for_write,
    parse_cell_reference,
    resolve_workbook_record,
    result_from_exception,
    save_workbook_atomic,
    serialize_result,
)
from .registry import registry


class WriteRangeParams(BaseModel):
    path: str = Field(..., description="Path (relative to tool uploads) to the workbook.")
    sheet: str = Field(..., description="Name of the target sheet.")
    top_left: str = Field(..., description="Top-left cell coordinate (e.g. 'B3').")
    rows: list[list[object | None]] = Field(..., min_length=1, description="2D array of values to write.")

    @model_validator(mode="after")
    def _ensure_non_empty_rows(self) -> "WriteRangeParams":
        if not any(row for row in self.rows if len(row) > 0):
            raise ValueError("At least one value must be provided for write_range.")
        return self


class WriteRangeData(BaseModel):
    written_rows: int
    written_cols: int
    ref: str


WRITE_RANGE_NAME = "write_range"

WRITE_RANGE_DEFINITION = FunctionToolParam(
    type="function",
    name=WRITE_RANGE_NAME,
    description="Write a rectangular block of values into a worksheet.",
    parameters=WriteRangeParams.model_json_schema(),
    strict=False,
)


async def _execute_write_range(
    *,
    tool_id: int,
    arguments: Optional[Mapping[str, object]] = None,
    folder_prefix: str | None = None,
) -> ToolExecutionResult:
    args = WriteRangeParams.model_validate(arguments or {})

    try:
        start_row, start_col = parse_cell_reference(args.top_left)
        written_rows = len(args.rows)
        written_cols = max(len(row) for row in args.rows)
        if written_cols == 0:
            raise ValueError("Rows must contain at least one column value.")

        record = resolve_workbook_record(tool_id, args.path, folder_prefix=folder_prefix)
        with open_workbook_for_write(record.path) as workbook:
            sheet = get_required_sheet(workbook, args.sheet)
            for row_offset, row_values in enumerate(args.rows):
                row_index = start_row + row_offset
                for col_offset, value in enumerate(row_values):
                    column_index = start_col + col_offset
                    sheet.cell(row=row_index, column=column_index).value = value
            save_workbook_atomic(workbook, record.path)

        end_row = start_row + written_rows - 1
        end_col = start_col + written_cols - 1
        ref = format_range(start_row, start_col, end_row, end_col)
        data = WriteRangeData(
            written_rows=written_rows,
            written_cols=written_cols,
            ref=ref,
        )
        result: Result[WriteRangeData] = Result[WriteRangeData].ok(data)
        return ToolExecutionResult(success=True, output=serialize_result(result))
    except Exception as exc:  # pragma: no cover - defensive umbrella
        error_result = result_from_exception(exc)
        return ToolExecutionResult(
            success=False,
            output=serialize_result(error_result),
            error=error_result.message,
        )


write_range_tool = ResponseTool(
    name=WRITE_RANGE_NAME,
    definition=WRITE_RANGE_DEFINITION,
    executor=_execute_write_range,
)

registry.register(write_range_tool)

__all__ = [
    "WRITE_RANGE_NAME",
    "WRITE_RANGE_DEFINITION",
    "WriteRangeData",
    "write_range_tool",
]
