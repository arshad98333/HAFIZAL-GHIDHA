"""Structured, audit-grade logging. Every line is a JSON object with a wave and
correlation id, printed to the console immediately and mirrored to MongoDB
within a fraction of a second — there is no human tailing a local file as the
source of truth here, so the console alone is not an audit trail.

``configure_logging`` sets up the console sink synchronously at process start,
before Mongo is reachable. ``attach_mongo_sink`` is called once the Logbook's
connection is live and upgrades logging to also stream into the
``live_logs`` collection, batched every ``flush_interval_s`` for a real-time
feel without one round trip per log line.
"""

from __future__ import annotations

import asyncio
import contextvars
import datetime
import json
import logging
import sys
import time
import uuid
from typing import Any

_wave_ctx: contextvars.ContextVar[int | None] = contextvars.ContextVar("wave", default=None)
_run_id_ctx: contextvars.ContextVar[str] = contextvars.ContextVar("run_id", default="")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": time.time(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "run_id": _run_id_ctx.get(),
            "wave": _wave_ctx.get(),
        }
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        extra = getattr(record, "extra_fields", None)
        if extra:
            payload.update(extra)
        return json.dumps(payload, ensure_ascii=False, default=str)


def configure_logging(level: str = "INFO") -> None:
    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root.addHandler(handler)
    _run_id_ctx.set(str(uuid.uuid4()))


def set_wave(wave: int) -> None:
    _wave_ctx.set(wave)


def get_run_id() -> str:
    return _run_id_ctx.get()


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


def log_extra(logger: logging.Logger, level: int, msg: str, **fields) -> None:
    logger.log(level, msg, extra={"extra_fields": fields})


# --------------------------------------------------------------------------- #
# realtime Mongo sink
# --------------------------------------------------------------------------- #

class _MongoQueueHandler(logging.Handler):
    """Never blocks the caller. ``emit`` just enqueues; a background asyncio
    task owns the actual writes. If the queue is full (Mongo is down or slow),
    records are dropped rather than backing up the pipeline — a lost log line
    is recoverable from the console; a stalled wave is not."""

    def __init__(self, queue: asyncio.Queue, loop: asyncio.AbstractEventLoop):
        super().__init__()
        self._queue = queue
        self._loop = loop

    def emit(self, record: logging.LogRecord) -> None:
        try:
            doc: dict[str, Any] = {
                "ts": datetime.datetime.now(datetime.timezone.utc),
                "level": record.levelname,
                "logger": record.name,
                "msg": record.getMessage(),
                "run_id": _run_id_ctx.get(),
                "wave": _wave_ctx.get(),
            }
            extra = getattr(record, "extra_fields", None)
            if extra:
                doc.update(extra)
            if record.exc_info:
                doc["exc_info"] = self.format(record) if self.formatter else str(record.exc_info)
            self._loop.call_soon_threadsafe(self._queue.put_nowait, doc)
        except asyncio.QueueFull:
            pass
        except Exception:  # noqa: BLE001 — logging must never raise into caller code
            pass


async def _drain_loop(queue: asyncio.Queue, db: Any, flush_interval_s: float) -> None:
    batch: list[dict[str, Any]] = []
    while True:
        try:
            doc = await asyncio.wait_for(queue.get(), timeout=flush_interval_s)
            batch.append(doc)
            while not queue.empty() and len(batch) < 500:
                batch.append(queue.get_nowait())
        except asyncio.TimeoutError:
            pass
        except asyncio.CancelledError:
            if batch:
                await db.live_logs.insert_many(batch, ordered=False)
            raise
        if batch:
            try:
                await db.live_logs.insert_many(batch, ordered=False)
            except Exception:  # noqa: BLE001 — a broken log sink must not sink the wave
                pass
            batch = []


def attach_mongo_sink(db: Any, level: str = "INFO", flush_interval_s: float = 0.5) -> asyncio.Task:
    """Call once, after the Mongo connection is live. Returns the drain task —
    cancel it on shutdown (the runner does this in its finally block)."""
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue(maxsize=10_000)
    handler = _MongoQueueHandler(queue, loop)
    handler.setLevel(level)
    logging.getLogger().addHandler(handler)
    return asyncio.create_task(_drain_loop(queue, db, flush_interval_s), name="mongo-log-sink")
