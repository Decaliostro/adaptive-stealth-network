"""
Tests for the route scoring algorithm.
"""

import pytest

from controller.scoring import ScoredRoute, rank_routes, score_route, select_best_route


class TestScoreRoute:
    """Tests for the score_route function."""

    def test_perfect_route(self):
        """A route with zero latency/loss/errors and high throughput gets a very low score."""
        result = score_route(
            latency_ms=0,
            packet_loss_percent=0,
            throughput_mbps=100,
            error_count=0,
        )
        assert result < 0  # throughput pulls score negative

    def test_bad_route(self):
        """A route with high latency, loss, and errors gets a high score."""
        result = score_route(
            latency_ms=500,
            packet_loss_percent=50,
            throughput_mbps=0,
            error_count=5,
        )
        assert result > 500

    def test_moderate_route(self):
        """A moderate route scores between perfect and bad."""
        result = score_route(
            latency_ms=50,
            packet_loss_percent=2,
            throughput_mbps=50,
            error_count=0,
        )
        # 50*0.4 + 2*2.0 + 50*(-0.3) + 0*100 = 20 + 4 - 15 = 9
        assert result == 9.0

    def test_error_count_dominates(self):
        """Error count with weight 100 should dominate the score."""
        no_errors = score_route(50, 0, 100, 0)
        with_errors = score_route(50, 0, 100, 3)
        assert with_errors - no_errors == 300.0

    def test_custom_weights(self):
        """Custom weights should override defaults."""
        default = score_route(100, 10, 50, 0)
        custom = score_route(
            100, 10, 50, 0,
            weights={"latency": 1.0, "packet_loss": 1.0, "throughput": 0, "error_count": 0},
        )
        # custom: 100*1.0 + 10*1.0 + 50*0 + 0*0 = 110
        assert custom == 110.0
        assert custom != default


class TestRankRoutes:
    """Tests for route ranking."""

    def _make_route(self, route_id: str, score: float, state: str = "healthy") -> ScoredRoute:
        return ScoredRoute(
            route_id=route_id,
            score=score,
            latency_ms=50,
            packet_loss_percent=0,
            throughput_mbps=100,
            error_count=0,
            state=state,
            entry_node_id="e1",
            relay_node_id=None,
            exit_node_id="x1",
            transport="quic",
            is_single_node=False,
        )

    def test_ranking_order(self):
        """Routes should be sorted by score ascending (best first)."""
        routes = [
            self._make_route("r3", 30),
            self._make_route("r1", 10),
            self._make_route("r2", 20),
        ]
        ranked = rank_routes(routes)
        assert [r.route_id for r in ranked] == ["r1", "r2", "r3"]

    def test_exclude_blocked(self):
        """Blocked routes should be excluded by default."""
        routes = [
            self._make_route("r1", 10),
            self._make_route("r2", 5, state="blocked"),
        ]
        ranked = rank_routes(routes, exclude_blocked=True)
        assert len(ranked) == 1
        assert ranked[0].route_id == "r1"

    def test_include_blocked(self):
        """Blocked routes should be kept when exclude_blocked=False."""
        routes = [
            self._make_route("r1", 10),
            self._make_route("r2", 5, state="blocked"),
        ]
        ranked = rank_routes(routes, exclude_blocked=False)
        assert len(ranked) == 2

    def test_empty_list(self):
        """Empty list should return empty."""
        assert rank_routes([]) == []


class TestSelectBestRoute:
    """Tests for select_best_route."""

    def _make_route(
        self, route_id: str, score: float,
        latency: float = 50, throughput: float = 100,
    ) -> ScoredRoute:
        return ScoredRoute(
            route_id=route_id,
            score=score,
            latency_ms=latency,
            packet_loss_percent=0,
            throughput_mbps=throughput,
            error_count=0,
            state="healthy",
            entry_node_id="e1",
            relay_node_id=None,
            exit_node_id="x1",
            transport="quic",
            is_single_node=False,
        )

    def test_streaming_prefers_throughput(self):
        """Streaming should select the route with highest throughput."""
        routes = [
            self._make_route("fast", 10, throughput=500),
            self._make_route("slow", 5, throughput=50),
        ]
        best = select_best_route(routes, traffic_type="streaming")
        assert best.route_id == "fast"

    def test_gaming_prefers_latency(self):
        """Gaming should select the route with lowest latency."""
        routes = [
            self._make_route("high_lat", 5, latency=100),
            self._make_route("low_lat", 10, latency=10),
        ]
        best = select_best_route(routes, traffic_type="gaming")
        assert best.route_id == "low_lat"

    def test_default_uses_score(self):
        """Default selection should use composite score."""
        routes = [
            self._make_route("r1", 20),
            self._make_route("r2", 5),
        ]
        best = select_best_route(routes)
        assert best.route_id == "r2"

    def test_empty_returns_none(self):
        """No routes should return None."""
        assert select_best_route([]) is None
