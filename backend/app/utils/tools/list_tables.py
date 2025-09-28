"""Overview tool that lists tables in worksheets."""

from __future__ import annotations

from typing import Mapping, Optional

from openai.types.responses import FunctionToolParam
from pydantic import BaseModel, Field

from .base import ResponseTool, ToolExecutionResult
from .excel_common import (
    Result,
    open_workbook,
    parse_a1_range,
    resolve_workbook_record,
    result_from_exception,
    serialize_result,
)
from .registry import registry


class ListTablesParams(BaseModel):
    path: str = Field(..., description="Path (relative to tool uploads) to the workbook.")


class TableInfo(BaseModel):
    sheet: str
    table_name: str
    ref: str


class ListTablesData(BaseModel):
    tables: list[TableInfo]


LIST_TABLES_NAME = "list_tables"

LIST_TABLES_DEFINITION = FunctionToolParam(
    type="function",
    name=LIST_TABLES_NAME,
    description="List Excel tables present in the workbook.",
    parameters=ListTablesParams.model_json_schema(),
    strict=False,
)


def _collect_tables(path: str) -> list[TableInfo]:
    tables: list[TableInfo] = []
    with open_workbook(path, read_only=False, data_only=True) as workbook:
        for sheet in workbook.worksheets:
            for table in getattr(sheet, "tables", {}).values():
                ref = getattr(table, "ref", None)
                if not ref:
                    continue
                try:
                    parse_a1_range(ref)
                except Exception:
                    continue
                tables.append(
                    TableInfo(
                        sheet=sheet.title,
                        table_name=getattr(table, "name", ""),
                        ref=ref,
                    )
                )
    return tables


async def _execute_list_tables(
    *,
    tool_id: int,
    arguments: Optional[Mapping[str, str]] = None,
    folder_prefix: str | None = None,
) -> ToolExecutionResult:
    args = ListTablesParams.model_validate(arguments or {})

    try:
        record = resolve_workbook_record(tool_id, args.path, folder_prefix=folder_prefix)
        tables = _collect_tables(str(record.path))
        data = ListTablesData(tables=tables)
        result: Result[ListTablesData] = Result[ListTablesData].ok(data)
        return ToolExecutionResult(success=True, output=serialize_result(result))
    except Exception as exc:  # pragma: no cover - defensive umbrella
        error_result = result_from_exception(exc)
        return ToolExecutionResult(
            success=False,
            output=serialize_result(error_result),
            error=error_result.message,
        )


list_tables_tool = ResponseTool(
    name=LIST_TABLES_NAME,
    definition=LIST_TABLES_DEFINITION,
    executor=_execute_list_tables,
)

registry.register(list_tables_tool)

__all__ = [
    "LIST_TABLES_NAME",
    "LIST_TABLES_DEFINITION",
    "ListTablesData",
    "list_tables_tool",
]
