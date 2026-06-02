"""Multi-tenancy support for Graxia Tool.

Provides:
- Tenant model with isolation
- Per-tenant vault path, cost, cache
- Tenant manager with CRUD
- Resource quota per tenant
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class Tenant:
    """A tenant (organization or user group)."""
    id: str
    name: str
    vault_path: Optional[str] = None
    cost_limit_usd: float = 100.0  # monthly limit
    rate_limit: int = 100  # requests per minute
    storage_quota_mb: int = 1000
    created_at: float = field(default_factory=time.time)
    settings: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "vault_path": self.vault_path,
            "cost_limit_usd": self.cost_limit_usd,
            "rate_limit": self.rate_limit,
            "storage_quota_mb": self.storage_quota_mb,
            "created_at": self.created_at,
            "settings": self.settings,
        }


@dataclass
class TenantUsage:
    """Track tenant resource usage."""
    tenant_id: str
    cost_usd: float = 0.0
    requests: int = 0
    storage_bytes: int = 0
    cache_entries: int = 0
    last_reset: float = field(default_factory=time.time)

    def reset(self):
        """Reset usage counters."""
        self.cost_usd = 0.0
        self.requests = 0
        self.cache_entries = 0
        self.last_reset = time.time()


class TenantManager:
    """Manages tenants and their isolation."""

    def __init__(self):
        self._tenants: dict[str, Tenant] = {}
        self._usage: dict[str, TenantUsage] = {}

    def create_tenant(
        self,
        tenant_id: str,
        name: str,
        vault_path: Optional[str] = None,
        cost_limit_usd: float = 100.0,
        rate_limit: int = 100,
        storage_quota_mb: int = 1000,
        settings: Optional[dict] = None,
    ) -> Tenant:
        """Create a new tenant."""
        if tenant_id in self._tenants:
            raise ValueError(f"Tenant {tenant_id} already exists")

        tenant = Tenant(
            id=tenant_id,
            name=name,
            vault_path=vault_path or f"./vaults/{tenant_id}",
            cost_limit_usd=cost_limit_usd,
            rate_limit=rate_limit,
            storage_quota_mb=storage_quota_mb,
            settings=settings or {},
        )
        self._tenants[tenant_id] = tenant
        self._usage[tenant_id] = TenantUsage(tenant_id=tenant_id)
        return tenant

    def get_tenant(self, tenant_id: str) -> Optional[Tenant]:
        """Get tenant by ID."""
        return self._tenants.get(tenant_id)

    def delete_tenant(self, tenant_id: str) -> bool:
        """Delete tenant."""
        if tenant_id in self._tenants:
            del self._tenants[tenant_id]
            self._usage.pop(tenant_id, None)
            return True
        return False

    def list_tenants(self) -> list[Tenant]:
        """List all tenants."""
        return list(self._tenants.values())

    def get_usage(self, tenant_id: str) -> Optional[TenantUsage]:
        """Get usage for tenant."""
        return self._usage.get(tenant_id)

    def record_cost(self, tenant_id: str, cost_usd: float) -> None:
        """Record cost for tenant."""
        if tenant_id in self._usage:
            self._usage[tenant_id].cost_usd += cost_usd

    def record_request(self, tenant_id: str) -> None:
        """Record a request for tenant."""
        if tenant_id in self._usage:
            self._usage[tenant_id].requests += 1

    def is_within_cost_limit(self, tenant_id: str) -> bool:
        """Check if tenant is within cost limit."""
        tenant = self.get_tenant(tenant_id)
        usage = self.get_usage(tenant_id)
        if tenant is None or usage is None:
            return False
        return usage.cost_usd < tenant.cost_limit_usd

    def is_within_storage_quota(self, tenant_id: str, additional_bytes: int = 0) -> bool:
        """Check if adding bytes would exceed storage quota."""
        tenant = self.get_tenant(tenant_id)
        usage = self.get_usage(tenant_id)
        if tenant is None or usage is None:
            return False
        quota_bytes = tenant.storage_quota_mb * 1024 * 1024
        return (usage.storage_bytes + additional_bytes) <= quota_bytes

    def can_access(self, tenant_id: str, resource: str) -> bool:
        """Check if tenant can access a resource (basic isolation)."""
        tenant = self.get_tenant(tenant_id)
        if tenant is None:
            return False
        # Resource must be prefixed with tenant_id for isolation
        return resource.startswith(f"{tenant_id}/") or resource.startswith(f"./{tenant_id}/")

    def get_vault_path(self, tenant_id: str) -> Optional[str]:
        """Get isolated vault path for tenant."""
        tenant = self.get_tenant(tenant_id)
        if tenant is None:
            return None
        return tenant.vault_path

    def get_stats(self) -> dict[str, Any]:
        """Get manager statistics."""
        return {
            "total_tenants": len(self._tenants),
            "total_cost_usd": sum(u.cost_usd for u in self._usage.values()),
            "total_requests": sum(u.requests for u in self._usage.values()),
            "tenants": [t.to_dict() for t in self._tenants.values()],
        }


# Singleton
_tenant_manager: Optional[TenantManager] = None


def get_tenant_manager() -> TenantManager:
    """Get global tenant manager."""
    global _tenant_manager
    if _tenant_manager is None:
        _tenant_manager = TenantManager()
    return _tenant_manager


def isolate_resource(tenant_id: str, resource: str) -> str:
    """Add tenant prefix to resource name for isolation."""
    if resource.startswith(f"{tenant_id}/"):
        return resource
    return f"{tenant_id}/{resource.lstrip('/')}"
