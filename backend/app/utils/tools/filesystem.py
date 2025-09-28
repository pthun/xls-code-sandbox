"""Helpers for locating tool-scoped files stored on disk and in SQLite."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterator

__all__ = [
    "DATABASE_PATH",
    "UPLOAD_ROOT",
    "ToolFileRecord",
    "ToolFileNotFoundError",
    "ToolNotFoundError",
    "InvalidToolFilePathError",
    "db_connection",
    "ensure_tool_exists",
    "list_tool_files",
    "normalize_tool_path",
    "resolve_tool_file",
]

# Compute shared storage locations relative to the backend package root.
INSTANCE_DIR = Path(__file__).resolve().parents[3] / "instance"
DATABASE_PATH = INSTANCE_DIR / "tools.db"
UPLOAD_ROOT = INSTANCE_DIR / "uploads"


class ToolNotFoundError(LookupError):
    """Raised when a referenced tool_id does not exist."""


class ToolFileNotFoundError(FileNotFoundError):
    """Raised when a tool-scoped file record cannot be located."""


class InvalidToolFilePathError(ValueError):
    """Raised when a provided path escapes the tool's upload directory."""


@dataclass(slots=True)
class ToolFileRecord:
    """Materialized view of a stored tool file."""

    id: int
    tool_id: int
    original_filename: str
    stored_filename: str
    content_type: str | None
    size_bytes: int
    uploaded_at: datetime
    path: Path
    exists: bool


@contextmanager
def db_connection() -> Iterator[sqlite3.Connection]:
    """Yield a SQLite connection with row_factory configured."""

    connection = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
    connection.row_factory = sqlite3.Row
    try:
        yield connection
    finally:
        connection.close()


def ensure_tool_exists(connection: sqlite3.Connection, tool_id: int) -> None:
    """Validate that a tool id exists before performing file lookups."""

    row = connection.execute("SELECT 1 FROM tools WHERE id = ?", (tool_id,)).fetchone()
    if row is None:
        msg = f"Tool {tool_id} not found"
        raise ToolNotFoundError(msg)


def list_tool_files(tool_id: int) -> list[ToolFileRecord]:
    """Return all file records for a tool, newest first."""

    with db_connection() as connection:
        ensure_tool_exists(connection, tool_id)
        rows = connection.execute(
            """
            SELECT id, tool_id, original_filename, stored_filename, content_type, size_bytes, uploaded_at
            FROM tool_files
            WHERE tool_id = ?
            ORDER BY uploaded_at DESC
            """,
            (tool_id,),
        ).fetchall()

    records: list[ToolFileRecord] = []
    base_dir = (UPLOAD_ROOT / str(tool_id)).resolve()
    for row in rows:
        stored_filename = row["stored_filename"]
        file_path = (base_dir / stored_filename).resolve()
        records.append(
            ToolFileRecord(
                id=int(row["id"]),
                tool_id=tool_id,
                original_filename=row["original_filename"],
                stored_filename=stored_filename,
                content_type=row["content_type"],
                size_bytes=int(row["size_bytes"]),
                uploaded_at=datetime.fromisoformat(row["uploaded_at"]),
                path=file_path,
                exists=file_path.exists(),
            )
        )
    return records


def normalize_tool_path(tool_id: int, path_str: str) -> Path:
    """Normalize a possibly-relative path and enforce it stays within the upload dir."""

    base_dir = (UPLOAD_ROOT / str(tool_id)).resolve()
    candidate = Path(path_str)
    if not candidate.is_absolute():
        candidate = base_dir / candidate
    candidate = candidate.resolve()
    if not _is_relative_to(candidate, base_dir):
        msg = f"Path '{candidate}' is outside the upload directory for tool {tool_id}"
        raise InvalidToolFilePathError(msg)
    return candidate


def resolve_tool_file(
    tool_id: int,
    *,
    file_id: int | None = None,
    path: str | None = None,
) -> ToolFileRecord:
    """Resolve a specific file record by id or filesystem path."""

    if (file_id is None and path is None) or (file_id is not None and path is not None):
        raise ValueError("Provide exactly one of file_id or path")

    normalized_path: Path | None = None
    stored_filename: str | None = None
    base_dir = (UPLOAD_ROOT / str(tool_id)).resolve()

    with db_connection() as connection:
        ensure_tool_exists(connection, tool_id)
        if file_id is not None:
            row = connection.execute(
                """
                SELECT id, tool_id, original_filename, stored_filename, content_type, size_bytes, uploaded_at
                FROM tool_files
                WHERE tool_id = ? AND id = ?
                """,
                (tool_id, file_id),
            ).fetchone()
        else:
            normalized_path = normalize_tool_path(tool_id, path)
            candidate_name = normalized_path.name
            # Primary lookup: stored filename on disk.
            row = connection.execute(
                """
                SELECT id, tool_id, original_filename, stored_filename, content_type, size_bytes, uploaded_at
                FROM tool_files
                WHERE tool_id = ? AND stored_filename = ?
                """,
                (tool_id, candidate_name),
            ).fetchone()

            if row is None:
                # Secondary lookup: original filename as uploaded by the user.
                row = connection.execute(
                    """
                    SELECT id, tool_id, original_filename, stored_filename, content_type, size_bytes, uploaded_at
                    FROM tool_files
                    WHERE tool_id = ? AND original_filename = ?
                    ORDER BY uploaded_at DESC
                    LIMIT 1
                    """,
                    (tool_id, candidate_name),
                ).fetchone()

            if row is None:
                # Final attempt: treat the provided path as already relative to the tool directory.
                try:
                    relative_candidate = normalized_path.relative_to(base_dir)
                except ValueError:  # pragma: no cover - should not happen after normalize
                    relative_candidate = None

                if relative_candidate is not None and str(relative_candidate) != candidate_name:
                    row = connection.execute(
                        """
                        SELECT id, tool_id, original_filename, stored_filename, content_type, size_bytes, uploaded_at
                        FROM tool_files
                        WHERE tool_id = ? AND stored_filename = ?
                        """,
                        (tool_id, str(relative_candidate)),
                    ).fetchone()

    if row is None:
        if file_id is None:
            hint = normalized_path if normalized_path is not None else stored_filename
            msg = f"File not found for tool {tool_id}: {hint}"
        else:
            msg = f"File id {file_id} not found for tool {tool_id}"
        raise ToolFileNotFoundError(msg)

    stored_filename = row["stored_filename"]
    file_path = (base_dir / stored_filename).resolve()
    return ToolFileRecord(
        id=int(row["id"]),
        tool_id=tool_id,
        original_filename=row["original_filename"],
        stored_filename=stored_filename,
        content_type=row["content_type"],
        size_bytes=int(row["size_bytes"]),
        uploaded_at=datetime.fromisoformat(row["uploaded_at"]),
        path=file_path,
        exists=file_path.exists(),
    )


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False
