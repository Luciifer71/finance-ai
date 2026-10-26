from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI(title="Finance AI API", version="0.1.0")


class HealthResponse(BaseModel):
    status: str
    service: str


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok", service="finance-ai-api")
