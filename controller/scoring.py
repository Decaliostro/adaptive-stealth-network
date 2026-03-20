"""
Route scoring algorithm.

Computes a composite score for each route based on latency,
packet loss, throughput, and error count. **Lower score = better route.**

Scoring formula (from specification)::

    score = latency * 0.4
          + packet_loss * 2.0
          - throughput * 0.3
          + error_count * 100
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger("asn.controller.scoring")

# ---------------------------------------------------------------------------
# Weights (configurable via settings.yaml)
# ---------------------------------------------------------------------------
DEFAULT_WEIGHTS = {
    "latency": 0.4,
    "packet_loss": 2.0,
    "throughput": -0.3,  # negative because higher throughput is better
    "error_count": 100.0,
}


@dataclass
class ScoredRoute:
    """A route with its computed score and metadata."""

    route_id: str
    score: float
    latency_ms: float
    packet_loss_percent: float
    throughput_mbps: float
    error_count: int
    state: str  # healthy / degraded / blocked
    entry_node_id: str
    relay_node_id: Optional[str]
    exit_node_id: str
    transport: str
    is_single_node: bool


def score_route(
    latency_ms: float,
    packet_loss_percent: float,
    throughput_mbps: float,
    error_count: int,
    weights: Optional[dict] = None,
) -> float:
    """
    Compute a composite score for a route.

    Lower scores indicate healthier, faster routes.

    Args:
        latency_ms:          Average latency in milliseconds.
        packet_loss_percent: Packet loss as a percentage (0–100).
        throughput_mbps:     Measured throughput in Mbps.
        error_count:         Number of errors since last measurement.
        weights:             Custom weight overrides (optional).

    Returns:
        Composite score (float). Lower is better.

    Examples:
        >>> score_route(50, 0, 100, 0)
        -10.0
        >>> score_route(200, 5, 50, 1)
        175.0
    """
    w = {**DEFAULT_WEIGHTS, **(weights or {})}

    result = (
        latency_ms * w["latency"]
        + packet_loss_percent * w["packet_loss"]
        + throughput_mbps * w["throughput"]
        + error_count * w["error_count"]
    )

    logger.debug(
        "Score: latency=%.1f loss=%.1f throughput=%.1f errors=%d → score=%.2f",
        latency_ms, packet_loss_percent, throughput_mbps, error_count, result,
    )
    return float(round(result, 2))


def rank_routes(
    routes: list[ScoredRoute],
    exclude_blocked: bool = True,
) -> list[ScoredRoute]:
    """
    Sort routes by score (ascending — lowest score first).

    Args:
        routes:          List of ``ScoredRoute`` objects.
        exclude_blocked: If True, filter out blocked routes.

    Returns:
        Sorted list of routes. Best route is at index 0.
    """
    filtered = routes
    if exclude_blocked:
        filtered = [r for r in routes if r.state != "blocked"]

    ranked = sorted(filtered, key=lambda r: r.score)

    if ranked:
        logger.info(
            "Route ranking: best=%s (score=%.2f), worst=%s (score=%.2f), total=%d",
            ranked[0].route_id, ranked[0].score,
            ranked[-1].route_id, ranked[-1].score,
            len(ranked),
        )

    return ranked


def select_best_route(
    routes: list[ScoredRoute],
    traffic_type: Optional[str] = None,
) -> Optional[ScoredRoute]:
    """
    Select the best route from a ranked list, optionally filtering by traffic type.

    Applied logic:
        - For ``streaming``: prefer routes with high throughput (re-weight).
        - For ``gaming``: prefer routes with low latency (re-weight).
        - For ``browsing``/``api``: use default ranking.

    Args:
        routes:       List of scored routes.
        traffic_type: Optional traffic category.

    Returns:
        The best ``ScoredRoute``, or None if no routes are available.
    """
    if not routes:
        return None

    ranked = rank_routes(routes)

    if not ranked:
        return None

    if traffic_type == "streaming":
        # Re-sort preferring higher throughput
        ranked = sorted(ranked, key=lambda r: -r.throughput_mbps)
    elif traffic_type == "gaming":
        # Re-sort preferring lower latency
        ranked = sorted(ranked, key=lambda r: r.latency_ms)

    return ranked[0]
