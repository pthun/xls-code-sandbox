from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from contextlib import suppress
from string import Template
from typing import Any, Callable, Dict, Iterable, Mapping, Protocol
from uuid import uuid4

from e2b import CommandExitException, FileType
from e2b_code_interpreter import Sandbox

from .models import E2BFileInfo, E2BTestRequest, E2BTestResponse


class HostAction(Protocol):
    def __call__(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        ...


@dataclass
class PersistedFile:
    sandbox_path: str
    local_path: Path
    size_bytes: int


@dataclass
class SandboxExecutionResult:
    response: E2BTestResponse
    persisted_files: list[PersistedFile]
    logs_path: Path | None
    run_dir: Path | None
    code_version: int


E2B_APP_DIR = "/app"
E2B_SDK_DIR = f"{E2B_APP_DIR}/sdk"
E2B_RUNNER_PATH = f"{E2B_APP_DIR}/runner.py"
E2B_IO_DIR = "/io"
E2B_REQUEST_DIR = f"{E2B_IO_DIR}/requests"
E2B_RESPONSE_DIR = f"{E2B_IO_DIR}/responses"
E2B_LOG_FILE = f"{E2B_IO_DIR}/host.log"
E2B_CONFIG_PATH = f"{E2B_IO_DIR}/config.json"
E2B_ARTIFACT_DIR = f"{E2B_IO_DIR}/artifacts"
E2B_INPUT_DIR = f"{E2B_IO_DIR}/inputs"
E2B_WORKSPACE_DIR = "/workspace/user"
E2B_USER_SCRIPT = f"{E2B_WORKSPACE_DIR}/user_script.py"


E2B_RUNNER_CODE = Template(
    """
import importlib.util
import json
import os
import sys
import traceback
from types import SimpleNamespace
from typing import Any, Dict

CONF_PATH = "${CONF_PATH}"
LOG_FILE = "${LOG_FILE}"
IO_DIR = "${IO_DIR}"
INPUT_DIR = "${INPUT_DIR}"
ARTIFACT_DIR = "${ARTIFACT_DIR}"


def _log(message: str) -> None:
    os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
    with open(LOG_FILE, "a", encoding="utf-8") as handle:
        handle.write(str(message).rstrip() + "\\n")


def _load_module(entry_path: str):
    spec = importlib.util.spec_from_file_location("user_module", entry_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load module from {entry_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules["user_module"] = module
    spec.loader.exec_module(module)
    return module


def _build_ctx(
    call_host,
    async_call_host,
    sdk_log,
    read_inputs,
    write_outputs,
    list_input_files,
    list_output_files,
):
    return SimpleNamespace(
        rpc_call=call_host,
        rpc_call_async=async_call_host,
        log=sdk_log,
        read_inputs=read_inputs,
        write_outputs=write_outputs,
        io_dir=IO_DIR,
        input_dir=INPUT_DIR,
        output_dir=ARTIFACT_DIR,
        list_input_files=list_input_files,
        list_output_files=list_output_files,
    )


def main() -> None:
    with open(CONF_PATH, "r", encoding="utf-8") as handle:
        config: Dict[str, Any] = json.load(handle)

    entry_path = config["entrypoint"]
    params = config.get("params", {})

    _log(f"[runner] launching {entry_path}")

    from sdk.rpc import call_host, async_call_host
    from sdk.io import (
        list_input_files,
        list_output_files,
        read_inputs,
        write_outputs,
    )
    from sdk.log import log as sdk_log

    ctx = _build_ctx(
        call_host,
        async_call_host,
        sdk_log,
        read_inputs,
        write_outputs,
        list_input_files,
        list_output_files,
    )

    module = _load_module(entry_path)
    if not hasattr(module, "run"):
        raise RuntimeError("AI script must expose run(params, ctx)")

    try:
        result = module.run(params=params, ctx=ctx)
        _log(f"[runner] run completed result={result}")
    except Exception:
        _log("[runner] ERROR:\\n" + traceback.format_exc())
        raise


if __name__ == "__main__":
    main()
"""
).substitute(
    CONF_PATH=E2B_CONFIG_PATH,
    LOG_FILE=E2B_LOG_FILE,
    IO_DIR=E2B_IO_DIR,
    INPUT_DIR=E2B_INPUT_DIR,
    ARTIFACT_DIR=E2B_ARTIFACT_DIR,
)


E2B_SDK_RPC_CODE = Template(
    """
import json
import os
import time
import uuid

REQUEST_DIR = "${REQUEST_DIR}"
RESPONSE_DIR = "${RESPONSE_DIR}"
LOG_FILE = "${LOG_FILE}"

os.makedirs(REQUEST_DIR, exist_ok=True)
os.makedirs(RESPONSE_DIR, exist_ok=True)


def _log(message: str) -> None:
    os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
    with open(LOG_FILE, "a", encoding="utf-8") as handle:
        handle.write(str(message).rstrip() + "\\n")


def call_host(action: str, payload: dict, timeout: float = 30.0) -> dict:
    correlation_id = str(uuid.uuid4())
    request_path = os.path.join(REQUEST_DIR, f"{correlation_id}.json")
    response_path = os.path.join(RESPONSE_DIR, f"{correlation_id}.json")

    with open(request_path, "w", encoding="utf-8") as handle:
        json.dump({"action": action, "payload": payload, "corr_id": correlation_id, "ts": time.time()}, handle)

    start = time.time()
    while not os.path.exists(response_path):
        time.sleep(0.1)
        if time.time() - start > timeout:
            raise TimeoutError(f"Host timed out waiting for {correlation_id}")

    with open(response_path, "r", encoding="utf-8") as handle:
        data = json.load(handle)

    try:
        os.remove(response_path)
    except FileNotFoundError:
        pass

    return data


async def async_call_host(action: str, payload: dict, timeout: float = 30.0) -> dict:
    import asyncio

    correlation_id = str(uuid.uuid4())
    request_path = os.path.join(REQUEST_DIR, f"{correlation_id}.json")
    response_path = os.path.join(RESPONSE_DIR, f"{correlation_id}.json")

    with open(request_path, "w", encoding="utf-8") as handle:
        json.dump({"action": action, "payload": payload, "corr_id": correlation_id, "ts": time.time()}, handle)

    start = time.time()
    while not os.path.exists(response_path):
        await asyncio.sleep(0.1)
        if time.time() - start > timeout:
            raise TimeoutError(f"Host timed out waiting for {correlation_id}")

    with open(response_path, "r", encoding="utf-8") as handle:
        data = json.load(handle)

    try:
        os.remove(response_path)
    except FileNotFoundError:
        pass

    return data
"""
).substitute(
    REQUEST_DIR=E2B_REQUEST_DIR,
    RESPONSE_DIR=E2B_RESPONSE_DIR,
    LOG_FILE=E2B_LOG_FILE,
)


E2B_SDK_IO_CODE = Template(
    """
import json
import os
from pathlib import Path

IO_DIR = "${IO_DIR}"
INPUT_DIR = "${INPUT_DIR}"
ARTIFACT_DIR = "${ARTIFACT_DIR}"

os.makedirs(INPUT_DIR, exist_ok=True)
os.makedirs(ARTIFACT_DIR, exist_ok=True)


def read_inputs():
    datasets = {}
    for path in Path(INPUT_DIR).glob("*"):
        if path.suffix.lower() == ".json":
            with path.open("r", encoding="utf-8") as handle:
                datasets[path.stem] = json.load(handle)
    return datasets


def write_outputs(**artifacts):
    stored = {}
    for name, value in artifacts.items():
        target = Path(ARTIFACT_DIR) / f"{name}.json"
        with target.open("w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
        stored[name] = str(target)
    return stored
 
 
def list_input_files(pattern: str = "*"):
    return [str(path) for path in Path(INPUT_DIR).glob(pattern)]
 
 
def list_output_files(pattern: str = "*"):
    return [str(path) for path in Path(ARTIFACT_DIR).glob(pattern)]
"""
).substitute(
    IO_DIR=E2B_IO_DIR,
    INPUT_DIR=E2B_INPUT_DIR,
    ARTIFACT_DIR=E2B_ARTIFACT_DIR,
)


E2B_SDK_LOG_CODE = Template(
    """
import os

LOG_FILE = "${LOG_FILE}"


def log(message: str) -> None:
    os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
    with open(LOG_FILE, "a", encoding="utf-8") as handle:
        handle.write(str(message).rstrip() + "\\n")
"""
).substitute(LOG_FILE=E2B_LOG_FILE)

def _create_sandbox(allow_internet: bool) -> Sandbox:
    return Sandbox.create(allow_internet_access=bool(allow_internet))
    

def _sandbox_mkdirs(sandbox: Sandbox, paths: Iterable[str]) -> None:
    for path in paths:
        with suppress(Exception):
            sandbox.files.make_dir(path)


def _sandbox_write_text(sandbox: Sandbox, path: str, content: str) -> None:
    sandbox.files.write(path, content)


def _sandbox_read_bytes(sandbox: Sandbox, path: str) -> bytes:
    data = sandbox.files.read(path, format="bytes")
    return bytes(data)


def _sandbox_delete(sandbox: Sandbox, path: str) -> None:
    with suppress(Exception):
        sandbox.files.remove(path)


def _service_host_requests(
    sandbox: Sandbox, host_actions: Dict[str, HostAction]
) -> None:
    try:
        entries = sandbox.files.list(E2B_REQUEST_DIR)
    except Exception:
        return

    for entry in entries or []:
        request_path = getattr(entry, "path", "")
        if not request_path.endswith(".json"):
            continue

        raw = _sandbox_read_bytes(sandbox, request_path)
        _sandbox_delete(sandbox, request_path)

        try:
            payload = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            continue

        action = payload.get("action")
        correlation_id = payload.get("corr_id") or uuid4().hex
        handler = host_actions.get(action)

        try:
            result: dict[str, Any] = (
                handler(payload.get("payload", {}))
                if handler
                else {"ok": False, "error": f"unsupported_action:{action}"}
            )
        except Exception as exc:  # pragma: no cover - conversational safety
            result = {"ok": False, "error": str(exc)}

        response_path = f"{E2B_RESPONSE_DIR}/{correlation_id}.json"
        _sandbox_write_text(sandbox, response_path, json.dumps(result))


def _collect_file_info(sandbox: Sandbox, roots: Iterable[str]) -> list[E2BFileInfo]:
    files: dict[str, E2BFileInfo] = {}

    for root in roots:
        try:
            entries = sandbox.files.list(root)
        except Exception:
            continue

        queue = list(entries or [])
        while queue:
            current = queue.pop()
            path = getattr(current, "path", "")
            if not path:
                continue

            if path.startswith(E2B_REQUEST_DIR) or path.startswith(E2B_RESPONSE_DIR):
                continue

            entry_type = getattr(current, "type", None)
            if entry_type == FileType.DIR:
                try:
                    children = sandbox.files.list(path)
                except Exception:
                    children = []
                queue.extend(children or [])
                continue

            try:
                content = _sandbox_read_bytes(sandbox, path)
            except Exception:
                content = b""

            size_bytes = getattr(current, "size", None)
            if not isinstance(size_bytes, int):
                size_bytes = len(content)

            preview: str | None = None
            if content and size_bytes <= 4096:
                with suppress(UnicodeDecodeError):
                    preview = content.decode("utf-8")[:400]

            files[path] = E2BFileInfo(path=path, size_bytes=size_bytes, preview=preview)

    return sorted(files.values(), key=lambda item: item.path)


LogSink = Callable[[list[str]], None]


def execute_e2b_test(
    payload: E2BTestRequest,
    *,
    log_sink: LogSink | None = None,
    run_id: str | None = None,
    persist_root: Path | None = None,
    code_version: int,
) -> SandboxExecutionResult:
    """Spin up a sandbox, run the supplied code, and optionally persist artefacts."""

    sandbox = _create_sandbox(payload.allow_internet)
    host_actions: Dict[str, HostAction] = {
        "ping": lambda data: {"ok": True, "pong": data},
        "enrich_customer": lambda data: {
            "ok": True,
            "data": {
                "customer_id": data.get("customer_id"),
                "tier": data.get("tier", "Gold"),
            },
        },
    }
    stdout_lines: list[str] = []
    log_lines: list[str] = []
    persisted_files: list[PersistedFile] = []
    logs_path: Path | None = None
    run_dir: Path | None = None

    if run_id and persist_root:
        run_dir = persist_root / run_id
        run_dir.mkdir(parents=True, exist_ok=True)

    def _emit(lines: list[str]) -> None:
        if log_sink and lines:
            log_sink(lines)

    try:
        _sandbox_mkdirs(
            sandbox,
            [
                E2B_APP_DIR,
                E2B_SDK_DIR,
                E2B_IO_DIR,
                E2B_REQUEST_DIR,
                E2B_RESPONSE_DIR,
                E2B_ARTIFACT_DIR,
                E2B_INPUT_DIR,
                E2B_WORKSPACE_DIR,
            ],
        )

        _sandbox_write_text(sandbox, E2B_RUNNER_PATH, E2B_RUNNER_CODE)
        _sandbox_write_text(sandbox, f"{E2B_SDK_DIR}/rpc.py", E2B_SDK_RPC_CODE)
        _sandbox_write_text(sandbox, f"{E2B_SDK_DIR}/io.py", E2B_SDK_IO_CODE)
        _sandbox_write_text(sandbox, f"{E2B_SDK_DIR}/log.py", E2B_SDK_LOG_CODE)
        _sandbox_write_text(sandbox, E2B_USER_SCRIPT, payload.code)

        config_payload: dict[str, Any] = {"entrypoint": E2B_USER_SCRIPT, "params": payload.params}
        _sandbox_write_text(sandbox, E2B_CONFIG_PATH, json.dumps(config_payload))

        _sandbox_delete(sandbox, E2B_LOG_FILE)

        def _read_log_updates() -> None:
            try:
                data = _sandbox_read_bytes(sandbox, E2B_LOG_FILE)
            except Exception:
                return

            decoded = data.decode("utf-8", errors="ignore").splitlines()
            filtered = [line for line in decoded if line]
            if len(filtered) > len(log_lines):
                diff = filtered[len(log_lines) :]
                log_lines[:] = filtered
                _emit(diff)

        def _capture_stream(chunk: Any) -> None:
            if not chunk:
                return
            if isinstance(chunk, bytes):
                text = chunk.decode("utf-8", errors="ignore")
            else:
                text = str(chunk)
            lines = [line for line in text.splitlines() if line]
            stdout_lines.extend(lines)
            _emit(lines)

        if payload.pip_packages:
            requirements_path = f"{E2B_IO_DIR}/requirements.txt"
            requirements_content = "\n".join(
                pkg.strip() for pkg in payload.pip_packages if pkg.strip()
            )
            if requirements_content:
                exit_error: str | None = None
                _sandbox_write_text(sandbox, requirements_path, requirements_content)
                try:
                    result = sandbox.commands.run(
                        f"pip install -r {requirements_path}",
                        on_stdout=_capture_stream,
                        on_stderr=_capture_stream,
                    )
                    if result.exit_code != 0:
                        exit_error = result.error or (
                            f"pip install exited with code {result.exit_code}"
                        )
                except CommandExitException as exc:
                    exit_error = exc.error or (
                        f"pip install exited with code {exc.exit_code}"
                    )
                if exit_error is not None:
                    _read_log_updates()
                    files = _collect_file_info(sandbox, [E2B_ARTIFACT_DIR, E2B_IO_DIR])
                    combined_logs = log_lines + [
                        line for line in stdout_lines if line not in log_lines
                    ]
                    if run_dir:
                        persisted_files, logs_path = _finalize_persistence(
                            sandbox, run_dir, files, combined_logs
                        )
                    response = E2BTestResponse(
                        run_id=run_id,
                        code_version=code_version,
                        ok=False,
                        sandbox_id=getattr(sandbox, "sandbox_id", "unknown"),
                        logs=combined_logs,
                        files=files,
                        error=exit_error,
                    )
                    return SandboxExecutionResult(
                        response=response,
                        persisted_files=persisted_files,
                        logs_path=logs_path,
                        run_dir=run_dir,
                        code_version=code_version,
                    )

        command_handle = sandbox.commands.run(
            f"python {E2B_RUNNER_PATH}",
            background=True,
        )
        start_time = time.time()
        timeout_seconds = 90

        exit_error: str | None = None
        exit_code: int | None = None
        wait_complete = threading.Event()

        def _wait_for_command() -> None:
            nonlocal exit_error, exit_code
            try:
                result = command_handle.wait(
                    on_stdout=_capture_stream,
                    on_stderr=_capture_stream,
                )
                exit_code = result.exit_code
                if result.exit_code != 0 and exit_error is None:
                    exit_error = result.error or f"Sandbox process exited with code {result.exit_code}"
            except CommandExitException as exc:
                exit_code = exc.exit_code
                if exit_error is None:
                    exit_error = exc.error or f"Sandbox process exited with code {exc.exit_code}"
            finally:
                wait_complete.set()

        wait_thread = threading.Thread(target=_wait_for_command, daemon=True)
        wait_thread.start()

        while True:
            _service_host_requests(sandbox, host_actions)
            _read_log_updates()

            if wait_complete.wait(timeout=0.0):
                break

            if time.time() - start_time > timeout_seconds:
                exit_error = "Sandbox execution timed out"
                with suppress(Exception):
                    command_handle.kill()
                break

            wait_complete.wait(timeout=0.2)

        _read_log_updates()
        wait_complete.wait(timeout=5.0)
        wait_thread.join(timeout=5.0)

        if stdout_lines:
            seen = set(log_lines)
            for line in stdout_lines:
                if line not in seen:
                    log_lines.append(line)
                    seen.add(line)

        files = _collect_file_info(sandbox, [E2B_ARTIFACT_DIR, E2B_IO_DIR])

        sandbox_id = getattr(sandbox, "sandbox_id", "unknown")

        if exit_error is None and exit_code not in (None, 0):
            exit_error = f"Sandbox process exited with code {exit_code}"

        if run_dir:
            persisted_files, logs_path = _finalize_persistence(
                sandbox, run_dir, files, log_lines
            )

        response = E2BTestResponse(
            run_id=run_id,
            code_version=code_version,
            ok=exit_error is None,
            sandbox_id=sandbox_id,
            logs=log_lines,
            files=files,
            error=exit_error,
        )
        return SandboxExecutionResult(
            response=response,
            persisted_files=persisted_files,
            logs_path=logs_path,
            run_dir=run_dir,
            code_version=code_version,
        )
    finally:
        if hasattr(sandbox, "close"):
            with suppress(Exception):
                sandbox.kill()


def _finalize_persistence(
    sandbox: Sandbox,
    run_dir: Path,
    files: list[E2BFileInfo],
    logs: list[str],
) -> tuple[list[PersistedFile], Path]:
    persisted: list[PersistedFile] = []
    for file_info in files:
        sandbox_path = file_info.path
        relative = Path(sandbox_path.lstrip("/"))
        target = run_dir / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        data = _sandbox_read_bytes(sandbox, sandbox_path)
        target.write_bytes(data)
        persisted.append(
            PersistedFile(
                sandbox_path=sandbox_path,
                local_path=target,
                size_bytes=file_info.size_bytes,
            )
        )

    logs_path = run_dir / "logs.txt"
    logs_path.parent.mkdir(parents=True, exist_ok=True)
    logs_path.write_text("\n".join(logs), encoding="utf-8")

    return persisted, logs_path
