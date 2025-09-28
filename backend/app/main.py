from __future__ import annotations

import asyncio
import csv
import io
import json
import logging
import os
import shutil
import sqlite3
import urllib.parse
from contextlib import asynccontextmanager, suppress
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Generator, Literal, Sequence
from uuid import uuid4

import dotenv

from fastapi import Depends, FastAPI, File, HTTPException, Query, Response, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field, ValidationError
from pydantic.config import ConfigDict
from openai.types.responses import ResponseInputItemParam

from .prompts.e2b_assistant import build_e2b_assistant_prompt
from .prompts.eval_file_generator import build_eval_file_prompt
from .utils.e2b import (
    E2BTestRequest,
    E2BTestResponse,
    PersistedFile,
    SandboxExecutionResult,
    execute_e2b_test,
)
from .utils.openai import (
    call_openai_responses,
)
from .utils.tools import (
    EDIT_TOOL_NAMES,
    READ_ONLY_TOOL_NAMES,
    ResponseTool,
    registry as tool_registry,
)
from .utils.tools.filesystem import (
    DEFAULT_FOLDER_PREFIX,
    VARIATION_METADATA_FILENAME,
    VARIATION_PREFIX,
    VariationFileEntry,
    InvalidFolderPrefixError,
    InvalidToolFilePathError,
    VariationNotFoundError,
    VariationRecord,
    create_variation_snapshot,
    get_variation_record,
    list_tool_files,
    list_variations,
    normalize_folder_prefix,
    normalize_tool_path,
    resolve_storage_root,
)
from .utils.misc.typeguards import is_any_list

dotenv.load_dotenv()


INSTANCE_DIR = Path(__file__).resolve().parent.parent / "instance"
DATABASE_PATH = INSTANCE_DIR / "tools.db"
UPLOAD_ROOT = INSTANCE_DIR / "uploads"
RUNS_ROOT = INSTANCE_DIR / "runs"
ALLOWED_EXTENSIONS = {".csv", ".xls", ".xlsx"}


logger = logging.getLogger(__name__)


LogSinkFn = Callable[[list[str]], None]


ParamMetadata = dict[str, object]
FileMetadata = dict[str, object]


class DoubleRequest(BaseModel):
    """Request payload sent by the frontend when asking for a doubled value."""

    value: float = Field(..., description="The numeric value to double")


class DoubleResponse(BaseModel):
    """Response returned by the API once the value has been doubled."""

    input: float = Field(..., description="The original value provided by the client")
    doubled: float = Field(..., description="The doubled result")
    message: str = Field(..., description="A human friendly explanation of the result")


class HealthResponse(BaseModel):
    """Simple response model used for the root health check."""

    status: str = Field(..., description="Overall API status indicator")
    message: str = Field(..., description="Additional context about the API state")


class Tool(BaseModel):
    id: int
    name: str
    created_at: datetime


class ToolFile(BaseModel):
    filename: str
    path: str
    size_bytes: int
    modified_at: datetime


class ToolDetail(Tool):
    files: list[ToolFile] = Field(default_factory=lambda: [])


class ToolUpdateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)


ChatRole = Literal["user", "assistant"]


class ChatMessage(BaseModel):
    role: ChatRole
    content: str = Field(..., min_length=1)


class ChatRequest(BaseModel):
    messages: Sequence[ChatMessage] = Field(..., min_length=1)
    model: str | None = Field(
        default=None, description="Override the default OpenAI model name"
    )
    folder_prefix: str | None = Field(
        default=DEFAULT_FOLDER_PREFIX,
        description=(
            "Storage namespace to expose to the assistant (e.g. 'uploads' or 'variation/0001')."
        ),
    )


class ChatHistoryUpdateRequest(BaseModel):
    messages: list[StoredChatMessage] = Field(default_factory=lambda: [])


