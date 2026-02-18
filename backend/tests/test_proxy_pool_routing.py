from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from app.core.errors import ApiError, ErrorCode
from app.core.proxy_routing import resolve_pool_id_for_host, select_proxy_uri_for_url, should_use_proxy_for_host
from app.core.runtime_settings import load_runtime_config
from app.db.models.base import Base
from app.db.models.proxy_endpoints import ProxyEndpoint
from app.db.models.proxy_pool_endpoints import ProxyPoolEndpoint
from app.db.models.proxy_pools import ProxyPool
from app.db.models.runtime_settings import RuntimeSetting
from app.db.session import create_sessionmaker
from app.main import create_app


def test_proxy_route_pools_suffix_matching_prefers_longest() -> None:
    class _Runtime:
        proxy_route_pools = {"pximg.net": 2, "i.pximg.net": 1}
        proxy_default_pool_id = None

    pool = resolve_pool_id_for_host(_Runtime(), host="i.pximg.net")  # type: ignore[arg-type]
    assert pool == 1


def test_select_proxy_uri_for_url_uses_configured_pool(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "proxy_pool_routing.db"
    db_url = "sqlite+aiosqlite:///" + db_path.as_posix()

    monkeypatch.setenv("APP_ENV", "dev")
    monkeypatch.setenv("DATABASE_URL", db_url)

    app = create_app()

    async def _seed() -> None:
        async with app.state.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        Session = create_sessionmaker(app.state.engine)
        async with Session() as session:
            pool = ProxyPool(name="pool1", description=None, enabled=1)
            session.add(pool)
            await session.flush()

            ep = ProxyEndpoint(
                scheme="http",
                host="1.2.3.4",
                port=8080,
                username="",
                password_enc="",
                enabled=1,
                source="manual",
                source_ref=None,
            )
            session.add(ep)
            await session.flush()

            session.add(ProxyPoolEndpoint(pool_id=int(pool.id), endpoint_id=int(ep.id), enabled=1, weight=3))

            session.add_all(
                [
                    RuntimeSetting(key="proxy.enabled", value_json="true", description=None, updated_by=None),
                    RuntimeSetting(key="proxy.fail_closed", value_json="true", description=None, updated_by=None),
                    RuntimeSetting(
                        key="proxy.route_mode",
                        value_json=json.dumps("all", separators=(",", ":"), ensure_ascii=False),
                        description=None,
                        updated_by=None,
                    ),
                    RuntimeSetting(
                        key="proxy.default_pool_id",
                        value_json=str(int(pool.id)),
                        description=None,
                        updated_by=None,
                    ),
                    RuntimeSetting(
                        key="proxy.route_pools",
                        value_json=json.dumps({"i.pximg.net": int(pool.id)}, separators=(",", ":"), ensure_ascii=False),
                        description=None,
                        updated_by=None,
                    ),
                ]
            )
            await session.commit()

    asyncio.run(_seed())

    async def _run() -> str:
        runtime = await load_runtime_config(app.state.engine)
        assert should_use_proxy_for_host(runtime, host="i.pximg.net") is True
        picked = await select_proxy_uri_for_url(
            app.state.engine,
            app.state.settings,
            runtime,
            url="https://i.pximg.net/img-original/img/2020/01/01/00/00/00/12345678_p0.jpg",
        )
        assert picked is not None
        return picked.uri

    uri = asyncio.run(_run())
    assert uri == "http://1.2.3.4:8080"


def test_select_proxy_uri_for_url_proxy_required_includes_pool_stats_when_all_blacklisted(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "proxy_pool_routing_blacklisted.db"
    db_url = "sqlite+aiosqlite:///" + db_path.as_posix()

    monkeypatch.setenv("APP_ENV", "dev")
    monkeypatch.setenv("DATABASE_URL", db_url)

    app = create_app()

    blacklisted_until = "2999-01-01T00:00:00.000Z"

    async def _seed() -> int:
        async with app.state.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        Session = create_sessionmaker(app.state.engine)
        async with Session() as session:
            pool = ProxyPool(name="pool1", description=None, enabled=1)
            session.add(pool)
            await session.flush()

            ep = ProxyEndpoint(
                scheme="http",
                host="1.2.3.4",
                port=8080,
                username="",
                password_enc="",
                enabled=1,
                source="manual",
                source_ref=None,
                blacklisted_until=blacklisted_until,
            )
            session.add(ep)
            await session.flush()

            session.add(ProxyPoolEndpoint(pool_id=int(pool.id), endpoint_id=int(ep.id), enabled=1, weight=1))

            session.add_all(
                [
                    RuntimeSetting(key="proxy.enabled", value_json="true", description=None, updated_by=None),
                    RuntimeSetting(key="proxy.fail_closed", value_json="true", description=None, updated_by=None),
                    RuntimeSetting(
                        key="proxy.route_mode",
                        value_json=json.dumps("all", separators=(",", ":"), ensure_ascii=False),
                        description=None,
                        updated_by=None,
                    ),
                    RuntimeSetting(
                        key="proxy.default_pool_id",
                        value_json=str(int(pool.id)),
                        description=None,
                        updated_by=None,
                    ),
                ]
            )
            await session.commit()
            return int(pool.id)

    pool_id = asyncio.run(_seed())

    async def _run() -> None:
        runtime = await load_runtime_config(app.state.engine)
        with pytest.raises(ApiError) as ei:
            await select_proxy_uri_for_url(
                app.state.engine,
                app.state.settings,
                runtime,
                url="https://i.pximg.net/img-original/img/2020/01/01/00/00/00/12345678_p0.jpg",
            )
        exc = ei.value
        assert exc.code == ErrorCode.PROXY_REQUIRED
        assert exc.status_code == 502
        assert isinstance(exc.details, dict)
        assert exc.details.get("reason") == "all_endpoints_blacklisted"
        assert exc.details.get("pool_id") == pool_id
        assert exc.details.get("endpoints_total") == 1
        assert exc.details.get("endpoints_eligible") == 0
        assert exc.details.get("next_available_at") == blacklisted_until

    asyncio.run(_run())
