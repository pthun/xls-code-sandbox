from __future__ import annotations

import os
import asyncio
import json
import shutil
import sqlite3
import urllib.parse
from contextlib import asynccontextmanager, suppress
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Generator, Literal, Sequence
from uuid import uuid4

import dotenv

from fastapi import Depends, FastAPI, File, HTTPException, Query, Response, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

from .prompts.e2b_assistant import E2B_ASSISTANT_PROMPT
from .utils.e2b import (
    E2BTestRequest,
    E2BTestResponse,
    PersistedFile,
    SandboxExecutionResult,
    execute_e2b_test,
)
from .utils.openai import RoleLiteral, call_openai_responses

dotenv.load_dotenv()


INSTANCE_DIR = Path(__file__).resolve().parent.parent / "instance"
DATABASE_PATH = INSTANCE_DIR / "tools.db"
UPLOAD_ROOT = INSTANCE_DIR / "uploads"
RUNS_ROOT = INSTANCE_DIR / "runs"
ALLOWED_EXTENSIONS = {".csv", ".xls", ".xlsx"}


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
    id: int
    tool_id: int
    original_filename: str
    stored_filename: str
    content_type: str | None
    size_bytes: int
    uploaded_at: datetime


class ToolDetail(Tool):
    files: list[ToolFile] = Field(default_factory=list)


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


class ChatAssistantMessage(BaseModel):
    role: Literal["assistant"] = "assistant"
    content: str


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


def _write_run_metadata(run_dir: Path, metadata: dict[str, Any]) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    metadata_path = run_dir / "metadata.json"
    metadata_path.write_text(json.dumps(metadata, indent=2, default=str), encoding="utf-8")


def _save_run_record(
    *,
    run_id: str,
    created_at: str,
    payload: E2BTestRequest,
    response: E2BTestResponse,
    run_dir: Path,
    persisted_files: Sequence[PersistedFile],
    logs_path: Path,
) -> None:
    params_json = json.dumps(payload.params)
    pip_json = json.dumps(payload.pip_packages)
    allow_internet = 1 if payload.allow_internet else 0
    ok_value = None if response.ok is None else int(bool(response.ok))
    error_text = response.error
    logs_relative = str(logs_path.relative_to(run_dir))

    connection = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
    try:
        connection.execute("PRAGMA foreign_keys = ON;")
        connection.execute(
            """
            INSERT OR REPLACE INTO e2b_runs (
                id,
                created_at,
                code,
                params,
                pip_packages,
                allow_internet,
                ok,
                error,
                logs_path
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                created_at,
                payload.code,
                params_json,
                pip_json,
                allow_internet,
                ok_value,
                error_text,
                logs_relative,
            ),
        )

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

    metadata = {
        "run_id": run_id,
        "created_at": created_at.isoformat(),
        "code": payload.code,
        "params": payload.params,
        "pip_packages": payload.pip_packages,
        "allow_internet": payload.allow_internet,
        "response": execution.response.model_dump(),
    }
    _write_run_metadata(run_dir, metadata)

    _save_run_record(
        run_id=run_id,
        created_at=_iso(created_at),
        payload=payload,
        response=execution.response,
        run_dir=run_dir,
        persisted_files=execution.persisted_files,
        logs_path=logs_path,
    )


def _execute_run(
    payload: E2BTestRequest,
    *,
    run_id: str,
    log_sink=None,
) -> SandboxExecutionResult:
    execution = execute_e2b_test(
        payload,
        log_sink=log_sink,
        run_id=run_id,
        persist_root=RUNS_ROOT,
    )
    if execution.response.run_id is None:
        execution.response.run_id = run_id
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


class RunDetailResponse(RunSummaryResponse):
    code: str
    params: dict[str, Any]
    pip_packages: list[str]
    allow_internet: bool
    logs: list[str]
    files: list[RunFileResponse]


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def init_storage() -> None:
    UPLOAD_ROOT.mkdir(parents=True, exist_ok=True)
    RUNS_ROOT.mkdir(parents=True, exist_ok=True)


def init_db() -> None:
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DATABASE_PATH, check_same_thread=False) as connection:
        connection.execute("PRAGMA foreign_keys = ON;")
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS tools (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS tool_files (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tool_id INTEGER NOT NULL REFERENCES tools(id) ON DELETE CASCADE,
                original_filename TEXT NOT NULL,
                stored_filename TEXT NOT NULL,
                content_type TEXT,
                size_bytes INTEGER NOT NULL,
                uploaded_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS e2b_runs (
                id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                code TEXT NOT NULL,
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
            """
        )
        connection.commit()


