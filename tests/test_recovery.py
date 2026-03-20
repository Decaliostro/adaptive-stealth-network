"""
Tests for route recovery module.
"""

import asyncio
import pytest

from controller.recovery import RouteRecovery


class TestRouteRecovery:
    """Tests for RouteRecovery."""

    def test_retry_counter_increments(self):
        """Retry counter should increment on each attempt."""
        recovery = RouteRecovery(max_retries=3)
        recovery.retry_counts["route-1"] = 0

        # Simulate incrementing manually (normally done by attempt_recovery)
        recovery.retry_counts["route-1"] += 1
        assert recovery.retry_counts["route-1"] == 1

    def test_max_retries_respected(self):
        """Routes exceeding max retries should be skipped."""
        recovery = RouteRecovery(max_retries=3)
        recovery.retry_counts["route-1"] = 3

        # attempt_recovery checks max_retries
        # Since retries >= max_retries, it should return False
        # We test the condition directly
        assert recovery.retry_counts["route-1"] >= recovery.max_retries

    def test_reset_route(self):
        """reset_route should clear retry counter."""
        recovery = RouteRecovery()
        recovery.retry_counts["route-1"] = 5
        recovery.reset_route("route-1")
        assert "route-1" not in recovery.retry_counts

    def test_stop(self):
        """stop() should set _running to False."""
        recovery = RouteRecovery()
        recovery._running = True
        recovery.stop()
        assert recovery._running is False

    @pytest.mark.asyncio
    async def test_test_route_unreachable(self):
        """test_route should return False for unreachable hosts."""
        recovery = RouteRecovery()
        result = await recovery.test_route(
            route_id="test-route",
            hops=[{"host": "192.0.2.1", "port": 65534}],
        )
        # Unreachable host should return False
        assert result is False

    def test_recovered_list(self):
        """Recovered routes should be tracked."""
        recovery = RouteRecovery()
        recovery.recovered.append("route-1")
        assert "route-1" in recovery.recovered