class StoredChatMessage(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str | None = None
    role: ChatRole
    content: str
    code: str | None = None
    pipPackages: list[str] | None = None
    kind: str | None = None


class ChatAssistantMessage(BaseModel):
    role: Literal["assistant"] = "assistant"
    content: str


class VariationFilePayload(BaseModel):
    filename: str
    path: str
    size_bytes: int
    modified_at: datetime


class VariationResponse(BaseModel):
    id: str
    tool_id: int
    label: str | None
    created_at: datetime
    prefix: str
    files: list[VariationFilePayload] = Field(default_factory=lambda: [])


class VariationCreateRequest(BaseModel):
    label: str | None = Field(default=None, max_length=200)


class ChatUsage(BaseModel):
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None


class ChatCompletionResponse(BaseModel):
    message: ChatAssistantMessage
    code: str | None = None
    pip_packages: list[str] = Field(default_factory=list)
    usage: ChatUsage | None = None
    raw: str | None = None
    version: int | None = None
    params: list[ParamMetadata] = Field(default_factory=lambda: [])
    required_files: list[FileMetadata] = Field(default_factory=lambda: [])


class ToolCallResult(BaseModel):
    """Outcome of a single tool execution."""

    success: bool
    output: dict[str, Any] | str | None = None
    error: str | None = None


class EvalChatCompletionResponse(BaseModel):
    """Response payload for the eval file generation chat endpoint."""

    message: ChatAssistantMessage
    usage: ChatUsage | None = None
    raw: str | None = None


class ToolTestPayload(BaseModel):
    """Minimal payload returned by the hello world tool test endpoint."""

    assistant_text: str
    raw_text: str
    tool_result: ToolCallResult | None = None


def _usage_from_tokens(
    prompt_tokens: int | None,
    completion_tokens: int | None,
    total_tokens: int | None,
) -> ChatUsage | None:
    if prompt_tokens is None and completion_tokens is None and total_tokens is None:
        return None
    return ChatUsage(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
    )


def _ensure_initial_code_version_for_tool(tool_id: int) -> CodeVersionDetail:
    _ensure_tool_exists(tool_id)
    connection = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA foreign_keys = ON;")
        row = connection.execute(
            """
            SELECT tool_version
            FROM code_versions
            WHERE tool_id = ?
            ORDER BY tool_version DESC
            LIMIT 1
            """,
            (tool_id,),
        ).fetchone()
        if row is not None and row["tool_version"]:
            version = int(row["tool_version"])
            return _get_code_version_detail(tool_id, version)
    finally:
        connection.close()

    return _create_code_version(
        tool_id=tool_id,
        code=DEFAULT_CODE,
        pip_packages=DEFAULT_PIP_PACKAGES,
        author="system",
        note="Initial version",
        origin_run_id=None,
        params=[],
        required_files=[],
    )


def _parse_param_specs(value: str | None) -> list[ParamSpec]:
    if not value:
        return []
    try:
        raw = json.loads(value)
    except json.JSONDecodeError:
        return []

    specs: list[ParamSpec] = []
    if is_any_list(raw):
        for item in raw:
            if not isinstance(item, dict):
                continue
            try:
                specs.append(ParamSpec.model_validate(item))
            except ValidationError:
                continue
    return specs


def _parse_file_requirements(value: str | None) -> list[FileRequirement]:
    if not value:
        return []
    try:
        raw = json.loads(value)
    except json.JSONDecodeError:
        return []

    files: list[FileRequirement] = []
    if is_any_list(raw):
        for item in raw:
            if not isinstance(item, dict):
                continue
            try:
                files.append(FileRequirement.model_validate(item))
            except ValidationError:
                continue
    return files


def _coerce_param_specs(items: Sequence[ParamMetadata]) -> list[ParamSpec]:
    specs: list[ParamSpec] = []
    for item in items:
        try:
            specs.append(ParamSpec.model_validate(item))
        except ValidationError:
            continue
    return specs


def _coerce_file_requirements(items: Sequence[FileMetadata]) -> list[FileRequirement]:
    files: list[FileRequirement] = []
    for item in items:
        try:
            files.append(FileRequirement.model_validate(item))
        except ValidationError:
            continue
    return files


def _params_to_dicts(items: Sequence[ParamSpec]) -> list[ParamMetadata]:
    dictionaries: list[ParamMetadata] = []
    for item in items:
        dumped = item.model_dump()
        dictionaries.append({key: value for key, value in dumped.items()})
    return dictionaries


def _files_to_dicts(items: Sequence[FileRequirement]) -> list[FileMetadata]:
    dictionaries: list[FileMetadata] = []
    for item in items:
        dumped = item.model_dump()
        dictionaries.append({key: value for key, value in dumped.items()})
    return dictionaries


def _load_chat_history_for_table(
    table: str,
    tool_id: int,
) -> list[StoredChatMessage]:
    connection = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
    connection.row_factory = sqlite3.Row
    try:
        rows = connection.execute(
            f"""
            SELECT payload
            FROM {table}
            WHERE tool_id = ?
            ORDER BY order_index ASC, id ASC
            """,
            (tool_id,),
        ).fetchall()
    finally:
        connection.close()

    history: list[StoredChatMessage] = []
    for row in rows:
        payload = row["payload"]
        if not payload:
            continue
        try:
            message = StoredChatMessage.model_validate_json(payload)
        except ValidationError:
            try:
                parsed = json.loads(payload)
            except json.JSONDecodeError:
                continue
            try:
                message = StoredChatMessage.model_validate(parsed)
            except ValidationError:
                continue
        history.append(message)
    return history


def _load_chat_history(tool_id: int) -> list[StoredChatMessage]:
    return _load_chat_history_for_table("e2b_chat_messages", tool_id)


def _load_eval_chat_history(tool_id: int) -> list[StoredChatMessage]:
    return _load_chat_history_for_table("eval_chat_messages", tool_id)


def _replace_chat_history_for_table(
    table: str,
    tool_id: int,
    messages: Sequence[StoredChatMessage],
) -> None:
    connection = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
    try:
        connection.execute("PRAGMA foreign_keys = ON;")
        connection.execute(
            f"DELETE FROM {table} WHERE tool_id = ?",
            (tool_id,),
        )
        now_iso = _iso(datetime.now(timezone.utc))
        for order, message in enumerate(messages):
            connection.execute(
                f"""
                INSERT INTO {table} (
                    tool_id,
                    created_at,
                    order_index,
                    payload
                ) VALUES (?, ?, ?, ?)
                """,
                (
                    tool_id,
                    now_iso,
                    order,
                    json.dumps(message.model_dump(mode="json")),
                ),
            )
        connection.commit()
    finally:
        connection.close()


def _replace_chat_history(tool_id: int, messages: Sequence[StoredChatMessage]) -> None:
    _replace_chat_history_for_table("e2b_chat_messages", tool_id, messages)


def _replace_eval_chat_history(tool_id: int, messages: Sequence[StoredChatMessage]) -> None:
    _replace_chat_history_for_table("eval_chat_messages", tool_id, messages)


def _clear_chat_history_for_table(table: str, tool_id: int) -> None:
    connection = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
    try:
        connection.execute("PRAGMA foreign_keys = ON;")
        connection.execute(f"DELETE FROM {table} WHERE tool_id = ?", (tool_id,))
        connection.commit()
    finally:
        connection.close()


def _clear_chat_history(tool_id: int) -> None:
    _clear_chat_history_for_table("e2b_chat_messages", tool_id)


def _clear_eval_chat_history(tool_id: int) -> None:
    _clear_chat_history_for_table("eval_chat_messages", tool_id)


def _param_matches_type(value: Any, expected: str) -> bool:
    normalized = expected.strip().lower()
    if normalized in {"string", "str"}:
        return isinstance(value, str)
    if normalized in {"integer", "int"}:
        return isinstance(value, int) and not isinstance(value, bool)
    if normalized in {"number", "float"}:
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if normalized in {"boolean", "bool"}:
        return isinstance(value, bool)
    if normalized in {"object", "dict"}:
        return isinstance(value, dict)
    if normalized in {"array", "list"}:
        return isinstance(value, list)
    return True


def _glob_required_files(pattern: str, *, base_dir: Path | None = None) -> list[Path]:
    if not pattern:
        return []

    candidate = Path(pattern)
    if candidate.is_absolute():
        return [candidate] if candidate.exists() else []

    search_roots: list[Path] = []
    if base_dir is not None:
        search_roots.append(base_dir)
    else:
        search_roots.append(UPLOAD_ROOT)

    matches: list[Path] = []
    for root in search_roots:
        if not root.exists():
            continue
        if "/" in pattern or pattern.startswith("**"):
            matches.extend(root.glob(pattern))
        else:
            matches.extend(root.rglob(pattern))

    # Deduplicate while preserving order
    seen: set[Path] = set()
    unique_matches: list[Path] = []
    for path in matches:
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        unique_matches.append(resolved)

    return unique_matches


def _canonical_folder_prefix(folder_prefix: str | None) -> str:
    """Return the normalized storage prefix or raise an HTTP error if invalid."""

    try:
        kind, variation_id = normalize_folder_prefix(folder_prefix)
    except InvalidFolderPrefixError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if kind == DEFAULT_FOLDER_PREFIX:
        return DEFAULT_FOLDER_PREFIX

    if variation_id is None:
        raise HTTPException(status_code=400, detail="Variation identifier is required")

    return f"{VARIATION_PREFIX}/{variation_id}"


def _collect_input_files(tool_id: int, folder_prefix: str) -> list[tuple[str, Path]]:
    """Resolve file tuples to seed into the sandbox for a given storage prefix."""

    kind, variation_id = normalize_folder_prefix(folder_prefix)

    if kind == DEFAULT_FOLDER_PREFIX:
        records = list_tool_files(tool_id)
        return [
            (record.original_filename, record.path)
            for record in records
            if record.path.is_file()
        ]

    if kind == VARIATION_PREFIX and variation_id is not None:
        try:
            variation = get_variation_record(tool_id, variation_id)
        except VariationNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

        inputs: list[tuple[str, Path]] = []
        for entry in variation.files:
            candidate = (variation.path / entry.stored_filename).resolve()
            if not candidate.is_file():
                continue
            inputs.append((entry.original_filename, candidate))
        return inputs

    raise HTTPException(
        status_code=400,
        detail=f"Unsupported folder prefix '{folder_prefix}'",
    )


def _validate_run_inputs(
    payload: E2BTestRequest,
    detail: CodeVersionDetail,
    *,
    tool_id: int,
    folder_prefix: str,
) -> None:
    params = payload.params or {}
    missing_params: list[str] = []
    invalid_params: list[dict[str, str]] = []
    for spec in detail.params:
        if spec.required and spec.name not in params:
            missing_params.append(spec.name)
            continue
        if spec.name in params and spec.type:
            if not _param_matches_type(params[spec.name], spec.type):
                invalid_params.append(
                    {
                        "name": spec.name,
                        "expected": spec.type,
                        "actual": type(params[spec.name]).__name__,
                    }
                )

    missing_files: list[str] = []
    try:
        base_dir = resolve_storage_root(tool_id, folder_prefix)
    except VariationNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    for requirement in detail.required_files:
        if not requirement.required:
            continue
        matches = _glob_required_files(requirement.pattern, base_dir=base_dir)
        if not matches:
            missing_files.append(requirement.pattern)

    if missing_params or invalid_params or missing_files:
        detail_payload: dict[str, Any] = {
            "message": "Run requirements not satisfied",
            "missing_params": missing_params or None,
            "invalid_params": invalid_params or None,
            "missing_files": missing_files or None,
        }
        raise HTTPException(status_code=400, detail=detail_payload)


def _row_to_code_version_detail(row: sqlite3.Row) -> CodeVersionDetail:
    params_payload = row["params_model"] if "params_model" in row.keys() else None
    files_payload = row["required_files"] if "required_files" in row.keys() else None
    tool_version = row["tool_version"] if "tool_version" in row.keys() else None
    if tool_version is None:
        tool_version = row["version"]
    return CodeVersionDetail(
        version=tool_version,
        created_at=datetime.fromisoformat(row["created_at"]),
        author=row["author"],
        note=row["note"],
        code=row["code"],
        pip_packages=json.loads(row["pip_packages"] or "[]"),
        origin_run_id=row["origin_run_id"],
        params=_parse_param_specs(params_payload),
        required_files=_parse_file_requirements(files_payload),
        record_id=row["version"],
    )


def _row_to_code_version_summary(row: sqlite3.Row) -> CodeVersionSummary:
    tool_version = row["tool_version"] if "tool_version" in row.keys() else None
    if tool_version is None:
        tool_version = row["version"]
    return CodeVersionSummary(
        version=tool_version,
        created_at=datetime.fromisoformat(row["created_at"]),
        author=row["author"],
        note=row["note"],
        record_id=row["version"],
    )


def _ensure_current_code_version(tool_id: int) -> CodeVersionDetail:
    return _ensure_initial_code_version_for_tool(tool_id)


def _get_code_version_detail(tool_id: int, version: int) -> CodeVersionDetail:
    connection = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
    connection.row_factory = sqlite3.Row
    try:
        row = connection.execute(
            """
            SELECT version, tool_id, tool_version, created_at, author, note, code, pip_packages, origin_run_id, params_model, required_files
            FROM code_versions
            WHERE tool_id = ? AND tool_version = ?
            """,
            (tool_id, version),
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Code version not found")
        return _row_to_code_version_detail(row)
    finally:
        connection.close()


def _resolve_code_version_detail(tool_id: int, payload: E2BTestRequest) -> CodeVersionDetail:
    current_detail = _ensure_current_code_version(tool_id)
    requested = payload.code_version
    if requested is not None and requested != current_detail.version:
        return _get_code_version_detail(tool_id, requested)
    return current_detail


def _list_code_versions(tool_id: int, limit: int = 50) -> list[CodeVersionSummary]:
    connection = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
    connection.row_factory = sqlite3.Row
    try:
        rows = connection.execute(
            """
            SELECT version, tool_version, created_at, author, note
            FROM code_versions
            WHERE tool_id = ?
            ORDER BY tool_version DESC
            LIMIT ?
            """,
            (tool_id, limit),
        ).fetchall()
        return [_row_to_code_version_summary(row) for row in rows]
    finally:
        connection.close()


def _create_code_version(
    *,
    tool_id: int,
    code: str,
    pip_packages: Sequence[str],
    author: str,
    note: str | None = None,
    origin_run_id: str | None = None,
    params: Sequence[ParamSpec] | None = None,
    required_files: Sequence[FileRequirement] | None = None,
) -> CodeVersionDetail:
    now = datetime.now(timezone.utc)
    connection = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
    try:
        connection.execute("PRAGMA foreign_keys = ON;")
        connection.row_factory = sqlite3.Row
        tool_version_row = connection.execute(
            "SELECT COALESCE(MAX(tool_version), 0) + 1 AS next_version FROM code_versions WHERE tool_id = ?",
            (tool_id,),
        ).fetchone()
        next_tool_version = int(tool_version_row["next_version"]) if tool_version_row else 1
        cursor = connection.execute(
            """
            INSERT INTO code_versions (
                tool_id,
                tool_version,
                created_at,
                author,
                note,
                code,
                pip_packages,
                origin_run_id,
                params_model,
                required_files
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                tool_id,
                next_tool_version,
                _iso(now),
                author,
                note,
                code,
                json.dumps(list(pip_packages)),
                origin_run_id,
                json.dumps(_params_to_dicts(params or [])),
                json.dumps(_files_to_dicts(required_files or [])),
            ),
        )
        version = cursor.lastrowid
        connection.commit()
    finally:
        connection.close()
    if version is None:
        raise RuntimeError("Failed to create new code version")
    return _get_code_version_detail(tool_id, next_tool_version)


def _build_version_chat_message(
    *,
    actor: str,
    description: str,
    version: CodeVersionDetail,
    base_version: int | None = None,
) -> str:
    lines = [f"{actor} {description}. (version {version.version})"]
    if base_version is not None:
        lines.append(f"Based on version {base_version}.")
    lines.append(f"<CodeOutput>{version.code}</CodeOutput>")
    if version.pip_packages:
        lines.append("<Pip>\n" + "\n".join(version.pip_packages) + "\n</Pip>")
    if version.params:
        params_json = json.dumps(_params_to_dicts(version.params), indent=2)
        lines.append("<Params>\n" + params_json + "\n</Params>")
    if version.required_files:
        files_json = json.dumps(_files_to_dicts(version.required_files), indent=2)
        lines.append("<FileList>\n" + files_json + "\n</FileList>")
    return "\n".join(lines)
def _write_run_metadata(run_dir: Path, metadata: dict[str, object]) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    metadata_path = run_dir / "metadata.json"
    metadata_path.write_text(json.dumps(metadata, indent=2, default=str), encoding="utf-8")


def _save_run_record(
    *,
    tool_id: int,
    run_id: str,
    created_at: str,
    payload: E2BTestRequest,
    response: E2BTestResponse,
    run_dir: Path,
    persisted_files: Sequence[PersistedFile],
    logs_path: Path,
    code_version_label: int,
    code_version_id: int | None,
    folder_prefix: str,
) -> None:
    params_json = json.dumps(payload.params)
    pip_json = json.dumps(payload.pip_packages)
    allow_internet = 1 if payload.allow_internet else 0
    ok_value = int(bool(response.ok))
    error_text = response.error
    logs_relative = str(logs_path.relative_to(run_dir))

    connection = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
    try:
        connection.execute("PRAGMA foreign_keys = ON;")
        if code_version_id is None:
            lookup = connection.execute(
                "SELECT version FROM code_versions WHERE tool_id = ? AND tool_version = ?",
                (tool_id, code_version_label),
            ).fetchone()
            if lookup is None:
                raise HTTPException(status_code=404, detail="Associated code version not found")
            code_version_id = int(lookup["version"])
        try:
            connection.execute(
                """
                INSERT OR REPLACE INTO e2b_runs (
                    id,
                    tool_id,
                    created_at,
                    code_version,
                    params,
                    pip_packages,
                    allow_internet,
                    ok,
                    error,
                    logs_path,
                    folder_prefix
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    tool_id,
                    created_at,
                    code_version_id,
                    params_json,
                    pip_json,
                    allow_internet,
                    ok_value,
                    error_text,
                    logs_relative,
                    folder_prefix,
                ),
            )
        except sqlite3.IntegrityError as exc:
            logger.error(
                "Failed to persist run %s (code_version=%s): %s",
                run_id,
                code_version_id,
                exc,
            )
            raise HTTPException(
                status_code=500,
                detail={
                    "message": "Unable to record run in history",
                    "code_version": code_version_label,
                    "error": str(exc),
                },
            ) from exc

        connection.execute(
            "DELETE FROM e2b_run_files WHERE run_id = ?",
            (run_id,),
        )

        for file_record in persisted_files:
            local_relative = str(file_record.local_path.relative_to(run_dir))
            connection.execute(
                """
                INSERT INTO e2b_run_files (
                    run_id,
                    sandbox_path,
                    local_path,
                    size_bytes
                ) VALUES (?, ?, ?, ?)
                """,
                (
                    run_id,
                    file_record.sandbox_path,
                    local_relative,
                    file_record.size_bytes,
                ),
            )

        connection.commit()
    finally:
        connection.close()


def _finalize_run_record(
    run_id: str,
    payload: E2BTestRequest,
    execution: SandboxExecutionResult,
    created_at: datetime,
    tool_id: int,
) -> None:
    run_dir = execution.run_dir or (RUNS_ROOT / run_id)
    run_dir.mkdir(parents=True, exist_ok=True)

    logs_path = execution.logs_path
    if logs_path is None:
        logs_path = run_dir / "logs.txt"
        logs_path.write_text(
            "\n".join(execution.response.logs),
            encoding="utf-8",
        )

    metadata: dict[str, object] = {
        "run_id": run_id,
        "tool_id": tool_id,
        "created_at": created_at.isoformat(),
        "code": payload.code,
        "params": payload.params,
        "pip_packages": payload.pip_packages,
        "allow_internet": payload.allow_internet,
        "response": execution.response.model_dump(),
        "code_version": execution.code_version,
        "folder_prefix": payload.folder_prefix or DEFAULT_FOLDER_PREFIX,
    }
    _write_run_metadata(run_dir, metadata)

    folder_prefix = payload.folder_prefix or DEFAULT_FOLDER_PREFIX

    _save_run_record(
        tool_id=tool_id,
        run_id=run_id,
        created_at=_iso(created_at),
        payload=payload,
        response=execution.response,
        run_dir=run_dir,
        persisted_files=execution.persisted_files,
        logs_path=logs_path,
        code_version_label=execution.code_version,
        code_version_id=execution.code_version_id
        if execution.code_version_id is not None
        else execution.code_version,
        folder_prefix=folder_prefix,
    )


def _execute_run(
    payload: E2BTestRequest,
    *,
    tool_id: int,
    run_id: str,
    log_sink: LogSinkFn | None = None,
) -> SandboxExecutionResult:
    folder_prefix = _canonical_folder_prefix(payload.folder_prefix)
    payload.folder_prefix = folder_prefix  # ensure downstream consumers see the canonical value
    version_detail = _resolve_code_version_detail(tool_id, payload)
    code_version_label = version_detail.version
    code_version_id = version_detail.record_id
    logger.info(
        "Executing run %s for tool %s using code_version=%s (requested=%s, prefix=%s)",
        run_id,
        tool_id,
        code_version_label,
        payload.code_version,
        folder_prefix,
    )
    _validate_run_inputs(payload, version_detail, tool_id=tool_id, folder_prefix=folder_prefix)
    sandbox_inputs = _collect_input_files(tool_id, folder_prefix)
    execution = execute_e2b_test(
        payload,
        log_sink=log_sink,
        run_id=run_id,
        persist_root=RUNS_ROOT,
        code_version=code_version_label,
        input_files=sandbox_inputs,
    )
    if execution.response.run_id is None:
        execution.response.run_id = run_id
    if execution.response.code_version is None:
        execution.response.code_version = code_version_label
    execution.code_version_id = code_version_id
    return execution

class RunFileResponse(BaseModel):
    sandbox_path: str
    local_path: str
    size_bytes: int
    download_url: str


class RunSummaryResponse(BaseModel):
    id: str
    created_at: datetime
    ok: bool | None
    error: str | None
    code_version: int
    folder_prefix: str | None = None


class RunDetailResponse(RunSummaryResponse):
    code: str
    params: dict[str, Any]
    pip_packages: list[str]
    allow_internet: bool
    logs: list[str]
    files: list[RunFileResponse]
    code_version: int


class ParamSpec(BaseModel):
    name: str = Field(..., min_length=1)
    type: str | None = Field(default=None)
    required: bool = True
    description: str | None = None


class FileRequirement(BaseModel):
    pattern: str = Field(..., min_length=1)
    required: bool = True
    description: str | None = None


class CodeVersionSummary(BaseModel):
    version: int
    created_at: datetime
    author: str
    note: str | None
    record_id: int = Field(..., exclude=True)


class CodeVersionDetail(CodeVersionSummary):
    code: str
    pip_packages: list[str]
    origin_run_id: str | None
    params: list[ParamSpec]
    required_files: list[FileRequirement]


class CodeVersionUpdateRequest(BaseModel):
    code: str = Field(..., min_length=1)
    pip_packages: list[str] = Field(default_factory=list)
    note: str | None = None
    params: list[ParamSpec] = Field(default_factory=lambda: [])
    required_files: list[FileRequirement] = Field(default_factory=lambda: [])


class CodeVersionRevertRequest(BaseModel):
    version: int
    note: str | None = None


class CodeVersionUpdateResponse(BaseModel):
    version: CodeVersionDetail
    chat_message: str


DEFAULT_CODE = '''def run(params, ctx):
    """Default sandbox entrypoint."""

    ctx.log("Starting default run")
    return {"ok": True}
'''
DEFAULT_PIP_PACKAGES: list[str] = []


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def init_storage() -> None:
    UPLOAD_ROOT.mkdir(parents=True, exist_ok=True)
    RUNS_ROOT.mkdir(parents=True, exist_ok=True)


def init_db() -> None:
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DATABASE_PATH, check_same_thread=False) as connection:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON;")
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS tools (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS code_versions (
                version INTEGER PRIMARY KEY AUTOINCREMENT,
                tool_id INTEGER REFERENCES tools(id) ON DELETE CASCADE,
                created_at TEXT NOT NULL,
                author TEXT NOT NULL,
                note TEXT,
                code TEXT NOT NULL,
                pip_packages TEXT NOT NULL,
                origin_run_id TEXT,
                params_model TEXT NOT NULL DEFAULT '[]',
                required_files TEXT NOT NULL DEFAULT '[]'
            );

            CREATE TABLE IF NOT EXISTS e2b_runs (
                id TEXT PRIMARY KEY,
                tool_id INTEGER REFERENCES tools(id) ON DELETE CASCADE,
                created_at TEXT NOT NULL,
                code_version INTEGER NOT NULL REFERENCES code_versions(version),
                params TEXT NOT NULL,
                pip_packages TEXT NOT NULL,
                allow_internet INTEGER NOT NULL,
                ok INTEGER,
                error TEXT,
                logs_path TEXT
            );

            CREATE TABLE IF NOT EXISTS e2b_run_files (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL REFERENCES e2b_runs(id) ON DELETE CASCADE,
                sandbox_path TEXT NOT NULL,
                local_path TEXT NOT NULL,
                size_bytes INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS e2b_chat_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tool_id INTEGER NOT NULL REFERENCES tools(id) ON DELETE CASCADE,
                created_at TEXT NOT NULL,
                order_index INTEGER NOT NULL,
                payload TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS eval_chat_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tool_id INTEGER NOT NULL REFERENCES tools(id) ON DELETE CASCADE,
                created_at TEXT NOT NULL,
                order_index INTEGER NOT NULL,
                payload TEXT NOT NULL
            );
            """
        )

        def _ensure_column(table: str, column: str, definition: str) -> None:
            columns = connection.execute(f"PRAGMA table_info({table})").fetchall()
            if not any(col["name"] == column for col in columns):
                connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

        _ensure_column(
            "code_versions",
            "tool_id",
            "INTEGER REFERENCES tools(id) ON DELETE CASCADE",
        )
        _ensure_column(
            "code_versions",
            "tool_version",
            "INTEGER NOT NULL DEFAULT 0",
        )
        _ensure_column(
            "e2b_runs",
            "tool_id",
            "INTEGER REFERENCES tools(id) ON DELETE CASCADE",
        )
        _ensure_column(
            "e2b_runs",
            "folder_prefix",
            "TEXT",
        )

        connection.execute(
            "UPDATE e2b_runs SET folder_prefix = ? WHERE folder_prefix IS NULL",
            (DEFAULT_FOLDER_PREFIX,),
        )

        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_code_versions_tool ON code_versions(tool_id, version)"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_e2b_runs_tool ON e2b_runs(tool_id, created_at DESC)"
        )
        connection.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_code_versions_tool_version ON code_versions(tool_id, tool_version)"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_chat_messages_tool ON e2b_chat_messages(tool_id, order_index)"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_eval_chat_messages_tool ON eval_chat_messages(tool_id, order_index)"
        )

        rows = connection.execute(
            "SELECT version, tool_id FROM code_versions WHERE tool_version = 0 ORDER BY tool_id, version"
        ).fetchall()
        progress: dict[int, int] = {}
        for row in rows:
            tool_value = row["tool_id"]
            if tool_value is None:
                connection.execute(
                    "UPDATE code_versions SET tool_version = ? WHERE version = ?",
                    (row["version"], row["version"]),
                )
                continue
            next_index = progress.get(tool_value, 0) + 1
            connection.execute(
                "UPDATE code_versions SET tool_version = ? WHERE version = ?",
                (next_index, row["version"]),
            )
            progress[tool_value] = next_index
        connection.commit()

def get_db() -> Generator[sqlite3.Connection, None, None]:
    connection = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON;")
    try:
        yield connection
    finally:
        connection.close()


def _ensure_tool_exists(tool_id: int, connection: sqlite3.Connection | None = None) -> None:
    owns_connection = False
    if connection is None:
        connection = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON;")
        owns_connection = True
    try:
        row = connection.execute(
            "SELECT 1 FROM tools WHERE id = ?",
            (tool_id,),
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Tool not found")
    finally:
        if owns_connection:
            connection.close()


def row_to_tool(row: sqlite3.Row) -> Tool:
    return Tool(
        id=row["id"],
        name=row["name"],
        created_at=datetime.fromisoformat(row["created_at"]),
    )


def validate_upload_contents(extension: str, contents: bytes) -> None:
    if extension == ".csv":
        try:
            sample = contents.decode("utf-8-sig")
        except UnicodeDecodeError as exc:  # pragma: no cover
            raise HTTPException(status_code=400, detail=f"CSV decode error: {exc}") from exc

        reader = csv.reader(io.StringIO(sample))
        try:
            next(reader)
        except StopIteration:
            raise HTTPException(status_code=400, detail="CSV file appears to be empty")
        except csv.Error as exc:
            raise HTTPException(status_code=400, detail=f"CSV parsing failed: {exc}") from exc
    elif extension == ".xlsx":
        if openpyxl is None:  # pragma: no cover
            return
        try:
            workbook = openpyxl.load_workbook(io.BytesIO(contents), read_only=True)
            workbook.close()
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Invalid XLSX file: {exc}") from exc
    elif extension == ".xls":
        if xlrd is None:  # pragma: no cover
            return
        try:
            xlrd.open_workbook(file_contents=contents)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Invalid XLS file: {exc}") from exc


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_storage()
    init_db()
    yield


app = FastAPI(
    title="Tool Builder API",
    version="0.2.0",
    summary="Manage analysis tools and their uploaded data",
    lifespan=lifespan,
)


allowed_origins = [
    "http://localhost:3100",
    "http://127.0.0.1:3100",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/", response_model=HealthResponse, summary="Service status")
def read_root() -> HealthResponse:
    """Return a basic health-check payload for quick diagnostics."""

    return HealthResponse(
        status="ok",
        message="Tool Builder API is running",
    )


@app.post(
    "/api/double",
    response_model=DoubleResponse,
    summary="Double the provided numeric value",
)
def double_number(payload: DoubleRequest) -> DoubleResponse:
    """Double the incoming value and return a descriptive response."""

    doubled_value = payload.value * 2
    return DoubleResponse(
        input=payload.value,
        doubled=doubled_value,
        message=f"{payload.value} doubled is {doubled_value}",
    )


@app.get(
    "/api/tool-test",
    response_model=ToolTestPayload,
    summary="Invoke the built-in hello world tool",
)
async def run_tool_test() -> ToolTestPayload:
    """Execute a minimal Responses invocation that triggers the hello world tool."""

    tool = tool_registry.get("hello_world")
    api_key = os.getenv("OPENAI_API_KEY")

    if not api_key:
        raise HTTPException(
            status_code=500,
            detail="OPENAI_API_KEY is not configured on the server",
        )

    system_prompt = "Call the provided tools whenever they help answer the user."
    messages: list[ResponseInputItemParam] = [
        {
            "role": "user",
            "content": "Use the hello_world tool once and share the greeting that it returns.",
        },
    ]

    model_name = os.getenv("OPENAI_TOOL_TEST_MODEL", os.getenv("OPENAI_MODEL", "gpt-4.1"))

    try:
        (
            _response,
            display_text,
            _code,
            _pip_packages,
            _params_model,
            _file_requirements,
            _params_present,
            _file_present,
            _prompt_tokens,
            _completion_tokens,
            _total_tokens,
            raw_text,
            executions,
        ) = await call_openai_responses(
            tool_id=0,
            api_key=api_key,
            system_prompt=system_prompt,
            messages=messages,
            model_name=model_name,
            tool_names=[tool.name],
            folder_prefix=DEFAULT_FOLDER_PREFIX,
        )
    except Exception as exc:  # pragma: no cover - network interaction
        logger.exception("OpenAI tool test failed", exc_info=exc)
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    tool_result = None
    if executions:
        first_execution = executions[0]
        parsed_output: dict[str, Any] | str | None = None
        raw_output = first_execution.output
        if isinstance(raw_output, str):
            try:
                parsed_output = json.loads(raw_output)
            except json.JSONDecodeError:
                parsed_output = raw_output
        else:
            parsed_output = raw_output

        tool_result = ToolCallResult(
            success=first_execution.success,
            output=parsed_output,
            error=first_execution.error,
        )

    return ToolTestPayload(
        assistant_text=display_text,
        raw_text=raw_text,
        tool_result=tool_result,
    )


@app.post(
    "/api/tools/{tool_id}/e2b-test",
    response_model=E2BTestResponse,
    summary="Execute AI-authored Python inside an E2B sandbox",
)
def run_e2b_test(tool_id: int, payload: E2BTestRequest) -> E2BTestResponse:
    """Create a fresh E2B sandbox, seed the runner scaffolding, and execute the provided code."""

    _ensure_tool_exists(tool_id)
    run_id = uuid4().hex
    created_at = datetime.now(timezone.utc)
    execution = _execute_run(payload, tool_id=tool_id, run_id=run_id)
    _finalize_run_record(run_id, payload, execution, created_at, tool_id=tool_id)
    return execution.response


@app.post(
    "/api/tools/{tool_id}/e2b-chat",
    response_model=ChatCompletionResponse,
    summary="Generate sandbox code with the OpenAI Responses API",
)
async def chat_with_openai(tool_id: int, payload: ChatRequest) -> ChatCompletionResponse:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise HTTPException(
            status_code=500,
            detail="OPENAI_API_KEY is not configured on the server",
        )

    _ensure_tool_exists(tool_id)
    model_name = payload.model or os.getenv("OPENAI_MODEL", "gpt-4.1")

    message_payload: list[ResponseInputItemParam] = []
    for message in payload.messages:
        content = message.content.strip()
        if not content:
            continue
        role = message.role  # ChatMessage enforces valid roles
        message_payload.append({ "role": role, "content": content })

    folder_prefix = payload.folder_prefix or DEFAULT_FOLDER_PREFIX

    try:
        tool_names = _tool_names_for_prefix(folder_prefix)
    except InvalidFolderPrefixError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    available_tools = tool_registry.get_many(tool_names)
    tool_descriptors = [_tool_descriptor(tool) for tool in available_tools]
    system_prompt = build_e2b_assistant_prompt(tool_descriptors)

    try:
        (
            _response,
            display_text,
            code_snippet,
            pip_packages,
            params_payload,
            file_payload,
            params_present,
            files_present,
            prompt_tokens,
            completion_tokens,
            total_tokens,
            raw_text,
            _executed_tools,
        ) = await call_openai_responses(
            tool_id=tool_id,
            api_key=api_key,
            system_prompt=system_prompt,
            messages=message_payload,
            model_name=model_name,
            tool_names=tool_names,
            folder_prefix=folder_prefix,
        )
    except Exception as exc:  # pragma: no cover - network interaction
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    current_detail = _ensure_current_code_version(tool_id)

    incoming_code = code_snippet.strip() if isinstance(code_snippet, str) else None
    update_pip = bool(pip_packages) or code_snippet is not None
    target_code = incoming_code if incoming_code is not None else current_detail.code
    target_pip_packages = pip_packages if update_pip else current_detail.pip_packages
    target_params = current_detail.params
    if params_present:
        target_params = _coerce_param_specs(params_payload)
    target_files = current_detail.required_files
    if files_present:
        target_files = _coerce_file_requirements(file_payload)

    changed = (
        target_code != current_detail.code
        or target_pip_packages != current_detail.pip_packages
        or _params_to_dicts(target_params) != _params_to_dicts(current_detail.params)
        or _files_to_dicts(target_files) != _files_to_dicts(current_detail.required_files)
    )

    if changed:
        detail = _create_code_version(
            tool_id=tool_id,
            code=target_code,
            pip_packages=target_pip_packages,
            author="assistant",
            note="Assistant update",
            origin_run_id=None,
            params=target_params,
            required_files=target_files,
        )
    else:
        detail = current_detail

    version_number = detail.version
    target_code = detail.code
    target_pip_packages = detail.pip_packages
    target_params = detail.params
    target_files = detail.required_files
    code_snippet_value = target_code if (changed or code_snippet is not None) else None

    usage = _usage_from_tokens(prompt_tokens, completion_tokens, total_tokens)
    final_text = display_text.strip()
    if not final_text:
        if changed and target_code != current_detail.code and target_pip_packages != current_detail.pip_packages:
            final_text = "Updated the sandbox module and pip requirements."
        elif changed and target_code != current_detail.code:
            final_text = "Updated the sandbox module."
        elif changed and target_pip_packages != current_detail.pip_packages:
            final_text = "Updated pip requirements."
        elif changed:
            final_text = "Updated sandbox metadata."
        else:
            final_text = "No changes were proposed."
    if changed:
        final_text = f"{final_text} (version {version_number})"
    assistant_message = ChatAssistantMessage(content=final_text)

    return ChatCompletionResponse(
        message=assistant_message,
        code=code_snippet_value,
        pip_packages=target_pip_packages,
        usage=usage,
        raw=raw_text,
        version=version_number,
        params=_params_to_dicts(target_params),
        required_files=_files_to_dicts(target_files),
    )


@app.post(
    "/api/tools/{tool_id}/eval-chat",
    response_model=EvalChatCompletionResponse,
    summary="Generate evaluation file variations with the OpenAI Responses API",
)
async def chat_generate_eval_files(
    tool_id: int, payload: ChatRequest
) -> EvalChatCompletionResponse:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise HTTPException(
            status_code=500,
            detail="OPENAI_API_KEY is not configured on the server",
        )

    _ensure_tool_exists(tool_id)
    model_name = payload.model or os.getenv("OPENAI_MODEL", "gpt-4.1")

    message_payload: list[ResponseInputItemParam] = []
    for message in payload.messages:
        content = message.content.strip()
        if not content:
            continue
        message_payload.append({"role": message.role, "content": content})

    folder_prefix = payload.folder_prefix or DEFAULT_FOLDER_PREFIX

    try:
        tool_names = _tool_names_for_prefix(folder_prefix)
    except InvalidFolderPrefixError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    available_tools = tool_registry.get_many(tool_names)
    tool_descriptors = [_tool_descriptor(tool) for tool in available_tools]
    system_prompt = build_eval_file_prompt(tool_descriptors)

    try:
        (
            _response,
            display_text,
            _code_snippet,
            _pip_packages,
            _params_payload,
            _file_payload,
            _params_present,
            _files_present,
            prompt_tokens,
            completion_tokens,
            total_tokens,
            raw_text,
            _executed_tools,
        ) = await call_openai_responses(
            tool_id=tool_id,
            api_key=api_key,
            system_prompt=system_prompt,
            messages=message_payload,
            model_name=model_name,
            tool_names=tool_names,
            parse_structured_tags=False,
            folder_prefix=folder_prefix,
        )
    except Exception as exc:  # pragma: no cover - network interaction
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    final_text = display_text.strip()
    if not final_text and raw_text:
        final_text = raw_text.strip()
    if not final_text:
        final_text = "I wasn't able to produce a response."

    assistant_message = ChatAssistantMessage(content=final_text)
    usage = _usage_from_tokens(prompt_tokens, completion_tokens, total_tokens)

    return EvalChatCompletionResponse(
        message=assistant_message,
        usage=usage,
        raw=raw_text,
    )


@app.get(
    "/api/tools/{tool_id}/e2b-chat/history",
    response_model=list[StoredChatMessage],
    summary="Load the saved chat history for a tool",
)
def get_chat_history(tool_id: int) -> list[StoredChatMessage]:
    _ensure_tool_exists(tool_id)
    return _load_chat_history(tool_id)


@app.put(
    "/api/tools/{tool_id}/e2b-chat/history",
    response_model=list[StoredChatMessage],
    summary="Replace the chat history for a tool",
)
def replace_chat_history(tool_id: int, payload: ChatHistoryUpdateRequest) -> list[StoredChatMessage]:
    _ensure_tool_exists(tool_id)
    messages = [StoredChatMessage.model_validate(message) for message in payload.messages]
    _replace_chat_history(tool_id, messages)
    return messages


@app.delete(
    "/api/tools/{tool_id}/e2b-chat/history",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Clear saved chat messages for a tool",
)
def clear_chat_history(tool_id: int) -> Response:
    _ensure_tool_exists(tool_id)
    _clear_chat_history(tool_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.get(
    "/api/tools/{tool_id}/eval-chat/history",
    response_model=list[StoredChatMessage],
    summary="Load the saved eval chat history for a tool",
)
def get_eval_chat_history(tool_id: int) -> list[StoredChatMessage]:
    _ensure_tool_exists(tool_id)
    return _load_eval_chat_history(tool_id)


@app.put(
    "/api/tools/{tool_id}/eval-chat/history",
    response_model=list[StoredChatMessage],
    summary="Replace the eval chat history for a tool",
)
def replace_eval_chat_history(
    tool_id: int, payload: ChatHistoryUpdateRequest
) -> list[StoredChatMessage]:
    _ensure_tool_exists(tool_id)
    messages = [StoredChatMessage.model_validate(message) for message in payload.messages]
    _replace_eval_chat_history(tool_id, messages)
    return messages


@app.delete(
    "/api/tools/{tool_id}/eval-chat/history",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Clear saved eval chat messages for a tool",
)
def clear_eval_chat_history(tool_id: int) -> Response:
    _ensure_tool_exists(tool_id)
    _clear_eval_chat_history(tool_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.get(
    "/api/tools/{tool_id}/e2b-code/current",
    response_model=CodeVersionDetail,
    summary="Fetch the currently active code version",
)
def get_current_code_version(tool_id: int) -> CodeVersionDetail:
    _ensure_tool_exists(tool_id)
    return _ensure_current_code_version(tool_id)


@app.get(
    "/api/tools/{tool_id}/e2b-code/versions",
    response_model=list[CodeVersionSummary],
    summary="List recent code versions",
)
def list_code_versions(
    tool_id: int,
    limit: int = Query(20, ge=1, le=200),
) -> list[CodeVersionSummary]:
    _ensure_tool_exists(tool_id)
    _ensure_initial_code_version_for_tool(tool_id)
    return _list_code_versions(tool_id, limit)


@app.get(
    "/api/tools/{tool_id}/e2b-code/versions/{version}",
    response_model=CodeVersionDetail,
    summary="Fetch a specific code version",
)
def get_code_version(tool_id: int, version: int) -> CodeVersionDetail:
    _ensure_tool_exists(tool_id)
    return _get_code_version_detail(tool_id, version)


@app.post(
    "/api/tools/{tool_id}/e2b-code/versions",
    response_model=CodeVersionUpdateResponse,
    summary="Create a new manual code version",
)
def create_code_version_endpoint(
    tool_id: int,
    request: CodeVersionUpdateRequest,
) -> CodeVersionUpdateResponse:
    _ensure_tool_exists(tool_id)
    detail = _create_code_version(
        tool_id=tool_id,
        code=request.code,
        pip_packages=request.pip_packages,
        author="user",
        note=request.note or "Manual update",
        origin_run_id=None,
        params=request.params,
        required_files=request.required_files,
    )
    message = _build_version_chat_message(
        actor="User",
        description="saved a manual code update",
        version=detail,
    )
    return CodeVersionUpdateResponse(version=detail, chat_message=message)


@app.post(
    "/api/tools/{tool_id}/e2b-code/revert",
    response_model=CodeVersionUpdateResponse,
    summary="Create a new code version by reverting to a previous one",
)
def revert_code_version(tool_id: int, request: CodeVersionRevertRequest) -> CodeVersionUpdateResponse:
    _ensure_tool_exists(tool_id)
    base_detail = _get_code_version_detail(tool_id, request.version)
    detail = _create_code_version(
        tool_id=tool_id,
        code=base_detail.code,
        pip_packages=base_detail.pip_packages,
        author="user",
        note=request.note or f"Revert to version {request.version}",
        origin_run_id=base_detail.origin_run_id,
        params=base_detail.params,
        required_files=base_detail.required_files,
    )
    message = _build_version_chat_message(
        actor="User",
        description=f"reverted the code to version {request.version}",
        version=detail,
        base_version=request.version,
    )
    return CodeVersionUpdateResponse(version=detail, chat_message=message)


@app.post(
    "/api/tools/{tool_id}/e2b-test/stream",
    summary="Stream E2B sandbox execution logs in real time",
)
async def run_e2b_test_stream(tool_id: int, payload: E2BTestRequest) -> StreamingResponse:
    """Start a sandbox run and emit newline-delimited JSON events as it progresses."""

    _ensure_tool_exists(tool_id)
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[str] = asyncio.Queue()
    run_id = uuid4().hex
    created_at = datetime.now(timezone.utc)

    def _enqueue(event: dict[str, object]) -> None:
        message = json.dumps(event, ensure_ascii=False)
        loop.call_soon_threadsafe(queue.put_nowait, message)

    def _log_sink(lines: list[str]) -> None:
        if lines:
            _enqueue({"type": "log", "lines": lines})

    def _worker() -> None:
        try:
            execution = _execute_run(payload, tool_id=tool_id, run_id=run_id, log_sink=_log_sink)
            result = execution.response
            _enqueue({"type": "result", "data": result.model_dump()})
            _finalize_run_record(run_id, payload, execution, created_at, tool_id=tool_id)
        except HTTPException as http_exc:  # propagate structured error
            _enqueue({"type": "error", "status": http_exc.status_code, "detail": http_exc.detail})
        except Exception as exc:  # pragma: no cover - defensive guard
            logger.exception("Run %s failed", run_id, exc_info=exc)
            _enqueue({"type": "error", "status": 500, "detail": str(exc)})
        finally:
            loop.call_soon_threadsafe(queue.put_nowait, "__EOF__")

    worker_future = loop.run_in_executor(None, _worker)

    async def _event_stream():
        try:
            while True:
                item = await queue.get()
                if item == "__EOF__":
                    break
                yield item + "\n"
        finally:
            with suppress(Exception):
                await worker_future

    return StreamingResponse(_event_stream(), media_type="application/jsonlines")


@app.get(
    "/api/tools/{tool_id}/e2b-runs",
    response_model=list[RunSummaryResponse],
    summary="List sandbox runs",
)
def list_e2b_runs(
    tool_id: int,
    folder_prefix: str | None = Query(None, description="Optional storage prefix filter"),
    connection: sqlite3.Connection = Depends(get_db),
) -> list[RunSummaryResponse]:
    _ensure_tool_exists(tool_id, connection)

    canonical_filter: str | None = None
    if folder_prefix is not None:
        canonical_filter = _canonical_folder_prefix(folder_prefix)

    query = (
        "SELECT r.id, r.created_at, r.ok, r.error, v.tool_version, r.folder_prefix "
        "FROM e2b_runs AS r "
        "JOIN code_versions AS v ON r.code_version = v.version "
        "WHERE r.tool_id = ?"
    )
    params: list[object] = [tool_id]
    if canonical_filter is not None:
        query += " AND COALESCE(r.folder_prefix, ?) = ?"
        params.extend([DEFAULT_FOLDER_PREFIX, canonical_filter])
    query += " ORDER BY r.created_at DESC"

    rows = connection.execute(query, params).fetchall()

    summaries: list[RunSummaryResponse] = []
    for row in rows:
        created_at = datetime.fromisoformat(row["created_at"])
        ok_value = row["ok"]
        ok_bool = None if ok_value is None else bool(ok_value)
        tool_version_value = row["tool_version"]
        if tool_version_value is None:
            continue
        code_version_label = int(tool_version_value)
        folder_value = row["folder_prefix"]
        summaries.append(
            RunSummaryResponse(
                id=row["id"],
                created_at=created_at,
                ok=ok_bool,
                error=row["error"],
                code_version=code_version_label,
                folder_prefix=folder_value if folder_value is not None else DEFAULT_FOLDER_PREFIX,
            )
        )
    return summaries


@app.get(
    "/api/tools/{tool_id}/e2b-runs/{run_id}",
    response_model=RunDetailResponse,
    summary="Fetch sandbox run details",
)
def get_e2b_run(
    tool_id: int,
    run_id: str,
    connection: sqlite3.Connection = Depends(get_db),
) -> RunDetailResponse:
    _ensure_tool_exists(tool_id, connection)
    run_row = connection.execute(
        """
        SELECT
            r.id,
            r.created_at,
            r.code_version AS code_version_id,
            r.params,
            r.pip_packages,
            r.allow_internet,
            r.ok,
            r.error,
            r.logs_path,
            r.folder_prefix,
            v.tool_version
        FROM e2b_runs AS r
        JOIN code_versions AS v ON r.code_version = v.version
        WHERE r.id = ? AND r.tool_id = ?
        """,
        (run_id, tool_id),
    ).fetchone()

    if run_row is None:
        raise HTTPException(status_code=404, detail="Run not found")

    created_at = datetime.fromisoformat(run_row["created_at"])
    params = json.loads(run_row["params"])
    pip_packages = json.loads(run_row["pip_packages"])
    allow_internet = bool(run_row["allow_internet"])
    ok_value = run_row["ok"]
    ok_bool = None if ok_value is None else bool(ok_value)
    error_text = run_row["error"]
    tool_version_value = run_row["tool_version"]
    if tool_version_value is None:
        raise HTTPException(status_code=404, detail="Associated code version not found")
    code_version = int(tool_version_value)
    code_detail = _get_code_version_detail(tool_id, code_version)
    folder_prefix = run_row["folder_prefix"] or DEFAULT_FOLDER_PREFIX

    run_dir = RUNS_ROOT / run_id
    logs_relative = run_row["logs_path"] or "logs.txt"
    logs_file = _resolve_run_file(run_dir, logs_relative)
    logs: list[str] = []
    if logs_file.exists():
        logs = logs_file.read_text(encoding="utf-8").splitlines()

    files_rows = connection.execute(
        """
        SELECT sandbox_path, local_path, size_bytes
        FROM e2b_run_files
        WHERE run_id = ?
        ORDER BY sandbox_path
        """,
        (run_id,),
    ).fetchall()

    files: list[RunFileResponse] = []
    for file_row in files_rows:
        local_path = file_row["local_path"]
        download_url = (
            f"/api/tools/{tool_id}/e2b-runs/{run_id}/file?path="
            f"{urllib.parse.quote(local_path, safe='')}"
        )
        files.append(
            RunFileResponse(
                sandbox_path=file_row["sandbox_path"],
                local_path=local_path,
                size_bytes=file_row["size_bytes"],
                download_url=download_url,
            )
        )

    return RunDetailResponse(
        id=run_row["id"],
        created_at=created_at,
        ok=ok_bool,
        error=error_text,
        code=code_detail.code,
        params=params,
        pip_packages=pip_packages,
        allow_internet=allow_internet,
        logs=logs,
        files=files,
        code_version=code_version,
        folder_prefix=folder_prefix,
    )


@app.get(
    "/api/tools/{tool_id}/e2b-runs/{run_id}/file",
    summary="Download a file generated by a sandbox run",
)
def download_e2b_run_file(
    tool_id: int,
    run_id: str,
    path: str = Query(..., description="Relative file path"),
    connection: sqlite3.Connection = Depends(get_db),
) -> FileResponse:
    _ensure_tool_exists(tool_id, connection)
    run_exists = connection.execute(
        "SELECT 1 FROM e2b_runs WHERE id = ? AND tool_id = ?",
        (run_id, tool_id),
    ).fetchone()
    if run_exists is None:
        raise HTTPException(status_code=404, detail="Run not found")
    run_dir = RUNS_ROOT / run_id
    target = _resolve_run_file(run_dir, path)
    if not target.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(target)


@app.delete(
    "/api/tools/{tool_id}/e2b-runs/{run_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a sandbox run",
)
def delete_e2b_run(
    tool_id: int,
    run_id: str,
    connection: sqlite3.Connection = Depends(get_db),
) -> Response:
    _ensure_tool_exists(tool_id, connection)
    cursor = connection.execute(
        "DELETE FROM e2b_runs WHERE id = ? AND tool_id = ?",
        (run_id, tool_id),
    )
    connection.commit()

    if cursor.rowcount == 0:
        raise HTTPException(status_code=404, detail="Run not found")

    run_dir = RUNS_ROOT / run_id
    if run_dir.exists():
        shutil.rmtree(run_dir, ignore_errors=True)

    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _resolve_run_file(run_dir: Path, relative_path: str) -> Path:
    target = (run_dir / relative_path).resolve()
    run_dir_resolved = run_dir.resolve()
    if not str(target).startswith(str(run_dir_resolved)):
        raise HTTPException(status_code=400, detail="Invalid file path")
    return target

@app.get("/api/tools", response_model=list[Tool], summary="List available tools")
def list_tools(connection: sqlite3.Connection = Depends(get_db)) -> list[Tool]:
    rows = connection.execute(
        "SELECT id, name, created_at FROM tools ORDER BY created_at DESC"
    ).fetchall()
    return [row_to_tool(row) for row in rows]


@app.post("/api/tools", response_model=Tool, summary="Create a new tool")
def create_tool(connection: sqlite3.Connection = Depends(get_db)) -> Tool:
    created_at = _iso(datetime.now(timezone.utc))

    # Generate a unique default name using the "New Tool (x)" convention
    existing_names = {
        row["name"]
        for row in connection.execute(
            "SELECT name FROM tools WHERE name LIKE 'New Tool (%)'"
        ).fetchall()
    }
    suffix = 1
    while True:
        candidate = f"New Tool ({suffix})"
        if candidate not in existing_names:
            break
        suffix += 1

    cursor = connection.execute(
        "INSERT INTO tools (name, created_at) VALUES (?, ?)",
        (candidate, created_at),
    )
    connection.commit()
    tool_id = cursor.lastrowid
    row = connection.execute(
        "SELECT id, name, created_at FROM tools WHERE id = ?",
        (tool_id,),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=500, detail="Failed to load created tool")
    tool = row_to_tool(row)
    _ensure_initial_code_version_for_tool(tool.id)
    return tool


@app.patch(
    "/api/tools/{tool_id}",
    response_model=Tool,
    summary="Rename an existing tool",
)
def rename_tool(
    tool_id: int,
    payload: ToolUpdateRequest,
    connection: sqlite3.Connection = Depends(get_db),
) -> Tool:
    new_name = payload.name.strip()
    if not new_name:
        raise HTTPException(status_code=400, detail="Tool name cannot be empty")

    result = connection.execute(
        "UPDATE tools SET name = ? WHERE id = ?",
        (new_name, tool_id),
    )
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="Tool not found")
    connection.commit()

    row = connection.execute(
        "SELECT id, name, created_at FROM tools WHERE id = ?",
        (tool_id,),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Tool not found")
    return row_to_tool(row)


@app.delete(
    "/api/tools/{tool_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a tool and its uploaded files",
)
def delete_tool(tool_id: int, connection: sqlite3.Connection = Depends(get_db)) -> Response:
    row = connection.execute(
        "SELECT id FROM tools WHERE id = ?",
        (tool_id,),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Tool not found")

    connection.execute("DELETE FROM tools WHERE id = ?", (tool_id,))
    connection.commit()

    tool_upload_dir = UPLOAD_ROOT / str(tool_id)
    if tool_upload_dir.exists():
        shutil.rmtree(tool_upload_dir, ignore_errors=True)

    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.get(
    "/api/tools/{tool_id}",
    response_model=ToolDetail,
    summary="Fetch a tool with uploaded files",
)
def get_tool(tool_id: int, connection: sqlite3.Connection = Depends(get_db)) -> ToolDetail:
    tool_row = connection.execute(
        "SELECT id, name, created_at FROM tools WHERE id = ?",
        (tool_id,),
    ).fetchone()
    if tool_row is None:
        raise HTTPException(status_code=404, detail="Tool not found")

    return ToolDetail(
        **row_to_tool(tool_row).model_dump(),
        files=[
            ToolFile(
                filename=record.original_filename,
                path=record.original_filename,
                size_bytes=record.size_bytes,
                modified_at=record.uploaded_at,
            )
            for record in list_tool_files(tool_id)
        ],
    )


@app.post(
    "/api/tools/{tool_id}/files",
    response_model=list[ToolFile],
    summary="Upload one or more data files to a tool",
)
async def upload_tool_files(
    tool_id: int,
    files: list[UploadFile] = File(..., description="Files to attach to the tool"),
    connection: sqlite3.Connection = Depends(get_db),
) -> list[ToolFile]:
    tool_exists = connection.execute(
        "SELECT 1 FROM tools WHERE id = ?",
        (tool_id,),
    ).fetchone()
    if tool_exists is None:
        raise HTTPException(status_code=404, detail="Tool not found")

    target_dir = resolve_storage_root(tool_id, DEFAULT_FOLDER_PREFIX, create=True)
    saved_files: list[ToolFile] = []

    for upload in files:
        original_name = Path(upload.filename or "").name
        extension = Path(original_name).suffix.lower()
        if extension not in ALLOWED_EXTENSIONS:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Unsupported file type '{extension}'. Allowed extensions: "
                    f"{', '.join(sorted(ALLOWED_EXTENSIONS))}"
                ),
            )

        contents = await upload.read()
        if not contents:
            raise HTTPException(status_code=400, detail="Uploaded file is empty")

        validate_upload_contents(extension, contents)

        target_path = target_dir / original_name
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_bytes(contents)

        stat = target_path.stat()
        saved_files.append(
            ToolFile(
                filename=original_name,
                path=original_name,
                size_bytes=stat.st_size,
                modified_at=datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc),
            )
        )

    return saved_files


@app.delete(
    "/api/tools/{tool_id}/files/{filename:path}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove a file from a tool",
)
def delete_tool_file(
    tool_id: int,
    filename: str,
    connection: sqlite3.Connection = Depends(get_db),
) -> Response:
    tool_exists = connection.execute(
        "SELECT 1 FROM tools WHERE id = ?",
        (tool_id,),
    ).fetchone()
    if tool_exists is None:
        raise HTTPException(status_code=404, detail="Tool not found")

    try:
        target_path = normalize_tool_path(tool_id, filename)
    except InvalidToolFilePathError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if not target_path.exists():
        raise HTTPException(status_code=404, detail="File not found")

    with suppress(FileNotFoundError):
        target_path.unlink()

    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.get(
    "/api/tools/{tool_id}/variations",
    response_model=list[VariationResponse],
    summary="List variation workspaces for a tool",
)
def list_tool_variations_endpoint(tool_id: int) -> list[VariationResponse]:
    _ensure_tool_exists(tool_id)
    records = list_variations(tool_id)
    return [_variation_to_response(record) for record in records]


@app.post(
    "/api/tools/{tool_id}/variations",
    response_model=VariationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a variation workspace by cloning current uploads",
)
def create_tool_variation_endpoint(
    tool_id: int, payload: VariationCreateRequest
) -> VariationResponse:
    _ensure_tool_exists(tool_id)
    record = create_variation_snapshot(tool_id, label=payload.label)
    return _variation_to_response(record)

try:
    import openpyxl  # type: ignore[import]
except ModuleNotFoundError:  # pragma: no cover
    openpyxl = None

try:
    import xlrd  # type: ignore[import]
except ModuleNotFoundError:  # pragma: no cover
    xlrd = None


def _variation_file_payload(
    record: VariationRecord,
    entry: VariationFileEntry,
) -> VariationFilePayload:
    path = (record.path / entry.stored_filename).resolve()
    size_bytes = entry.size_bytes
    modified_at = entry.uploaded_at or record.created_at
    if path.exists():
        stat = path.stat()
        size_bytes = stat.st_size
        modified_at = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)
    if modified_at.tzinfo is None:
        modified_at = modified_at.replace(tzinfo=timezone.utc)
    return VariationFilePayload(
        filename=entry.original_filename,
        path=entry.stored_filename,
        size_bytes=size_bytes,
        modified_at=modified_at.astimezone(timezone.utc),
    )


def _variation_to_response(record: VariationRecord) -> VariationResponse:
    files: list[VariationFilePayload] = []
    seen: set[str] = set()
    for entry in record.files:
        payload = _variation_file_payload(record, entry)
        files.append(payload)
        seen.add(payload.path)

    for child in record.path.rglob("*"):
        if child.is_dir() or child.name == VARIATION_METADATA_FILENAME:
            continue
        rel_path = child.relative_to(record.path).as_posix()
        if rel_path in seen:
            continue
        stat = child.stat()
        files.append(
            VariationFilePayload(
                filename=child.name,
                path=rel_path,
                size_bytes=stat.st_size,
                modified_at=datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc),
            )
        )
        seen.add(rel_path)

    files.sort(key=lambda item: item.path.lower())

    return VariationResponse(
        id=record.id,
        tool_id=record.tool_id,
        label=record.label,
        created_at=record.created_at.astimezone(timezone.utc),
        prefix=f"{VARIATION_PREFIX}/{record.id}",
        files=files,
    )
def _tool_descriptor(tool: ResponseTool) -> tuple[str, str | None]:
    """Return a human-friendly (name, description) pair for a registered tool."""

    definition = tool.definition
    description = getattr(definition, "description", None)
    if description is None:
        function_payload = getattr(definition, "function", None)
        if function_payload is not None:
            if isinstance(function_payload, dict):
                description = function_payload.get("description")
            else:
                description = getattr(function_payload, "description", None)
    if description is not None:
        description = str(description)
    return tool.name, description


def _tool_names_for_prefix(folder_prefix: str | None) -> list[str]:
    kind, _variation_id = normalize_folder_prefix(folder_prefix)
    names = set(READ_ONLY_TOOL_NAMES)
    if kind == VARIATION_PREFIX:
        names |= set(EDIT_TOOL_NAMES)
    return sorted(names)
