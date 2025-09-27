from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field


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


app = FastAPI(title="Double API", version="0.1.0", summary="Simple doubling service")

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

    return HealthResponse(status="ok", message="Double API is running")

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
