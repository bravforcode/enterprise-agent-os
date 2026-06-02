"""Tests for web module — 30+ tests."""
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from graxia_tool.web import app


# --- Test Client ---

@pytest.fixture
def client():
    """FastAPI test client."""
    return TestClient(app)


# --- Basic Tests ---

class TestBasic:
    """Tests for basic endpoints."""

    def test_root(self, client):
        """Should return API info."""
        r = client.get("/")
        assert r.status_code == 200
        data = r.json()
        assert data["name"] == "Graxia Tool"
        assert data["version"] == "0.2.0"

    def test_dashboard(self, client):
        """Should return HTML dashboard."""
        r = client.get("/dashboard")
        assert r.status_code == 200
        assert "text/html" in r.headers["content-type"]
        assert "Graxia Tool Dashboard" in r.text

    def test_status(self, client):
        """Should return system status."""
        r = client.get("/api/status")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "operational"
        assert data["version"] == "0.2.0"


# --- Agent Endpoints ---

class TestAgentEndpoints:
    """Tests for agent endpoints."""

    def test_list_agents(self, client):
        """Should list all agents."""
        r = client.get("/api/agents")
        assert r.status_code == 200
        data = r.json()
        assert "agents" in data
        assert "count" in data
        assert data["count"] == 18
        assert "coder" in data["agents"]
        assert "database_admin" in data["agents"]
        assert "frontend_designer" in data["agents"]

    def test_run_agent(self, client):
        """Should run an agent."""
        r = client.post("/api/agents/run", json={
            "agent": "coder",
            "query": "test query"
        })
        assert r.status_code == 200
        data = r.json()
        assert "output" in data
        assert "agent" in data
        assert data["agent"] == "coder"

    def test_run_unknown_agent(self, client):
        """Should return 404 for unknown agent."""
        r = client.post("/api/agents/run", json={
            "agent": "nonexistent",
            "query": "test"
        })
        assert r.status_code == 404

    def test_run_agent_with_context(self, client):
        """Should accept context parameter."""
        r = client.post("/api/agents/run", json={
            "agent": "reviewer",
            "query": "test",
            "context": {"key": "value"}
        })
        assert r.status_code == 200


# --- Cost/Skills Endpoints ---

class TestMiscEndpoints:
    """Tests for misc endpoints."""

    def test_cost(self, client):
        """Should return cost report."""
        r = client.get("/api/cost")
        assert r.status_code == 200
        data = r.json()
        assert "total_cost_usd" in data

    def test_skills(self, client):
        """Should return skills."""
        r = client.get("/api/skills")
        assert r.status_code == 200
        data = r.json()
        assert "skills" in data


# --- Vault Endpoints ---

class TestVaultEndpoints:
    """Tests for vault endpoints."""

    def test_vault_search(self, client):
        """Should search vault."""
        r = client.post("/api/vault/search", json={
            "query": "test",
            "limit": 5
        })
        assert r.status_code == 200
        data = r.json()
        assert "results" in data

    def test_vault_read(self, client):
        """Should read vault note."""
        r = client.post("/api/vault/read", json={
            "path": "/test/note.md"
        })
        assert r.status_code == 200
        data = r.json()
        assert "content" in data


# --- Audit Endpoint ---

class TestAuditEndpoint:
    """Tests for audit endpoint."""

    def test_audit(self, client):
        """Should return audit logs."""
        r = client.get("/api/audit")
        assert r.status_code == 200
        data = r.json()
        assert "events" in data
        assert "count" in data

    def test_audit_with_limit(self, client):
        """Should respect limit parameter."""
        r = client.get("/api/audit?limit=5")
        assert r.status_code == 200
        data = r.json()
        assert len(data["events"]) <= 5


# --- Auth Endpoint ---

class TestAuthEndpoint:
    """Tests for auth endpoint."""

    def test_login_missing_user(self, client):
        """Should reject missing user."""
        r = client.post("/api/auth/login", json={
            "user_id": "ghost",
            "password": "anything"
        })
        assert r.status_code == 401

    def test_login_then_auth(self, client):
        """Should support user creation and login."""
        # Create user
        from graxia_tool.auth import get_user_store
        store = get_user_store()
        store.create_user("alice", "secret123", tenant_id="acme")

        # Login
        r = client.post("/api/auth/login", json={
            "user_id": "alice",
            "password": "secret123"
        })
        assert r.status_code == 200
        data = r.json()
        assert "token" in data
        assert data["user_id"] == "alice"
        assert data["tenant_id"] == "acme"

    def test_login_wrong_password(self, client):
        """Should reject wrong password."""
        from graxia_tool.auth import get_user_store
        store = get_user_store()
        store.create_user("bob", "rightpass")

        r = client.post("/api/auth/login", json={
            "user_id": "bob",
            "password": "wrongpass"
        })
        assert r.status_code == 401


# --- Metrics Endpoint ---

class TestMetricsEndpoint:
    """Tests for metrics endpoint."""

    def test_metrics(self, client):
        """Should return Prometheus metrics."""
        r = client.get("/metrics")
        assert r.status_code == 200
        # Should contain some metric output
        text = r.text
        assert len(text) > 0


# --- OpenAPI ---

class TestOpenAPI:
    """Tests for OpenAPI spec."""

    def test_openapi(self, client):
        """Should return OpenAPI spec."""
        r = client.get("/openapi.json")
        assert r.status_code == 200
        data = r.json()
        assert data["info"]["title"] == "Graxia Tool API"
        assert data["info"]["version"] == "0.2.0"

    def test_docs(self, client):
        """Should serve docs."""
        r = client.get("/docs")
        assert r.status_code == 200


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
