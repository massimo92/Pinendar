from typing import Any

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from pinendar.application.state import DomainError


def error_body(
    code: str, message: str, field: str | None = None, details: dict[str, Any] | None = None
) -> dict[str, Any]:
    return {"error": {"code": code, "message": message, "field": field, "details": details or {}}}


async def domain_error_handler(_request: Request, error: DomainError) -> JSONResponse:
    status = (
        401
        if error.code in {"UNAUTHORIZED", "INVALID_CREDENTIALS", "INVALID_RECOVERY_CODE"}
        else 429
        if error.code == "SIGNUP_RATE_LIMITED"
        else 403
        if error.code in {"SIGNUP_DISABLED", "FORBIDDEN", "ADMIN_ACCOUNT_PROTECTED"}
        else 404
        if error.code.endswith("NOT_FOUND")
        else 409
    )
    return JSONResponse(status_code=status, content=error_body(error.code, error.message, error.field, error.details))


async def validation_error_handler(_request: Request, error: RequestValidationError) -> JSONResponse:
    first = error.errors()[0] if error.errors() else {}
    location = first.get("loc", [])
    field = str(location[-1]) if location else None
    return JSONResponse(
        status_code=422, content=error_body("VALIDATION_ERROR", "Dades invàlides", field, {"errors": error.errors()})
    )