def get_db() -> Generator[sqlite3.Connection, None, None]:
    connection = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON;")
    try:
        yield connection
    finally:
        connection.close()


def row_to_tool(row: sqlite3.Row) -> Tool:
    return Tool(
        id=row["id"],
        name=row["name"],
        created_at=datetime.fromisoformat(row["created_at"]),
    )


def row_to_tool_file(row: sqlite3.Row) -> ToolFile:
    return ToolFile(
        id=row["id"],
        tool_id=row["tool_id"],
        original_filename=row["original_filename"],
        stored_filename=row["stored_filename"],
        content_type=row["content_type"],
        size_bytes=row["size_bytes"],
        uploaded_at=datetime.fromisoformat(row["uploaded_at"]),
    )


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


@app.post(
    "/api/e2b-test",
    response_model=E2BTestResponse,
    summary="Execute AI-authored Python inside an E2B sandbox",
)
def run_e2b_test(payload: E2BTestRequest) -> E2BTestResponse:
    """Create a fresh E2B sandbox, seed the runner scaffolding, and execute the provided code."""

    run_id = uuid4().hex
    created_at = datetime.now(timezone.utc)
    execution = _execute_run(payload, run_id=run_id)
    _finalize_run_record(run_id, payload, execution, created_at)
    return execution.response


@app.post(
    "/api/e2b-chat",
    response_model=ChatCompletionResponse,
    summary="Generate sandbox code with the OpenAI Responses API",
)
def chat_with_openai(payload: ChatRequest) -> ChatCompletionResponse:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise HTTPException(
            status_code=500,
            detail="OPENAI_API_KEY is not configured on the server",
        )

    model_name = payload.model or os.getenv("OPENAI_MODEL", "gpt-4.1-mini")

    message_payload: list[tuple[RoleLiteral, str]] = []
    for message in payload.messages:
        content = message.content.strip()
        if not content:
            continue
        role: RoleLiteral = message.role  # ChatMessage enforces valid roles
        message_payload.append((role, content))

    try:
        (
            _response,
            display_text,
            code_snippet,
            pip_packages,
            prompt_tokens,
            completion_tokens,
            total_tokens,
            raw_text,
        ) = call_openai_responses(
            api_key=api_key,
            system_prompt=E2B_ASSISTANT_PROMPT,
            messages=message_payload,
            model_name=model_name,
        )
    except Exception as exc:  # pragma: no cover - network interaction
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    usage = _usage_from_tokens(prompt_tokens, completion_tokens, total_tokens)
    final_text = display_text.strip()
    if not final_text:
        if pip_packages and code_snippet:
            final_text = "Updated the sandbox module and pip requirements."
        elif code_snippet:
            final_text = "Updated the sandbox module."
        elif pip_packages:
            final_text = "Updated pip requirements."
        else:
            final_text = "No changes were proposed."
    assistant_message = ChatAssistantMessage(content=final_text)

    return ChatCompletionResponse(
        message=assistant_message,
        code=code_snippet,
        pip_packages=pip_packages,
        usage=usage,
        raw=raw_text,
    )


@app.post(
    "/api/e2b-test/stream",
    summary="Stream E2B sandbox execution logs in real time",
)
async def run_e2b_test_stream(payload: E2BTestRequest) -> StreamingResponse:
    """Start a sandbox run and emit newline-delimited JSON events as it progresses."""

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
            execution = _execute_run(payload, run_id=run_id, log_sink=_log_sink)
            result = execution.response
            _enqueue({"type": "result", "data": result.model_dump()})
            _finalize_run_record(run_id, payload, execution, created_at)
        except HTTPException as http_exc:  # propagate structured error
            _enqueue({"type": "error", "status": http_exc.status_code, "detail": http_exc.detail})
        except Exception as exc:  # pragma: no cover - defensive guard
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


