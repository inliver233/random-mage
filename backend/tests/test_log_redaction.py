from __future__ import annotations

import io
import logging

from app.core.logging import RedactFilter
from app.core.redact import REDACTED, redact_any, redact_text


def test_redact_proxy_uri_password_with_at() -> None:
    raw = "http://user:pa@ss@1.2.3.4:2323"
    redacted = redact_text(raw)
    assert "pa@ss" not in redacted
    assert redacted == "http://user:***@1.2.3.4:2323"


def test_redact_bearer_token() -> None:
    raw = "Authorization: Bearer abc.def.ghi"
    redacted = redact_text(raw)
    assert "abc.def.ghi" not in redacted
    assert "Bearer ***" in redacted


def test_redact_mapping_sensitive_keys() -> None:
    raw = {"refresh_token": "secret", "nested": {"password": "p"}, "ok": 1}
    redacted = redact_any(raw)
    assert redacted["refresh_token"] == REDACTED
    assert redacted["nested"]["password"] == REDACTED
    assert redacted["ok"] == 1


def test_logging_filter_redacts_output() -> None:
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger = logging.getLogger("redact_test")
    logger.handlers = [handler]
    logger.setLevel(logging.INFO)
    logger.propagate = False
    logger.addFilter(RedactFilter())

    logger.info("Authorization: Bearer %s", "supersecret")
    out = stream.getvalue()
    assert "supersecret" not in out
    assert "***" in out

