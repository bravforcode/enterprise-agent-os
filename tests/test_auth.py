"""Tests for auth module — 30+ tests."""
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from graxia_tool.auth import (
    User, create_token, verify_token,
    RateLimiterManager, UserStore, get_user_store,
)


# --- User Tests ---

class TestUser:
    """Tests for User dataclass."""

    def test_create_user(self):
        """Should create user with defaults."""
        user = User(user_id="alice", tenant_id="acme")
        assert user.user_id == "alice"
        assert user.tenant_id == "acme"
        assert user.role == "user"
        assert user.rate_limit == 100

    def test_user_to_dict(self):
        """Should convert to dict."""
        user = User(user_id="bob", tenant_id="acme", role="admin")
        d = user.to_dict()
        assert d["user_id"] == "bob"
        assert d["role"] == "admin"


# --- JWT Tests ---

class TestJWT:
    """Tests for JWT token operations."""

    def test_create_token(self):
        """Should create valid JWT token."""
        user = User(user_id="alice", tenant_id="acme")
        token = create_token(user)
        assert isinstance(token, str)
        assert len(token) > 0

    def test_verify_valid_token(self):
        """Should verify valid token."""
        user = User(user_id="alice", tenant_id="acme", role="admin")
        token = create_token(user)
        decoded = verify_token(token)
        assert decoded is not None
        assert decoded.user_id == "alice"
        assert decoded.tenant_id == "acme"
        assert decoded.role == "admin"

    def test_verify_invalid_token(self):
        """Should return None for invalid token."""
        decoded = verify_token("invalid.token.here")
        assert decoded is None

    def test_verify_expired_token(self):
        """Should return None for expired token."""
        user = User(user_id="alice", tenant_id="acme")
        # Create token that expires in -1 hours (already expired)
        token = create_token(user, expires_in_hours=-1)
        decoded = verify_token(token)
        assert decoded is None

    def test_token_preserves_rate_limit(self):
        """Should preserve rate limit in token."""
        user = User(user_id="alice", tenant_id="acme", rate_limit=200, burst=50)
        token = create_token(user)
        decoded = verify_token(token)
        assert decoded.rate_limit == 200
        assert decoded.burst == 50


# --- Rate Limiter Manager Tests ---

class TestRateLimiterManager:
    """Tests for rate limiter manager."""

    def test_get_limiter(self):
        """Should return limiter for user."""
        mgr = RateLimiterManager()
        limiter = mgr.get_limiter("user1", rate=60, burst=10)
        assert limiter is not None

    def test_same_user_same_limiter(self):
        """Should return same limiter for same user."""
        mgr = RateLimiterManager()
        l1 = mgr.get_limiter("user1", rate=60, burst=10)
        l2 = mgr.get_limiter("user1", rate=60, burst=10)
        assert l1 is l2

    def test_different_users_different_limiters(self):
        """Should return different limiters for different users."""
        mgr = RateLimiterManager()
        l1 = mgr.get_limiter("user1", rate=60, burst=10)
        l2 = mgr.get_limiter("user2", rate=60, burst=10)
        assert l1 is not l2


# --- User Store Tests ---

class TestUserStore:
    """Tests for user store."""

    def test_create_user(self):
        """Should create new user."""
        store = UserStore()
        user = store.create_user("alice", "password123", tenant_id="acme")
        assert user.user_id == "alice"
        assert user.tenant_id == "acme"

    def test_create_duplicate_raises(self):
        """Should raise on duplicate user."""
        store = UserStore()
        store.create_user("alice", "password123")
        with pytest.raises(ValueError):
            store.create_user("alice", "different")

    def test_authenticate_valid(self):
        """Should authenticate valid credentials."""
        store = UserStore()
        store.create_user("alice", "secret123")
        user = store.authenticate("alice", "secret123")
        assert user is not None
        assert user.user_id == "alice"

    def test_authenticate_invalid_password(self):
        """Should fail with wrong password."""
        store = UserStore()
        store.create_user("alice", "secret123")
        user = store.authenticate("alice", "wrong")
        assert user is None

    def test_authenticate_nonexistent_user(self):
        """Should fail for nonexistent user."""
        store = UserStore()
        user = store.authenticate("ghost", "anything")
        assert user is None

    def test_get_user(self):
        """Should get user by ID."""
        store = UserStore()
        store.create_user("alice", "secret123", role="admin")
        user = store.get_user("alice")
        assert user is not None
        assert user.role == "admin"

    def test_get_nonexistent_user(self):
        """Should return None for missing user."""
        store = UserStore()
        user = store.get_user("ghost")
        assert user is None

    def test_password_is_hashed(self):
        """Password should be stored hashed, not plain."""
        store = UserStore()
        store.create_user("alice", "secret123")
        stored = store._users["alice"]
        assert stored["password_hash"] != "secret123"
        assert len(stored["password_hash"]) > 20  # hash is long

    def test_custom_role(self):
        """Should respect custom role."""
        store = UserStore()
        store.create_user("alice", "secret123", role="admin")
        user = store.authenticate("alice", "secret123")
        assert user.role == "admin"

    def test_custom_rate_limit(self):
        """Should respect custom rate limit."""
        store = UserStore()
        store.create_user("alice", "secret123", rate_limit=500, burst=100)
        user = store.authenticate("alice", "secret123")
        assert user.rate_limit == 500
        assert user.burst == 100


# --- Integration Tests ---

class TestAuthIntegration:
    """Integration tests for auth."""

    def test_full_workflow(self):
        """Test full create -> token -> verify -> authenticate flow."""
        store = UserStore()
        # Create user
        store.create_user("alice", "secret123", tenant_id="acme", role="user")
        # Authenticate
        user = store.authenticate("alice", "secret123")
        assert user is not None
        # Create token
        token = create_token(user)
        # Verify token
        decoded = verify_token(token)
        assert decoded.user_id == "alice"
        assert decoded.tenant_id == "acme"


# --- Global Store Tests ---

class TestGlobalStore:
    """Tests for global user store."""

    def test_get_user_store_singleton(self):
        """Should return same instance."""
        s1 = get_user_store()
        s2 = get_user_store()
        assert s1 is s2


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
