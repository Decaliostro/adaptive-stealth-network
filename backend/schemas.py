"""
Pydantic schemas for request/response validation.

Provides type-safe API contracts with automatic OpenAPI
documentation generation via FastAPI.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator


# ====================================================================
# Node schemas
# ====================================================================

class NodeCreate(BaseModel):
    """Schema for creating a new node (POST /api/nodes)."""

    name: str = Field(..., min_length=1, max_length=128, description="Human-readable node name")
    ip: str = Field(..., min_length=1, description="IP address or hostname")
    port: int = Field(443, ge=1, le=65535, description="Listening port")
    node_type: str = Field(..., description="Node type: entry, relay, or exit")
    role: str = Field("slave", description="Node role: master or slave")
    location: Optional[str] = Field(None, max_length=8, description="Country/region code")
    bandwidth_mbps: float = Field(100.0, ge=0, description="Available bandwidth in Mbps")
    cpu_score: float = Field(50.0, ge=0, le=100, description="Relative CPU score 0-100")
    allow_streaming: bool = Field(True, description="Allow streaming traffic")
    allow_gaming: bool = Field(True, description="Allow gaming traffic")
    allow_browsing: bool = Field(True, description="Allow browsing traffic")
    allow_relay: bool = Field(False, description="Allow usage as relay by others")
    max_connections: int = Field(100, ge=1, description="Max connections when used as relay")
    transport: str = Field("quic", description="Transport protocol: quic or tcp")
    protocol: str = Field("vless", description="Proxy protocol: vless, shadowsocks, etc.")
    tls_enabled: bool = Field(True, description="Whether TLS is enabled")

    @field_validator("node_type")
    @classmethod
    def validate_node_type(cls, v: str) -> str:
        """Ensure node_type is one of the allowed values."""
        allowed = {"entry", "relay", "exit"}
        if v.lower() not in allowed:
            raise ValueError(f"node_type must be one of {allowed}")
        return v.lower()

    @field_validator("role")
    @classmethod
    def validate_role(cls, v: str) -> str:
        """Ensure role is master or slave."""
        allowed = {"master", "slave"}
        if v.lower() not in allowed:
            raise ValueError(f"role must be one of {allowed}")
        return v.lower()

    @field_validator("transport")
    @classmethod
    def validate_transport(cls, v: str) -> str:
        """Ensure transport is quic or tcp."""
        allowed = {"quic", "tcp"}
        if v.lower() not in allowed:
            raise ValueError(f"transport must be one of {allowed}")
        return v.lower()


class NodeUpdate(BaseModel):
    """Schema for partially updating a node (PATCH /api/nodes/{id})."""

    name: Optional[str] = None
    ip: Optional[str] = None
    port: Optional[int] = Field(None, ge=1, le=65535)
    node_type: Optional[str] = None
    location: Optional[str] = None
    bandwidth_mbps: Optional[float] = Field(None, ge=0)
    cpu_score: Optional[float] = Field(None, ge=0, le=100)
    allow_streaming: Optional[bool] = None
    allow_gaming: Optional[bool] = None
    allow_browsing: Optional[bool] = None
    allow_relay: Optional[bool] = None
    max_connections: Optional[int] = Field(None, ge=1)
    transport: Optional[str] = None
    is_active: Optional[bool] = None


class NodeResponse(BaseModel):
    """Schema for node responses."""

    id: str
    name: str
    ip: str
    port: int
    node_type: str
    role: str
    location: Optional[str]
    bandwidth_mbps: float
    cpu_score: float
    allow_streaming: bool
    allow_gaming: bool
    allow_browsing: bool
    allow_relay: bool
    max_connections: int
    transport: str
    protocol: str
    tls_enabled: bool
    is_active: bool
    created_at: datetime
    updated_at: Optional[datetime]

    model_config = {"from_attributes": True}


# ====================================================================
# Route schemas
# ====================================================================

class RouteGenerateRequest(BaseModel):
    """Schema for requesting route generation."""

    max_routes: int = Field(10, ge=1, le=100, description="Maximum number of routes to generate")


class RouteUpdate(BaseModel):
    """Schema for updating route state (PATCH /api/routes/{id})."""

    state: Optional[str] = Field(None, description="Route state: healthy, degraded, blocked")
    transport: Optional[str] = Field(None, description="Transport: quic or tcp")
    score: Optional[float] = None

    @field_validator("state")
    @classmethod
    def validate_state(cls, v: Optional[str]) -> Optional[str]:
        """Ensure state is valid."""
        if v is None:
            return v
        allowed = {"healthy", "degraded", "blocked"}
        if v.lower() not in allowed:
            raise ValueError(f"state must be one of {allowed}")
        return v.lower()


class RouteResponse(BaseModel):
    """Schema for route responses."""

    id: str
    entry_node_id: str
    relay_node_id: Optional[str]
    exit_node_id: str
    state: str
    transport: str
    is_single_node: bool
    score: Optional[float]
    cooldown_until: Optional[datetime]
    created_at: datetime

    model_config = {"from_attributes": True}


# ====================================================================
# Metrics schemas
# ====================================================================

class MetricsCreate(BaseModel):
    """Schema for submitting metric measurements."""

    node_id: Optional[str] = Field(None, description="Target node ID")
    route_id: Optional[str] = Field(None, description="Target route ID")
    latency_ms: float = Field(0.0, ge=0, description="Latency in milliseconds")
    packet_loss_percent: float = Field(0.0, ge=0, le=100, description="Packet loss %")
    throughput_mbps: float = Field(0.0, ge=0, description="Throughput in Mbps")
    error_count: int = Field(0, ge=0, description="Error count")
    uptime_seconds: float = Field(0.0, ge=0, description="Uptime in seconds")


class MetricsResponse(BaseModel):
    """Schema for metrics responses."""

    id: int
    node_id: Optional[str]
    route_id: Optional[str]
    latency_ms: float
    packet_loss_percent: float
    throughput_mbps: float
    error_count: int
    uptime_seconds: float
    recorded_at: datetime

    model_config = {"from_attributes": True}


# ====================================================================
# Health check
# ====================================================================

class HealthResponse(BaseModel):
    """Schema for health check endpoint."""

    status: str = "ok"
    version: str = "1.0.0"
    nodes_count: int = 0
    routes_count: int = 0
