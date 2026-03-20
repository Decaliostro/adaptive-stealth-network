"""
Blocked route recovery module.

Periodically re-tests routes marked as BLOCKED to determine if
they have become reachable again. Recovered routes are moved to
DEGRADED status before being considered for active use.

Recovery interval is randomized (60–120 seconds) for anti-detection.
"""

from __future__ import annotations

import asyncio
import logging
import random
from datetime import datetime, timezone
from typing import Callable, Optional

from controller.metrics import measure_latency

logger = logging.getLogger("asn.controller.recovery")


class RouteRecovery:
    """
    Manages periodic recovery checks for blocked routes.

    Attributes:
        min_interval:   Minimum seconds between recovery cycles.
        max_interval:   Maximum seconds between recovery cycles.
        max_retries:    Max consecutive recovery attempts per route.
        retry_counts:   Dict tracking retries per route_id.
        recovered:      List of recently recovered route IDs.
    """

    def __init__(
        self,
        min_interval: int = 60,
        max_interval: int = 120,
        max_retries: int = 5,
    ) -> None:
        """
        Initialize route recovery.

        Args:
            min_interval: Minimum recovery loop interval (seconds).
            max_interval: Maximum recovery loop interval (seconds).
            max_retries:  Max retries before permanent block.
        """
        self.min_interval = min_interval
        self.max_interval = max_interval
        self.max_retries = max_retries
        self.retry_counts: dict[str, int] = {}
        self.recovered: list[str] = []
        self._running = False

    async def test_route(
        self,
        route_id: str,
        hops: list[dict],
    ) -> bool:
        """
        Test if a blocked route has become reachable.

        Tests each hop in the route chain. If all hops respond,
        the route is considered recoverable.

        Args:
            route_id: Unique route identifier.
            hops:     List of dicts with ``host`` and ``port`` keys.

        Returns:
            True if all hops are reachable.
        """
        for hop in hops:
            latency, reachable = await measure_latency(
                host=hop["host"],
                port=hop["port"],
                timeout=5.0,
                samples=2,
            )
            if not reachable:
                logger.debug(
                    "Recovery test failed for route %s at hop %s:%d",
                    route_id, hop["host"], hop["port"],
                )
                return False

            # Random delay between hop tests (anti-DPI)
            await asyncio.sleep(random.uniform(0.1, 0.5))

        logger.info("✅ Route %s passed recovery test", route_id)
        return True

    async def attempt_recovery(
        self,
        route_id: str,
        hops: list[dict],
        on_recovered: Optional[Callable] = None,
    ) -> bool:
        """
        Attempt to recover a single blocked route.

        Args:
            route_id:     Route to recover.
            hops:         Hop list for the route.
            on_recovered: Callback invoked on successful recovery.

        Returns:
            True if recovery was successful.
        """
        retries = self.retry_counts.get(route_id, 0)

        if retries >= self.max_retries:
            logger.warning(
                "Route %s: max retries (%d) reached, skipping",
                route_id, self.max_retries,
            )
            return False

        self.retry_counts[route_id] = retries + 1

        is_alive = await self.test_route(route_id, hops)

        if is_alive:
            self.recovered.append(route_id)
            self.retry_counts.pop(route_id, None)
            logger.info(
                "🔄 Route %s recovered → moving to DEGRADED",
                route_id,
            )
            if on_recovered:
                await on_recovered(route_id) if asyncio.iscoroutinefunction(on_recovered) \
                    else on_recovered(route_id)
            return True

        return False

    async def recovery_loop(
        self,
        get_blocked_routes: Callable,
        on_recovered: Optional[Callable] = None,
    ) -> None:
        """
        Main recovery loop — runs continuously in background.

        Every 60–120 seconds (randomized), re-tests all blocked routes.

        Args:
            get_blocked_routes: Callable that returns list of
                                ``(route_id, hops)`` tuples.
            on_recovered:       Callback for recovered routes.
        """
        self._running = True
        logger.info("Recovery loop started")

        while self._running:
            # Randomized interval for anti-detection
            interval = random.randint(self.min_interval, self.max_interval)
            logger.debug("Next recovery check in %d seconds", interval)
            await asyncio.sleep(interval)

            if not self._running:
                break

            blocked = await get_blocked_routes() if asyncio.iscoroutinefunction(
                get_blocked_routes
            ) else get_blocked_routes()

            if not blocked:
                logger.debug("No blocked routes to recover")
                continue

            logger.info("Recovery: testing %d blocked routes", len(blocked))

            for route_id, hops in blocked:
                if not self._running:
                    break
                await self.attempt_recovery(route_id, hops, on_recovered)
                # Stagger tests to avoid burst patterns
                await asyncio.sleep(random.uniform(1.0, 3.0))

    def stop(self) -> None:
        """Stop the recovery loop gracefully."""
        self._running = False
        logger.info("Recovery loop stopping")

    def reset_route(self, route_id: str) -> None:
        """
        Reset retry counter for a route (e.g., after manual intervention).

        Args:
            route_id: Route to reset.
        """
        self.retry_counts.pop(route_id, None)
        logger.debug("Reset retry counter for route %s", route_id)
