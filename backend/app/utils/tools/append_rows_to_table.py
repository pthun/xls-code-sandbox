"""Edit tool that appends rows to an existing Excel table."""

from __future__ import annotations

from typing import Mapping, Optional

from openai.types.responses import FunctionToolParam
from pydantic import BaseModel, Field, model_validator

from .base import ResponseTool, ToolExecutionResult
from .excel_common import (
    Result,
    WorkbookItemNotFoundError,
    format_range,
    get_required_sheet,
    open_workbook_for_write,
    parse_a1_range,
    resolve_workbook_record,
    result_from_exception,
    save_workbook_atomic,
    serialize_result,
)
from .registry import registry


class AppendRowsToTableParams(BaseModel):
    path: str = Field(..., description="Path (relative to tool uploads) to the workbook.")
    sheet: str = Field(..., description="Name of the sheet containing the table.")
    table_name: str = Field(..., min_length=1, description="Name of the table to modify.")
    rows: list[list[object | None]] = Field(..., min_length=1, description="Rows to append to the table.")

    @model_validator(mode="after")
    def _ensure_rows_present(self) -> "AppendRowsToTableParams":
        if not any(self.rows):
            raise ValueError("At least one row with data must be provided.")
        return self


class AppendRowsToTableData(BaseModel):
    table_name: str
    ref: str
    appended: int


APPEND_ROWS_TO_TABLE_NAME = "append_rows_to_table"

APPEND_ROWS_TO_TABLE_DEFINITION = FunctionToolParam(
    type="function",
    name=APPEND_ROWS_TO_TABLE_NAME,
    description="Append data rows to an existing table, expanding its range.",
    parameters=AppendRowsToTableParams.model_json_schema(),
    strict=False,
)


def _pad_row(row: list[object | None], width: int) -> list[object | None]:
    if len(row) > width:
        raise ValueError(f"Provided row has {len(row)} values but table expects {width} columns.")
    if len(row) < width:
        return row + [None] * (width - len(row))
    return row


async def _execute_append_rows_to_table(
    *,
    tool_id: int,
    arguments: Optional[Mapping[str, object]] = None,
    folder_prefix: str | None = None,
) -> ToolExecutionResult:
    args = AppendRowsToTableParams.model_validate(arguments or {})

    try:
        record = resolve_workbook_record(tool_id, args.path, folder_prefix=folder_prefix)
        with open_workbook_for_write(record.path) as workbook:
            sheet = get_required_sheet(workbook, args.sheet)
            table = getattr(sheet, "tables", {}).get(args.table_name)
            if table is None:
                raise WorkbookItemNotFoundError(
                    f"Table '{args.table_name}' not found on sheet '{sheet.title}'."
                )
            min_row, min_col, max_row, max_col = parse_a1_range(table.ref)
            width = max_col - min_col + 1
            padded_rows = [_pad_row(list(row), width) for row in args.rows]
            append_start = max_row + 1
            for row_offset, row_values in enumerate(padded_rows):
                row_index = append_start + row_offset
                for col_offset, value in enumerate(row_values):
                    sheet.cell(row=row_index, column=min_col + col_offset).value = value
            new_max_row = max_row + len(padded_rows)
            table.ref = format_range(min_row, min_col, new_max_row, max_col)
            save_workbook_atomic(workbook, record.path)
        data = AppendRowsToTableData(
            table_name=args.table_name,
            ref=format_range(min_row, min_col, new_max_row, max_col),
            appended=len(args.rows),
        )
        result: Result[AppendRowsToTableData] = Result[AppendRowsToTableData].ok(data)
        return ToolExecutionResult(success=True, output=serialize_result(result))
    except Exception as exc:  # pragma: no cover - defensive umbrella
        error_result = result_from_exception(exc)
        return ToolExecutionResult(
            success=False,
            output=serialize_result(error_result),
            error=error_result.message,
        )


append_rows_to_table_tool = ResponseTool(
    name=APPEND_ROWS_TO_TABLE_NAME,
    definition=APPEND_ROWS_TO_TABLE_DEFINITION,
    executor=_execute_append_rows_to_table,
)

registry.register(append_rows_to_table_tool)

__all__ = [
    "APPEND_ROWS_TO_TABLE_NAME",
    "APPEND_ROWS_TO_TABLE_DEFINITION",
    "AppendRowsToTableData",
    "append_rows_to_table_tool",
]
