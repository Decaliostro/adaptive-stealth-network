"""
Route switching logic with cooldown and anti-flapping.

Implements the fallback priority from the specification::

    1. Change Exit node
    2. Change Relay node
    3. Change Entry node
    4. Fallback to SingleNode mode
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from controller.scoring import ScoredRoute

logger = logging.getLogger("asn.controller.switcher")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
DEFAULT_COOLDOWN_SEC = 30
"""Minimum seconds between route switches for the same traffic type."""

SCORE_THRESHOLD = 15.0
"""Minimum score improvement required to trigger a switch."""


class RouteSwitcher:
    """
    Manages route switching decisions with cooldown and anti-flapping.

    Attributes:
        cooldowns:     Dict mapping ``traffic_type`` → ``switch_available_at``.
        current_routes: Dict mapping ``traffic_type`` → ``ScoredRoute``.
        switch_history: List of past switch events.
    """

    def __init__(
        self,
        cooldown_sec: int = DEFAULT_COOLDOWN_SEC,
        score_threshold: float = SCORE_THRESHOLD,
    ) -> None:
        """
        Initialize the route switcher.

        Args:
            cooldown_sec:    Cooldown period between switches (seconds).
            score_threshold: Minimum improvement in score to trigger a switch.
        """
        self.cooldown_sec = cooldown_sec
        self.score_threshold = score_threshold
        self.cooldowns: dict[str, datetime] = {}
        self.current_routes: dict[str, ScoredRoute] = {}
        self.switch_history: list[dict] = []

    def is_on_cooldown(self, traffic_type: str) -> bool:
        """
        Check if a traffic type is on switch cooldown.

        Args:
            traffic_type: The traffic category (streaming/gaming/browsing/api).

        Returns:
            True if switching is blocked by cooldown.
        """
        until = self.cooldowns.get(traffic_type)
        if until is None:
            return False
        return datetime.now(timezone.utc) < until

    def should_switch(
        self,
        traffic_type: str,
        candidate: ScoredRoute,
    ) -> bool:
        """
        Determine whether to switch to a candidate route.

        A switch is recommended when:
            1. No current route exists for this traffic type.
            2. Cooldown period has elapsed.
            3. Candidate score is better by at least ``score_threshold``.
            4. Current route is degraded or blocked.

        Args:
            traffic_type: Traffic category.
            candidate:    The proposed replacement route.

        Returns:
            True if a switch is recommended.
        """
        current = self.current_routes.get(traffic_type)

        # No current route → always switch
        if current is None:
            return True

        # On cooldown → don't switch
        if self.is_on_cooldown(traffic_type):
            logger.debug(
                "Traffic %s: switch blocked by cooldown", traffic_type
            )
            return False

        # Current route is blocked → always switch
        if current.state == "blocked":
            return True

        # Current route is degraded → switch if candidate is healthy
        if current.state == "degraded" and candidate.state == "healthy":
            return True

        # Score improvement must exceed threshold
        improvement = current.score - candidate.score
        if improvement >= self.score_threshold:
            logger.info(
                "Traffic %s: candidate %s improves score by %.2f (threshold=%.2f)",
                traffic_type, candidate.route_id, improvement, self.score_threshold,
            )
            return True

        return False

    def switch_route(
        self,
        traffic_type: str,
        new_route: ScoredRoute,
    ) -> dict:
        """
        Execute a route switch for a given traffic type.

        Sets the new current route, activates cooldown, and logs the event.

        Args:
            traffic_type: Traffic category.
            new_route:    The route to switch to.

        Returns:
            Switch event dict with old/new route info.
        """
        old_route = self.current_routes.get(traffic_type)

        event = {
            "traffic_type": traffic_type,
            "old_route_id": old_route.route_id if old_route else None,
            "new_route_id": new_route.route_id,
            "old_score": old_route.score if old_route else None,
            "new_score": new_route.score,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        self.current_routes[traffic_type] = new_route
        self.cooldowns[traffic_type] = datetime.now(timezone.utc) + timedelta(
            seconds=self.cooldown_sec
        )
        self.switch_history.append(event)

        logger.info(
            "🔄 SWITCH %s: %s → %s (score: %s → %.2f)",
            traffic_type,
            event["old_route_id"] or "none",
            new_route.route_id,
            event["old_score"],
            new_route.score,
        )
        return event

    def get_fallback_candidates(
        self,
        routes: list[ScoredRoute],
        current: ScoredRoute,
    ) -> list[ScoredRoute]:
        """
        Generate fallback candidates following the priority order.

        Priority::

            1. Routes with different Exit (same Entry/Relay)
            2. Routes with different Relay (same Entry/Exit)
            3. Routes with different Entry (same Relay/Exit)
            4. SingleNode routes

        Args:
            routes:  All available scored routes.
            current: The currently failing route.

        Returns:
            Ordered list of fallback candidates.
        """
        candidates: list[ScoredRoute] = []

        # 1. Different Exit
        diff_exit = [
            r for r in routes
            if r.route_id != current.route_id
            and r.entry_node_id == current.entry_node_id
            and r.relay_node_id == current.relay_node_id
            and r.exit_node_id != current.exit_node_id
            and r.state != "blocked"
        ]
        candidates.extend(sorted(diff_exit, key=lambda r: r.score))

        # 2. Different Relay
        diff_relay = [
            r for r in routes
            if r.route_id != current.route_id
            and r.entry_node_id == current.entry_node_id
            and r.relay_node_id != current.relay_node_id
            and r.exit_node_id == current.exit_node_id
            and r.state != "blocked"
        ]
        candidates.extend(sorted(diff_relay, key=lambda r: r.score))

        # 3. Different Entry
        diff_entry = [
            r for r in routes
            if r.route_id != current.route_id
            and r.entry_node_id != current.entry_node_id
            and r.state != "blocked"
        ]
        candidates.extend(sorted(diff_entry, key=lambda r: r.score))

        # 4. SingleNode fallback
        single_node = [
            r for r in routes
            if r.is_single_node
            and r.route_id != current.route_id
            and r.state != "blocked"
        ]
        candidates.extend(sorted(single_node, key=lambda r: r.score))

        # Remove duplicates while preserving order
        seen = set()
        unique = []
        for c in candidates:
            if c.route_id not in seen:
                seen.add(c.route_id)
                unique.append(c)

        return unique

    def execute_fallback(
        self,
        traffic_type: str,
        routes: list[ScoredRoute],
    ) -> Optional[dict]:
        """
        Attempt a fallback switch when the current route fails.

        Args:
            traffic_type: Traffic category.
            routes:       All available routes with scores.

        Returns:
            Switch event dict if fallback was successful, None otherwise.
        """
        current = self.current_routes.get(traffic_type)
        if current is None:
            return None

        candidates = self.get_fallback_candidates(routes, current)

        for candidate in candidates:
            if candidate.state != "blocked":
                # Force switch (bypass cooldown for fallback)
                self.cooldowns.pop(traffic_type, None)
                return self.switch_route(traffic_type, candidate)

        logger.error(
            "❌ FALLBACK FAILED for %s: no viable candidates",
            traffic_type,
        )
        return None
