"""
Tests for the traffic assignment module.
"""

import pytest

from controller.scoring import ScoredRoute
from controller.traffic_assign import (
    TRAFFIC_TYPES,
    assign_all_routes,
    assign_route,
    filter_routes_for_traffic,
)


def _make_route(
    route_id: str,
    latency: float = 50,
    packet_loss: float = 0,
    throughput: float = 100,
    error_count: int = 0,
    state: str = "healthy",
) -> ScoredRoute:
    """Helper to create a ScoredRoute for tests."""
    return ScoredRoute(
        route_id=route_id,
        score=latency * 0.4 + packet_loss * 2.0 - throughput * 0.3 + error_count * 100,
        latency_ms=latency,
        packet_loss_percent=packet_loss,
        throughput_mbps=throughput,
        error_count=error_count,
        state=state,
        entry_node_id="e1",
        relay_node_id=None,
        exit_node_id="x1",
        transport="quic",
        is_single_node=False,
    )


class TestFilterRoutes:
    """Tests for filter_routes_for_traffic."""

    def test_gaming_filters_high_latency(self):
        """Gaming should filter out routes with latency > 80ms."""
        routes = [
            _make_route("fast", latency=30),
            _make_route("slow", latency=150),
        ]
        filtered = filter_routes_for_traffic(routes, "gaming")
        assert len(filtered) == 1
        assert filtered[0].route_id == "fast"

    def test_streaming_filters_low_throughput(self):
        """Streaming should filter routes with throughput < 10 Mbps."""
        routes = [
            _make_route("high_bw", throughput=50),
            _make_route("low_bw", throughput=5),
        ]
        filtered = filter_routes_for_traffic(routes, "streaming")
        assert len(filtered) == 1
        assert filtered[0].route_id == "high_bw"

    def test_blocked_routes_excluded(self):
        """Blocked routes should always be filtered out."""
        routes = [
            _make_route("good", state="healthy"),
            _make_route("blocked", state="blocked"),
        ]
        filtered = filter_routes_for_traffic(routes, "browsing")
        assert len(filtered) == 1

    def test_unknown_type_returns_all(self):
        """Unknown traffic type should return all routes."""
        routes = [_make_route("r1"), _make_route("r2")]
        filtered = filter_routes_for_traffic(routes, "unknown_type")
        assert len(filtered) == 2


class TestAssignRoute:
    """Tests for assign_route."""

    def test_streaming_picks_highest_throughput(self):
        """Streaming should pick the route with highest throughput."""
        routes = [
            _make_route("r1", throughput=100),
            _make_route("r2", throughput=500),
        ]
        best = assign_route("streaming", routes)
        assert best is not None
        assert best.route_id == "r2"

    def test_gaming_picks_lowest_latency(self):
        """Gaming should pick the route with lowest latency."""
        routes = [
            _make_route("r1", latency=50),
            _make_route("r2", latency=10),
        ]
        best = assign_route("gaming", routes)
        assert best is not None
        assert best.route_id == "r2"

    def test_no_routes_returns_none(self):
        """Empty route list should return None."""
        result = assign_route("browsing", [])
        assert result is None

    def test_all_blocked_returns_none(self):
        """If all routes are blocked, should return None."""
        routes = [
            _make_route("r1", state="blocked"),
            _make_route("r2", state="blocked"),
        ]
        result = assign_route("browsing", routes)
        assert result is None


class TestAssignAllRoutes:
    """Tests for assign_all_routes."""

    def test_assigns_for_all_types(self):
        """Should return assignments for all traffic types."""
        routes = [_make_route("r1", latency=20, throughput=200)]
        assignments = assign_all_routes(routes)
        assert set(assignments.keys()) == set(TRAFFIC_TYPES)

    def test_empty_routes_gives_none(self):
        """Empty routes should give None for all types."""
        assignments = assign_all_routes([])
        for tt in TRAFFIC_TYPES:
            assert assignments[tt] is None
