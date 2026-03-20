"""
REST API endpoints for the Adaptive Stealth Network backend.

Provides CRUD operations for:
    - **Nodes** — network servers.
    - **Routes** — traffic paths through the network.
    - **Metrics** — performance measurements.
    - **Health** — service health check.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from itertools import product
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.models import (
    MetricRecord,
    Node,
    NodeRole,
    NodeType,
    Route,
    RouteState,
    TransportType,
)
from backend.schemas import (
    HealthResponse,
    MetricsCreate,
    MetricsResponse,
    NodeCreate,
    NodeResponse,
    NodeUpdate,
    RouteGenerateRequest,
    RouteResponse,
    RouteUpdate,
)

router = APIRouter(prefix="/api", tags=["api"])


# ====================================================================
# Nodes
# ====================================================================

@router.get("/nodes", response_model=List[NodeResponse])
async def list_nodes(
    node_type: Optional[str] = Query(None, description="Filter by type: entry/relay/exit"),
    role: Optional[str] = Query(None, description="Filter by role: master/slave"),
    is_active: Optional[bool] = Query(None, description="Filter by active status"),
    db: AsyncSession = Depends(get_db),
) -> list:
    """
    List all registered nodes with optional filters.

    Returns:
        List of nodes matching the filter criteria.
    """
    stmt = select(Node)
    if node_type:
        stmt = stmt.where(Node.node_type == NodeType(node_type.lower()))
    if role:
        stmt = stmt.where(Node.role == NodeRole(role.lower()))
    if is_active is not None:
        stmt = stmt.where(Node.is_active == is_active)

    result = await db.execute(stmt)
    return result.scalars().all()


@router.post("/nodes", response_model=NodeResponse, status_code=201)
async def create_node(
    body: NodeCreate,
    db: AsyncSession = Depends(get_db),
) -> Node:
    """
    Register a new node in the network.

    The node is assigned a unique UUID and stored in the database.
    By default new nodes have ``role=slave``.

    Args:
        body: Node creation payload.

    Returns:
        The newly created node.
    """
    node = Node(
        id=str(uuid.uuid4()),
        name=body.name,
        ip=body.ip,
        port=body.port,
        node_type=NodeType(body.node_type),
        role=NodeRole(body.role),
        location=body.location,
        bandwidth_mbps=body.bandwidth_mbps,
        cpu_score=body.cpu_score,
        allow_streaming=body.allow_streaming,
        allow_gaming=body.allow_gaming,
        allow_browsing=body.allow_browsing,
        allow_relay=body.allow_relay,
        max_connections=body.max_connections,
        transport=TransportType(body.transport),
        protocol=body.protocol,
        tls_enabled=body.tls_enabled,
    )
    db.add(node)
    await db.flush()
    await db.refresh(node)
    return node


@router.get("/nodes/{node_id}", response_model=NodeResponse)
async def get_node(
    node_id: str,
    db: AsyncSession = Depends(get_db),
) -> Node:
    """
    Retrieve a single node by its ID.

    Args:
        node_id: UUID of the node.

    Raises:
        HTTPException: 404 if not found.
    """
    result = await db.execute(select(Node).where(Node.id == node_id))
    node = result.scalar_one_or_none()
    if node is None:
        raise HTTPException(status_code=404, detail="Node not found")
    return node


@router.patch("/nodes/{node_id}", response_model=NodeResponse)
async def update_node(
    node_id: str,
    body: NodeUpdate,
    db: AsyncSession = Depends(get_db),
) -> Node:
    """
    Partially update a node's attributes.

    Only provided fields are updated; others remain unchanged.

    Args:
        node_id: UUID of the node.
        body:    Fields to update.

    Raises:
        HTTPException: 404 if not found.
    """
    result = await db.execute(select(Node).where(Node.id == node_id))
    node = result.scalar_one_or_none()
    if node is None:
        raise HTTPException(status_code=404, detail="Node not found")

    update_data = body.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        if field == "node_type" and value:
            value = NodeType(value.lower())
        elif field == "transport" and value:
            value = TransportType(value.lower())
        setattr(node, field, value)

    node.updated_at = datetime.now(timezone.utc)
    await db.flush()
    await db.refresh(node)
    return node


@router.delete("/nodes/{node_id}", status_code=204)
async def delete_node(
    node_id: str,
    db: AsyncSession = Depends(get_db),
) -> None:
    """
    Delete a node from the network.

    Also removes all routes and metrics associated with this node.

    Args:
        node_id: UUID of the node.

    Raises:
        HTTPException: 404 if not found.
    """
    result = await db.execute(select(Node).where(Node.id == node_id))
    node = result.scalar_one_or_none()
    if node is None:
        raise HTTPException(status_code=404, detail="Node not found")

    await db.delete(node)
    await db.flush()


# ====================================================================
# Routes
# ====================================================================

@router.get("/routes", response_model=List[RouteResponse])
async def list_routes(
    state: Optional[str] = Query(None, description="Filter by state"),
    db: AsyncSession = Depends(get_db),
) -> list:
    """
    List all generated routes with optional state filter.

    Returns:
        List of routes.
    """
    stmt = select(Route)
    if state:
        stmt = stmt.where(Route.state == RouteState(state.lower()))
    result = await db.execute(stmt)
    return result.scalars().all()


@router.post("/routes/generate", response_model=List[RouteResponse], status_code=201)
async def generate_routes(
    body: RouteGenerateRequest = RouteGenerateRequest(),
    db: AsyncSession = Depends(get_db),
) -> list:
    """
    Generate routes from the current node pool.

    Algorithm:
        1. If only one active node exists → create a SingleNode route.
        2. Otherwise → generate Entry × Relay(optional) × Exit combinations.
        3. Limit to ``max_routes`` best combinations.

    Args:
        body: Generation parameters (max_routes).

    Returns:
        List of newly created routes.
    """
    # Fetch active nodes grouped by type
    result = await db.execute(select(Node).where(Node.is_active == True))  # noqa: E712
    nodes = result.scalars().all()

    if not nodes:
        raise HTTPException(status_code=400, detail="No active nodes available")

    entries = [n for n in nodes if n.node_type == NodeType.ENTRY]
    relays = [n for n in nodes if n.node_type == NodeType.RELAY and n.allow_relay]
    exits = [n for n in nodes if n.node_type == NodeType.EXIT]

    routes: list[Route] = []

    # SingleNode mode: if only one node, use it for all hops
    if len(nodes) == 1:
        node = nodes[0]
        route = Route(
            id=str(uuid.uuid4()),
            entry_node_id=node.id,
            relay_node_id=None,
            exit_node_id=node.id,
            is_single_node=True,
            transport=node.transport,
        )
        db.add(route)
        routes.append(route)
    else:
        # If no explicit entries/exits, any node can serve
        if not entries:
            entries = nodes
        if not exits:
            exits = nodes

        # Generate direct routes (Entry → Exit)
        for entry, exit_node in product(entries, exits):
            if entry.id == exit_node.id:
                continue
            route = Route(
                id=str(uuid.uuid4()),
                entry_node_id=entry.id,
                relay_node_id=None,
                exit_node_id=exit_node.id,
                is_single_node=False,
                transport=entry.transport,
            )
            db.add(route)
            routes.append(route)

        # Generate relay routes (Entry → Relay → Exit)
        for entry, relay, exit_node in product(entries, relays, exits):
            if len({entry.id, relay.id, exit_node.id}) < 3:
                continue
            route = Route(
                id=str(uuid.uuid4()),
                entry_node_id=entry.id,
                relay_node_id=relay.id,
                exit_node_id=exit_node.id,
                is_single_node=False,
                transport=entry.transport,
            )
            db.add(route)
            routes.append(route)

    # Limit
    routes = list(routes[: body.max_routes])
    await db.flush()

    # Refresh all routes
    for r in routes:
        await db.refresh(r)

    return routes


@router.patch("/routes/{route_id}", response_model=RouteResponse)
async def update_route(
    route_id: str,
    body: RouteUpdate,
    db: AsyncSession = Depends(get_db),
) -> Route:
    """
    Update a route's state, transport, or score.

    Args:
        route_id: UUID of the route.
        body:     Fields to update.

    Raises:
        HTTPException: 404 if not found.
    """
    result = await db.execute(select(Route).where(Route.id == route_id))
    route = result.scalar_one_or_none()
    if route is None:
        raise HTTPException(status_code=404, detail="Route not found")

    if body.state is not None:
        route.state = RouteState(body.state)
    if body.transport is not None:
        route.transport = TransportType(body.transport)
    if body.score is not None:
        route.score = body.score

    await db.flush()
    await db.refresh(route)
    return route


# ====================================================================
# Metrics
# ====================================================================

@router.get("/metrics", response_model=List[MetricsResponse])
async def list_metrics(
    node_id: Optional[str] = Query(None),
    route_id: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
) -> list:
    """
    List metric records with optional node/route filters.

    Args:
        node_id:  Filter by node.
        route_id: Filter by route.
        limit:    Maximum records to return.

    Returns:
        List of metric records ordered by timestamp descending.
    """
    stmt = select(MetricRecord).order_by(MetricRecord.recorded_at.desc()).limit(limit)
    if node_id:
        stmt = stmt.where(MetricRecord.node_id == node_id)
    if route_id:
        stmt = stmt.where(MetricRecord.route_id == route_id)

    result = await db.execute(stmt)
    return result.scalars().all()


@router.post("/metrics", response_model=MetricsResponse, status_code=201)
async def create_metric(
    body: MetricsCreate,
    db: AsyncSession = Depends(get_db),
) -> MetricRecord:
    """
    Submit a new metric measurement.

    Args:
        body: Metric data.

    Returns:
        The stored metric record.
    """
    record = MetricRecord(
        node_id=body.node_id,
        route_id=body.route_id,
        latency_ms=body.latency_ms,
        packet_loss_percent=body.packet_loss_percent,
        throughput_mbps=body.throughput_mbps,
        error_count=body.error_count,
        uptime_seconds=body.uptime_seconds,
    )
    db.add(record)
    await db.flush()
    await db.refresh(record)
    return record


# ====================================================================
# Health
# ====================================================================

@router.get("/health", response_model=HealthResponse)
async def health_check(db: AsyncSession = Depends(get_db)) -> dict:
    """
    Check service health and basic stats.

    Returns:
        Status, version, and counts of nodes/routes.
    """
    nodes_count = (await db.execute(select(func.count(Node.id)))).scalar() or 0
    routes_count = (await db.execute(select(func.count(Route.id)))).scalar() or 0

    return {
        "status": "ok",
        "version": "1.0.0",
        "nodes_count": nodes_count,
        "routes_count": routes_count,
    }
