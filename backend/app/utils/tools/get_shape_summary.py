"""Tool that summarises the shape of a CSV file."""

from __future__ import annotations

import csv
from typing import Mapping, Optional, Any

from pydantic import BaseModel, Field, model_validator
from openai.types.responses import FunctionToolParam

from .base import ResponseTool, ToolExecutionResult
from .filesystem import (
    InvalidToolFilePathError,
    ToolFileNotFoundError,
    ToolFileRecord,
    ToolNotFoundError,
    resolve_tool_file,
)
from .registry import registry


MAX_SAMPLE_ROWS = 5


class CsvFileArgs(BaseModel):
    """Arguments accepted by the get_shape_summary tool."""

    path: str | None = Field(
        default=None,
        description="Absolute or relative path to the CSV file inside the uploads directory.",
    )
    file_id: int | None = Field(
        default=None,
        ge=1,
        description="Identifier of the uploaded file (alternative to path).",
    )

    @model_validator(mode="after")
    def validate_locator(self) -> "CsvFileArgs":
        if (self.path is None and self.file_id is None) or (
            self.path is not None and self.file_id is not None
        ):
            raise ValueError("Provide exactly one of 'path' or 'file_id'.")
        return self


class CsvSampleRow(BaseModel):
    row_number: int = Field(description="1-based line number for the sampled row.")
    values: list[str]


class CsvShapeSummary(BaseModel):
    """JSON payload describing the shape of a CSV file."""

    tool_id: int
    path: str
    columns: list[str]
    total_rows: int = Field(description="Total rows including the header if present.")
    data_rows: int = Field(description="Rows excluding the header.")
    delimiter: str
    quotechar: str | None
    sample_rows: list[CsvSampleRow]


GET_SHAPE_SUMMARY_NAME = "get_shape_summary"

GET_SHAPE_SUMMARY_DEFINITION = FunctionToolParam(
    type="function",
    name=GET_SHAPE_SUMMARY_NAME,
    description=(
        "Summarise a CSV file: show the header, sample rows, and total length."
    ),
    parameters=CsvFileArgs.model_json_schema(),
    strict=False,
)


def _summarise_csv(record: ToolFileRecord) -> CsvShapeSummary:
    path = record.path
    if not path.exists():
        msg = f"File not found on disk: {path}"
        raise ToolFileNotFoundError(msg)

    sample_rows: list[CsvSampleRow] = []
    header: list[str] = []
    data_rows = 0

    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        sample_text = handle.read(4096)
        handle.seek(0)
        if not sample_text.strip():
            dialect = csv.get_dialect("excel")
        else:
            try:
                dialect = csv.Sniffer().sniff(sample_text)
            except csv.Error:
                dialect = csv.get_dialect("excel")
        reader = csv.reader(handle, dialect)
        try:
            header = next(reader)
        except StopIteration:
            header = []
        if header:
            start_row = 2
        else:
            start_row = 1
        for index, row in enumerate(reader, start=start_row):
            data_rows += 1
            if len(sample_rows) < MAX_SAMPLE_ROWS:
                sample_rows.append(CsvSampleRow(row_number=index, values=row))

    total_rows = data_rows + (1 if header else 0)
    return CsvShapeSummary(
        tool_id=record.tool_id,
        path=str(path),
        columns=header,
        total_rows=total_rows,
        data_rows=data_rows,
        delimiter=dialect.delimiter,
        quotechar=getattr(dialect, "quotechar", None),
        sample_rows=sample_rows,
    )


async def _execute_get_shape_summary(
    *, tool_id: int, arguments: Optional[Mapping[str, Any]] = None
) -> ToolExecutionResult:
    args = CsvFileArgs.model_validate(arguments or {})

    try:
        record = resolve_tool_file(
            tool_id,
            file_id=args.file_id,
            path=args.path,
        )
    except ToolNotFoundError as exc:
        return ToolExecutionResult(success=False, output="{}", error=str(exc))
    except ToolFileNotFoundError as exc:
        return ToolExecutionResult(success=False, output="{}", error=str(exc))
    except InvalidToolFilePathError as exc:
        return ToolExecutionResult(success=False, output="{}", error=str(exc))

    if record.path.suffix.lower() != ".csv":
        msg = (
            f"Unsupported file type '{record.path.suffix}'. Expected a .csv file."
        )
        return ToolExecutionResult(success=False, output="{}", error=msg)

    try:
        payload = _summarise_csv(record)
    except (UnicodeDecodeError, csv.Error, ToolFileNotFoundError) as exc:
        return ToolExecutionResult(success=False, output="{}", error=str(exc))

    return ToolExecutionResult(
        success=True,
        output=payload.model_dump_json(),
    )


get_shape_summary_tool = ResponseTool(
    name=GET_SHAPE_SUMMARY_NAME,
    definition=GET_SHAPE_SUMMARY_DEFINITION,
    executor=_execute_get_shape_summary,
)

registry.register(get_shape_summary_tool)

__all__ = [
    "GET_SHAPE_SUMMARY_NAME",
    "GET_SHAPE_SUMMARY_DEFINITION",
    "CsvFileArgs",
    "CsvShapeSummary",
    "get_shape_summary_tool",
]
