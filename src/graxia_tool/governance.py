"""Enterprise Agent OS — Governance Module.

- Policy engine: who can do what
- Audit log: every action tracked
- Compliance: rule-based checks
- Alert system: notify on policy violations
"""
from __future__ import annotations
import uuid
import time
import json
from datetime import datetime
from dataclasses import dataclass, field
from typing import Any, Optional, Callable
from enum import Enum
from .core.logging import get_logger

logger = get_logger("governance")


class PolicyDecision(str, Enum):
    ALLOW = "allow"
    DENY = "deny"
    ALLOW_WITH_APPROVAL = "allow_with_approval"


@dataclass
class Policy:
    """A governance policy."""
    name: str
    description: str
    rule: Callable[[dict], bool]  # returns True if ALLOW
    requires_approval: bool = False
    severity: int = 0  # 0=info, 1=warn, 2=critical
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class AuditEntry:
    """An audit log entry."""
    id: str
    timestamp: datetime
    user_id: Optional[str]
    action: str
    target: str
    decision: PolicyDecision
    policy_name: Optional[str]
    reason: str
    extra: dict[str, Any] = field(default_factory=dict)


class PolicyEngine:
    """
    Evaluates policies against actions.
    """

    def __init__(self):
        self.policies: list[Policy] = []
        self.audit_log: list[AuditEntry] = []
        # Default policies
        self._register_defaults()

    def _register_defaults(self):
        """Register default safety policies."""
        # Never allow destructive operations without approval
        self.policies.append(Policy(
            name="no_destructive_ops",
            description="Block rm -rf, DROP TABLE, etc.",
            rule=lambda ctx: "rm -rf" not in ctx.get("command", "").lower()
                         and "drop table" not in ctx.get("query", "").lower(),
            requires_approval=False,
            severity=2,
        ))

        # No production access without approval
        self.policies.append(Policy(
            name="no_prod_access",
            description="Production access requires approval",
            rule=lambda ctx: ctx.get("environment") != "production",
            requires_approval=True,
            severity=2,
        ))

        # No secret access without approval
        self.policies.append(Policy(
            name="no_secret_access",
            description="Accessing secrets requires approval",
            rule=lambda ctx: "secret" not in ctx.get("action", "").lower(),
            requires_approval=True,
            severity=2,
        ))

        # No outbound network without approval
        self.policies.append(Policy(
            name="no_unauth_network",
            description="Unauthenticated network calls blocked",
            rule=lambda ctx: ctx.get("authenticated", True),
            requires_approval=True,
            severity=1,
        ))

    def add_policy(self, policy: Policy) -> None:
        """Add a custom policy."""
        self.policies.append(policy)
        logger.info("policy_added", name=policy.name)

    def evaluate(
        self,
        action: str,
        context: dict[str, Any],
        user_id: Optional[str] = None,
    ) -> tuple[PolicyDecision, str]:
        """
        Evaluate an action against all policies.

        Returns:
            (decision, reason)
        """
        context["action"] = action
        requires_approval = False
        deny_reasons = []
        approval_reasons = []

        for policy in self.policies:
            try:
                allowed = policy.rule(context)
            except Exception as e:
                logger.warning("policy_error", name=policy.name, error=str(e))
                continue
            if not allowed:
                if policy.requires_approval:
                    requires_approval = True
                    approval_reasons.append(policy.name)
                else:
                    deny_reasons.append(policy.name)
                    # Log denied action
                    self._audit(
                        user_id=user_id,
                        action=action,
                        target=context.get("target", "unknown"),
                        decision=PolicyDecision.DENY,
                        policy_name=policy.name,
                        reason=policy.description,
                        extra=context,
                    )
                    return PolicyDecision.DENY, f"Denied by policy: {policy.name}"

        if requires_approval:
            self._audit(
                user_id=user_id,
                action=action,
                target=context.get("target", "unknown"),
                decision=PolicyDecision.ALLOW_WITH_APPROVAL,
                policy_name=",".join(approval_reasons),
                reason=f"Requires approval: {', '.join(approval_reasons)}",
                extra=context,
            )
            return PolicyDecision.ALLOW_WITH_APPROVAL, f"Requires approval: {', '.join(approval_reasons)}"

        # Log allowed action
        self._audit(
            user_id=user_id,
            action=action,
            target=context.get("target", "unknown"),
            decision=PolicyDecision.ALLOW,
            policy_name=None,
            reason="No policy violations",
            extra=context,
        )
        return PolicyDecision.ALLOW, "OK"

    def _audit(
        self,
        user_id: Optional[str],
        action: str,
        target: str,
        decision: PolicyDecision,
        policy_name: Optional[str],
        reason: str,
        extra: dict,
    ) -> None:
        """Log an audit entry."""
        entry = AuditEntry(
            id=str(uuid.uuid4()),
            timestamp=datetime.utcnow(),
            user_id=user_id,
            action=action,
            target=target,
            decision=decision,
            policy_name=policy_name,
            reason=reason,
            extra=extra,
        )
        self.audit_log.append(entry)
        if decision != PolicyDecision.ALLOW:
            logger.warning(
                "policy_violation",
                action=action,
                decision=decision.value,
                policy=policy_name,
                reason=reason,
            )

    def get_audit_log(
        self,
        user_id: Optional[str] = None,
        decision: Optional[PolicyDecision] = None,
        limit: int = 100,
    ) -> list[AuditEntry]:
        """Get audit log entries."""
        entries = self.audit_log
        if user_id:
            entries = [e for e in entries if e.user_id == user_id]
        if decision:
            entries = [e for e in entries if e.decision == decision]
        return entries[-limit:]

    def get_stats(self) -> dict[str, Any]:
        """Get governance statistics."""
        total = len(self.audit_log)
        by_decision = {}
        for entry in self.audit_log:
            key = entry.decision.value
            by_decision[key] = by_decision.get(key, 0) + 1
        return {
            "total_actions": total,
            "by_decision": by_decision,
            "policies": len(self.policies),
        }
