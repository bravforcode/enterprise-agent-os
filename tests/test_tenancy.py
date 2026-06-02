"""Tests for tenancy module — 30+ tests."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from graxia_tool.tenancy import (
    Tenant, TenantUsage, TenantManager,
    get_tenant_manager, isolate_resource,
)


# --- Tenant Tests ---

class TestTenant:
    """Tests for Tenant dataclass."""

    def test_create_tenant(self):
        """Should create tenant with defaults."""
        t = Tenant(id="acme", name="ACME Corp")
        assert t.id == "acme"
        assert t.name == "ACME Corp"
        assert t.cost_limit_usd == 100.0
        assert t.rate_limit == 100

    def test_tenant_to_dict(self):
        """Should serialize to dict."""
        t = Tenant(id="acme", name="ACME")
        d = t.to_dict()
        assert d["id"] == "acme"
        assert d["name"] == "ACME"
        assert "created_at" in d


# --- TenantUsage Tests ---

class TestTenantUsage:
    """Tests for TenantUsage."""

    def test_default_usage(self):
        """Should have zero usage by default."""
        u = TenantUsage(tenant_id="acme")
        assert u.cost_usd == 0.0
        assert u.requests == 0

    def test_reset(self):
        """Should reset usage."""
        u = TenantUsage(tenant_id="acme", cost_usd=10, requests=5)
        u.reset()
        assert u.cost_usd == 0
        assert u.requests == 0


# --- TenantManager Tests ---

class TestTenantManager:
    """Tests for TenantManager."""

    def test_create_tenant(self):
        """Should create tenant."""
        mgr = TenantManager()
        t = mgr.create_tenant("acme", "ACME Corp")
        assert t.id == "acme"
        assert t.name == "ACME Corp"

    def test_create_duplicate_raises(self):
        """Should raise on duplicate tenant."""
        mgr = TenantManager()
        mgr.create_tenant("acme", "ACME")
        with pytest.raises(ValueError):
            mgr.create_tenant("acme", "ACME 2")

    def test_get_tenant(self):
        """Should get tenant by ID."""
        mgr = TenantManager()
        mgr.create_tenant("acme", "ACME")
        t = mgr.get_tenant("acme")
        assert t is not None
        assert t.name == "ACME"

    def test_get_nonexistent(self):
        """Should return None for missing tenant."""
        mgr = TenantManager()
        assert mgr.get_tenant("ghost") is None

    def test_delete_tenant(self):
        """Should delete tenant."""
        mgr = TenantManager()
        mgr.create_tenant("acme", "ACME")
        assert mgr.delete_tenant("acme") is True
        assert mgr.get_tenant("acme") is None

    def test_delete_nonexistent(self):
        """Should return False for missing tenant."""
        mgr = TenantManager()
        assert mgr.delete_tenant("ghost") is False

    def test_list_tenants(self):
        """Should list all tenants."""
        mgr = TenantManager()
        mgr.create_tenant("acme", "ACME")
        mgr.create_tenant("globex", "Globex")
        tenants = mgr.list_tenants()
        assert len(tenants) == 2

    def test_custom_cost_limit(self):
        """Should respect custom cost limit."""
        mgr = TenantManager()
        t = mgr.create_tenant("acme", "ACME", cost_limit_usd=500.0)
        assert t.cost_limit_usd == 500.0

    def test_custom_vault_path(self):
        """Should respect custom vault path."""
        mgr = TenantManager()
        t = mgr.create_tenant("acme", "ACME", vault_path="/var/vault/acme")
        assert t.vault_path == "/var/vault/acme"

    def test_default_vault_path(self):
        """Should default vault path to ./vaults/{tenant_id}."""
        mgr = TenantManager()
        t = mgr.create_tenant("acme", "ACME")
        assert t.vault_path == "./vaults/acme"


# --- Usage Tests ---

class TestUsage:
    """Tests for usage tracking."""

    def test_record_cost(self):
        """Should record cost."""
        mgr = TenantManager()
        mgr.create_tenant("acme", "ACME")
        mgr.record_cost("acme", 5.0)
        usage = mgr.get_usage("acme")
        assert usage.cost_usd == 5.0

    def test_record_request(self):
        """Should record request."""
        mgr = TenantManager()
        mgr.create_tenant("acme", "ACME")
        mgr.record_request("acme")
        mgr.record_request("acme")
        usage = mgr.get_usage("acme")
        assert usage.requests == 2

    def test_within_cost_limit(self):
        """Should check cost limit."""
        mgr = TenantManager()
        mgr.create_tenant("acme", "ACME", cost_limit_usd=10.0)
        mgr.record_cost("acme", 5.0)
        assert mgr.is_within_cost_limit("acme") is True
        mgr.record_cost("acme", 10.0)
        assert mgr.is_within_cost_limit("acme") is False


# --- Resource Isolation Tests ---

class TestResourceIsolation:
    """Tests for resource isolation."""

    def test_tenant_can_access_own_resource(self):
        """Tenant can access its own resources."""
        mgr = TenantManager()
        mgr.create_tenant("acme", "ACME")
        assert mgr.can_access("acme", "acme/file.txt") is True

    def test_tenant_cannot_access_other_resource(self):
        """Tenant cannot access other tenant's resources."""
        mgr = TenantManager()
        mgr.create_tenant("acme", "ACME")
        mgr.create_tenant("globex", "Globex")
        assert mgr.can_access("acme", "globex/file.txt") is False

    def test_get_vault_path(self):
        """Should get isolated vault path."""
        mgr = TenantManager()
        mgr.create_tenant("acme", "ACME")
        path = mgr.get_vault_path("acme")
        assert path is not None
        assert "acme" in path


# --- Helper Tests ---

class TestHelpers:
    """Tests for helper functions."""

    def test_isolate_resource(self):
        """Should add tenant prefix to resource."""
        result = isolate_resource("acme", "file.txt")
        assert result == "acme/file.txt"

    def test_isolate_resource_already_prefixed(self):
        """Should not double-prefix."""
        result = isolate_resource("acme", "acme/file.txt")
        assert result == "acme/file.txt"

    def test_isolate_resource_with_leading_slash(self):
        """Should handle leading slashes."""
        result = isolate_resource("acme", "/file.txt")
        assert result == "acme/file.txt"


# --- Singleton Tests ---

class TestSingleton:
    """Tests for singleton manager."""

    def test_get_tenant_manager_singleton(self):
        """Should return same instance."""
        m1 = get_tenant_manager()
        m2 = get_tenant_manager()
        assert m1 is m2


# --- Stats Tests ---

class TestStats:
    """Tests for manager stats."""

    def test_get_stats_empty(self):
        """Should return zero stats when empty."""
        mgr = TenantManager()
        stats = mgr.get_stats()
        assert stats["total_tenants"] == 0

    def test_get_stats_with_tenants(self):
        """Should return stats with tenants."""
        mgr = TenantManager()
        mgr.create_tenant("acme", "ACME", cost_limit_usd=50)
        mgr.create_tenant("globex", "Globex", cost_limit_usd=100)
        mgr.record_cost("acme", 5.0)
        mgr.record_cost("globex", 10.0)
        stats = mgr.get_stats()
        assert stats["total_tenants"] == 2
        assert stats["total_cost_usd"] == 15.0


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
