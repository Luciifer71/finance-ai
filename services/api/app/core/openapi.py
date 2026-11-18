"""Make the published OpenAPI contract describe the errors the API really returns.

FastAPI documents validation errors as ``{"detail": [...]}``, but every error
here is an RFC 9457 problem (see ``core/errors.py``). This replaces the 422
schema with the real one and documents 401 on every /api/v1 operation.
"""

from typing import Any

from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi

PROBLEM = {
    "type": "object",
    "required": ["type", "title", "status", "detail", "instance", "code"],
    "properties": {
        "type": {"type": "string", "examples": ["urn:finance-ai:problem:account.not_found"]},
        "title": {"type": "string"},
        "status": {"type": "integer"},
        "detail": {"type": "string"},
        "instance": {"type": "string", "examples": ["urn:finance-ai:request:4f1c..."]},
        "code": {"type": "string", "description": "Stable machine-readable error code"},
    },
}
VALIDATION_PROBLEM = {
    "allOf": [
        {"$ref": "#/components/schemas/Problem"},
        {
            "type": "object",
            "properties": {
                "errors": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["field", "message"],
                        "properties": {"field": {"type": "string"}, "message": {"type": "string"}},
                    },
                }
            },
        },
    ]
}


def _content(ref: str) -> dict[str, Any]:
    return {"application/problem+json": {"schema": {"$ref": f"#/components/schemas/{ref}"}}}


def install_openapi(app: FastAPI) -> None:
    def build() -> dict[str, Any]:
        if app.openapi_schema:
            return app.openapi_schema
        spec = get_openapi(title=app.title, version=app.version, routes=app.routes)
        schemas = spec.setdefault("components", {}).setdefault("schemas", {})
        schemas.pop("HTTPValidationError", None)
        schemas.pop("ValidationError", None)
        schemas["Problem"] = PROBLEM
        schemas["ValidationProblem"] = VALIDATION_PROBLEM
        for path, operations in spec.get("paths", {}).items():
            for operation in operations.values():
                responses = operation.setdefault("responses", {})
                if "422" in responses:
                    responses["422"] = {
                        "description": "Validation failed",
                        "content": _content("ValidationProblem"),
                    }
                if path.startswith("/api/v1"):
                    responses["401"] = {
                        "description": "Missing or invalid access token",
                        "content": _content("Problem"),
                    }
        app.openapi_schema = spec
        return spec

    app.openapi = build  # type: ignore[method-assign]  # FastAPI's documented customization hook
