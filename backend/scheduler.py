"""
Background scheduler for periodic metrics collection.

Uses APScheduler to ping nodes at regular intervals and persist
the results in the database. Integrated into the FastAPI lifespan.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select

from backend.database import async_session
from backend.models import MetricRecord, Node

logger = logging.getLogger("asn.scheduler")

# ---------------------------------------------------------------------------
# Singleton scheduler instance
# ---------------------------------------------------------------------------
scheduler: Optional[AsyncIOScheduler] = None


async def _ping_node(host: str, port: int, timeout: float = 5.0) -> dict:
    """
    Measure basic TCP latency to a node.

    Opens a TCP connection to ``host:port``, records the round-trip
    time, and returns the result.

    Args:
        host:    Target hostname or IP.
        port:    Target port.
        timeout: Connection timeout in seconds.

    Returns:
        Dict with ``latency_ms``, ``packet_loss_percent``, ``success``.
    """
    start = time.monotonic()
    try:
        _, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port),
            timeout=timeout,
        )
        elapsed = (time.monotonic() - start) * 1000  # ms
        writer.close()
        await writer.wait_closed()
        return {
            "latency_ms": float(round(elapsed, 2)),
            "packet_loss_percent": 0.0,
            "success": True,
        }
    except (asyncio.TimeoutError, OSError) as exc:
        elapsed = (time.monotonic() - start) * 1000
        logger.warning("Ping failed for %s:%d — %s", host, port, exc)
        return {
            "latency_ms": float(round(elapsed, 2)),
            "packet_loss_percent": 100.0,
            "success": False,
        }


async def collect_metrics() -> None:
    """
    Periodic job: measure latency for every active node and store results.

    This function is called by APScheduler at the configured interval
    (default: every 30 seconds).
    """
    logger.info("Starting metrics collection cycle")

    async with async_session() as session:
        result = await session.execute(
            select(Node).where(Node.is_active == True)  # noqa: E712
        )
        nodes = result.scalars().all()

        if not nodes:
            logger.info("No active nodes to measure")
            return

        for node in nodes:
            ping_result = await _ping_node(node.ip, node.port)
            record = MetricRecord(
                node_id=node.id,
                latency_ms=ping_result["latency_ms"],
                packet_loss_percent=ping_result["packet_loss_percent"],
                throughput_mbps=0.0,  # full throughput requires a data transfer test
                error_count=0 if ping_result["success"] else 1,
            )
            session.add(record)
            logger.debug(
                "Node %s (%s): latency=%.1fms loss=%.0f%%",
                node.name,
                node.ip,
                ping_result["latency_ms"],
                ping_result["packet_loss_percent"],
            )

        await session.commit()
        logger.info("Metrics collection complete — %d nodes measured", len(nodes))


# ---------------------------------------------------------------------------
# Start / Stop
# ---------------------------------------------------------------------------

def start_scheduler(interval_seconds: int = 30) -> AsyncIOScheduler:
    """
    Create and start the background metrics scheduler.

    Args:
        interval_seconds: How often to run ``collect_metrics``.

    Returns:
        The running ``AsyncIOScheduler`` instance.
    """
    global scheduler
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        collect_metrics,
        "interval",
        seconds=interval_seconds,
        id="metrics_collection",
        replace_existing=True,
    )
    scheduler.start()
    logger.info("Scheduler started — collecting every %ds", interval_seconds)
    return scheduler


def stop_scheduler() -> None:
    """Shut down the background scheduler gracefully."""
    global scheduler
    if scheduler and scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")
        scheduler = None
