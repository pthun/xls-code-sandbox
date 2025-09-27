from __future__ import annotations

import dotenv
dotenv.load_dotenv()

import shutil
import sqlite3
import asyncio
import json
from contextlib import asynccontextmanager, suppress
from datetime import datetime, timezone
from pathlib import Path
from typing import Generator
from uuid import uuid4

from fastapi import Depends, FastAPI, File, HTTPException, Response, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from .utils.e2b import E2BTestRequest, E2BTestResponse, execute_e2b_test


INSTANCE_DIR = Path(__file__).resolve().parent.parent / "instance"
DATABASE_PATH = INSTANCE_DIR / "tools.db"
UPLOAD_ROOT = INSTANCE_DIR / "uploads"
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


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def init_storage() -> None:
    UPLOAD_ROOT.mkdir(parents=True, exist_ok=True)


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

    return execute_e2b_test(payload)


@app.post(
    "/api/e2b-test/stream",
    summary="Stream E2B sandbox execution logs in real time",
)
async def run_e2b_test_stream(payload: E2BTestRequest) -> StreamingResponse:
    """Start a sandbox run and emit newline-delimited JSON events as it progresses."""

    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[str] = asyncio.Queue()

    def _enqueue(event: dict[str, object]) -> None:
        message = json.dumps(event, ensure_ascii=False)
        loop.call_soon_threadsafe(queue.put_nowait, message)

    def _log_sink(lines: list[str]) -> None:
        if lines:
            _enqueue({"type": "log", "lines": lines})

    def _worker() -> None:
        try:
            result = execute_e2b_test(payload, log_sink=_log_sink)
            _enqueue({"type": "result", "data": result.model_dump()})
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
