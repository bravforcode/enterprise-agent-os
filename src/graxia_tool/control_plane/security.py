"""Security gate for input validation, content filtering, and audit logging."""

import json
import re
import sqlite3
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple


class ThreatLevel(Enum):
    """Severity of detected threats."""

    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class SecurityEvent:
    """A single security audit event."""

    event_type: str
    threat_level: ThreatLevel
    details: str
    input_text: str
    blocked: bool
    timestamp: float = field(default_factory=time.time)


@dataclass
class SecurityConfig:
    """Configuration for the security gate."""

    db_path: str = "graxia_security.db"
    failure_threshold: int = 5
    circuit_open_duration: float = 60.0
    max_tool_calls_per_request: int = 50
    enabled: bool = True


# --- Prompt Injection Patterns ---
PROMPT_INJECTION_PATTERNS = [
    r"ignore\s+(all\s+)?(previous|prior|above|earlier)\s+(instructions?|prompts?|rules?)",
    r"disregard\s+(all\s+)?(previous|prior|above)\s+(instructions?|context)",
    r"you\s+are\s+now\s+(a|an|the)\s+\w+",
    r"new\s+(instructions?|system\s*prompt|role)\s*:",
    r"override\s+(your|the|all)\s+(instructions?|rules?|safety)",
    r"(reveal|show|display|print)\s+(your|the)\s+(system\s*prompt|instructions?|rules?)",
    r"what\s+(are|is)\s+your\s+(system\s*prompt|instructions?|initial\s*prompt)",
    r"act\s+as\s+if\s+you\s+(have|had)\s+no\s+(restrictions?|rules?|limits?)",
    r"pretend\s+you\s+(are|were)\s+(unrestricted|without\s+rules?|free)",
    r"(bypass|skip|disable|turn\s*off)\s+(your\s+)?(safety|security|filter|guard)",
]

# --- Exfiltration Patterns ---
EXFILTRATION_PATTERNS = [
    r"(send|email|upload|post|transmit)\s+(this|all|the|every)\s+(data|info|file|content|code)",
    r"(copy|move)\s+(all|the|everything)\s+to\s+(an?\s+)?(external|remote|other)",
    r"(curl|wget|fetch)\s+(https?://[^\s]+)",
    r"base64\s*(encode|decode)\s+(and\s+)?(send|transmit|upload)",
    r"(exfil|exfiltrate|steal|leak)\s+(data|information|secrets?)",
    r"write\s+(to|into)\s+(a\s+)?(http|ftp|s3|cloud)",
]

# --- Escalation Patterns ---
ESCALATION_PATTERNS = [
    r"(sudo|su\s+-|run\s+as\s+admin|administrator|elevated)",
    r"(chmod|chown)\s+((777|0777|a\+x|o\+w)\s+)",
    r"(rm\s+-rf\s+/|rmdir\s+/[a-z]|del\s+/[a-z]:\\\\)",
    r"(format\s+[a-z]:|mkfs\.|fdisk|diskpart)",
    r"(shutdown|reboot|halt|poweroff)\s+(-[hHr]|--halt|--reboot)",
    r"(drop\s+table|truncate\s+table|delete\s+from\s+\w+\s+where\s+1)",
    r"(exec|eval|system|passthru|shell_exec)\s*\(",
    r"(\/etc\/passwd|\/etc\/shadow|C:\\Windows\\System32)",
    r"(iptables|firewall)\s+--(flush|delete|drop)",
    r"(kill\s+-9|taskkill\s+/f|Stop-Process\s+-Force)",
]


