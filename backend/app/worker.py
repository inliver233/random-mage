from __future__ import annotations

import asyncio
import os
import signal
import time
from collections.abc import Awaitable, Callable
from typing import Any

from app.easy_proxies.auto_refresh import EasyProxiesAutoRefreshConfig, EasyProxiesAutoRefresher
from app.core.config import load_settings
from app.core.logging import configure_logging, get_logger
from app.core.runtime_settings import set_runtime_setting
from app.core.time import iso_utc_ms
from app.db.engine import create_engine

log = get_logger(__name__)


def _install_signal_handlers(stop_event: asyncio.Event) -> None:
    loop = asyncio.get_running_loop()
    signals = [signal.SIGINT]
    if hasattr(signal, "SIGTERM"):
        signals.append(signal.SIGTERM)

    for sig in signals:
        try:
            loop.add_signal_handler(sig, stop_event.set)
        except NotImplementedError:
            signal.signal(sig, lambda *_: stop_event.set())
        except Exception:
            continue


async def _poll_once() -> None:
    return None


async def run_worker(
    *,
    poll_interval_s: float = 1.0,
    max_iterations: int | None = None,
    on_tick: Callable[[], Awaitable[None]] | None = None,
) -> None:
    stop_event = asyncio.Event()
    _install_signal_handlers(stop_event)

    on_tick = on_tick or _poll_once
    iterations = 0

    while not stop_event.is_set():
        await on_tick()

        iterations += 1
        if max_iterations is not None and iterations >= max_iterations:
            break

        if poll_interval_s > 0:
            await asyncio.sleep(poll_interval_s)


async def main_async(*, max_iterations: int | None = None, poll_interval_s: float = 1.0) -> None:
    configure_logging()
    settings = load_settings()

    engine = create_engine(settings.database_url)
    try:
        base_url = (os.environ.get("EASY_PROXIES_BASE_URL") or "").strip()
        try:
            interval_s = float((os.environ.get("EASY_PROXIES_REFRESH_INTERVAL_SECONDS") or "0").strip() or "0")
        except Exception:
            interval_s = 0.0
        conflict_policy = (os.environ.get("EASY_PROXIES_CONFLICT_POLICY") or "skip_non_easy_proxies").strip()

        refresher = EasyProxiesAutoRefresher(
            EasyProxiesAutoRefreshConfig(
                base_url=base_url,
                interval_s=interval_s,
                conflict_policy=conflict_policy or "skip_non_easy_proxies",
            )
        )
        if refresher.enabled:
            log.info("easy_proxies_auto_refresh_enabled base_url=%s interval_s=%s", base_url, interval_s)

        worker_id = (os.environ.get("WORKER_ID") or f"pid{os.getpid()}").strip()
        try:
            heartbeat_interval_s = float((os.environ.get("WORKER_HEARTBEAT_INTERVAL_SECONDS") or "10").strip() or "10")
        except Exception:
            heartbeat_interval_s = 10.0
        heartbeat_interval_s = max(1.0, min(float(heartbeat_interval_s), 300.0))
        last_heartbeat_m = 0.0

        async def _on_tick() -> None:
            nonlocal last_heartbeat_m
            now_m = time.monotonic()
            if now_m - last_heartbeat_m >= heartbeat_interval_s:
                last_heartbeat_m = now_m
                try:
                    await set_runtime_setting(
                        engine,
                        key="worker.last_seen_at",
                        value={"at": iso_utc_ms(), "worker_id": worker_id, "pid": int(os.getpid())},
                        description="worker heartbeat",
                        updated_by=f"worker:{worker_id}",
                    )
                except Exception:
                    log.warning("worker_heartbeat_update_failed")

            await refresher.tick(engine)
            await _poll_once()

        log.info("worker_start env=%s", settings.app_env)
        await run_worker(
            max_iterations=max_iterations,
            poll_interval_s=poll_interval_s,
            on_tick=_on_tick,
        )
        log.info("worker_stop")
    finally:
        await engine.dispose()


def main(argv: list[str] | None = None) -> None:
    _argv = argv or []
    _ = _argv
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
