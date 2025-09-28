"""Detailed profiling tool for a worksheet range."""

from __future__ import annotations

from math import sqrt
from typing import Mapping, Optional

from openai.types.responses import FunctionToolParam
from pydantic import BaseModel, Field

from .base import ResponseTool, ToolExecutionResult
from .excel_common import (
    Result,
    column_letter,
    get_required_sheet,
    is_blank_value,
    open_workbook,
    parse_a1_range,
    resolve_workbook_record,
    result_from_exception,
    serialize_result,
    value_to_display,
)
from .registry import registry


class NumericStats(BaseModel):
    count: int
    mean: float
    std: float
    min: float
    max: float


class ColumnProfile(BaseModel):
    name: str
    rows: int
    nulls: int
    non_nulls: int
    unique: int
    dominant_type: str
    numeric_stats: NumericStats | None
    sample: list[object]


class ProfileRangeParams(BaseModel):
    path: str = Field(..., description="Path (relative to tool uploads) to the workbook.")
    sheet: str = Field(..., description="Name of the sheet to profile.")
    a1_range: str = Field(..., description="Target range in A1 notation.")
    header: bool = Field(True, description="Treat the first row as header names when true.")


class ProfileRangeData(BaseModel):
    rows: int
    columns: int
    columns_profile: list[ColumnProfile]


PROFILE_RANGE_NAME = "profile_range"

PROFILE_RANGE_DEFINITION = FunctionToolParam(
    type="function",
    name=PROFILE_RANGE_NAME,
    description="Profile values within a worksheet range (null counts, types, numeric stats).",
    parameters=ProfileRangeParams.model_json_schema(),
    strict=False,
)


_TYPE_PRIORITY = {
    "int": 0,
    "float": 1,
    "str": 2,
    "bool": 3,
    "date": 4,
    "other": 5,
    "unknown": 6,
}


def _classify_value(value: object) -> str:
    from datetime import date, datetime
    from decimal import Decimal

    if value is None:
        return "unknown"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, (float, Decimal)):
        return "float"
    if isinstance(value, str):
        return "str"
    if isinstance(value, (date, datetime)):
        return "date"
    return "other"


def _is_numeric(value: object) -> bool:
    from decimal import Decimal

    return isinstance(value, (int, float, Decimal)) and not isinstance(value, bool)


def _compute_numeric_stats(values: list[object]) -> NumericStats | None:
    numeric_values: list[float] = []
    for value in values:
        if _is_numeric(value):
            numeric_values.append(float(value))
    count = len(numeric_values)
    if count == 0:
        return None
    total = sum(numeric_values)
    mean = total / count
    if count > 1:
        variance = sum((val - mean) ** 2 for val in numeric_values) / (count - 1)
        std = sqrt(variance)
    else:
        std = 0.0
    return NumericStats(
        count=count,
        mean=mean,
        std=std,
        min=min(numeric_values),
        max=max(numeric_values),
    )


def _profile_columns(
    rows: list[list[object]],
    header: bool,
    min_col: int,
) -> list[ColumnProfile]:
    if not rows:
        return []

    total_rows = len(rows) - (1 if header else 0)
    total_rows = max(total_rows, 0)
    column_count = len(rows[0]) if rows else 0
    columns_profile: list[ColumnProfile] = []

    header_values: list[str] = []
    data_rows_start = 1 if header else 0

    if header and rows:
        header_row = rows[0]
        for idx in range(column_count):
            value = header_row[idx] if idx < len(header_row) else None
            display = value_to_display(value)
            header_values.append(display if display else column_letter(min_col + idx))
    else:
        header_values = [column_letter(min_col + idx) for idx in range(column_count)]

    data_rows = rows[data_rows_start:]

    for col_idx in range(column_count):
        values = [row[col_idx] if col_idx < len(row) else None for row in data_rows]
        nulls = sum(1 for value in values if is_blank_value(value))
        non_nulls = total_rows - nulls

        unique_values: set[object] = set()
        for value in values:
            if is_blank_value(value):
                continue
            try:
                unique_values.add(value)
            except TypeError:
                unique_values.add(value_to_display(value))

        type_counts: dict[str, int] = {}
        for value in values:
            if is_blank_value(value):
                continue
            category = _classify_value(value)
            type_counts[category] = type_counts.get(category, 0) + 1

        if type_counts:
            dominant_type = max(
                type_counts.items(),
                key=lambda item: (item[1], -_TYPE_PRIORITY.get(item[0], 99)),
            )[0]
        else:
            dominant_type = "unknown"

        numeric_stats = _compute_numeric_stats(values)
        sample: list[object] = []
        for value in values:
            if is_blank_value(value):
                continue
            sample.append(value)
            if len(sample) == 5:
                break

        columns_profile.append(
            ColumnProfile(
                name=header_values[col_idx] if col_idx < len(header_values) else column_letter(min_col + col_idx),
                rows=total_rows,
                nulls=nulls,
                non_nulls=non_nulls,
                unique=len(unique_values),
                dominant_type=dominant_type,
                numeric_stats=numeric_stats,
                sample=sample,
            )
        )

    return columns_profile


async def _execute_profile_range(
    *,
    tool_id: int,
    arguments: Optional[Mapping[str, object]] = None,
    folder_prefix: str | None = None,
) -> ToolExecutionResult:
    args = ProfileRangeParams.model_validate(arguments or {})

    try:
        bounds = parse_a1_range(args.a1_range)
        record = resolve_workbook_record(tool_id, args.path, folder_prefix=folder_prefix)
        with open_workbook(record.path, read_only=True, data_only=True) as workbook:
            sheet = get_required_sheet(workbook, args.sheet)
            min_row, min_col, max_row, max_col = bounds
            rows_data: list[list[object]] = []
            for row in sheet.iter_rows(
                min_row=min_row,
                max_row=max_row,
                min_col=min_col,
                max_col=max_col,
                values_only=True,
            ):
                rows_data.append(list(row))
        columns_profile = _profile_columns(rows_data, args.header, min_col)
        total_rows = len(rows_data) - (1 if args.header and rows_data else 0)
        total_rows = max(total_rows, 0)
        total_columns = len(rows_data[0]) if rows_data else 0
        data = ProfileRangeData(
            rows=total_rows,
            columns=total_columns,
            columns_profile=columns_profile,
        )
        result: Result[ProfileRangeData] = Result[ProfileRangeData].ok(data)
        return ToolExecutionResult(success=True, output=serialize_result(result))
    except Exception as exc:  # pragma: no cover - defensive umbrella
        error_result = result_from_exception(exc)
        return ToolExecutionResult(
            success=False,
            output=serialize_result(error_result),
            error=error_result.message,
        )


profile_range_tool = ResponseTool(
    name=PROFILE_RANGE_NAME,
    definition=PROFILE_RANGE_DEFINITION,
    executor=_execute_profile_range,
)

registry.register(profile_range_tool)

__all__ = [
    "PROFILE_RANGE_NAME",
    "PROFILE_RANGE_DEFINITION",
    "ProfileRangeData",
    "profile_range_tool",
]