@app.get("/api/e2b-runs", response_model=list[RunSummaryResponse], summary="List sandbox runs")
def list_e2b_runs(connection: sqlite3.Connection = Depends(get_db)) -> list[RunSummaryResponse]:
    rows = connection.execute(
        "SELECT id, created_at, ok, error FROM e2b_runs ORDER BY created_at DESC"
    ).fetchall()

    summaries: list[RunSummaryResponse] = []
    for row in rows:
        created_at = datetime.fromisoformat(row["created_at"])
        ok_value = row["ok"]
        ok_bool = None if ok_value is None else bool(ok_value)
        summaries.append(
            RunSummaryResponse(
                id=row["id"],
                created_at=created_at,
                ok=ok_bool,
                error=row["error"],
            )
        )
    return summaries


@app.get(
    "/api/e2b-runs/{run_id}",
    response_model=RunDetailResponse,
    summary="Fetch sandbox run details",
)
def get_e2b_run(run_id: str, connection: sqlite3.Connection = Depends(get_db)) -> RunDetailResponse:
    run_row = connection.execute(
        """
        SELECT id, created_at, code, params, pip_packages, allow_internet, ok, error, logs_path
        FROM e2b_runs
        WHERE id = ?
        """,
        (run_id,),
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
            f"/api/e2b-runs/{run_id}/file?path="
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
        code=run_row["code"],
        params=params,
        pip_packages=pip_packages,
        allow_internet=allow_internet,
        logs=logs,
        files=files,
    )


@app.get(
    "/api/e2b-runs/{run_id}/file",
    summary="Download a file generated by a sandbox run",
)
def download_e2b_run_file(run_id: str, path: str = Query(..., description="Relative file path")) -> FileResponse:
    run_dir = RUNS_ROOT / run_id
    target = _resolve_run_file(run_dir, path)
    if not target.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(target)


@app.delete(
    "/api/e2b-runs/{run_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a sandbox run",
)
def delete_e2b_run(run_id: str) -> Response:
    connection = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
    try:
        connection.execute("PRAGMA foreign_keys = ON;")
        cursor = connection.execute(
            "DELETE FROM e2b_runs WHERE id = ?",
            (run_id,),
        )
        connection.commit()
    finally:
        connection.close()

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
    return row_to_tool(row)


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

    files_rows = connection.execute(
        """
        SELECT id, tool_id, original_filename, stored_filename, content_type, size_bytes, uploaded_at
        FROM tool_files
        WHERE tool_id = ?
        ORDER BY uploaded_at DESC
        """,
        (tool_id,),
    ).fetchall()

    return ToolDetail(
        **row_to_tool(tool_row).model_dump(),
        files=[row_to_tool_file(row) for row in files_rows],
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

    saved_files: list[ToolFile] = []
    for upload in files:
        original_name = Path(upload.filename or "").name
        extension = Path(original_name).suffix.lower()
        if extension not in ALLOWED_EXTENSIONS:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported file type '{extension}'. Allowed extensions: {', '.join(sorted(ALLOWED_EXTENSIONS))}",
            )

        stored_filename = f"{uuid4().hex}{extension}"
        target_dir = UPLOAD_ROOT / str(tool_id)
        target_dir.mkdir(parents=True, exist_ok=True)
        target_path = target_dir / stored_filename

        contents = await upload.read()
        if not contents:
            raise HTTPException(status_code=400, detail="Uploaded file is empty")
        target_path.write_bytes(contents)
        upload_ts = _iso(datetime.now(timezone.utc))

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
                original_name,
                stored_filename,
                upload.content_type,
                len(contents),
                upload_ts,
            ),
        )
        file_id = cursor.lastrowid
        connection.commit()

        file_row = connection.execute(
            """
            SELECT id, tool_id, original_filename, stored_filename, content_type, size_bytes, uploaded_at
            FROM tool_files
            WHERE id = ?
            """,
            (file_id,),
        ).fetchone()

        if file_row is None:
            raise HTTPException(status_code=500, detail="Failed to load uploaded file")

        saved_files.append(row_to_tool_file(file_row))

    return saved_files