class SecurityGate:
    """Security gate with validation, filtering, audit, and circuit breaker.

    Features:
    - Prompt injection detection (10 patterns)
    - Exfiltration detection (6 patterns)
    - Escalation detection (10 patterns)
    - Structured audit trail to SQLite
    - Circuit breaker (5 failures -> open 60s)
    - Rate limiting (50 tool calls per request)
    """

    def __init__(self, config: Optional[SecurityConfig] = None):
        self.config = config or SecurityConfig()
        self.conn = sqlite3.connect(self.config.db_path)
        self.conn.row_factory = sqlite3.Row
        self._init_db()

        self._circuit_open_until: float = 0.0
        self._failure_count: int = 0
        self._tool_call_counts: Dict[str, int] = {}

        self._injection_re = [re.compile(p, re.IGNORECASE) for p in PROMPT_INJECTION_PATTERNS]
        self._exfil_re = [re.compile(p, re.IGNORECASE) for p in EXFILTRATION_PATTERNS]
        self._escalation_re = [re.compile(p, re.IGNORECASE) for p in ESCALATION_PATTERNS]

    def _init_db(self) -> None:
        """Initialize audit log table."""
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp REAL NOT NULL,
                event_type TEXT NOT NULL,
                threat_level TEXT NOT NULL,
                details TEXT NOT NULL,
                input_text TEXT NOT NULL,
                blocked INTEGER NOT NULL
            )
            """
        )
        self.conn.commit()

    def _record_event(self, event: SecurityEvent) -> None:
        """Write a security event to the audit log."""
        self.conn.execute(
            """
            INSERT INTO audit_log (timestamp, event_type, threat_level, details, input_text, blocked)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                event.timestamp,
                event.event_type,
                event.threat_level.value,
                event.details,
                event.input_text[:1000],
                1 if event.blocked else 0,
            ),
        )
        self.conn.commit()

    def _check_circuit(self) -> bool:
        """Check if circuit breaker is open. Returns True if blocked."""
        if self._failure_count >= self.config.failure_threshold:
            if time.time() < self._circuit_open_until:
                return True
            self._failure_count = 0
        return False

    def _trip_circuit(self) -> None:
        """Trip the circuit breaker."""
        self._failure_count += 1
        self._circuit_open_until = time.time() + self.config.circuit_open_duration

    def validate_input(self, text: str) -> Tuple[bool, ThreatLevel, str]:
        """Check text for prompt injection patterns.

        Returns:
            (safe, threat_level, details)
        """
        if not self.config.enabled:
            return True, ThreatLevel.NONE, ""

        for i, pattern in enumerate(self._injection_re):
            match = pattern.search(text)
            if match:
                level = ThreatLevel.CRITICAL
                details = f"Prompt injection detected (pattern {i + 1}): '{match.group()}'"
                event = SecurityEvent(
                    event_type="prompt_injection",
                    threat_level=level,
                    details=details,
                    input_text=text,
                    blocked=True,
                )
                self._record_event(event)
                self._trip_circuit()
                return False, level, details

        return True, ThreatLevel.NONE, ""

    def filter_content(self, text: str) -> Tuple[bool, ThreatLevel, str]:
        """Check text for exfiltration and escalation patterns.

        Returns:
            (safe, threat_level, details)
        """
        if not self.config.enabled:
            return True, ThreatLevel.NONE, ""

        for i, pattern in enumerate(self._exfil_re):
            match = pattern.search(text)
            if match:
                level = ThreatLevel.HIGH
                details = f"Exfiltration attempt detected (pattern {i + 1}): '{match.group()}'"
                event = SecurityEvent(
                    event_type="exfiltration",
                    threat_level=level,
                    details=details,
                    input_text=text,
                    blocked=True,
                )
                self._record_event(event)
                self._trip_circuit()
                return False, level, details

        for i, pattern in enumerate(self._escalation_re):
            match = pattern.search(text)
            if match:
                level = ThreatLevel.HIGH
                details = f"Escalation attempt detected (pattern {i + 1}): '{match.group()}'"
                event = SecurityEvent(
                    event_type="escalation",
                    threat_level=level,
                    details=details,
                    input_text=text,
                    blocked=True,
                )
                self._record_event(event)
                self._trip_circuit()
                return False, level, details

        return True, ThreatLevel.NONE, ""

    def check_tool_call(self, request_id: str, tool_name: str) -> Tuple[bool, str]:
        """Rate limit tool calls per request.

        Returns:
            (allowed, details)
        """
        if not self.config.enabled:
            return True, ""

        key = request_id
        count = self._tool_call_counts.get(key, 0)

        if count >= self.config.max_tool_calls_per_request:
            details = f"Rate limit exceeded: {count}/{self.config.max_tool_calls_per_request} tool calls"
            event = SecurityEvent(
                event_type="rate_limit",
                threat_level=ThreatLevel.MEDIUM,
                details=details,
                input_text=f"tool={tool_name}",
                blocked=True,
            )
            self._record_event(event)
            return False, details

        self._tool_call_counts[key] = count + 1
        return True, ""

    def reset_request(self, request_id: str) -> None:
        """Reset rate limit counter for a request."""
        self._tool_call_counts.pop(request_id, None)

    def check(self, text: str) -> Tuple[bool, ThreatLevel, str]:
        """Full security check: circuit breaker + injection + exfiltration + escalation.

        Returns:
            (safe, threat_level, details)
        """
        if self._check_circuit():
            return False, ThreatLevel.CRITICAL, "Circuit breaker open: too many failures"

        safe, level, details = self.validate_input(text)
        if not safe:
            return False, level, details

        safe, level, details = self.filter_content(text)
        if not safe:
            return False, level, details

        return True, ThreatLevel.NONE, ""

    def get_audit_log(
        self,
        limit: int = 100,
        event_type: Optional[str] = None,
        min_level: Optional[ThreatLevel] = None,
    ) -> List[Dict[str, Any]]:
        """Query the audit log."""
        query = "SELECT * FROM audit_log WHERE 1=1"
        params: list = []

        if event_type:
            query += " AND event_type = ?"
            params.append(event_type)

        if min_level:
            levels = [l.value for l in ThreatLevel if ThreatLevel.__members__.get(l.name, ThreatLevel.NONE) >= min_level]
            placeholders = ",".join("?" * len(levels))
            query += f" AND threat_level IN ({placeholders})"
            params.extend(levels)

        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)

        cur = self.conn.execute(query, params)
        return [dict(row) for row in cur.fetchall()]

    def stats(self) -> Dict[str, Any]:
        """Get security statistics."""
        cur = self.conn.execute(
            """
            SELECT
                COUNT(*) as total_events,
                SUM(CASE WHEN blocked = 1 THEN 1 ELSE 0 END) as blocked_count,
                SUM(CASE WHEN blocked = 0 THEN 1 ELSE 0 END) as allowed_count
            FROM audit_log
            """
        )
        row = cur.fetchone()

        cur2 = self.conn.execute(
            "SELECT threat_level, COUNT(*) as cnt FROM audit_log GROUP BY threat_level"
        )
        by_level = {r["threat_level"]: r["cnt"] for r in cur2.fetchall()}

        return {
            "total_events": row["total_events"],
            "blocked_count": row["blocked_count"],
            "allowed_count": row["allowed_count"],
            "by_threat_level": by_level,
            "circuit_open": time.time() < self._circuit_open_until,
            "failure_count": self._failure_count,
        }

    def close(self) -> None:
        """Close the database connection."""
        self.conn.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
