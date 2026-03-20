"""
Network metrics measurement module.

Provides functions for measuring latency, packet loss, and throughput
for individual nodes and complete routes (Entry → Relay → Exit chains).
"""

from __future__ import annotations

import asyncio
import logging
import random
import struct
import time
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger("asn.controller.metrics")


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class NodeMetrics:
    """Measurement results for a single node."""

    node_id: str
    host: str
    port: int
    latency_ms: float = 0.0
    packet_loss_percent: float = 0.0
    throughput_mbps: float = 0.0
    error_count: int = 0
    reachable: bool = True


@dataclass
class RouteMetrics:
    """Aggregated metrics for an entire route chain."""

    route_id: str
    total_latency_ms: float = 0.0
    max_packet_loss: float = 0.0
    min_throughput_mbps: float = 0.0
    total_errors: int = 0
    hops: list[NodeMetrics] = field(default_factory=list)

    @property
    def is_healthy(self) -> bool:
        """Route is healthy if all hops are reachable and latency is acceptable."""
        return (
            all(h.reachable for h in self.hops)
            and self.total_latency_ms < 500
            and self.max_packet_loss < 20
        )


# ---------------------------------------------------------------------------
# Measurement functions
# ---------------------------------------------------------------------------

async def measure_latency(
    host: str,
    port: int,
    timeout: float = 5.0,
    samples: int = 3,
) -> tuple[float, bool]:
    """
    Measure TCP connection latency to a host.

    Performs ``samples`` TCP handshakes and returns the average
    round-trip time in milliseconds.

    Args:
        host:    Target hostname or IP address.
        port:    Target port number.
        timeout: Connection timeout per sample (seconds).
        samples: Number of measurements to average.

    Returns:
        Tuple of (average_latency_ms, is_reachable).
    """
    latencies: list[float] = []
    failures = 0

    for _ in range(samples):
        start = time.monotonic()
        try:
            _, writer = await asyncio.wait_for(
                asyncio.open_connection(host, port),
                timeout=timeout,
            )
            elapsed = (time.monotonic() - start) * 1000
            latencies.append(elapsed)
            writer.close()
            await writer.wait_closed()
        except (asyncio.TimeoutError, OSError):
            failures = failures + 1
        # Small delay between samples to avoid triggering DPI
        await asyncio.sleep(random.uniform(0.05, 0.15))

    if not latencies:
        return 0.0, False

    avg_latency = sum(latencies) / len(latencies)
    return float(round(avg_latency, 2)), True


async def measure_packet_loss(
    host: str,
    port: int,
    count: int = 10,
    timeout: float = 3.0,
) -> float:
    """
    Estimate packet loss by attempting multiple TCP connections.

    Args:
        host:    Target hostname or IP.
        port:    Target port.
        count:   Number of connection attempts.
        timeout: Timeout per attempt (seconds).

    Returns:
        Packet loss as a percentage (0–100).
    """
    successes = 0

    for _ in range(count):
        try:
            _, writer = await asyncio.wait_for(
                asyncio.open_connection(host, port),
                timeout=timeout,
            )
            writer.close()
            await writer.wait_closed()
            successes = successes + 1
        except (asyncio.TimeoutError, OSError):
            pass
        await asyncio.sleep(random.uniform(0.02, 0.08))

    loss: float = ((count - successes) / count) * 100
    return float(round(loss, 1))


async def measure_throughput(
    host: str,
    port: int,
    duration: float = 2.0,
    timeout: float = 5.0,
) -> float:
    """
    Estimate throughput by sending data over a TCP connection.

    This is a simplified estimation — it sends random data and
    measures how much can be pushed within ``duration`` seconds.
    For accurate results, the target should accept incoming data
    (e.g., a discard service).

    Args:
        host:     Target hostname or IP.
        port:     Target port.
        duration: Test duration in seconds.
        timeout:  Connection timeout.

    Returns:
        Estimated throughput in Mbps.
    """
    try:
        _, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port),
            timeout=timeout,
        )
    except (asyncio.TimeoutError, OSError):
        return 0.0

    chunk = bytes(random.getrandbits(8) for _ in range(8192))
    total_bytes = 0
    start = time.monotonic()

    try:
        while (time.monotonic() - start) < duration:
            writer.write(chunk)
            await writer.drain()
            total_bytes += len(chunk)
    except (OSError, ConnectionError):
        pass
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except OSError:
            pass

    elapsed = time.monotonic() - start
    if elapsed == 0:
        return 0.0

    throughput_mbps = (total_bytes * 8) / (elapsed * 1_000_000)
    return float(round(throughput_mbps, 2))


async def measure_node(
    node_id: str,
    host: str,
    port: int,
    full: bool = False,
) -> NodeMetrics:
    """
    Perform a comprehensive measurement of a single node.

    Args:
        node_id: Unique node identifier.
        host:    Node hostname or IP.
        port:    Node port.
        full:    If True, also measure throughput (slower).

    Returns:
        ``NodeMetrics`` with all measured values.
    """
    latency, reachable = await measure_latency(host, port)
    loss = await measure_packet_loss(host, port, count=5) if reachable else 100.0
    throughput = 0.0

    if full and reachable:
        throughput = await measure_throughput(host, port)

    metrics = NodeMetrics(
        node_id=node_id,
        host=host,
        port=port,
        latency_ms=latency,
        packet_loss_percent=loss,
        throughput_mbps=throughput,
        error_count=0 if reachable else 1,
        reachable=reachable,
    )

    logger.debug(
        "Node %s (%s:%d): latency=%.1fms loss=%.1f%% throughput=%.1fMbps reachable=%s",
        node_id, host, port, latency, loss, throughput, reachable,
    )
    return metrics


async def measure_route(
    route_id: str,
    hops: list[dict],
    full: bool = False,
) -> RouteMetrics:
    """
    Measure a complete route chain (Entry → Relay → Exit).

    Args:
        route_id: Unique route identifier.
        hops:     List of dicts with ``node_id``, ``host``, ``port`` keys.
        full:     If True, also measure throughput.

    Returns:
        ``RouteMetrics`` with aggregated data for the entire chain.
    """
    route_metrics = RouteMetrics(route_id=route_id)

    for hop in hops:
        node_metrics = await measure_node(
            node_id=hop["node_id"],
            host=hop["host"],
            port=hop["port"],
            full=full,
        )
        route_metrics.hops.append(node_metrics)

    if route_metrics.hops:
        route_metrics.total_latency_ms = sum(h.latency_ms for h in route_metrics.hops)
        route_metrics.max_packet_loss = max(h.packet_loss_percent for h in route_metrics.hops)
        route_metrics.min_throughput_mbps = min(
            (h.throughput_mbps for h in route_metrics.hops if h.throughput_mbps > 0),
            default=0.0,
        )
        route_metrics.total_errors = sum(h.error_count for h in route_metrics.hops)

    logger.info(
        "Route %s: total_latency=%.1fms max_loss=%.1f%% errors=%d healthy=%s",
        route_id,
        route_metrics.total_latency_ms,
        route_metrics.max_packet_loss,
        route_metrics.total_errors,
        route_metrics.is_healthy,
    )
    return route_metrics
