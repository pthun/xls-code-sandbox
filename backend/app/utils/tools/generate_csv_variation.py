"""Tool that generates a CSV variation by mutating an existing upload."""

from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Any, Iterable, Mapping, Optional, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from openai.types.responses import FunctionToolParam

from .base import ResponseTool, ToolExecutionResult
from .filesystem import (
    ToolFileNotFoundError,
    ToolNotFoundError,
    UPLOAD_ROOT,
    db_connection,
    resolve_tool_file,
)
from .get_shape_summary import CsvFileArgs
from .registry import registry


class NewColumnSpec(BaseModel):
    """Specification for a column to add to the CSV."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1, description="Name of the column to add.")
    values: list[Any] | None = Field(
        default=None,
        description="Optional explicit values for each existing row (must match row count).",
    )
    default_value: Any | None = Field(
        default=None,
        description="Value applied to existing rows when explicit values are not provided.",
    )
    description: str | None = None

    @model_validator(mode="after")
    def _ensure_values_or_default(self) -> "NewColumnSpec":
        if self.values is None and self.default_value is None:
            msg = "Provide either 'values' or 'default_value' for a new column"
            raise ValueError(msg)
        return self


class AddColumnsOperation(BaseModel):
    """Operation that adds one or more columns to the CSV."""

    model_config = ConfigDict(extra="forbid")

    operation: Literal["add_columns"] = "add_columns"  # type: ignore[assignment]
    columns: list[NewColumnSpec] = Field(
        ..., min_length=1, description="Columns that should be appended to the CSV."
    )
    overwrite_existing: bool = Field(
        default=False,
        description=(
            "Whether to overwrite existing columns with the same name. Defaults to false, "
            "in which case duplicate names raise an error."
        ),
    )


class AppendRowsOperation(BaseModel):
    """Operation that appends fully-specified rows to the CSV."""

    model_config = ConfigDict(extra="forbid")

    operation: Literal["append_rows"] = "append_rows"  # type: ignore[assignment]
    rows: list[Mapping[str, Any]] = Field(
        default_factory=list,
        description="Rows to append. Keys map to column names; missing values use 'fill_missing_with'.",
    )
    fill_missing_with: Any | None = Field(
        default="",
        description="Fallback value for columns not provided in a row.",
    )


CsvVariationOperation = Annotated[
    AddColumnsOperation | AppendRowsOperation,
    Field(discriminator="operation"),
]


class CsvVariationArgs(CsvFileArgs):
    """Arguments accepted by the CSV variation tool."""

    operations: list[CsvVariationOperation] = Field(
        ..., min_length=1, description="Sequence of operations to apply to the CSV."
    )
    output_filename: str | None = Field(
        default=None,
        description="Optional filename for the generated CSV. Defaults to '<original>-variant.csv'.",
    )


class CsvVariationFile(BaseModel):
    """Metadata about the newly generated CSV file."""

    id: int
    original_filename: str
    stored_filename: str
    path: str
    relative_path: str
    size_bytes: int
    uploaded_at: str


class CsvVariationResult(BaseModel):
    """JSON payload returned after generating the CSV variation."""

    tool_id: int
    base_file_id: int
    base_filename: str
    new_file: CsvVariationFile
    added_columns: list[str]
    appended_rows: int


GENERATE_CSV_VARIATION_NAME = "generate_csv_variation"
GENERATE_CSV_VARIATION_DEFINITION = FunctionToolParam(
    type="function",
    name=GENERATE_CSV_VARIATION_NAME,
    description="Create a new CSV by adding columns and rows to an existing uploaded CSV file.",
    parameters=CsvVariationArgs.model_json_schema(),
    strict=False,
)


def _stringify(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (int, float)):
        return str(value)
    return str(value)


def _load_csv_contents(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise ValueError("CSV file does not contain a header row")
        columns = list(reader.fieldnames)
        rows: list[dict[str, str]] = []
        for row in reader:
            rows.append({key: _stringify(value) for key, value in row.items()})
    return columns, rows


def _apply_add_columns(
    columns: list[str],
    rows: list[dict[str, str]],
    defaults: dict[str, str],
    op: AddColumnsOperation,
) -> list[str]:
    added: list[str] = []
    row_count = len(rows)
    for column in op.columns:
        name = column.name.strip()
        if not name:
            raise ValueError("Column names cannot be empty")
        exists = name in columns
        if exists and not op.overwrite_existing:
            msg = f"Column '{name}' already exists; set overwrite_existing=true to replace it"
            raise ValueError(msg)
        if not exists:
            columns.append(name)
            added.append(name)
        values: Optional[list[str]] = None
        if column.values is not None:
            values = [_stringify(value) for value in column.values]
            if row_count != len(values):
                msg = (
                    f"Column '{name}' expects {row_count} values but received {len(values)}"
                )
                raise ValueError(msg)
        default_value = _stringify(column.default_value) if column.default_value is not None else ""
        defaults[name] = default_value
        for index, row in enumerate(rows):
            if values is not None:
                row[name] = values[index]
            else:
                row[name] = default_value
    return added


def _apply_append_rows(
    columns: list[str],
    rows: list[dict[str, str]],
    defaults: dict[str, str],
    op: AppendRowsOperation,
) -> int:
    appended = 0
    fill_value = _stringify(op.fill_missing_with)
    for incoming in op.rows:
        if not isinstance(incoming, Mapping):
            raise ValueError("Each appended row must be an object mapping column names to values")
        extra_columns = [key for key in incoming.keys() if key not in columns]
        if extra_columns:
            for column in extra_columns:
                columns.append(column)
                defaults.setdefault(column, fill_value)
            for row in rows:
                for column in extra_columns:
                    row[column] = defaults[column]
        row_payload: dict[str, str] = {}
        for column in columns:
            if column in incoming:
                row_payload[column] = _stringify(incoming[column])
            else:
                row_payload[column] = defaults.get(column, fill_value)
        rows.append(row_payload)
        appended += 1
    return appended


def _write_csv(path: Path, columns: Iterable[str], rows: Iterable[Mapping[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(columns))
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


async def _execute_generate_csv_variation(
    *,
    tool_id: int,
    arguments: Optional[Mapping[str, Any]] = None,
) -> ToolExecutionResult:
    try:
        args = CsvVariationArgs.model_validate(arguments or {})
    except ValidationError as exc:
        return ToolExecutionResult(success=False, output="{}", error=str(exc))

    try:
        record = resolve_tool_file(
            tool_id,
            file_id=args.file_id,
            path=args.path,
        )
    except (ToolNotFoundError, ToolFileNotFoundError) as exc:
        return ToolExecutionResult(success=False, output="{}", error=str(exc))
    except Exception as exc:  # pragma: no cover - defensive
        return ToolExecutionResult(success=False, output="{}", error=str(exc))

    if record.path.suffix.lower() != ".csv":
        msg = f"Unsupported file type '{record.path.suffix}'. Only CSV files are supported."
        return ToolExecutionResult(success=False, output="{}", error=msg)

    try:
        columns, rows = _load_csv_contents(record.path)
    except Exception as exc:
        return ToolExecutionResult(success=False, output="{}", error=str(exc))

    defaults: dict[str, str] = {column: "" for column in columns}
    added_columns: list[str] = []
    appended_rows = 0

    for operation in args.operations:
        if isinstance(operation, AddColumnsOperation):
            try:
                added = _apply_add_columns(columns, rows, defaults, operation)
            except Exception as exc:
                return ToolExecutionResult(success=False, output="{}", error=str(exc))
            added_columns.extend(added)
        elif isinstance(operation, AppendRowsOperation):
            try:
                appended_rows += _apply_append_rows(columns, rows, defaults, operation)
            except Exception as exc:
                return ToolExecutionResult(success=False, output="{}", error=str(exc))
        else:  # pragma: no cover - exhaustive guard
            return ToolExecutionResult(success=False, output="{}", error="Unsupported operation type")

    target_dir = (UPLOAD_ROOT / str(tool_id)).resolve()
    target_dir.mkdir(parents=True, exist_ok=True)

    original_name = Path(record.original_filename)
    suggested_name = args.output_filename or f"{original_name.stem}-variant.csv"
    stored_filename = f"{uuid4().hex}.csv"
    target_path = target_dir / stored_filename

    try:
        _write_csv(target_path, columns, rows)
    except Exception as exc:
        return ToolExecutionResult(success=False, output="{}", error=str(exc))

    size_bytes = target_path.stat().st_size
    uploaded_at = datetime.now(timezone.utc).isoformat()

    with db_connection() as connection:
        cursor = connection.execute(
            """
            INSERT INTO tool_files (
                tool_id,
                original_filename,
                stored_filename,
                content_type,
                size_bytes,
                uploaded_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                tool_id,
                suggested_name,
                stored_filename,
                "text/csv",
                size_bytes,
                uploaded_at,
            ),
        )
        file_id = int(cursor.lastrowid)
        connection.commit()

    relative_path = stored_filename
    base_upload_dir = (UPLOAD_ROOT / str(tool_id)).resolve()
    try:
        relative_path = str(target_path.relative_to(base_upload_dir))
    except ValueError:  # pragma: no cover - defensive
        relative_path = stored_filename

    payload = CsvVariationResult(
        tool_id=tool_id,
        base_file_id=record.id,
        base_filename=record.original_filename,
        new_file=CsvVariationFile(
            id=file_id,
            original_filename=suggested_name,
            stored_filename=stored_filename,
            path=str(target_path),
            relative_path=relative_path,
            size_bytes=size_bytes,
            uploaded_at=uploaded_at,
        ),
        added_columns=added_columns,
        appended_rows=appended_rows,
    )

    return ToolExecutionResult(
        success=True,
        output=payload.model_dump_json(),
    )


generate_csv_variation_tool = ResponseTool(
    name=GENERATE_CSV_VARIATION_NAME,
    definition=GENERATE_CSV_VARIATION_DEFINITION,
    executor=_execute_generate_csv_variation,
)

registry.register(generate_csv_variation_tool)

__all__ = [
    "GENERATE_CSV_VARIATION_NAME",
    "GENERATE_CSV_VARIATION_DEFINITION",
    "CsvVariationArgs",
    "CsvVariationResult",
    "generate_csv_variation_tool",
]
