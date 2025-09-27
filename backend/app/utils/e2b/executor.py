from __future__ import annotations

import json
import time
from contextlib import suppress
from string import Template
from typing import Any, Callable, Dict, Iterable
from uuid import uuid4

from fastapi import HTTPException

from .models import E2BFileInfo, E2BTestRequest, E2BTestResponse

try:  # pragma: no cover - optional dependency resolution
    from e2b_code_interpreter import Sandbox  # type: ignore
except ImportError:  # pragma: no cover - fallback for alternate package name
    try:
        from e2b import CodeInterpreterSandbox as Sandbox  # type: ignore
    except ImportError:  # pragma: no cover - handled at runtime
        Sandbox = None  # type: ignore

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

CONF_PATH = "${CONF_PATH}"
LOG_FILE = "${LOG_FILE}"


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


def main() -> None:
    with open(CONF_PATH, "r", encoding="utf-8") as handle:
        config = json.load(handle)

    entry_path = config["entrypoint"]
    params = config.get("params", {})

    _log(f"[runner] launching {entry_path}")

    from sdk.rpc import call_host, async_call_host
    from sdk.io import read_inputs, write_outputs
    from sdk.log import log as sdk_log

    class Ctx:
        rpc_call = staticmethod(call_host)
        rpc_call_async = staticmethod(async_call_host)
        log = staticmethod(sdk_log)
        read_inputs = staticmethod(read_inputs)
        write_outputs = staticmethod(write_outputs)
        io_dir = "${IO_DIR}"

    module = _load_module(entry_path)
    if not hasattr(module, "run"):
        raise RuntimeError("AI script must expose run(params, ctx)")

    try:
        result = module.run(params=params, ctx=Ctx())
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


def _require_sandbox_available() -> None:
    if Sandbox is None:  # pragma: no cover - dependent on optional installation
        raise HTTPException(
            status_code=500,
            detail="E2B SDK is not installed. Install 'e2b-code-interpreter' to use this endpoint.",
        )


def _create_sandbox(allow_internet: bool):
    _require_sandbox_available()
    try:
        return Sandbox.create(allow_internet_access=bool(allow_internet))
    except TypeError:  # pragma: no cover - older SDK compatibility
        return Sandbox.create(allowInternetAccess=bool(allow_internet))


def _sandbox_mkdirs(sandbox: Any, paths: Iterable[str]) -> None:
    for path in paths:
        with suppress(Exception):
            sandbox.files.mkdir(path)


def _sandbox_write_text(sandbox: Any, path: str, content: str) -> None:
    sandbox.files.write(path, content)


def _sandbox_read_bytes(sandbox: Any, path: str) -> bytes:
    return sandbox.files.read(path)


def _sandbox_delete(sandbox: Any, path: str) -> None:
    with suppress(Exception):
        sandbox.files.delete(path)


def _service_host_requests(
    sandbox: Any, host_actions: Dict[str, Callable[[Dict[str, Any]], Dict[str, Any]]]
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
            result = (
                handler(payload.get("payload", {}))
                if handler
                else {"ok": False, "error": f"unsupported_action:{action}"}
            )
        except Exception as exc:  # pragma: no cover - conversational safety
            result = {"ok": False, "error": str(exc)}

        response_path = f"{E2B_RESPONSE_DIR}/{correlation_id}.json"
        _sandbox_write_text(sandbox, response_path, json.dumps(result))


def _collect_file_info(sandbox: Any, roots: Iterable[str]) -> list[E2BFileInfo]:
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

            entry_type = getattr(current, "type", "file")
            if entry_type == "directory":
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


def execute_e2b_test(payload: E2BTestRequest) -> E2BTestResponse:
    """Spin up a sandbox, run the supplied code, and return logs plus artifacts."""

    sandbox = _create_sandbox(payload.allow_internet)
    host_actions: Dict[str, Callable[[Dict[str, Any]], Dict[str, Any]]] = {
        "ping": lambda data: {"ok": True, "pong": data},
        "enrich_customer": lambda data: {
            "ok": True,
            "data": {
                "customer_id": data.get("customer_id"),
                "tier": data.get("tier", "Gold"),
            },
        },
    }

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

        config_payload = {"entrypoint": E2B_USER_SCRIPT, "params": payload.params}
        _sandbox_write_text(sandbox, E2B_CONFIG_PATH, json.dumps(config_payload))

        _sandbox_delete(sandbox, E2B_LOG_FILE)

        process = sandbox.commands.run(f"python {E2B_RUNNER_PATH}")
        start_time = time.time()
        timeout_seconds = 90

        while True:
            _service_host_requests(sandbox, host_actions)

            finished = getattr(process, "finished", None)
            if finished is True:
                break

            if hasattr(process, "poll") and process.poll() is not None:
                break

            if time.time() - start_time > timeout_seconds:
                raise TimeoutError("Sandbox execution timed out")

            if hasattr(process, "wait"):
                try:
                    process.wait(timeout=0.2)
                except Exception:
                    pass
            else:
                time.sleep(0.2)

        log_bytes = b""
        with suppress(Exception):
            log_bytes = _sandbox_read_bytes(sandbox, E2B_LOG_FILE)

        logs = [line for line in log_bytes.decode("utf-8", errors="ignore").splitlines() if line]
        files = _collect_file_info(sandbox, [E2B_ARTIFACT_DIR, E2B_IO_DIR])

        return E2BTestResponse(
            sandbox_id=getattr(sandbox, "sandbox_id", "unknown"),
            logs=logs,
            files=files,
        )
    except TimeoutError as exc:
        raise HTTPException(status_code=504, detail=str(exc)) from exc
    finally:
        if hasattr(sandbox, "close"):
            with suppress(Exception):
                sandbox.close()
