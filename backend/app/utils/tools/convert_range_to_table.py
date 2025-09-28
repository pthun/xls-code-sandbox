"""Edit tool that converts a range into an Excel table."""

from __future__ import annotations

from typing import Mapping, Optional

from openai.types.responses import FunctionToolParam
from pydantic import BaseModel, Field

from .base import ResponseTool, ToolExecutionResult
from .excel_common import (
    ConflictError,
    Result,
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


class ConvertRangeToTableParams(BaseModel):
    path: str = Field(..., description="Path (relative to tool uploads) to the workbook.")
    sheet: str = Field(..., description="Name of the target sheet.")
    a1_range: str = Field(..., description="Range to convert, e.g. 'A1:C10'.")
    table_name: str = Field("Table1", min_length=1, description="Name for the new table.")
    style_name: str = Field("TableStyleMedium9", description="Table style to apply.")


class ConvertToTableData(BaseModel):
    sheet: str
    table_name: str
    ref: str


CONVERT_RANGE_TO_TABLE_NAME = "convert_range_to_table"

CONVERT_RANGE_TO_TABLE_DEFINITION = FunctionToolParam(
    type="function",
    name=CONVERT_RANGE_TO_TABLE_NAME,
    description="Convert a rectangular range into an Excel table.",
    parameters=ConvertRangeToTableParams.model_json_schema(),
    strict=False,
)


def _create_table(sheet, ref: str, table_name: str, style_name: str) -> None:
    from openpyxl.worksheet.table import Table, TableStyleInfo  # type: ignore[import]

    if table_name in getattr(sheet, "tables", {}):
        raise ConflictError(f"Table '{table_name}' already exists on sheet '{sheet.title}'.")

    table = Table(displayName=table_name, ref=ref)
    style = TableStyleInfo(name=style_name, showRowStripes=True, showColumnStripes=False)
    table.tableStyleInfo = style
    sheet.add_table(table)


async def _execute_convert_range_to_table(
    *,
    tool_id: int,
    arguments: Optional[Mapping[str, object]] = None,
    folder_prefix: str | None = None,
) -> ToolExecutionResult:
    args = ConvertRangeToTableParams.model_validate(arguments or {})

    try:
        min_row, min_col, max_row, max_col = parse_a1_range(args.a1_range)
        ref = format_range(min_row, min_col, max_row, max_col)
        record = resolve_workbook_record(tool_id, args.path, folder_prefix=folder_prefix)
        with open_workbook_for_write(record.path) as workbook:
            sheet = get_required_sheet(workbook, args.sheet)
            _create_table(sheet, ref, args.table_name, args.style_name)
            save_workbook_atomic(workbook, record.path)
        data = ConvertToTableData(sheet=args.sheet, table_name=args.table_name, ref=ref)
        result: Result[ConvertToTableData] = Result[ConvertToTableData].ok(data)
        return ToolExecutionResult(success=True, output=serialize_result(result))
    except Exception as exc:  # pragma: no cover - defensive umbrella
        error_result = result_from_exception(exc)
        return ToolExecutionResult(
            success=False,
            output=serialize_result(error_result),
            error=error_result.message,
        )


convert_range_to_table_tool = ResponseTool(
    name=CONVERT_RANGE_TO_TABLE_NAME,
    definition=CONVERT_RANGE_TO_TABLE_DEFINITION,
    executor=_execute_convert_range_to_table,
)

registry.register(convert_range_to_table_tool)

__all__ = [
    "CONVERT_RANGE_TO_TABLE_NAME",
    "CONVERT_RANGE_TO_TABLE_DEFINITION",
    "ConvertToTableData",
    "convert_range_to_table_tool",
]
