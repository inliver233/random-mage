from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class ErrorCode(str, Enum):
    # 4.1 通用
    BAD_REQUEST = "BAD_REQUEST"
    UNAUTHORIZED = "UNAUTHORIZED"
    FORBIDDEN = "FORBIDDEN"
    NOT_FOUND = "NOT_FOUND"
    RATE_LIMITED = "RATE_LIMITED"
    INTERNAL_ERROR = "INTERNAL_ERROR"
    # 4.2 Random
    NO_MATCH = "NO_MATCH"
    UPSTREAM_STREAM_ERROR = "UPSTREAM_STREAM_ERROR"
    UPSTREAM_403 = "UPSTREAM_403"
    UPSTREAM_404 = "UPSTREAM_404"
    UPSTREAM_RATE_LIMIT = "UPSTREAM_RATE_LIMIT"
    # 4.3 Import
    INVALID_UPLOAD_TYPE = "INVALID_UPLOAD_TYPE"
    PAYLOAD_TOO_LARGE = "PAYLOAD_TOO_LARGE"
    UNSUPPORTED_URL = "UNSUPPORTED_URL"
    # 4.4 Pixiv/Token
    TOKEN_REFRESH_FAILED = "TOKEN_REFRESH_FAILED"
    TOKEN_BACKOFF = "TOKEN_BACKOFF"
    NO_TOKEN_AVAILABLE = "NO_TOKEN_AVAILABLE"
    # 4.5 Proxy
    PROXY_REQUIRED = "PROXY_REQUIRED"
    PROXY_AUTH_FAILED = "PROXY_AUTH_FAILED"
    PROXY_CONNECT_FAILED = "PROXY_CONNECT_FAILED"


UNKNOWN_REQUEST_ID = "req_unknown"


@dataclass(frozen=True, slots=True)
class ApiError(Exception):
    code: ErrorCode
    message: str
    status_code: int = 400
    details: dict[str, Any] | None = None


def _coerce_request_id(request_id: str | None) -> str:
    request_id = (request_id or "").strip()
    return request_id if request_id else UNKNOWN_REQUEST_ID


def _request_id_from_request(request: Any | None) -> str | None:
    if request is None:
        return None
    request_id = getattr(getattr(request, "state", None), "request_id", None)
    if request_id:
        return str(request_id)
    header = request.headers.get("X-Request-Id")
    return header.strip() if header else None


def error_body(
    *,
    code: ErrorCode,
    message: str,
    request_id: str | None = None,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "ok": False,
        "code": code.value,
        "message": message,
        "request_id": _coerce_request_id(request_id),
        "details": details or {},
    }


def json_error_response(
    *,
    code: ErrorCode,
    message: str,
    status_code: int,
    request: Any | None = None,
    request_id: str | None = None,
    details: dict[str, Any] | None = None,
) -> Any:
    if request_id is None:
        request_id = _request_id_from_request(request)
    from fastapi.responses import JSONResponse

    return JSONResponse(
        status_code=status_code,
        content=error_body(code=code, message=message, request_id=request_id, details=details),
    )
