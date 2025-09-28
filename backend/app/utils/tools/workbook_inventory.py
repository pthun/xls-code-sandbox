"""Overview tool providing a lightweight workbook inventory."""

from __future__ import annotations

from typing import Any, Mapping, Optional

from openai.types.responses import FunctionToolParam
from pydantic import BaseModel, Field

from .base import ResponseTool, ToolExecutionResult
from .excel_common import (
    Result,
    format_range,
    is_blank_value,
    open_workbook,
    resolve_workbook_record,
    result_from_exception,
    serialize_result,
    sheet_dimension_bounds,
)
from .filesystem import ToolFileRecord
from .registry import registry


class WorkbookInventoryParams(BaseModel):
    path: str = Field(..., description="Path (relative to tool uploads) to the workbook.")


class SheetInventory(BaseModel):
    sheet: str
    used_range: str
    approx_cells: int
    approx_non_empty: int
    approx_formula_cells: int


class WorkbookInventoryData(BaseModel):
    sheets: list[SheetInventory]


WORKBOOK_INVENTORY_NAME = "workbook_inventory"

WORKBOOK_INVENTORY_DEFINITION = FunctionToolParam(
    type="function",
    name=WORKBOOK_INVENTORY_NAME,
    description="Return approximate usage stats for each worksheet in an XLSX file.",
    parameters=WorkbookInventoryParams.model_json_schema(),
    strict=False,
)


def _inventory_sheet(
    sheet: "openpyxl.worksheet.worksheet.Worksheet",  # type: ignore[name-defined]
) -> tuple[SheetInventory, tuple[int, int, int, int]]:
    min_row, min_col, max_row, max_col = sheet_dimension_bounds(sheet)
    width = max_col - min_col + 1
    height = max_row - min_row + 1
    approx_cells = width * height
    approx_non_empty = 0

    for row in sheet.iter_rows(
        min_row=min_row,
        max_row=max_row,
        min_col=min_col,
        max_col=max_col,
        values_only=True,
    ):
        for value in row:
            if not is_blank_value(value):
                approx_non_empty += 1

    inventory = SheetInventory(
        sheet=sheet.title,
        used_range=format_range(min_row, min_col, max_row, max_col),
        approx_cells=approx_cells,
        approx_non_empty=approx_non_empty,
        approx_formula_cells=0,
    )
    return inventory, (min_row, min_col, max_row, max_col)


def _append_formula_counts(
    sheet: "openpyxl.worksheet.worksheet.Worksheet",  # type: ignore[name-defined]
    inventory: SheetInventory,
    bounds: tuple[int, int, int, int],
) -> None:
    min_row, min_col, max_row, max_col = bounds
    approx_formula_cells = 0
    for row in sheet.iter_rows(
        min_row=min_row,
        max_row=max_row,
        min_col=min_col,
        max_col=max_col,
        values_only=True,
    ):
        for value in row:
            if isinstance(value, str) and value.startswith("="):
                approx_formula_cells += 1
    inventory.approx_formula_cells = approx_formula_cells


def _build_inventory(record: ToolFileRecord) -> WorkbookInventoryData:
    with open_workbook(record.path, read_only=True, data_only=True) as workbook:
        inventories: list[SheetInventory] = []
        bounds_map: dict[str, tuple[int, int, int, int]] = {}
        for sheet in workbook.worksheets:
            inventory, bounds = _inventory_sheet(sheet)
            inventories.append(inventory)
            bounds_map[inventory.sheet] = bounds

    if inventories:
        inventory_by_sheet = {item.sheet: item for item in inventories}
        with open_workbook(record.path, read_only=True, data_only=False) as workbook:
            for sheet in workbook.worksheets:
                inventory = inventory_by_sheet.get(sheet.title)
                if inventory is None:
                    continue
                bounds = bounds_map.get(inventory.sheet)
                if bounds is None:
                    bounds = sheet_dimension_bounds(sheet)
                _append_formula_counts(sheet, inventory, bounds)

    return WorkbookInventoryData(sheets=inventories)


async def _execute_workbook_inventory(
    *,
    tool_id: int,
    arguments: Optional[Mapping[str, Any]] = None,
    folder_prefix: str | None = None,
) -> ToolExecutionResult:
    args = WorkbookInventoryParams.model_validate(arguments or {})

    try:
        record = resolve_workbook_record(tool_id, args.path, folder_prefix=folder_prefix)
        data = _build_inventory(record)
        result: Result[WorkbookInventoryData] = Result[WorkbookInventoryData].ok(data)
        return ToolExecutionResult(success=True, output=serialize_result(result))
    except Exception as exc:  # pragma: no cover - defensive umbrella
        error_result = result_from_exception(exc)
        return ToolExecutionResult(
            success=False,
            output=serialize_result(error_result),
            error=error_result.message,
        )


workbook_inventory_tool = ResponseTool(
    name=WORKBOOK_INVENTORY_NAME,
    definition=WORKBOOK_INVENTORY_DEFINITION,
    executor=_execute_workbook_inventory,
)

registry.register(workbook_inventory_tool)

__all__ = [
    "WORKBOOK_INVENTORY_NAME",
    "WORKBOOK_INVENTORY_DEFINITION",
    "WorkbookInventoryData",
    "workbook_inventory_tool",
]
