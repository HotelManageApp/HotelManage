"""Error envelope shared by every endpoint.

    {"error": {"code": "...", "message": "...", "details": [...], "request_id": "..."}}

See spec/SPEC-foundation.md, "Định dạng lỗi API".
"""

from http import HTTPStatus
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


class AppError(Exception):
    status_code: int = HTTPStatus.BAD_REQUEST
    code: str = "BAD_REQUEST"
    message: str = "Yêu cầu không hợp lệ"

    def __init__(
        self,
        message: str | None = None,
        *,
        code: str | None = None,
        details: list[dict[str, Any]] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.message = message or type(self).message
        self.code = code or type(self).code
        self.details = details or []
        self.headers = headers or {}
        super().__init__(self.message)


class BadRequest(AppError):
    pass


class ValidationFailed(AppError):
    code = "VALIDATION_ERROR"
    message = "Dữ liệu gửi lên không hợp lệ"


class Unauthorized(AppError):
    status_code = HTTPStatus.UNAUTHORIZED
    code = "UNAUTHORIZED"
    message = "Bạn cần đăng nhập để tiếp tục"


class Forbidden(AppError):
    status_code = HTTPStatus.FORBIDDEN
    code = "FORBIDDEN"
    message = "Bạn không có quyền thực hiện thao tác này"


class NotFound(AppError):
    status_code = HTTPStatus.NOT_FOUND
    code = "NOT_FOUND"
    message = "Không tìm thấy dữ liệu"


class Conflict(AppError):
    status_code = HTTPStatus.CONFLICT
    code = "CONFLICT"
    message = "Dữ liệu đã thay đổi hoặc xung đột, vui lòng tải lại"


class InvalidTransition(Conflict):
    code = "INVALID_TRANSITION"
    message = "Không thể chuyển sang trạng thái này"


class RateLimited(AppError):
    status_code = HTTPStatus.TOO_MANY_REQUESTS
    code = "RATE_LIMITED"
    message = "Bạn thao tác quá nhanh, vui lòng thử lại sau"

    def __init__(self, message: str | None = None, *, retry_after_seconds: int) -> None:
        super().__init__(message, headers={"Retry-After": str(max(1, retry_after_seconds))})


INTERNAL_ERROR_MESSAGE = "Đã có lỗi xảy ra, vui lòng thử lại sau"

_HTTP_STATUS_CODES: dict[int, str] = {
    400: "BAD_REQUEST",
    401: "UNAUTHORIZED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    405: "METHOD_NOT_ALLOWED",
    409: "CONFLICT",
    429: "RATE_LIMITED",
}


def error_response(
    status_code: int,
    code: str,
    message: str,
    request_id: str | None,
    *,
    details: list[dict[str, Any]] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    body = {
        "error": {
            "code": code,
            "message": message,
            "details": details or [],
            "request_id": request_id,
        }
    }
    return JSONResponse(status_code=status_code, content=body, headers=headers)


def _request_id(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


def _field_path(loc: tuple[Any, ...]) -> str:
    """("body", "items", 0, "quantity") -> "items[0].quantity"."""
    parts = list(loc)
    if parts and parts[0] in {"body", "query", "path", "header", "cookie"}:
        parts = parts[1:]
    path = ""
    for part in parts:
        if isinstance(part, int):
            path += f"[{part}]"
        else:
            path += f".{part}" if path else str(part)
    return path


async def _app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    return error_response(
        exc.status_code,
        exc.code,
        exc.message,
        _request_id(request),
        details=exc.details,
        headers=exc.headers,
    )


async def _validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    details = [
        {"field": _field_path(tuple(err["loc"])), "issue": err["msg"]} for err in exc.errors()
    ]
    return error_response(
        HTTPStatus.BAD_REQUEST,
        ValidationFailed.code,
        ValidationFailed.message,
        _request_id(request),
        details=details,
    )


async def _http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    fallback = "BAD_REQUEST" if exc.status_code < 500 else "INTERNAL_ERROR"
    code = _HTTP_STATUS_CODES.get(exc.status_code, fallback)
    message = (
        HTTPStatus(exc.status_code).phrase if exc.status_code < 500 else INTERNAL_ERROR_MESSAGE
    )
    if exc.status_code == HTTPStatus.NOT_FOUND:
        message = NotFound.message
    return error_response(
        exc.status_code, code, message, _request_id(request), headers=getattr(exc, "headers", None)
    )


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, _app_error_handler)
    app.add_exception_handler(RequestValidationError, _validation_error_handler)
    app.add_exception_handler(StarletteHTTPException, _http_exception_handler)
