from __future__ import annotations

import json
from typing import Any

import httpx
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.config import load_settings
from app.core.crypto import FieldEncryptor
from app.core.proxy_uri import parse_proxy_uri
from app.core.time import iso_utc_ms
from app.db.models.proxy_endpoints import ProxyEndpoint
from app.db.session import create_sessionmaker, with_sqlite_busy_retry
from app.easy_proxies.client import EasyProxiesError, easy_proxies_auth, easy_proxies_export
from app.jobs.errors import JobPermanentError


def _parse_payload(payload_json: str) -> dict[str, Any]:
    try:
        data = json.loads(payload_json)
    except Exception as exc:
        raise JobPermanentError("payload_json is not valid JSON") from exc
    if not isinstance(data, dict):
        raise JobPermanentError("payload_json must be an object")
    return data


def _parse_conflict_policy(value: Any) -> str:
    v = str(value or "").strip().lower() or "skip_non_easy_proxies"
    if v not in {"skip_non_easy_proxies", "skip", "overwrite"}:
        raise JobPermanentError("payload.conflict_policy invalid")
    return v


def build_easy_proxies_import_handler(engine: AsyncEngine, *, transport: httpx.BaseTransport | None = None) -> Any:
    settings = load_settings()
    encryptor = FieldEncryptor.from_key(settings.field_encryption_key)
    Session = create_sessionmaker(engine)

    async def _handler(job: dict[str, Any]) -> None:
        payload_json = str(job.get("payload_json") or "")
        payload = _parse_payload(payload_json)

        base_url = str(payload.get("base_url") or "").strip()
        if not base_url:
            raise JobPermanentError("payload.base_url is required")

        password = str(payload.get("password") or "").strip()
        conflict_policy = _parse_conflict_policy(payload.get("conflict_policy"))

        try:
            bearer_token: str | None = None
            if password:
                auth = await easy_proxies_auth(base_url=base_url, password=password, transport=transport)
                bearer_token = auth.token
            uris = await easy_proxies_export(base_url=base_url, bearer_token=bearer_token, transport=transport)
        except EasyProxiesError as exc:
            raise RuntimeError("easy_proxies import failed") from exc
        except Exception as exc:
            raise RuntimeError("easy_proxies import failed") from exc

        now = iso_utc_ms()

        async def _op() -> None:
            async with Session() as session:
                for uri in uris:
                    uri = (uri or "").strip()
                    if not uri:
                        continue
                    try:
                        parsed = parse_proxy_uri(uri)
                    except Exception:
                        continue

                    username = (parsed.username or "").strip()
                    password_v = parsed.password
                    password_enc = encryptor.encrypt_text(password_v) if password_v else ""

                    existing = (
                        (
                            await session.execute(
                                sa.select(ProxyEndpoint).where(
                                    ProxyEndpoint.scheme == parsed.scheme,
                                    ProxyEndpoint.host == parsed.host,
                                    ProxyEndpoint.port == int(parsed.port),
                                    ProxyEndpoint.username == username,
                                )
                            )
                        )
                        .scalars()
                        .first()
                    )

                    if existing is None:
                        session.add(
                            ProxyEndpoint(
                                scheme=parsed.scheme,
                                host=parsed.host,
                                port=int(parsed.port),
                                username=username,
                                password_enc=password_enc,
                                enabled=1,
                                source="easy_proxies",
                                source_ref=base_url,
                                updated_at=now,
                            )
                        )
                        continue

                    if conflict_policy == "skip_non_easy_proxies" and (existing.source or "") != "easy_proxies":
                        continue
                    if conflict_policy == "skip":
                        continue

                    existing.password_enc = password_enc
                    existing.enabled = 1
                    existing.source = "easy_proxies"
                    existing.source_ref = base_url
                    existing.updated_at = now

                await session.commit()

        await with_sqlite_busy_retry(_op)

    return _handler

