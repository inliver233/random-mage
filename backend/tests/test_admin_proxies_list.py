from __future__ import annotations

import asyncio
import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.core.security import create_jwt
from app.db.models.base import Base
from app.db.models.proxy_endpoints import ProxyEndpoint
from app.db.session import create_sessionmaker
from app.main import create_app


def test_admin_list_proxy_endpoints_does_not_echo_password(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "admin_list_proxies.db"
    db_url = "sqlite+aiosqlite:///" + db_path.as_posix()

    monkeypatch.setenv("APP_ENV", "dev")
    monkeypatch.setenv("DATABASE_URL", db_url)
    monkeypatch.setenv("SECRET_KEY", "secret_test")
    monkeypatch.setenv("ADMIN_USERNAME", "admin")

    app = create_app()

    async def _seed() -> None:
        async with app.state.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        Session = create_sessionmaker(app.state.engine)
        async with Session() as session:
            session.add(
                ProxyEndpoint(
                    scheme="http",
                    host="1.2.3.4",
                    port=8080,
                    username="u",
                    password_enc="enc_dummy",
                    enabled=1,
                    source="manual",
                )
            )
            await session.commit()

        await app.state.engine.dispose()

    asyncio.run(_seed())

    token = create_jwt(secret_key="secret_test", subject="admin", ttl_s=3600)
    with TestClient(app) as client:
        resp = client.get(
            "/admin/api/proxies/endpoints",
            headers={"Authorization": f"Bearer {token}", "X-Request-Id": "req_test"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["request_id"] == "req_test"
        assert resp.headers["X-Request-Id"] == "req_test"
        assert len(body["items"]) == 1

        dumped = json.dumps(body, ensure_ascii=False)
        assert "enc_dummy" not in dumped
        assert "password" not in dumped

