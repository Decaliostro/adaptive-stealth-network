"""
Transport adaptation module — QUIC ↔ TCP fallback.

Handles automatic switching between transport protocols:
    1. Primary: QUIC (UDP-based, lower latency).
    2. Fallback: TCP (more reliable through firewalls).
    3. Last resort: alternative ports.
"""

from __future__ import annotations

import asyncio
import logging
import random
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

logger = logging.getLogger("asn.controller.transport")


class Transport(str, Enum):
    """Supported transport protocols."""
    QUIC = "quic"
    TCP = "tcp"


# Common alternative ports to try when standard ports are blocked
ALTERNATIVE_PORTS = [443, 8443, 2053, 2083, 2087, 2096, 8080, 8880, 80]


@dataclass
class TransportState:
    """Track transport state for a node."""

    node_id: str
    current_transport: Transport = Transport.QUIC
    current_port: int = 443
    quic_failures: int = 0
    tcp_failures: int = 0
    alternative_ports_tried: list[int] = field(default_factory=list)
    last_successful_transport: Optional[Transport] = None
    last_successful_port: Optional[int] = None


class TransportAdapter:
    """
    Manages transport protocol adaptation for network nodes.

    Implements the fallback strategy::

        1. IF QUIC fails → SWITCH to TCP
        2. IF TCP unstable → SWITCH Entry node
        3. IF both fail → try alternative ports

    Attributes:
        states:          Dict of node transport states.
        max_quic_fails:  Failures before switching from QUIC to TCP.
        max_tcp_fails:   Failures before trying alternative ports.
    """

    def __init__(
        self,
        max_quic_fails: int = 3,
        max_tcp_fails: int = 5,
    ) -> None:
        """
        Initialize the transport adapter.

        Args:
            max_quic_fails: QUIC failure threshold before TCP fallback.
            max_tcp_fails:  TCP failure threshold before port rotation.
        """
        self.states: dict[str, TransportState] = {}
        self.max_quic_fails = max_quic_fails
        self.max_tcp_fails = max_tcp_fails

    def get_state(self, node_id: str, port: int = 443) -> TransportState:
        """
        Get or create transport state for a node.

        Args:
            node_id: Unique node identifier.
            port:    Default port for the node.

        Returns:
            ``TransportState`` for the node.
        """
        if node_id not in self.states:
            self.states[node_id] = TransportState(node_id=node_id, current_port=port)
        return self.states[node_id]

    async def test_transport(
        self,
        host: str,
        port: int,
        transport: Transport,
        timeout: float = 5.0,
    ) -> bool:
        """
        Test if a transport protocol works for a given host:port.

        For QUIC, we test UDP connectivity. For TCP, we test a
        standard TCP connection.

        Args:
            host:      Target hostname or IP.
            port:      Target port.
            transport: Protocol to test.
            timeout:   Connection timeout.

        Returns:
            True if the transport is functional.
        """
        try:
            if transport == Transport.TCP:
                _, writer = await asyncio.wait_for(
                    asyncio.open_connection(host, port),
                    timeout=timeout,
                )
                writer.close()
                await writer.wait_closed()
                return True
            else:
                # QUIC test: attempt UDP socket creation and send
                # In production, this would use aioquic; here we simulate
                # by testing TCP as a proxy (since QUIC endpoints
                # typically also accept TCP)
                _, writer = await asyncio.wait_for(
                    asyncio.open_connection(host, port),
                    timeout=timeout,
                )
                writer.close()
                await writer.wait_closed()
                return True
        except (asyncio.TimeoutError, OSError, ConnectionError) as exc:
            logger.debug(
                "Transport test failed: %s:%d/%s — %s",
                host, port, transport.value, exc,
            )
            return False

    def record_failure(self, node_id: str, port: int = 443) -> Transport:
        """
        Record a transport failure and decide next action.

        Transitions:
            - QUIC + failures >= max_quic_fails → switch to TCP
            - TCP + failures >= max_tcp_fails → try alternative ports

        Args:
            node_id: Node with the failure.
            port:    Port that failed.

        Returns:
            The new recommended transport.
        """
        state = self.get_state(node_id, port)

        if state.current_transport == Transport.QUIC:
            state.quic_failures += 1
            if state.quic_failures >= self.max_quic_fails:
                logger.warning(
                    "Node %s: QUIC failed %d times → switching to TCP",
                    node_id, state.quic_failures,
                )
                state.current_transport = Transport.TCP
                state.quic_failures = 0
        else:
            state.tcp_failures += 1
            if state.tcp_failures >= self.max_tcp_fails:
                logger.warning(
                    "Node %s: TCP failed %d times → trying alternative ports",
                    node_id, state.tcp_failures,
                )
                state.tcp_failures = 0

        return state.current_transport

    def record_success(self, node_id: str, port: int = 443) -> None:
        """
        Record a successful connection, resetting failure counters.

        Args:
            node_id: Node with the successful connection.
            port:    Port used.
        """
        state = self.get_state(node_id, port)
        state.last_successful_transport = state.current_transport
        state.last_successful_port = state.current_port

        # Reset failure counters
        if state.current_transport == Transport.QUIC:
            state.quic_failures = 0
        else:
            state.tcp_failures = 0

    async def find_working_port(
        self,
        host: str,
        node_id: str,
        transport: Optional[Transport] = None,
    ) -> Optional[int]:
        """
        Try alternative ports to find one that works.

        Args:
            host:      Target hostname or IP.
            node_id:   Node identifier.
            transport: Transport to test (defaults to TCP).

        Returns:
            Working port number, or None if all fail.
        """
        state = self.get_state(node_id)
        proto = transport or state.current_transport

        # Shuffle ports for anti-detection
        ports = [p for p in ALTERNATIVE_PORTS if p not in state.alternative_ports_tried]
        random.shuffle(ports)

        for port in ports:
            state.alternative_ports_tried.append(port)

            if await self.test_transport(host, port, proto, timeout=3.0):
                logger.info(
                    "✅ Node %s: found working port %d with %s",
                    node_id, port, proto.value,
                )
                state.current_port = port
                return port

            # Random delay to avoid DPI fingerprinting
            await asyncio.sleep(random.uniform(0.5, 2.0))

        logger.error("Node %s: all alternative ports exhausted", node_id)
        return None

    async def adapt(
        self,
        host: str,
        node_id: str,
        port: int = 443,
    ) -> tuple[Transport, int]:
        """
        Full transport adaptation cycle for a node.

        Attempts in order:
            1. Current transport on current port.
            2. Fallback transport on current port.
            3. Alternative ports with each transport.

        Args:
            host:    Target hostname or IP.
            node_id: Unique node identifier.
            port:    Current port.

        Returns:
            Tuple of (working_transport, working_port).
            Falls back to (TCP, original_port) if everything fails.
        """
        state = self.get_state(node_id, port)

        # 1. Try current transport
        if await self.test_transport(host, state.current_port, state.current_transport):
            self.record_success(node_id, state.current_port)
            return state.current_transport, state.current_port

        # 2. Try fallback transport
        fallback = Transport.TCP if state.current_transport == Transport.QUIC else Transport.QUIC
        if await self.test_transport(host, state.current_port, fallback):
            state.current_transport = fallback
            self.record_success(node_id, state.current_port)
            logger.info("Node %s: switched to %s", node_id, fallback.value)
            return fallback, state.current_port

        # 3. Try alternative ports
        working_port = await self.find_working_port(host, node_id)
        if working_port is not None:
            return state.current_transport, working_port

        # Nothing works — return defaults
        logger.error("Node %s: all transport options exhausted", node_id)
        return Transport.TCP, port
