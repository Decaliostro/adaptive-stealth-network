"""
Anti-DPI detection and evasion module.

Implements countermeasures against Deep Packet Inspection:
    - Random jitter (10–50ms) on connections.
    - Random reconnect intervals.
    - Avoidance of fixed packet patterns.
    - Limiting frequent switching to avoid behavioral fingerprinting.
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

logger = logging.getLogger("asn.controller.anti_dpi")


class BlockingType(str, Enum):
    """Detected DPI blocking patterns."""
    TIMEOUT = "timeout"
    CONNECTION_RESET = "connection_reset"
    UDP_FAILURE = "udp_failure"
    SHORT_LIVED = "short_lived"
    PATTERN_MATCH = "pattern_match"
    UNKNOWN = "unknown"


@dataclass
class DPIEvent:
    """Record of a detected DPI event."""

    blocking_type: BlockingType
    node_id: str
    timestamp: float = field(default_factory=time.time)
    details: str = ""


class AntiDPI:
    """
    Anti-DPI behaviour engine.

    Provides jitter injection, randomized timing, and DPI detection
    to help evade deep packet inspection systems.

    Attributes:
        min_jitter_ms: Minimum jitter delay in milliseconds.
        max_jitter_ms: Maximum jitter delay in milliseconds.
        events:        History of detected DPI events.
        switch_limit:  Maximum switches per minute to avoid detection.
    """

    def __init__(
        self,
        min_jitter_ms: float = 10.0,
        max_jitter_ms: float = 50.0,
        switch_limit: int = 4,
    ) -> None:
        """
        Initialize the Anti-DPI engine.

        Args:
            min_jitter_ms: Minimum jitter injection (ms).
            max_jitter_ms: Maximum jitter injection (ms).
            switch_limit:  Max route switches per minute.
        """
        self.min_jitter_ms = min_jitter_ms
        self.max_jitter_ms = max_jitter_ms
        self.switch_limit = switch_limit
        self.events: list[DPIEvent] = []
        self._switch_timestamps: list[float] = []

    async def apply_jitter(self) -> float:
        """
        Apply a random delay to disrupt timing-based DPI detection.

        The jitter value is uniformly distributed between
        ``min_jitter_ms`` and ``max_jitter_ms``.

        Returns:
            Actual jitter applied in milliseconds.
        """
        jitter_ms = random.uniform(self.min_jitter_ms, self.max_jitter_ms)
        await asyncio.sleep(jitter_ms / 1000.0)
        return jitter_ms

    def randomize_reconnect_interval(
        self,
        base_interval: float = 5.0,
    ) -> float:
        """
        Generate a randomized reconnect interval.

        Adds ±30% variation to the base interval to avoid creating
        predictable reconnection patterns.

        Args:
            base_interval: Base reconnect interval in seconds.

        Returns:
            Randomized interval in seconds.
        """
        variation = base_interval * 0.3
        interval = base_interval + random.uniform(-variation, variation)
        return max(1.0, interval)  # Never less than 1 second

    def detect_dpi_blocking(
        self,
        error: Exception,
        node_id: str,
        connection_duration: Optional[float] = None,
    ) -> Optional[DPIEvent]:
        """
        Analyze an error to determine if it indicates DPI blocking.

        Detection heuristics:
            - ``TimeoutError`` → timeout-based blocking.
            - ``ConnectionResetError`` → active connection reset.
            - Short-lived connections (<2s) → short-lived pattern.
            - ``OSError`` with specific codes → UDP/protocol blocking.

        Args:
            error:               The caught exception.
            node_id:             Node where the error occurred.
            connection_duration: How long the connection lasted (seconds).

        Returns:
            ``DPIEvent`` if blocking is detected, None otherwise.
        """
        event = None

        if isinstance(error, asyncio.TimeoutError):
            event = DPIEvent(
                blocking_type=BlockingType.TIMEOUT,
                node_id=node_id,
                details="Connection timed out — possible DPI timeout-based blocking",
            )
        elif isinstance(error, ConnectionResetError):
            event = DPIEvent(
                blocking_type=BlockingType.CONNECTION_RESET,
                node_id=node_id,
                details="Connection reset by remote — possible active DPI",
            )
        elif isinstance(error, OSError) and "udp" in str(error).lower():
            event = DPIEvent(
                blocking_type=BlockingType.UDP_FAILURE,
                node_id=node_id,
                details=f"UDP failure: {error}",
            )
        elif connection_duration is not None and connection_duration < 2.0:
            event = DPIEvent(
                blocking_type=BlockingType.SHORT_LIVED,
                node_id=node_id,
                details=f"Connection lasted only {connection_duration:.1f}s",
            )

        if event:
            self.events.append(event)
            logger.warning(
                "🛡️ DPI detected on node %s: %s — %s",
                node_id,
                event.blocking_type.value,
                event.details,
            )

        return event

    def is_switch_allowed(self) -> bool:
        """
        Check if a route switch is allowed without exceeding the
        frequency limit (anti-behavioral-fingerprinting).

        Returns:
            True if switching is allowed.
        """
        now = time.time()
        # Clean old timestamps
        self._switch_timestamps = [
            ts for ts in self._switch_timestamps
            if now - ts < 60.0
        ]

        if len(self._switch_timestamps) >= self.switch_limit:
            logger.debug(
                "Switch blocked: %d switches in last minute (limit=%d)",
                len(self._switch_timestamps),
                self.switch_limit,
            )
            return False

        return True

    def record_switch(self) -> None:
        """Record a route switch event for rate limiting."""
        self._switch_timestamps.append(time.time())

    def get_recent_events(
        self,
        node_id: Optional[str] = None,
        max_age_seconds: float = 300.0,
    ) -> list[DPIEvent]:
        """
        Get recent DPI events, optionally filtered by node.

        Args:
            node_id:          Filter by node (None = all nodes).
            max_age_seconds:  Maximum event age in seconds.

        Returns:
            List of matching events.
        """
        cutoff = time.time() - max_age_seconds
        events = [e for e in self.events if e.timestamp > cutoff]
        if node_id:
            events = [e for e in events if e.node_id == node_id]
        return events

    def is_node_under_dpi(
        self,
        node_id: str,
        threshold: int = 3,
    ) -> bool:
        """
        Determine if a node appears to be under active DPI.

        Args:
            node_id:   Node to check.
            threshold: Number of recent events indicating DPI.

        Returns:
            True if the node has more than ``threshold`` recent events.
        """
        recent = self.get_recent_events(node_id=node_id, max_age_seconds=300.0)
        return len(recent) >= threshold
