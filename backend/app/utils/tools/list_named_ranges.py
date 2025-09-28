"""Overview tool that lists named ranges in a workbook."""

from __future__ import annotations

from typing import Mapping, Optional

from openai.types.responses import FunctionToolParam
from pydantic import BaseModel, Field

from .base import ResponseTool, ToolExecutionResult
from .excel_common import (
    Result,
    parse_a1_range,
    resolve_workbook_record,
    result_from_exception,
    serialize_result,
    open_workbook,
)
from .registry import registry


class ListNamedRangesParams(BaseModel):
    path: str = Field(..., description="Path (relative to tool uploads) to the workbook.")


class NamedRangeInfo(BaseModel):
    name: str
    sheet: str
    ref: str


class ListNamedRangesData(BaseModel):
    named_ranges: list[NamedRangeInfo]


LIST_NAMED_RANGES_NAME = "list_named_ranges"

LIST_NAMED_RANGES_DEFINITION = FunctionToolParam(
    type="function",
    name=LIST_NAMED_RANGES_NAME,
    description="List named ranges defined in an XLSX workbook.",
    parameters=ListNamedRangesParams.model_json_schema(),
    strict=False,
)


def _collect_named_ranges(path: str) -> list[NamedRangeInfo]:
    named_ranges: list[NamedRangeInfo] = []
    with open_workbook(path, read_only=True, data_only=True) as workbook:
        for defined_name in workbook.defined_names.definedName:  # type: ignore[attr-defined]
            if defined_name is None:
                continue
            destinations = getattr(defined_name, "destinations", None)
            if destinations is None:
                continue
            for sheet_name, ref in destinations:
                if not sheet_name or not ref:
                    continue
                try:
                    parse_a1_range(ref)
                except Exception:
                    continue
                named_ranges.append(
                    NamedRangeInfo(
                        name=defined_name.name,
                        sheet=sheet_name,
                        ref=ref,
                    )
                )
    return named_ranges


async def _execute_list_named_ranges(
    *,
    tool_id: int,
    arguments: Optional[Mapping[str, Any]] = None,
    folder_prefix: str | None = None,
) -> ToolExecutionResult:
    args = ListNamedRangesParams.model_validate(arguments or {})

    try:
        record = resolve_workbook_record(tool_id, args.path, folder_prefix=folder_prefix)
        named_ranges = _collect_named_ranges(str(record.path))
        data = ListNamedRangesData(named_ranges=named_ranges)
        result: Result[ListNamedRangesData] = Result[ListNamedRangesData].ok(data)
        return ToolExecutionResult(success=True, output=serialize_result(result))
    except Exception as exc:  # pragma: no cover - defensive umbrella
        error_result = result_from_exception(exc)
        return ToolExecutionResult(
            success=False,
            output=serialize_result(error_result),
            error=error_result.message,
        )


list_named_ranges_tool = ResponseTool(
    name=LIST_NAMED_RANGES_NAME,
    definition=LIST_NAMED_RANGES_DEFINITION,
    executor=_execute_list_named_ranges,
)

registry.register(list_named_ranges_tool)

__all__ = [
    "LIST_NAMED_RANGES_NAME",
    "LIST_NAMED_RANGES_DEFINITION",
    "ListNamedRangesData",
    "list_named_ranges_tool",
]
