"""
Main controller loop for the Adaptive Stealth Network.

Orchestrates the complete adaptive routing cycle::

    1. Fetch routes from backend API.
    2. Measure metrics for each route.
    3. Score and rank routes.
    4. Assign best route per traffic type.
    5. Switch routes if better candidates found.
    6. Apply anti-DPI countermeasures.
    7. Handle transport fallback.
    8. Recover blocked routes (background).

Run with::

    python -m controller.main
"""

from __future__ import annotations

import asyncio
import logging
import signal
import sys
from typing import Optional

import httpx
import yaml

from controller.anti_dpi import AntiDPI
from controller.metrics import RouteMetrics, measure_route
from controller.recovery import RouteRecovery
from controller.scoring import ScoredRoute, score_route
from controller.singbox_manager import SingboxManager
from controller.switcher import RouteSwitcher
from controller.traffic_assign import TRAFFIC_TYPES, assign_all_routes
from controller.transport_adapt import TransportAdapter

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("asn.controller.main")


# ---------------------------------------------------------------------------
# Settings loader
# ---------------------------------------------------------------------------
def load_settings(path: str = "config/settings.yaml") -> dict:
    """
    Load controller settings from YAML file.

    Args:
        path: Path to settings.yaml.

    Returns:
        Settings dict with defaults for missing keys.
    """
    defaults = {
        "backend_url": "http://127.0.0.1:8000",
        "loop_interval": 5,
        "scoring_weights": {
            "latency": 0.4,
            "packet_loss": 2.0,
            "throughput": -0.3,
            "error_count": 100.0,
        },
        "cooldown_sec": 30,
        "score_threshold": 15.0,
        "recovery_min_interval": 60,
        "recovery_max_interval": 120,
        "singbox_binary": "sing-box",
        "listen_port": 10808,
    }

    try:
        with open(path, "r") as f:
            loaded = yaml.safe_load(f) or {}
        # Merge loaded over defaults
        for key, value in loaded.items():
            if isinstance(value, dict) and key in defaults and isinstance(defaults[key], dict):
                defaults[key].update(value)
            else:
                defaults[key] = value
        logger.info("Settings loaded from %s", path)
    except FileNotFoundError:
        logger.warning("Settings file %s not found, using defaults", path)

    return defaults


# ---------------------------------------------------------------------------
# Backend API client
# ---------------------------------------------------------------------------
class BackendClient:
    """
    Async HTTP client for the ASN backend API.

    Attributes:
        base_url: Backend API base URL.
        client:   httpx.AsyncClient instance.
    """

    def __init__(self, base_url: str = "http://127.0.0.1:8000") -> None:
        self.base_url = base_url.rstrip("/")
        self.client = httpx.AsyncClient(base_url=self.base_url, timeout=10.0)

    async def get_nodes(self) -> list[dict]:
        """Fetch all active nodes from the backend."""
        resp = await self.client.get("/api/nodes", params={"is_active": True})
        resp.raise_for_status()
        return resp.json()

    async def get_routes(self, state: Optional[str] = None) -> list[dict]:
        """Fetch routes, optionally filtered by state."""
        params = {}
        if state:
            params["state"] = state
        resp = await self.client.get("/api/routes", params=params)
        resp.raise_for_status()
        return resp.json()

    async def update_route(self, route_id: str, data: dict) -> dict:
        """Update route state/score on the backend."""
        resp = await self.client.patch(f"/api/routes/{route_id}", json=data)
        resp.raise_for_status()
        return resp.json()

    async def post_metrics(self, data: dict) -> dict:
        """Submit metrics to the backend."""
        resp = await self.client.post("/api/metrics", json=data)
        resp.raise_for_status()
        return resp.json()

    async def close(self) -> None:
        """Close the HTTP client."""
        await self.client.aclose()


