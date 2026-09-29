"""arq worker.

Phase 01 wires the queue and proves the worker boots. Trace jobs arrive in
phase 07; there is deliberately no trace task here yet, because a task that
returns a plausible-looking result without an engine behind it is worse than no
task at all.
"""

from __future__ import annotations

from typing import Any

from arq.connections import RedisSettings

from app.core.logging import configure_logging, get_logger
from app.core.settings import get_settings

configure_logging()
log = get_logger(__name__)


async def ping(ctx: dict[str, Any]) -> str:
    """Liveness task, used by the smoke test."""
    log.info("worker.ping", job_id=ctx.get("job_id"))
    return "pong"


async def startup(ctx: dict[str, Any]) -> None:
    settings = get_settings()
    log.info("worker.startup", data_mode=settings.data_mode.value)


class WorkerSettings:
    functions = [ping]
    on_startup = startup
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url or "redis://localhost:6379")
    max_jobs = 4
    job_timeout = get_settings().budget_wall_clock_seconds
