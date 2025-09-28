"""Detailed view tool returning the formula for a single cell."""

from __future__ import annotations

from typing import Mapping, Optional

from openai.types.responses import FunctionToolParam
from pydantic import BaseModel, Field

from .base import ResponseTool, ToolExecutionResult
from .excel_common import (
    Result,
    get_required_sheet,
    normalize_row,
    open_workbook,
    parse_column_ref,
    resolve_workbook_record,
    result_from_exception,
    serialize_result,
    to_a1,
)
from .registry import registry


class ReadCellFormulaParams(BaseModel):
    path: str = Field(..., description="Path (relative to tool uploads) to the workbook.")
    sheet: str = Field(..., description="Name of the sheet containing the cell.")
    row: int = Field(..., ge=1, description="1-based row index of the cell.")
    column: int | str = Field(..., description="1-based column index or Excel column letter.")


class ReadCellFormulaData(BaseModel):
    cell: str
    formula: str | None


READ_CELL_FORMULA_NAME = "read_cell_formula"

READ_CELL_FORMULA_DEFINITION = FunctionToolParam(
    type="function",
    name=READ_CELL_FORMULA_NAME,
    description="Read the formula assigned to a single cell.",
    parameters=ReadCellFormulaParams.model_json_schema(),
    strict=False,
)


async def _execute_read_cell_formula(
    *,
    tool_id: int,
    arguments: Optional[Mapping[str, object]] = None,
    folder_prefix: str | None = None,
) -> ToolExecutionResult:
    args = ReadCellFormulaParams.model_validate(arguments or {})

    try:
        record = resolve_workbook_record(tool_id, args.path, folder_prefix=folder_prefix)
        column_index = parse_column_ref(args.column)
        row_index = normalize_row(args.row)
        coord = to_a1(row_index, column_index)
        with open_workbook(record.path, read_only=True, data_only=False) as workbook:
            sheet = get_required_sheet(workbook, args.sheet)
            cell = sheet.cell(row=row_index, column=column_index)
            formula_value = cell.value if isinstance(cell.value, str) and cell.value.startswith("=") else None
        data = ReadCellFormulaData(cell=coord, formula=formula_value)
        result: Result[ReadCellFormulaData] = Result[ReadCellFormulaData].ok(data)
        return ToolExecutionResult(success=True, output=serialize_result(result))
    except Exception as exc:  # pragma: no cover - defensive umbrella
        error_result = result_from_exception(exc)
        return ToolExecutionResult(
            success=False,
            output=serialize_result(error_result),
            error=error_result.message,
        )


read_cell_formula_tool = ResponseTool(
    name=READ_CELL_FORMULA_NAME,
    definition=READ_CELL_FORMULA_DEFINITION,
    executor=_execute_read_cell_formula,
)

registry.register(read_cell_formula_tool)

__all__ = [
    "READ_CELL_FORMULA_NAME",
    "READ_CELL_FORMULA_DEFINITION",
    "ReadCellFormulaData",
    "read_cell_formula_tool",
]