# ---------------------------------------------------------------------------
# Controller
# ---------------------------------------------------------------------------
class Controller:
    """
    Main controller orchestrating the adaptive routing loop.

    Attributes:
        settings:     Configuration dict.
        backend:      Backend API client.
        switcher:     Route switch manager.
        anti_dpi:     Anti-DPI engine.
        recovery:     Blocked route recovery.
        transport:    Transport adapter.
        singbox:      Sing-box process manager.
    """

    def __init__(self, settings: dict) -> None:
        self.settings = settings
        self.backend = BackendClient(settings["backend_url"])
        self.switcher = RouteSwitcher(
            cooldown_sec=settings["cooldown_sec"],
            score_threshold=settings["score_threshold"],
        )
        self.anti_dpi = AntiDPI()
        self.recovery = RouteRecovery(
            min_interval=settings["recovery_min_interval"],
            max_interval=settings["recovery_max_interval"],
        )
        self.transport = TransportAdapter()
        self.singbox = SingboxManager(binary=settings["singbox_binary"])
        self._running = False
        self._nodes_cache: dict[str, dict] = {}

    async def _fetch_nodes(self) -> dict[str, dict]:
        """Fetch nodes and cache them by ID."""
        nodes = await self.backend.get_nodes()
        self._nodes_cache = {n["id"]: n for n in nodes}
        return self._nodes_cache

    def _build_hops(self, route: dict) -> list[dict]:
        """Build hop list from a route dict, looking up node details."""
        hops = []
        for key in ("entry_node_id", "relay_node_id", "exit_node_id"):
            node_id = route.get(key)
            if node_id and node_id in self._nodes_cache:
                node = self._nodes_cache[node_id]
                hops.append({
                    "node_id": node_id,
                    "host": node["ip"],
                    "port": node["port"],
                })
        return hops

    async def _measure_and_score(
        self,
        routes: list[dict],
    ) -> list[ScoredRoute]:
        """Measure metrics and compute scores for all routes."""
        scored: list[ScoredRoute] = []

        for route in routes:
            hops = self._build_hops(route)
            if not hops:
                continue

            route_metrics = await measure_route(
                route_id=route["id"],
                hops=hops,
            )

            s = score_route(
                latency_ms=route_metrics.total_latency_ms,
                packet_loss_percent=route_metrics.max_packet_loss,
                throughput_mbps=route_metrics.min_throughput_mbps,
                error_count=route_metrics.total_errors,
                weights=self.settings["scoring_weights"],
            )

            # Determine state based on metrics
            if not route_metrics.is_healthy:
                state = "blocked" if route_metrics.total_errors > 0 else "degraded"
            else:
                state = "healthy"

            scored_route = ScoredRoute(
                route_id=route["id"],
                score=s,
                latency_ms=route_metrics.total_latency_ms,
                packet_loss_percent=route_metrics.max_packet_loss,
                throughput_mbps=route_metrics.min_throughput_mbps,
                error_count=route_metrics.total_errors,
                state=state,
                entry_node_id=route["entry_node_id"],
                relay_node_id=route.get("relay_node_id"),
                exit_node_id=route["exit_node_id"],
                transport=route.get("transport", "quic"),
                is_single_node=route.get("is_single_node", False),
            )
            scored.append(scored_route)

            # Update route state on backend
            try:
                await self.backend.update_route(
                    route["id"],
                    {"state": state, "score": s},
                )
            except Exception as exc:
                logger.warning("Failed to update route %s: %s", route["id"], exc)

        return scored

    async def _apply_route_switch(
        self,
        traffic_type: str,
        route: ScoredRoute,
    ) -> None:
        """Apply a route switch by generating Sing-box config."""
        # Build route config for Sing-box
        entry = self._nodes_cache.get(route.entry_node_id, {})
        relay = self._nodes_cache.get(route.relay_node_id, {}) if route.relay_node_id else None
        exit_node = self._nodes_cache.get(route.exit_node_id, {})

        singbox_route = {
            "entry": entry if entry else None,
            "relay": relay,
            "exit": exit_node if exit_node else None,
        }

        config = self.singbox.generate_config(
            route=singbox_route,
            listen_port=self.settings["listen_port"],
        )

        config_path = self.singbox.write_config(
            config, filename=f"config_{traffic_type}.json"
        )
        logger.info(
            "Route config generated for %s → %s",
            traffic_type, config_path,
        )

    async def _get_blocked_routes(self) -> list[tuple]:
        """Get blocked routes for recovery."""
        try:
            routes = await self.backend.get_routes(state="blocked")
            result = []
            for route in routes:
                hops = self._build_hops(route)
                if hops:
                    result.append((route["id"], hops))
            return result
        except Exception as exc:
            logger.warning("Failed to fetch blocked routes: %s", exc)
            return []

    async def _on_route_recovered(self, route_id: str) -> None:
        """Callback when a blocked route is recovered."""
        try:
            await self.backend.update_route(route_id, {"state": "degraded"})
            logger.info("Route %s moved to DEGRADED after recovery", route_id)
        except Exception as exc:
            logger.warning("Failed to update recovered route: %s", exc)

    async def control_loop(self) -> None:
        """
        Main control loop — runs every ``loop_interval`` seconds.

        Steps:
            1. Fetch nodes and routes from backend.
            2. Measure and score all routes.
            3. Assign best route per traffic type.
            4. Switch routes if improvements found.
            5. Apply anti-DPI jitter.
        """
        interval = self.settings["loop_interval"]
        logger.info("Control loop started (interval=%ds)", interval)

        while self._running:
            try:
                # 1. Fetch data
                await self._fetch_nodes()
                routes = await self.backend.get_routes()

                if not routes:
                    logger.warning("No routes available — waiting")
                    await asyncio.sleep(interval)
                    continue

                # 2. Measure and score
                scored = await self._measure_and_score(routes)

                if not scored:
                    logger.warning("No measurable routes")
                    await asyncio.sleep(interval)
                    continue

                # 3. Assign routes per traffic type
                assignments = assign_all_routes(scored)

                # 4. Switch if needed
                for traffic_type, best_route in assignments.items():
                    if best_route is None:
                        continue

                    if self.anti_dpi.is_switch_allowed() and \
                       self.switcher.should_switch(traffic_type, best_route):
                        event = self.switcher.switch_route(traffic_type, best_route)
                        self.anti_dpi.record_switch()
                        await self._apply_route_switch(traffic_type, best_route)

                # 5. Anti-DPI jitter
                jitter = await self.anti_dpi.apply_jitter()
                logger.debug("Applied jitter: %.1fms", jitter)

            except httpx.ConnectError:
                logger.error(
                    "❌ Cannot connect to backend at %s — retrying",
                    self.settings["backend_url"],
                )
            except Exception as exc:
                logger.exception("Error in control loop: %s", exc)

            # Wait with randomized interval
            wait = self.anti_dpi.randomize_reconnect_interval(interval)
            await asyncio.sleep(wait)

    async def run(self) -> None:
        """
        Start the controller with main loop and recovery background task.
        """
        self._running = True
        logger.info("🚀 Adaptive Stealth Network controller starting")
        logger.info("Backend: %s", self.settings["backend_url"])

        # Start recovery loop in background
        recovery_task = asyncio.create_task(
            self.recovery.recovery_loop(
                get_blocked_routes=self._get_blocked_routes,
                on_recovered=self._on_route_recovered,
            )
        )

        # Run main control loop
        try:
            await self.control_loop()
        finally:
            self._running = False
            self.recovery.stop()
            recovery_task.cancel()
            try:
                await recovery_task
            except asyncio.CancelledError:
                pass
            self.singbox.stop()
            await self.backend.close()
            logger.info("🛑 Controller shut down")

    def stop(self) -> None:
        """Signal the controller to stop."""
        self._running = False


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    """CLI entry point for the controller."""
    settings = load_settings()
    ctrl = Controller(settings)

    # Handle graceful shutdown
    def _signal_handler(sig, frame):
        logger.info("Received signal %s — shutting down", sig)
        ctrl.stop()

    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    asyncio.run(ctrl.run())


if __name__ == "__main__":
    main()
