"""Detailed view tool returning the used range of a sheet as CSV."""

from __future__ import annotations

from typing import Mapping, Optional

from openai.types.responses import FunctionToolParam
from pydantic import BaseModel, Field

from .base import ResponseTool, ToolExecutionResult
from .excel_common import (
    CsvBuilder,
    Result,
    get_required_sheet,
    open_workbook,
    resolve_workbook_record,
    result_from_exception,
    serialize_result,
    sheet_dimension_bounds,
)
from .registry import registry


class ReadSheetParams(BaseModel):
    path: str = Field(..., description="Path (relative to tool uploads) to the workbook.")
    sheet: str = Field(..., description="Name of the sheet to sample.")
    data_only: bool = Field(True, description="If true, return computed values; otherwise raw formulas.")


SAMPLE_SHEET_USED_CSV_NAME = "sample_sheet_used_csv"

SAMPLE_SHEET_USED_CSV_DEFINITION = FunctionToolParam(
    type="function",
    name=SAMPLE_SHEET_USED_CSV_NAME,
    description="Return the used range of a sheet as CSV text.",
    parameters=ReadSheetParams.model_json_schema(),
    strict=False,
)


def _build_csv(
    sheet: "openpyxl.worksheet.worksheet.Worksheet",  # type: ignore[name-defined]
) -> str:
    min_row, min_col, max_row, max_col = sheet_dimension_bounds(sheet)
    builder = CsvBuilder()
    for row in sheet.iter_rows(
        min_row=min_row,
        max_row=max_row,
        min_col=min_col,
        max_col=max_col,
        values_only=True,
    ):
        builder.append(list(row))
    return builder.render()


async def _execute_sample_sheet_used_csv(
    *,
    tool_id: int,
    arguments: Optional[Mapping[str, Any]] = None,
    folder_prefix: str | None = None,
) -> ToolExecutionResult:
    args = ReadSheetParams.model_validate(arguments or {})

    try:
        record = resolve_workbook_record(tool_id, args.path, folder_prefix=folder_prefix)
        with open_workbook(record.path, read_only=True, data_only=args.data_only) as workbook:
            sheet = get_required_sheet(workbook, args.sheet)
            csv_text = _build_csv(sheet)
        result: Result[str] = Result[str].ok(csv_text)
        return ToolExecutionResult(success=True, output=serialize_result(result))
    except Exception as exc:  # pragma: no cover - defensive umbrella
        error_result = result_from_exception(exc)
        return ToolExecutionResult(
            success=False,
            output=serialize_result(error_result),
            error=error_result.message,
        )


sample_sheet_used_csv_tool = ResponseTool(
    name=SAMPLE_SHEET_USED_CSV_NAME,
    definition=SAMPLE_SHEET_USED_CSV_DEFINITION,
    executor=_execute_sample_sheet_used_csv,
)

registry.register(sample_sheet_used_csv_tool)

__all__ = [
    "SAMPLE_SHEET_USED_CSV_NAME",
    "SAMPLE_SHEET_USED_CSV_DEFINITION",
    "sample_sheet_used_csv_tool",
]
