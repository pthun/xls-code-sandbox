"""Helpers for locating tool-scoped files stored on disk."""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

__all__ = [
    "DATABASE_PATH",
    "UPLOAD_ROOT",
    "VARIATIONS_ROOT",
    "DEFAULT_FOLDER_PREFIX",
    "VARIATION_PREFIX",
    "VARIATION_METADATA_FILENAME",
    "ToolFileRecord",
    "VariationFileEntry",
    "VariationRecord",
    "ToolFileNotFoundError",
    "ToolNotFoundError",
    "VariationNotFoundError",
    "InvalidToolFilePathError",
    "InvalidFolderPrefixError",
    "ensure_tool_exists",
    "list_tool_files",
    "list_variations",
    "create_variation_snapshot",
    "normalize_tool_path",
    "normalize_folder_prefix",
    "get_variation_record",
    "resolve_tool_file",
    "resolve_storage_root",
]

INSTANCE_DIR = Path(__file__).resolve().parents[3] / "instance"
DATABASE_PATH = INSTANCE_DIR / "tools.db"  # retained for compatibility with other modules
UPLOAD_ROOT = INSTANCE_DIR / "uploads"
VARIATIONS_ROOT = INSTANCE_DIR / "variations"
DEFAULT_FOLDER_PREFIX = "uploads"
VARIATION_PREFIX = "variation"
VARIATION_METADATA_FILENAME = "metadata.json"


class ToolNotFoundError(LookupError):
    """Raised when a referenced tool_id does not exist."""


class ToolFileNotFoundError(FileNotFoundError):
    """Raised when a tool-scoped file record cannot be located."""


class VariationNotFoundError(LookupError):
    """Raised when a requested variation directory is missing."""


class InvalidToolFilePathError(ValueError):
    """Raised when a provided path escapes the configured directory."""


class InvalidFolderPrefixError(ValueError):
    """Raised when a folder prefix is unsupported or malformed."""


@dataclass(slots=True)
class ToolFileRecord:
    """Filesystem-backed metadata describing a stored tool file."""

    tool_id: int
    original_filename: str
    stored_filename: str
    size_bytes: int
    uploaded_at: datetime
    path: Path


@dataclass(slots=True)
class VariationFileEntry:
    """Metadata about a file tracked within a variation directory."""

    original_filename: str
    stored_filename: str
    size_bytes: int
    uploaded_at: datetime


@dataclass(slots=True)
class VariationRecord:
    """Metadata describing a variation directory."""

    id: str
    tool_id: int
    path: Path
    created_at: datetime
    label: str | None
    files: list[VariationFileEntry]


def ensure_tool_exists(tool_id: int) -> None:
    """Best-effort presence check by inspecting the uploads directory."""

    tool_dir = (UPLOAD_ROOT / str(tool_id)).resolve()
    if not tool_dir.exists():
        # Lazily allow creation when a tool uploads its first file.
        tool_dir.mkdir(parents=True, exist_ok=True)


def list_tool_files(tool_id: int) -> list[ToolFileRecord]:
    """Return filesystem metadata for files stored under the tool uploads directory."""

    root = (UPLOAD_ROOT / str(tool_id)).resolve()
    if not root.exists():
        return []

    records: list[ToolFileRecord] = []
    for entry in root.iterdir():
        if not entry.is_file():
            continue
        stat = entry.stat()
        uploaded_at = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)
        name = entry.name
        records.append(
            ToolFileRecord(
                tool_id=tool_id,
                original_filename=name,
                stored_filename=name,
                size_bytes=stat.st_size,
                uploaded_at=uploaded_at,
                path=entry,
            )
        )
    records.sort(key=lambda item: item.uploaded_at, reverse=True)
    return records


