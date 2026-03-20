"""
ORM models for the Adaptive Stealth Network.

Defines three core entities:
    - **Node**  — a network server (Entry / Relay / Exit).
    - **Route** — a chain of nodes forming a traffic path.
    - **MetricRecord** — a timestamped measurement for a node or route.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import relationship

from backend.database import Base


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class NodeType(str, enum.Enum):
    """Functional role of a node inside a route chain."""
    ENTRY = "entry"
    RELAY = "relay"
    EXIT = "exit"


class NodeRole(str, enum.Enum):
    """Operational role within the Master/Slave architecture."""
    MASTER = "master"
    SLAVE = "slave"


class RouteState(str, enum.Enum):
    """Current health state of a route."""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    BLOCKED = "blocked"


class TransportType(str, enum.Enum):
    """Transport protocol used by a route or node."""
    QUIC = "quic"
    TCP = "tcp"


# ---------------------------------------------------------------------------
# Node
# ---------------------------------------------------------------------------

class Node(Base):
    """
    Represents a single network node (server).

    Attributes:
        id:             Unique identifier (UUID string).
        name:           Human-readable name.
        ip:             IP address or hostname.
        port:           Listening port.
        node_type:      Entry / Relay / Exit.
        role:           Master / Slave.
        location:       Country or region code (e.g. ``"DE"``).
        bandwidth_mbps: Available bandwidth in Mbps.
        cpu_score:      Relative CPU performance score (0–100).
        allow_streaming: Whether the node may carry streaming traffic.
        allow_gaming:    Whether the node may carry gaming traffic.
        allow_browsing:  Whether the node may carry browsing traffic.
        allow_relay:    Whether others may use this node as a relay.
        max_connections: Connection limit when used as relay.
        transport:      Preferred transport (QUIC / TCP).
        is_active:      Operational status flag.
        created_at:     Timestamp of creation.
        updated_at:     Timestamp of last update.
    """

    __tablename__ = "nodes"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String(128), nullable=False)
    ip = Column(String(256), nullable=False)
    port = Column(Integer, nullable=False, default=443)
    node_type = Column(Enum(NodeType), nullable=False)
    role = Column(Enum(NodeRole), nullable=False, default=NodeRole.SLAVE)
    location = Column(String(8), nullable=True)
    bandwidth_mbps = Column(Float, nullable=False, default=100.0)
    cpu_score = Column(Float, nullable=False, default=50.0)

    # Allowed traffic types
    allow_streaming = Column(Boolean, default=True)
    allow_gaming = Column(Boolean, default=True)
    allow_browsing = Column(Boolean, default=True)

    # Relay settings
    allow_relay = Column(Boolean, default=False)
    max_connections = Column(Integer, default=100)

    # Transport & protocol
    transport = Column(Enum(TransportType), default=TransportType.QUIC)
    protocol = Column(String(32), default="vless")  # vless, shadowsocks, etc.
    tls_enabled = Column(Boolean, default=True)

    # Status
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    # Relationships
    metrics = relationship("MetricRecord", back_populates="node", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return (
            f"<Node(id={self.id!r}, name={self.name!r}, "
            f"type={self.node_type.value}, role={self.role.value})>"
        )


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------

class Route(Base):
    """
    A traffic path composed of up to three nodes:
    Entry → (optional) Relay → Exit.

    Attributes:
        id:              Unique identifier.
        entry_node_id:   FK to the Entry node.
        relay_node_id:   FK to the Relay node (nullable for SingleNode).
        exit_node_id:    FK to the Exit node.
        state:           Current health state.
        transport:       Active transport protocol.
        is_single_node:  True when all hops use the same server.
        score:           Cached composite score (lower = better).
        cooldown_until:  Prevents re-switching before this timestamp.
        created_at:      Timestamp of creation.
    """

    __tablename__ = "routes"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    entry_node_id = Column(String(36), ForeignKey("nodes.id"), nullable=False)
    relay_node_id = Column(String(36), ForeignKey("nodes.id"), nullable=True)
    exit_node_id = Column(String(36), ForeignKey("nodes.id"), nullable=False)
    state = Column(Enum(RouteState), default=RouteState.HEALTHY)
    transport = Column(Enum(TransportType), default=TransportType.QUIC)
    is_single_node = Column(Boolean, default=False)
    score = Column(Float, nullable=True)
    cooldown_until = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    # Relationships
    entry_node = relationship("Node", foreign_keys=[entry_node_id])
    relay_node = relationship("Node", foreign_keys=[relay_node_id])
    exit_node = relationship("Node", foreign_keys=[exit_node_id])
    metrics = relationship("MetricRecord", back_populates="route", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        relay = self.relay_node_id or "direct"
        return (
            f"<Route(id={self.id!r}, "
            f"{self.entry_node_id} → {relay} → {self.exit_node_id}, "
            f"state={self.state.value})>"
        )


# ---------------------------------------------------------------------------
# ClientUser
# ---------------------------------------------------------------------------

class ClientUser(Base):
    """
    Represents a VPN client subscription.

    Attributes:
        id:               Internal Unique identifier.
        username:         Display name.
        client_uuid:      UUID for VLESS/Reality authentication and sub URL.
        data_limit_gb:    Traffic limit in GB (None = unlimited).
        data_used_bytes:  Bytes used so far.
        speed_limit_mbps: Bandwidth limit in Mbps (None = unlimited).
        is_active:        Active block status.
        expire_at:        Subscription expiration date.
        created_at:       Timestamp of creation.
    """

    __tablename__ = "users"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    username = Column(String(128), unique=True, nullable=False)
    client_uuid = Column(String(36), default=lambda: str(uuid.uuid4()))
    data_limit_gb = Column(Float, nullable=True)
    data_used_bytes = Column(Float, default=0.0)
    speed_limit_mbps = Column(Float, nullable=True)
    is_active = Column(Boolean, default=True)
    expire_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    def __repr__(self) -> str:
        return f"<ClientUser(username={self.username!r}, active={self.is_active})>"


# ---------------------------------------------------------------------------
# MetricRecord
# ---------------------------------------------------------------------------

class MetricRecord(Base):
    """
    A single point-in-time measurement for a node or route.

    Attributes:
        id:                  Auto-incremented primary key.
        node_id:             FK to the measured node (nullable).
        route_id:            FK to the measured route (nullable).
        latency_ms:          Round-trip latency in milliseconds.
        packet_loss_percent: Packet loss as a percentage (0–100).
        throughput_mbps:     Measured throughput in Mbps.
        error_count:         Number of errors since last measurement.
        uptime_seconds:      Uptime of the node in seconds.
        recorded_at:         Timestamp of this measurement.
    """

    __tablename__ = "metrics"

    id = Column(Integer, primary_key=True, autoincrement=True)
    node_id = Column(String(36), ForeignKey("nodes.id"), nullable=True)
    route_id = Column(String(36), ForeignKey("routes.id"), nullable=True)
    latency_ms = Column(Float, default=0.0)
    packet_loss_percent = Column(Float, default=0.0)
    throughput_mbps = Column(Float, default=0.0)
    error_count = Column(Integer, default=0)
    uptime_seconds = Column(Float, default=0.0)
    recorded_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    # Relationships
    node = relationship("Node", back_populates="metrics")
    route = relationship("Route", back_populates="metrics")

    def __repr__(self) -> str:
        target = self.node_id or self.route_id
        return (
            f"<MetricRecord(id={self.id}, target={target!r}, "
            f"latency={self.latency_ms}ms, loss={self.packet_loss_percent}%)>"
        )
