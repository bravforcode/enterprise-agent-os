"""JWT auth + per-user rate limiting middleware for FastAPI.

Provides:
- JWT token creation/verification
- Per-user rate limiting (using AdvancedRateLimiter)
- Tenant isolation
- Audit logging integration
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Any, Optional

import jwt
from fastapi import HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .metrics import record_rate_limited
from .performance import AdvancedRateLimiter
from .security import AuditLogger, hash_password, verify_password


# Default JWT settings
JWT_SECRET = os.getenv("GRAXIA_JWT_SECRET", "change-me-in-production-please")
JWT_ALGORITHM = "HS256"
JWT_EXPIRATION_HOURS = 24


@dataclass
class User:
    """Authenticated user."""
    user_id: str
    tenant_id: str
    role: str = "user"
    rate_limit: int = 100  # requests per minute
    burst: int = 20

    def to_dict(self) -> dict:
        return {
            "user_id": self.user_id,
            "tenant_id": self.tenant_id,
            "role": self.role,
            "rate_limit": self.rate_limit,
            "burst": self.burst,
        }


# --- JWT Functions ---

def create_token(user: User, expires_in_hours: int = JWT_EXPIRATION_HOURS) -> str:
    """Create JWT token for user."""
    payload = {
        "sub": user.user_id,
        "tenant": user.tenant_id,
        "role": user.role,
        "rl": user.rate_limit,
        "burst": user.burst,
        "iat": int(time.time()),
        "exp": int(time.time()) + expires_in_hours * 3600,
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def verify_token(token: str) -> Optional[User]:
    """Verify JWT and return User."""
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return User(
            user_id=payload["sub"],
            tenant_id=payload.get("tenant", "default"),
            role=payload.get("role", "user"),
            rate_limit=payload.get("rl", 100),
            burst=payload.get("burst", 20),
        )
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None


# --- Rate Limiter Manager ---

class RateLimiterManager:
    """Manages per-user rate limiters."""

    def __init__(self):
        self._limiters: dict[str, AdvancedRateLimiter] = {}

    def get_limiter(self, user_id: str, rate: int = 100, burst: int = 20) -> AdvancedRateLimiter:
        """Get or create rate limiter for user."""
        if user_id not in self._limiters:
            # Convert per-minute to per-second
            rate_per_sec = rate / 60.0
            self._limiters[user_id] = AdvancedRateLimiter(
                rate=rate_per_sec,
                burst=burst,
                window_seconds=60.0,
            )
        return self._limiters[user_id]


# Global rate limiter manager
_rate_limiters = RateLimiterManager()
_audit_logger = AuditLogger()


# --- FastAPI Dependencies ---

bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = None,
) -> User:
    """FastAPI dependency to get current user from JWT."""
    if credentials is None:
        auth = request.headers.get("authorization", "")
        if not auth.startswith("Bearer "):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing authentication",
            )
        token = auth[7:]
    else:
        token = credentials.credentials

    user = verify_token(token)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )

    return user


async def check_rate_limit(request: Request, user: User) -> User:
    """FastAPI dependency to check rate limit per user."""
    limiter = _rate_limiters.get_limiter(user.user_id, user.rate_limit, user.burst)
    allowed, info = limiter.check(user.user_id)

    # Add rate limit headers
    request.state.rate_limit_remaining = info["remaining"]
    request.state.rate_limit_limit = info["limit"]

    if not allowed:
        record_rate_limited(user.user_id, str(request.url.path))
        _audit_logger.log(
            event_type="rate_limited",
            user_id=user.user_id,
            resource=str(request.url.path),
            action="request",
            result="blocked",
        )
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded",
            headers={
                "Retry-After": str(int(info.get("retry_after", 60))),
                "X-RateLimit-Remaining": "0",
                "X-RateLimit-Limit": str(info["limit"]),
            },
        )

    return user


# --- User Store (in-memory) ---

class UserStore:
    """Simple in-memory user store with hashed passwords."""

    def __init__(self):
        self._users: dict[str, dict[str, Any]] = {}

    def create_user(
        self,
        user_id: str,
        password: str,
        tenant_id: str = "default",
        role: str = "user",
        rate_limit: int = 100,
        burst: int = 20,
    ) -> User:
        """Create a new user with hashed password."""
        if user_id in self._users:
            raise ValueError(f"User {user_id} already exists")

        password_hash = hash_password(password)
        self._users[user_id] = {
            "password_hash": password_hash,
            "tenant_id": tenant_id,
            "role": role,
            "rate_limit": rate_limit,
            "burst": burst,
        }

        return User(
            user_id=user_id,
            tenant_id=tenant_id,
            role=role,
            rate_limit=rate_limit,
            burst=burst,
        )

    def authenticate(self, user_id: str, password: str) -> Optional[User]:
        """Authenticate user, return User if valid."""
        user_data = self._users.get(user_id)
        if user_data is None:
            return None

        if not verify_password(password, user_data["password_hash"]):
            return None

        return User(
            user_id=user_id,
            tenant_id=user_data["tenant_id"],
            role=user_data["role"],
            rate_limit=user_data["rate_limit"],
            burst=user_data["burst"],
        )

    def get_user(self, user_id: str) -> Optional[User]:
        """Get user by ID (no auth check)."""
        user_data = self._users.get(user_id)
        if user_data is None:
            return None
        return User(
            user_id=user_id,
            tenant_id=user_data["tenant_id"],
            role=user_data["role"],
            rate_limit=user_data["rate_limit"],
            burst=user_data["burst"],
        )


# Global user store
_user_store: Optional[UserStore] = None


def get_user_store() -> UserStore:
    """Get global user store (singleton)."""
    global _user_store
    if _user_store is None:
        _user_store = UserStore()
    return _user_store