def list_variations(tool_id: int) -> list[VariationRecord]:
    parent = (VARIATIONS_ROOT / str(tool_id)).resolve()
    if not parent.exists():
        return []

    records: list[VariationRecord] = []
    for entry in parent.iterdir():
        if not entry.is_dir() or not entry.name.isdigit():
            continue
        try:
            record = _load_variation_metadata(tool_id, entry.name)
        except VariationNotFoundError:
            continue
        records.append(record)
    records.sort(key=lambda item: item.created_at, reverse=True)
    return records


def create_variation_snapshot(tool_id: int, *, label: str | None = None) -> VariationRecord:
    variations_root = (VARIATIONS_ROOT / str(tool_id)).resolve()
    variations_root.mkdir(parents=True, exist_ok=True)

    variation_id = _next_variation_id(tool_id)
    target_dir = (variations_root / variation_id).resolve()
    target_dir.mkdir(parents=True, exist_ok=False)

    created_at = datetime.now(timezone.utc)
    source_files = list_tool_files(tool_id)

    files: list[VariationFileEntry] = []
    for record in source_files:
        destination = target_dir / record.stored_filename
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(record.path, destination)
        files.append(
            VariationFileEntry(
                original_filename=record.original_filename,
                stored_filename=record.stored_filename,
                size_bytes=record.size_bytes,
                uploaded_at=record.uploaded_at,
            )
        )

    variation = VariationRecord(
        id=variation_id,
        tool_id=tool_id,
        path=target_dir,
        created_at=created_at,
        label=label,
        files=files,
    )
    _write_variation_metadata(variation)
    return variation


def get_variation_record(tool_id: int, variation_id: str) -> VariationRecord:
    """Return metadata for a specific variation."""

    return _load_variation_metadata(tool_id, variation_id)


def resolve_storage_root(tool_id: int, folder_prefix: str | None = None, *, create: bool = False) -> Path:
    kind, variation_id = normalize_folder_prefix(folder_prefix)
    if kind == DEFAULT_FOLDER_PREFIX:
        base = (UPLOAD_ROOT / str(tool_id)).resolve()
        if create:
            base.mkdir(parents=True, exist_ok=True)
        return base

    base = (VARIATIONS_ROOT / str(tool_id) / variation_id).resolve()
    if create:
        base.mkdir(parents=True, exist_ok=True)
        return base
    if not base.exists():
        msg = f"Variation '{variation_id}' not found for tool {tool_id}"
        raise VariationNotFoundError(msg)
    return base


def normalize_tool_path(
    tool_id: int,
    path_str: str,
    *,
    folder_prefix: str | None = None,
) -> Path:
    base_dir = resolve_storage_root(tool_id, folder_prefix)
    candidate = Path(path_str)
    if not candidate.is_absolute():
        candidate = base_dir / candidate
    candidate = candidate.resolve()
    if not _is_relative_to(candidate, base_dir):
        msg = f"Path '{candidate}' is outside the allowed directory"
        raise InvalidToolFilePathError(msg)
    return candidate


def resolve_tool_file(
    tool_id: int,
    *,
    path: str,
    folder_prefix: str | None = None,
) -> ToolFileRecord:
    candidate = normalize_tool_path(tool_id, path, folder_prefix=folder_prefix)
    if not candidate.exists() or not candidate.is_file():
        msg = f"File not found for tool {tool_id}: {path}"
        raise ToolFileNotFoundError(msg)

    stat = candidate.stat()
    uploaded_at = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)
    name = candidate.name
    return ToolFileRecord(
        tool_id=tool_id,
        original_filename=name,
        stored_filename=name,
        size_bytes=stat.st_size,
        uploaded_at=uploaded_at,
        path=candidate,
    )


def normalize_folder_prefix(folder_prefix: str | None) -> tuple[str, str | None]:
    prefix = (folder_prefix or DEFAULT_FOLDER_PREFIX).strip()
    normalized = prefix.strip("/")

    if not normalized or normalized == DEFAULT_FOLDER_PREFIX:
        return DEFAULT_FOLDER_PREFIX, None

    if normalized.startswith(f"{VARIATION_PREFIX}/"):
        variation_id = normalized.split("/", 1)[1]
        if variation_id and variation_id.isdigit():
            return VARIATION_PREFIX, variation_id
        msg = f"Invalid variation prefix '{folder_prefix}'"
        raise InvalidFolderPrefixError(msg)

    msg = f"Unsupported folder prefix '{folder_prefix}'"
    raise InvalidFolderPrefixError(msg)


