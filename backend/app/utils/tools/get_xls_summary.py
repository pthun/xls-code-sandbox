"""Tool that summarises XLSX spreadsheets following the shared Result contract."""

from __future__ import annotations

from typing import Any, Mapping, Optional

from openai.types.responses import FunctionToolParam
from pydantic import BaseModel, Field

from .base import ResponseTool, ToolExecutionResult
from .excel_common import (
    FormulaCounter,
    Result,
    resolve_workbook_record,
    row_values_trimmed,
    serialize_result,
    sheet_dimension_bounds,
    open_workbook,
    result_from_exception,
)
from .filesystem import ToolFileRecord
from .registry import registry

DEFAULT_MAX_SAMPLE_ROWS = 5
MAX_SAMPLE_ROWS_CAP = 20


class SpreadsheetFileArgs(BaseModel):
    """Arguments accepted by the get_xls_summary tool."""

    path: str = Field(
        ...,
        description="Path (relative to the tool uploads directory) to the spreadsheet.",
    )
    include_formula_count: bool = Field(
        False,
        description="If true, perform a second pass to count formula cells per sheet.",
    )
    max_sample_rows: int = Field(
        DEFAULT_MAX_SAMPLE_ROWS,
        ge=0,
        le=MAX_SAMPLE_ROWS_CAP,
        description="Maximum number of data rows to sample per sheet.",
    )


class WorksheetSampleRow(BaseModel):
    row_number: int
    values: list[str]


class WorksheetSummary(BaseModel):
    name: str
    header: list[str]
    header_row_number: int | None
    total_rows: int
    data_rows: int
    columns: int
    sample_rows: list[WorksheetSampleRow]
    formula_cells: int | None = None


class SpreadsheetSummary(BaseModel):
    tool_id: int
    path: str
    sheet_count: int
    sheets: list[WorksheetSummary]


GET_XLS_SUMMARY_NAME = "get_xls_summary"

GET_XLS_SUMMARY_DEFINITION = FunctionToolParam(
    type="function",
    name=GET_XLS_SUMMARY_NAME,
    description="Summarise an XLSX file by reporting sheet counts and table shapes.",
    parameters=SpreadsheetFileArgs.model_json_schema(),
    strict=False,
)


def _summarise_worksheet(
    worksheet: "openpyxl.worksheet.worksheet.Worksheet",  # type: ignore[name-defined]
    *,
    max_sample_rows: int,
) -> tuple[WorksheetSummary, tuple[int, int, int, int]]:
    header: list[str] = []
    header_row_number: int | None = None
    data_rows = 0
    max_columns = 0
    samples: list[WorksheetSampleRow] = []

    for row_number, raw_row in enumerate(
        worksheet.iter_rows(values_only=True),
        start=1,
    ):
        trimmed = row_values_trimmed(list(raw_row))
        if not trimmed:
            continue
        max_columns = max(max_columns, len(trimmed))
        if header_row_number is None:
            header = trimmed
            header_row_number = row_number
            continue
        data_rows += 1
        if len(samples) < max_sample_rows:
            samples.append(WorksheetSampleRow(row_number=row_number, values=trimmed))

    total_rows = data_rows + (1 if header_row_number is not None else 0)
    summary = WorksheetSummary(
        name=worksheet.title,
        header=header,
        header_row_number=header_row_number,
        total_rows=total_rows,
        data_rows=data_rows,
        columns=max_columns,
        sample_rows=samples,
    )
    bounds = sheet_dimension_bounds(worksheet)
    return summary, bounds


def _summarise_workbook(
    record: ToolFileRecord,
    *,
    include_formula_count: bool,
    max_sample_rows: int,
) -> SpreadsheetSummary:
    with open_workbook(record.path, read_only=True, data_only=True) as workbook:
        summaries: list[WorksheetSummary] = []
        bounds_by_sheet: dict[str, tuple[int, int, int, int]] = {}
        for worksheet in workbook.worksheets:
            summary, bounds = _summarise_worksheet(worksheet, max_sample_rows=max_sample_rows)
            summaries.append(summary)
            bounds_by_sheet[summary.name] = bounds

    if include_formula_count and summaries:
        summary_by_name = {summary.name: summary for summary in summaries}
        with open_workbook(record.path, read_only=True, data_only=False) as workbook:
            for worksheet in workbook.worksheets:
                summary = summary_by_name.get(worksheet.title)
                if summary is None:
                    continue
                bounds = bounds_by_sheet.get(summary.name)
                if bounds is None:
                    bounds = sheet_dimension_bounds(worksheet)
                min_row, min_col, max_row, max_col = bounds
                counter = FormulaCounter()
                for row in worksheet.iter_rows(
                    min_row=min_row,
                    max_row=max_row,
                    min_col=min_col,
                    max_col=max_col,
                    values_only=True,
                ):
                    for value in row:
                        counter.feed(value)
                summary.formula_cells = counter.tally()

    return SpreadsheetSummary(
        tool_id=record.tool_id,
        path=str(record.path),
        sheet_count=len(summaries),
        sheets=summaries,
    )


async def _execute_get_xls_summary(
    *,
    tool_id: int,
    arguments: Optional[Mapping[str, Any]] = None,
    folder_prefix: str | None = None,
) -> ToolExecutionResult:
    args = SpreadsheetFileArgs.model_validate(arguments or {})
    max_sample_rows = min(args.max_sample_rows, MAX_SAMPLE_ROWS_CAP)

    try:
        record = resolve_workbook_record(tool_id, args.path, folder_prefix=folder_prefix)
        summary = _summarise_workbook(
            record,
            include_formula_count=args.include_formula_count,
            max_sample_rows=max_sample_rows,
        )
        result: Result[SpreadsheetSummary] = Result[SpreadsheetSummary].ok(summary)
        return ToolExecutionResult(
            success=True,
            output=serialize_result(result),
        )
    except Exception as exc:  # pragma: no cover - defensive umbrella
        error_result = result_from_exception(exc)
        return ToolExecutionResult(
            success=False,
            output=serialize_result(error_result),
            error=error_result.message,
        )


get_xls_summary_tool = ResponseTool(
    name=GET_XLS_SUMMARY_NAME,
    definition=GET_XLS_SUMMARY_DEFINITION,
    executor=_execute_get_xls_summary,
)

registry.register(get_xls_summary_tool)

__all__ = [
    "GET_XLS_SUMMARY_NAME",
    "GET_XLS_SUMMARY_DEFINITION",
    "SpreadsheetFileArgs",
    "SpreadsheetSummary",
    "get_xls_summary_tool",
]
