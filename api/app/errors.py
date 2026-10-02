"""One error format for every failure: {"error": {"code": ..., "message": ..., "details": ...}}."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException


class ErrorBody(BaseModel):
    code: str
    message: str
    details: Any | None = None


class ErrorResponse(BaseModel):
    error: ErrorBody


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, details: Any | None = None) -> None:
        super().__init__(message)
        self.status, self.code, self.message, self.details = status, code, message, details


def not_found(what: str) -> ApiError:
    return ApiError(404, "not_found", f"{what} not found")


def _payload(code: str, message: str, details: Any | None = None) -> dict[str, Any]:
    return {"error": {"code": code, "message": message, "details": details}}


_CODES = {400: "bad_request", 403: "forbidden", 404: "not_found", 405: "method_not_allowed", 409: "conflict", 422: "validation_error"}


def install(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def api_error(_: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(_payload(exc.code, exc.message, exc.details), status_code=exc.status)

    @app.exception_handler(StarletteHTTPException)
    async def http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        return JSONResponse(_payload(_CODES.get(exc.status_code, "error"), str(exc.detail)), status_code=exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        details = [{"field": ".".join(str(p) for p in e["loc"] if p not in ("body", "query", "path")), "message": e["msg"]}
                   for e in exc.errors()]
        return JSONResponse(_payload("validation_error", "the request is not valid", details), status_code=422)

    @app.exception_handler(Exception)
    async def unexpected(_: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(_payload("internal_error", f"unexpected error: {type(exc).__name__}"), status_code=500)