def _next_variation_id(tool_id: int) -> str:
    parent = (VARIATIONS_ROOT / str(tool_id)).resolve()
    if not parent.exists():
        return "0001"

    highest = 0
    for entry in parent.iterdir():
        if entry.is_dir() and entry.name.isdigit():
            highest = max(highest, int(entry.name))
    return f"{highest + 1:04d}"


def _load_variation_metadata(tool_id: int, variation_id: str) -> VariationRecord:
    directory = resolve_storage_root(tool_id, f"{VARIATION_PREFIX}/{variation_id}")
    metadata_path = directory / VARIATION_METADATA_FILENAME
    created_at = datetime.fromtimestamp(directory.stat().st_mtime, tz=timezone.utc)
    label: str | None = None
    files: list[VariationFileEntry] = []

    if metadata_path.exists():
        with metadata_path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        label = payload.get("label")
        created_raw = payload.get("created_at")
        if isinstance(created_raw, str):
            try:
                created_at = datetime.fromisoformat(created_raw)
                if created_at.tzinfo is None:
                    created_at = created_at.replace(tzinfo=timezone.utc)
                created_at = created_at.astimezone(timezone.utc)
            except ValueError:
                pass
        for raw in payload.get("files", []):
            name = raw.get("stored_filename") or raw.get("original_filename")
            if not isinstance(name, str):
                continue
            uploaded_at_raw = raw.get("uploaded_at")
            if isinstance(uploaded_at_raw, str):
                try:
                    uploaded_at = datetime.fromisoformat(uploaded_at_raw)
                    if uploaded_at.tzinfo is None:
                        uploaded_at = uploaded_at.replace(tzinfo=timezone.utc)
                    uploaded_at = uploaded_at.astimezone(timezone.utc)
                except ValueError:
                    uploaded_at = datetime.fromtimestamp(directory.stat().st_mtime, tz=timezone.utc)
            else:
                uploaded_at = datetime.fromtimestamp(directory.stat().st_mtime, tz=timezone.utc)
            size_bytes = int(raw.get("size_bytes", 0))
            files.append(
                VariationFileEntry(
                    original_filename=raw.get("original_filename", name),
                    stored_filename=name,
                    size_bytes=size_bytes,
                    uploaded_at=uploaded_at,
                )
            )

    if not files:
        for child in directory.iterdir():
            if child.is_dir() or child.name == VARIATION_METADATA_FILENAME:
                continue
            stat = child.stat()
            uploaded_at = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)
            files.append(
                VariationFileEntry(
                    original_filename=child.name,
                    stored_filename=child.name,
                    size_bytes=stat.st_size,
                    uploaded_at=uploaded_at,
                )
            )

    files.sort(key=lambda item: item.original_filename.lower())
    return VariationRecord(
        id=variation_id,
        tool_id=tool_id,
        path=directory,
        created_at=created_at,
        label=label,
        files=files,
    )


def _write_variation_metadata(record: VariationRecord) -> None:
    payload = {
        "id": record.id,
        "tool_id": record.tool_id,
        "label": record.label,
        "created_at": record.created_at.astimezone(timezone.utc).isoformat(),
        "files": [
            {
                "original_filename": entry.original_filename,
                "stored_filename": entry.stored_filename,
                "size_bytes": entry.size_bytes,
                "uploaded_at": entry.uploaded_at.astimezone(timezone.utc).isoformat(),
            }
            for entry in record.files
        ],
    }
    metadata_path = record.path / VARIATION_METADATA_FILENAME
    metadata_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False
