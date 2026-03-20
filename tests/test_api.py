"""
Tests for the backend REST API endpoints.
"""

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from backend.app import app
from backend.database import engine, init_db, Base


@pytest_asyncio.fixture(autouse=True)
async def setup_db():
    """Create fresh tables for each test."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def client():
    """Async test client for the FastAPI app."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.mark.asyncio
async def test_root(client: AsyncClient):
    """Root endpoint should return app info."""
    resp = await client.get("/")
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "Adaptive Stealth Network"


@pytest.mark.asyncio
async def test_health(client: AsyncClient):
    """Health endpoint should return ok status."""
    resp = await client.get("/api/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"


@pytest.mark.asyncio
async def test_create_node(client: AsyncClient):
    """POST /api/nodes should create a node and return 201."""
    payload = {
        "name": "Test Entry Node",
        "ip": "10.0.0.1",
        "port": 443,
        "node_type": "entry",
        "role": "slave",
        "location": "DE",
        "bandwidth_mbps": 100.0,
        "cpu_score": 70.0,
    }
    resp = await client.post("/api/nodes", json=payload)
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "Test Entry Node"
    assert data["node_type"] == "entry"
    assert data["is_active"] is True


@pytest.mark.asyncio
async def test_list_nodes(client: AsyncClient):
    """GET /api/nodes should return created nodes."""
    # Create a node first
    await client.post("/api/nodes", json={
        "name": "Node1", "ip": "10.0.0.1", "port": 443,
        "node_type": "entry", "role": "slave",
    })
    resp = await client.get("/api/nodes")
    assert resp.status_code == 200
    nodes = resp.json()
    assert len(nodes) >= 1


@pytest.mark.asyncio
async def test_get_node(client: AsyncClient):
    """GET /api/nodes/{id} should return the specific node."""
    create_resp = await client.post("/api/nodes", json={
        "name": "GetMe", "ip": "10.0.0.2", "port": 443,
        "node_type": "relay", "role": "slave",
    })
    node_id = create_resp.json()["id"]

    resp = await client.get(f"/api/nodes/{node_id}")
    assert resp.status_code == 200
    assert resp.json()["name"] == "GetMe"


@pytest.mark.asyncio
async def test_get_node_not_found(client: AsyncClient):
    """GET /api/nodes/{id} with bad ID should return 404."""
    resp = await client.get("/api/nodes/nonexistent-id")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_update_node(client: AsyncClient):
    """PATCH /api/nodes/{id} should update fields."""
    create_resp = await client.post("/api/nodes", json={
        "name": "UpdateMe", "ip": "10.0.0.3", "port": 443,
        "node_type": "exit", "role": "slave",
    })
    node_id = create_resp.json()["id"]

    resp = await client.patch(f"/api/nodes/{node_id}", json={"name": "Updated"})
    assert resp.status_code == 200
    assert resp.json()["name"] == "Updated"


@pytest.mark.asyncio
async def test_delete_node(client: AsyncClient):
    """DELETE /api/nodes/{id} should remove the node."""
    create_resp = await client.post("/api/nodes", json={
        "name": "DeleteMe", "ip": "10.0.0.4", "port": 443,
        "node_type": "entry", "role": "slave",
    })
    node_id = create_resp.json()["id"]

    resp = await client.delete(f"/api/nodes/{node_id}")
    assert resp.status_code == 204

    # Verify it's gone
    resp = await client.get(f"/api/nodes/{node_id}")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_generate_routes(client: AsyncClient):
    """POST /api/routes/generate should create routes from nodes."""
    # Create entry and exit nodes
    await client.post("/api/nodes", json={
        "name": "Entry", "ip": "10.0.0.1", "port": 443,
        "node_type": "entry", "role": "slave",
    })
    await client.post("/api/nodes", json={
        "name": "Exit", "ip": "10.0.0.2", "port": 443,
        "node_type": "exit", "role": "slave",
    })

    resp = await client.post("/api/routes/generate", json={"max_routes": 10})
    assert resp.status_code == 201
    routes = resp.json()
    assert len(routes) >= 1


@pytest.mark.asyncio
async def test_create_metric(client: AsyncClient):
    """POST /api/metrics should store a metric record."""
    # Create a node first
    node_resp = await client.post("/api/nodes", json={
        "name": "MetricNode", "ip": "10.0.0.5", "port": 443,
        "node_type": "entry", "role": "slave",
    })
    node_id = node_resp.json()["id"]

    resp = await client.post("/api/metrics", json={
        "node_id": node_id,
        "latency_ms": 45.5,
        "packet_loss_percent": 1.2,
        "throughput_mbps": 85.0,
        "error_count": 0,
    })
    assert resp.status_code == 201
    data = resp.json()
    assert data["latency_ms"] == 45.5
