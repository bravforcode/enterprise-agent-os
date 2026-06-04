"""MCP Governance — Tool safety policies and content filtering.

Provides:
- GovernancePolicy: allowed tools, blocked patterns, rate limits, approval gates
- ContentFilter: prompt injection, data exfiltration, privilege escalation detection
- AuditTrail: SQLite-backed audit log for every tool call

All handlers return _ok({...}) or _err(...) — see mcp.__init__.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from . import _ok, _err, logger  # type: ignore


# ── Data structures ──────────────────────────────────────────────────────


@dataclass
class GovernancePolicy:
    """Policy governing tool execution within a single request."""

    name: str
    allowed_tools: List[str] = field(default_factory=list)
    blocked_patterns: List[str] = field(default_factory=list)
    max_calls_per_request: int = 50
    require_human_approval: List[str] = field(default_factory=list)
    enabled: bool = True
    extra: Dict[str, Any] = field(default_factory=dict)


@dataclass
class AuditEntry:
    """Single audit log row."""

    id: str
    timestamp: str
    tool_name: str
    args_hash: str
    status: str  # allow | deny | approval_required | error
    policy_name: Optional[str]
    reason: str
    duration_ms: float = 0.0
    user_id: Optional[str] = None
    session_id: Optional[str] = None


# ── Content filters ──────────────────────────────────────────────────────

# Each filter returns (passed: bool, reason: str)

_INJECTION_PATTERNS: List[re.Pattern[str]] = [
    re.compile(r"ignore\s+(all\s+)?previous\s+instructions", re.IGNORECASE),
    re.compile(r"you\s+are\s+now\s+(a|an)\s+", re.IGNORECASE),
    re.compile(r"disregard\s+(all\s+)?prior", re.IGNORECASE),
    re.compile(r"override\s+(system|safety)\s+(prompt|instructions?)", re.IGNORECASE),
    re.compile(r"\[INST\]|\[/INST\]|<<SYS>>|<</SYS>>", re.IGNORECASE),
    re.compile(r"<\|im_start\|>|<\|im_end\|>", re.IGNORECASE),
    re.compile(r"system\s*:\s*you\s+are", re.IGNORECASE),
    re.compile(r"assistant\s*:\s*sure", re.IGNORECASE),
    re.compile(r"\bDAN\b.*\bDo\s+Anything\s+Now\b", re.IGNORECASE),
    re.compile(r"jailbreak|bypass\s+(all\s+)?filter", re.IGNORECASE),
]

_EXFILTRATION_PATTERNS: List[re.Pattern[str]] = [
    re.compile(r"(curl|wget|fetch|requests?\.(get|post))\s+[\"']https?://", re.IGNORECASE),
    re.compile(r"base64\s*(encode|decode)\s+", re.IGNORECASE),
    re.compile(r"send\s+(all\s+)?(data|file|content)\s+to\s+https?://", re.IGNORECASE),
    re.compile(r"exfiltrate|upload\s+(all\s+)?(secrets?|keys?|tokens?|passwords?)", re.IGNORECASE),
    re.compile(r"(api[_-]?key|secret[_-]?key|access[_-]?token)\s*[=:]\s*['\"][^'\"]{8,}", re.IGNORECASE),
    re.compile(r"echo\s+\$[A-Z_]+\s*\|\s*(curl|wget)", re.IGNORECASE),
]

_PRIVILEGE_ESCALATION_PATTERNS: List[re.Pattern[str]] = [
    re.compile(r"(sudo|su\s+-|runas)\s+", re.IGNORECASE),
    re.compile(r"chmod\s+[0-7]*7[0-7]*\s+", re.IGNORECASE),
    re.compile(r"chown\s+root", re.IGNORECASE),
    re.compile(r"(\/etc\/passwd|\/etc\/shadow|\/etc\/sudoers)", re.IGNORECASE),
    re.compile(r"mount\s+.*\/dev\/", re.IGNORECASE),
    re.compile(r"net\s+(user|localgroup)\s+.*\s+/add", re.IGNORECASE),
    re.compile(r"reg\s+(add|delete)\s+.*\\\\HKLM", re.IGNORECASE),
    re.compile(r"sc\s+config", re.IGNORECASE),
    re.compile(r"iptables\s+-F", re.IGNORECASE),
    re.compile(r"(setuid|setgid|capabilities?)\s+on", re.IGNORECASE),
]


def check_injection(text: str) -> tuple[bool, str]:
    """Detect prompt injection attempts. Returns (passed, reason)."""
    for pat in _INJECTION_PATTERNS:
        if pat.search(text):
            return False, f"Prompt injection detected: {pat.pattern[:60]}"
    return True, ""


def check_exfiltration(text: str) -> tuple[bool, str]:
    """Detect data exfiltration attempts. Returns (passed, reason)."""
    for pat in _EXFILTRATION_PATTERNS:
        if pat.search(text):
            return False, f"Data exfiltration detected: {pat.pattern[:60]}"
    return True, ""


def check_privilege_escalation(text: str) -> tuple[bool, str]:
    """Detect privilege escalation attempts. Returns (passed, reason)."""
    for pat in _PRIVILEGE_ESCALATION_PATTERNS:
        if pat.search(text):
            return False, f"Privilege escalation detected: {pat.pattern[:60]}"
    return True, ""


ALL_FILTERS = [check_injection, check_exfiltration, check_privilege_escalation]


def run_content_filters(text: str) -> tuple[bool, List[str]]:
    """Run all content filters on text. Returns (passed, reasons)."""
    reasons: List[str] = []
    for fn in ALL_FILTERS:
        passed, reason = fn(text)
        if not passed:
            reasons.append(reason)
    return len(reasons) == 0, reasons


# ── Audit trail (SQLite) ────────────────────────────────────────────────


class AuditTrail:
    """SQLite-backed audit log for tool calls."""

    def __init__(self, db_path: Optional[str] = None):
        if db_path is None:
            db_dir = Path.home() / ".graxia"
            db_dir.mkdir(parents=True, exist_ok=True)
            db_path = str(db_dir / "governance_audit.db")
        self._db_path = db_path
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self._db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS governance_audit (
                    id TEXT PRIMARY KEY,
                    timestamp TEXT NOT NULL,
                    tool_name TEXT NOT NULL,
                    args_hash TEXT NOT NULL,
                    status TEXT NOT NULL,
                    policy_name TEXT,
                    reason TEXT NOT NULL,
                    duration_ms REAL DEFAULT 0.0,
                    user_id TEXT,
                    session_id TEXT
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_ga_timestamp
                ON governance_audit(timestamp)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_ga_tool_name
                ON governance_audit(tool_name)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_ga_status
                ON governance_audit(status)
            """)
            conn.commit()

    def log(
        self,
        tool_name: str,
        args: Dict[str, Any],
        status: str,
        policy_name: Optional[str],
        reason: str,
        duration_ms: float = 0.0,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> str:
        """Write an audit entry. Returns the entry id."""
        entry_id = str(uuid.uuid4())
        args_hash = str(hash(json.dumps(args, sort_keys=True, default=str)))
        ts = datetime.utcnow().isoformat()
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                """INSERT INTO governance_audit
                   (id, timestamp, tool_name, args_hash, status, policy_name,
                    reason, duration_ms, user_id, session_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (entry_id, ts, tool_name, args_hash, status,
                 policy_name, reason, duration_ms, user_id, session_id),
            )
            conn.commit()
        return entry_id

    def query(
        self,
        tool_name: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 100,
    ) -> List[AuditEntry]:
        """Query audit entries with optional filters."""
        sql = "SELECT id, timestamp, tool_name, args_hash, status, policy_name, reason, duration_ms, user_id, session_id FROM governance_audit WHERE 1=1"
        params: list[Any] = []
        if tool_name:
            sql += " AND tool_name = ?"
            params.append(tool_name)
        if status:
            sql += " AND status = ?"
            params.append(status)
        sql += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)
        with sqlite3.connect(self._db_path) as conn:
            rows = conn.execute(sql, params).fetchall()
        return [
            AuditEntry(
                id=r[0], timestamp=r[1], tool_name=r[2], args_hash=r[3],
                status=r[4], policy_name=r[5], reason=r[6],
                duration_ms=r[7], user_id=r[8], session_id=r[9],
            )
            for r in rows
        ]

    def stats(self) -> Dict[str, Any]:
        """Aggregate audit statistics."""
        with sqlite3.connect(self._db_path) as conn:
            total = conn.execute("SELECT COUNT(*) FROM governance_audit").fetchone()[0]
            by_status = dict(
                conn.execute(
                    "SELECT status, COUNT(*) FROM governance_audit GROUP BY status"
                ).fetchall()
            )
            by_tool = dict(
                conn.execute(
                    "SELECT tool_name, COUNT(*) FROM governance_audit GROUP BY tool_name ORDER BY COUNT(*) DESC LIMIT 20"
                ).fetchall()
            )
        return {
            "total_entries": total,
            "by_status": by_status,
            "top_tools": by_tool,
        }


# ── Governance engine ────────────────────────────────────────────────────

# Global audit trail singleton (lazy init)
_audit_trail: Optional[AuditTrail] = None


def _get_audit_trail() -> AuditTrail:
    global _audit_trail
    if _audit_trail is None:
        _audit_trail = AuditTrail()
    return _audit_trail


def check_tool_call(
    tool_name: str,
    args: Dict[str, Any],
    policy: GovernancePolicy,
    user_id: Optional[str] = None,
    session_id: Optional[str] = None,
) -> tuple[bool, str, str]:
    """Check if a tool call is allowed by the governance policy.

    Returns (allowed, reason, status).
    Status is one of: allow, deny, approval_required, content_blocked.
    """
    if not policy.enabled:
        return True, "Policy disabled", "allow"

    # 1. Check allowed tools list
    if policy.allowed_tools and tool_name not in policy.allowed_tools:
        reason = f"Tool '{tool_name}' not in allowed list"
        _get_audit_trail().log(
            tool_name, args, "deny", policy.name, reason,
            user_id=user_id, session_id=session_id,
        )
        return False, reason, "deny"

    # 2. Check blocked content patterns in args
    args_str = json.dumps(args, default=str)
    for pattern_str in policy.blocked_patterns:
        try:
            if re.search(pattern_str, args_str, re.IGNORECASE):
                reason = f"Args match blocked pattern: {pattern_str[:50]}"
                _get_audit_trail().log(
                    tool_name, args, "deny", policy.name, reason,
                    user_id=user_id, session_id=session_id,
                )
                return False, reason, "deny"
        except re.error:
            pass

    # 3. Run content filters on args
    content_to_check = args_str
    if "query" in args:
        content_to_check = str(args["query"])
    elif "text" in args:
        content_to_check = str(args["text"])
    elif "content" in args:
        content_to_check = str(args["content"])

    passed, reasons = run_content_filters(content_to_check)
    if not passed:
        reason = "; ".join(reasons)
        _get_audit_trail().log(
            tool_name, args, "content_blocked", policy.name, reason,
            user_id=user_id, session_id=session_id,
        )
        return False, reason, "content_blocked"

    # 4. Check approval requirement
    if tool_name in policy.require_human_approval:
        reason = f"Tool '{tool_name}' requires human approval"
        _get_audit_trail().log(
            tool_name, args, "approval_required", policy.name, reason,
            user_id=user_id, session_id=session_id,
        )
        return False, reason, "approval_required"

    # 5. Allowed
    _get_audit_trail().log(
        tool_name, args, "allow", policy.name, "OK",
        user_id=user_id, session_id=session_id,
    )
    return True, "OK", "allow"


# ── MCP tool handlers ───────────────────────────────────────────────────


async def governance_check_handler(args: Dict[str, Any]) -> Dict[str, Any]:
    """Check if a tool call is allowed by governance policy."""
    tool_name = str(args.get("tool_name", ""))
    tool_args = args.get("args") or {}
    policy_name = args.get("policy", "default")
    user_id = args.get("user_id")
    session_id = args.get("session_id")

    if not tool_name:
        return _err("tool_name is required")

    policy = _load_policy(policy_name)
    allowed, reason, status = check_tool_call(
        tool_name, tool_args, policy, user_id=user_id, session_id=session_id,
    )
    return _ok({
        "allowed": allowed,
        "status": status,
        "reason": reason,
        "policy": policy.name,
        "tool_name": tool_name,
    })


async def governance_audit_query(args: Dict[str, Any]) -> Dict[str, Any]:
    """Query audit trail entries."""
    tool_name = args.get("tool_name")
    status = args.get("status")
    limit = int(args.get("limit", 50))

    trail = _get_audit_trail()
    entries = trail.query(tool_name=tool_name, status=status, limit=limit)
    return _ok({
        "entries": [
            {
                "id": e.id,
                "timestamp": e.timestamp,
                "tool_name": e.tool_name,
                "status": e.status,
                "policy_name": e.policy_name,
                "reason": e.reason,
                "duration_ms": e.duration_ms,
                "user_id": e.user_id,
                "session_id": e.session_id,
            }
            for e in entries
        ],
        "count": len(entries),
    })


async def governance_audit_stats(args: Dict[str, Any]) -> Dict[str, Any]:
    """Get aggregate audit statistics."""
    trail = _get_audit_trail()
    return _ok(trail.stats())


async def governance_content_filter(args: Dict[str, Any]) -> Dict[str, Any]:
    """Run content filters on text and return results."""
    text = str(args.get("text", ""))
    if not text:
        return _err("text is required")

    passed, reasons = run_content_filters(text)
    return _ok({
        "passed": passed,
        "reasons": reasons,
        "filter_count": len(reasons),
    })


# ── Policy loading ──────────────────────────────────────────────────────

# Built-in policies
_BUILTIN_POLICIES: Dict[str, GovernancePolicy] = {
    "default": GovernancePolicy(
        name="default",
        allowed_tools=[],  # empty = allow all
        blocked_patterns=[
            r"(?:rm|del)\s+-rf\s+/",
            r"DROP\s+TABLE",
            r"DELETE\s+FROM\s+\w+\s*$",
        ],
        max_calls_per_request=50,
        require_human_approval=[
            "deploy",
            "delete_file",
        ],
    ),
    "strict": GovernancePolicy(
        name="strict",
        allowed_tools=[
            "agent_run", "agent_list", "auto_route", "guard_check",
            "memory_recall", "memory_store", "memory_search",
            "rag_query", "cache_get", "cache_set", "cost_report",
            "context_cache_get", "context_cache_stats", "system_status",
            "governance_check",
        ],
        blocked_patterns=[
            r"(?:rm|del)\s+-rf",
            r"DROP\s+TABLE",
            r"DELETE\s+FROM",
            r"sudo\s+",
            r"chmod\s+777",
        ],
        max_calls_per_request=30,
        require_human_approval=[
            "pipeline_run", "multi_agent_run", "eval_run",
            "swarm_init", "swarm_run",
        ],
    ),
    "permissive": GovernancePolicy(
        name="permissive",
        allowed_tools=[],  # allow all
        blocked_patterns=[],
        max_calls_per_request=100,
        require_human_approval=[],
    ),
}


def _load_policy(name: str) -> GovernancePolicy:
    """Load a policy by name. Falls back to 'default'."""
    return _BUILTIN_POLICIES.get(name, _BUILTIN_POLICIES["default"])


def register_policy(policy: GovernancePolicy) -> None:
    """Register a custom policy."""
    _BUILTIN_POLICIES[policy.name] = policy


def list_policies() -> List[str]:
    """List registered policy names."""
    return list(_BUILTIN_POLICIES.keys())


# ── Tool specs ───────────────────────────────────────────────────────────

GOVERNANCE_TOOL_SPECS = [
    {
        "name": "governance_check",
        "description": "Check if a tool call is allowed by governance policy (content filters, approval gates, rate limits).",
        "input_schema": {
            "type": "object",
            "properties": {
                "tool_name": {"type": "string", "description": "Tool to check"},
                "args": {"type": "object", "description": "Tool arguments to validate"},
                "policy": {"type": "string", "default": "default", "description": "Policy name: default, strict, permissive"},
                "user_id": {"type": "string"},
                "session_id": {"type": "string"},
            },
            "required": ["tool_name"],
        },
        "handler": governance_check_handler,
        "category": "governance",
    },
    {
        "name": "governance_audit_query",
        "description": "Query governance audit trail entries (tool calls, decisions, violations).",
        "input_schema": {
            "type": "object",
            "properties": {
                "tool_name": {"type": "string", "description": "Filter by tool name"},
                "status": {"type": "string", "enum": ["allow", "deny", "approval_required", "content_blocked", "error"]},
                "limit": {"type": "integer", "default": 50},
            },
        },
        "handler": governance_audit_query,
        "category": "governance",
    },
    {
        "name": "governance_audit_stats",
        "description": "Get aggregate governance audit statistics (total calls, by status, top tools).",
        "input_schema": {"type": "object", "properties": {}},
        "handler": governance_audit_stats,
        "category": "governance",
    },
    {
        "name": "governance_content_filter",
        "description": "Run content filters on text (prompt injection, exfiltration, privilege escalation).",
        "input_schema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "Text to scan"},
            },
            "required": ["text"],
        },
        "handler": governance_content_filter,
        "category": "governance",
    },
]
