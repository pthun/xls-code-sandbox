"""Detailed view tool listing formulas within a range."""

from __future__ import annotations

from typing import Mapping, Optional

from openai.types.responses import FunctionToolParam
from pydantic import BaseModel, Field

from .base import ResponseTool, ToolExecutionResult
from .excel_common import (
    Result,
    get_required_sheet,
    open_workbook,
    parse_a1_range,
    resolve_workbook_record,
    result_from_exception,
    serialize_result,
    to_a1,
)
from .registry import registry


class ReadFormulasInRangeParams(BaseModel):
    path: str = Field(..., description="Path (relative to tool uploads) to the workbook.")
    sheet: str = Field(..., description="Name of the sheet to inspect.")
    a1_range: str = Field(..., description="Target range in A1 notation.")


class FormulaCell(BaseModel):
    cell: str
    formula: str


class ReadFormulasInRangeData(BaseModel):
    cells: list[FormulaCell]


READ_FORMULAS_IN_RANGE_NAME = "read_formulas_in_range"

READ_FORMULAS_IN_RANGE_DEFINITION = FunctionToolParam(
    type="function",
    name=READ_FORMULAS_IN_RANGE_NAME,
    description="List formulas present within a specified range.",
    parameters=ReadFormulasInRangeParams.model_json_schema(),
    strict=False,
)


def _collect_formulas(
    sheet: "openpyxl.worksheet.worksheet.Worksheet",  # type: ignore[name-defined]
    bounds: tuple[int, int, int, int],
) -> list[FormulaCell]:
    min_row, min_col, max_row, max_col = bounds
    formulas: list[FormulaCell] = []
    for row_index, row in enumerate(
        sheet.iter_rows(
            min_row=min_row,
            max_row=max_row,
            min_col=min_col,
            max_col=max_col,
            values_only=True,
        ),
        start=min_row,
    ):
        for offset, value in enumerate(row, start=min_col):
            if isinstance(value, str) and value.startswith("="):
                formulas.append(
                    FormulaCell(
                        cell=to_a1(row_index, offset),
                        formula=value,
                    )
                )
    return formulas


async def _execute_read_formulas_in_range(
    *,
    tool_id: int,
    arguments: Optional[Mapping[str, object]] = None,
    folder_prefix: str | None = None,
) -> ToolExecutionResult:
    args = ReadFormulasInRangeParams.model_validate(arguments or {})

    try:
        bounds = parse_a1_range(args.a1_range)
        record = resolve_workbook_record(tool_id, args.path, folder_prefix=folder_prefix)
        with open_workbook(record.path, read_only=True, data_only=False) as workbook:
            sheet = get_required_sheet(workbook, args.sheet)
            formulas = _collect_formulas(sheet, bounds)
        data = ReadFormulasInRangeData(cells=formulas)
        result: Result[ReadFormulasInRangeData] = Result[ReadFormulasInRangeData].ok(data)
        return ToolExecutionResult(success=True, output=serialize_result(result))
    except Exception as exc:  # pragma: no cover - defensive umbrella
        error_result = result_from_exception(exc)
        return ToolExecutionResult(
            success=False,
            output=serialize_result(error_result),
            error=error_result.message,
        )


read_formulas_in_range_tool = ResponseTool(
    name=READ_FORMULAS_IN_RANGE_NAME,
    definition=READ_FORMULAS_IN_RANGE_DEFINITION,
    executor=_execute_read_formulas_in_range,
)

registry.register(read_formulas_in_range_tool)

__all__ = [
    "READ_FORMULAS_IN_RANGE_NAME",
    "READ_FORMULAS_IN_RANGE_DEFINITION",
    "ReadFormulasInRangeData",
    "read_formulas_in_range_tool",
]
