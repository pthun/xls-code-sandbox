from __future__ import annotations

from typing import Any, Dict

from pydantic import BaseModel, Field


class E2BTestRequest(BaseModel):
    """Payload describing the sandbox execution request."""

    code: str = Field(
        ..., min_length=1, description="Python code that defines run(params, ctx)"
    )
    allow_internet: bool = Field(
        False, description="Toggle internet access for the sandbox"
    )
    params: Dict[str, Any] = Field(
        default_factory=dict, description="Parameters forwarded to run()"
    )
    pip_packages: list[str] = Field(
        default_factory=list,
        description="Packages to install via pip before running the script",
    )


class E2BFileInfo(BaseModel):
    """Metadata about a file produced during sandbox execution."""

    path: str
    size_bytes: int
    preview: str | None = None


class E2BTestResponse(BaseModel):
    """Structured response returned after sandbox execution."""

    ok: bool
    sandbox_id: str
    logs: list[str]
    files: list[E2BFileInfo]
    error: str | None = None
