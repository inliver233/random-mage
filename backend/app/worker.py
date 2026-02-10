from __future__ import annotations

import asyncio
import signal
from collections.abc import Awaitable, Callable
from typing import Any

from app.core.config import load_settings
from app.core.logging import configure_logging, get_logger
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
        log.info("worker_start env=%s", settings.app_env)
        await run_worker(max_iterations=max_iterations, poll_interval_s=poll_interval_s)
        log.info("worker_stop")
    finally:
        await engine.dispose()


def main(argv: list[str] | None = None) -> None:
    _argv = argv or []
    _ = _argv
    asyncio.run(main_async())


if __name__ == "__main__":
    main()

