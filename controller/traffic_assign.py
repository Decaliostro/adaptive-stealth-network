"""
Traffic segmentation and route assignment module.

Assigns routes to traffic types based on node capabilities:
    - **Streaming** — requires high bandwidth exit nodes.
    - **Gaming**    — requires lowest latency, closest nodes.
    - **Browsing**  — balanced, any stable node.
    - **API**       — requires stability, low overhead.
"""

from __future__ import annotations

import logging
from typing import Optional

from controller.scoring import ScoredRoute, rank_routes

logger = logging.getLogger("asn.controller.traffic")

# ---------------------------------------------------------------------------
# Traffic type definitions
# ---------------------------------------------------------------------------
TRAFFIC_TYPES = ("streaming", "gaming", "browsing", "api")

# Requirements per traffic type
TRAFFIC_REQUIREMENTS = {
    "streaming": {
        "min_throughput_mbps": 10.0,
        "max_latency_ms": 300.0,
        "max_packet_loss": 5.0,
        "prefer": "throughput",
    },
    "gaming": {
        "min_throughput_mbps": 1.0,
        "max_latency_ms": 80.0,
        "max_packet_loss": 2.0,
        "prefer": "latency",
    },
    "browsing": {
        "min_throughput_mbps": 1.0,
        "max_latency_ms": 500.0,
        "max_packet_loss": 10.0,
        "prefer": "balanced",
    },
    "api": {
        "min_throughput_mbps": 0.5,
        "max_latency_ms": 200.0,
        "max_packet_loss": 3.0,
        "prefer": "stability",
    },
}


def filter_routes_for_traffic(
    routes: list[ScoredRoute],
    traffic_type: str,
) -> list[ScoredRoute]:
    """
    Filter routes that meet the requirements for a specific traffic type.

    Args:
        routes:       All available scored routes.
        traffic_type: One of streaming/gaming/browsing/api.

    Returns:
        Filtered list of routes meeting the traffic requirements.
    """
    reqs = TRAFFIC_REQUIREMENTS.get(traffic_type)
    if reqs is None:
        logger.warning("Unknown traffic type: %s, using all routes", traffic_type)
        return routes

    filtered = []
    for route in routes:
        if route.state == "blocked":
            continue

        # Check latency requirement
        if route.latency_ms > reqs["max_latency_ms"]:
            continue

        # Check packet loss requirement
        if route.packet_loss_percent > reqs["max_packet_loss"]:
            continue

        # Check throughput requirement (if measured)
        if route.throughput_mbps > 0 and route.throughput_mbps < reqs["min_throughput_mbps"]:
            continue

        filtered.append(route)

    logger.debug(
        "Traffic %s: %d/%d routes meet requirements",
        traffic_type, len(filtered), len(routes),
    )
    return filtered


def assign_route(
    traffic_type: str,
    routes: list[ScoredRoute],
) -> Optional[ScoredRoute]:
    """
    Assign the best route for a given traffic type.

    Selection strategy varies by traffic type:
        - **streaming**: Prefer highest throughput among eligible routes.
        - **gaming**: Prefer lowest latency.
        - **browsing**: Use default score ranking (balanced).
        - **api**: Prefer lowest error count, then lowest latency.

    Args:
        traffic_type: Traffic category.
        routes:       All available scored routes.

    Returns:
        The best route for this traffic type, or None if none qualify.
    """
    eligible = filter_routes_for_traffic(routes, traffic_type)

    if not eligible:
        # Fallback: relax requirements and use all non-blocked routes
        logger.warning(
            "Traffic %s: no routes meet strict requirements, relaxing filters",
            traffic_type,
        )
        eligible = [r for r in routes if r.state != "blocked"]

    if not eligible:
        logger.error("Traffic %s: no routes available at all", traffic_type)
        return None

    reqs = TRAFFIC_REQUIREMENTS.get(traffic_type, {})
    preference = reqs.get("prefer", "balanced")

    if preference == "throughput":
        # Sort by throughput descending
        eligible.sort(key=lambda r: -r.throughput_mbps)
    elif preference == "latency":
        # Sort by latency ascending
        eligible.sort(key=lambda r: r.latency_ms)
    elif preference == "stability":
        # Sort by errors ascending, then latency
        eligible.sort(key=lambda r: (r.error_count, r.latency_ms))
    else:
        # Default: use composite score
        eligible = rank_routes(eligible, exclude_blocked=True)

    best = eligible[0]
    logger.info(
        "Traffic %s: assigned route %s (score=%.2f, latency=%.1fms, throughput=%.1fMbps)",
        traffic_type, best.route_id, best.score, best.latency_ms, best.throughput_mbps,
    )
    return best


def assign_all_routes(
    routes: list[ScoredRoute],
    traffic_types: tuple = TRAFFIC_TYPES,
) -> dict[str, Optional[ScoredRoute]]:
    """
    Assign best routes for all traffic types.

    Args:
        routes:        All available scored routes.
        traffic_types: Traffic categories to assign.

    Returns:
        Dict mapping traffic type → best ScoredRoute (or None).
    """
    assignments: dict[str, Optional[ScoredRoute]] = {}

    for tt in traffic_types:
        assignments[tt] = assign_route(tt, routes)

    return assignments
