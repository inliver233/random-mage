from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

REDACTED = "***"

_SENSITIVE_KEY_PARTS = (
    "refresh",
    "token",
    "authorization",
    "password",
    "secret",
    "cookie",
)

_BEARER_RE = re.compile(r"(?i)\bBearer\s+([^\s]+)")
_REFRESH_QUERY_RE = re.compile(r"(?i)(refresh_token=)([^&\s]+)")


def is_sensitive_key(key: str) -> bool:
    key_l = key.lower()
    return any(part in key_l for part in _SENSITIVE_KEY_PARTS)


def redact_proxy_uri(text: str) -> str:
    # Handles both normal and the common \"password contains @\" variant by treating the last '@' as separator.
    m = re.match(r"^(?P<scheme>https?|socks[45])://(?P<rest>.+)$", text, flags=re.IGNORECASE)
    if not m:
        return text

    scheme = m.group("scheme")
    rest = m.group("rest")
    if "@" not in rest or ":" not in rest:
        return text

    userinfo, hostpart = rest.rsplit("@", 1)
    if ":" not in userinfo:
        return text

    username, _password = userinfo.split(":", 1)
    return f"{scheme}://{username}:{REDACTED}@{hostpart}"


def redact_text(text: str) -> str:
    text = redact_proxy_uri(text)
    text = _BEARER_RE.sub("Bearer " + REDACTED, text)
    text = _REFRESH_QUERY_RE.sub(r"\1" + REDACTED, text)
    return text


def redact_any(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, bytes):
        try:
            return redact_text(value.decode("utf-8", errors="replace")).encode("utf-8")
        except Exception:
            return value
    if isinstance(value, Mapping):
        out: dict[Any, Any] = {}
        for k, v in value.items():
            if isinstance(k, str) and is_sensitive_key(k):
                out[k] = REDACTED
            else:
                out[k] = redact_any(v)
        return out
    if isinstance(value, (list, tuple)):
        seq = [redact_any(v) for v in value]
        return type(value)(seq) if isinstance(value, tuple) else seq
    return value
