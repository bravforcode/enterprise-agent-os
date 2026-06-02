"""Security hardening for graxia_tool — input validation, auth, secret handling.

This module provides:
1. Input validation at system boundaries
2. Secret detection and redaction
3. Injection prevention
4. Rate limiting
5. Audit logging
"""
from __future__ import annotations

import hashlib
import re
import time
from dataclasses import dataclass, field
from typing import Any, Optional

try:
    from ..core.logging import get_logger
    logger = get_logger("security")
except ImportError:
    import logging
    logger = logging.getLogger("security")


# --- Secret Detection ---

SECRET_PATTERNS = [
    (r"sk-[a-zA-Z0-9]{20,}", "OpenAI API Key"),
    (r"ghp_[a-zA-Z0-9]{36}", "GitHub Personal Access Token"),
    (r"AKIA[A-Z0-9]{16}", "AWS Access Key"),
    (r"xox[bpsa]-[a-zA-Z0-9-]+", "Slack Token"),
    (r"password\s*=\s*['\"][^'\"]+['\"]", "Hardcoded Password"),
    (r"secret\s*=\s*['\"][^'\"]+['\"]", "Hardcoded Secret"),
    (r"api[_-]?key\s*=\s*['\"][^'\"]+['\"]", "API Key"),
    (r"BEGIN\s+(RSA|DSA|EC)\s+PRIVATE\s+KEY", "Private Key"),
]


@dataclass
class SecretScanResult:
    """Result of secret scanning."""
    found: bool
    secrets: list[dict[str, str]] = field(default_factory=list)
    redacted_text: str = ""


def scan_for_secrets(text: str) -> SecretScanResult:
    """Scan text for secrets and return redacted version."""
    secrets = []
    redacted = text
    
    for pattern, secret_type in SECRET_PATTERNS:
        matches = re.finditer(pattern, text, re.IGNORECASE)
        for match in matches:
            secrets.append({
                "type": secret_type,
                "position": match.start(),
                "length": len(match.group()),
            })
            # Redact the secret
            redacted = redacted.replace(match.group(), f"[REDACTED:{secret_type}]")
    
    return SecretScanResult(
        found=len(secrets) > 0,
        secrets=secrets,
        redacted_text=redacted
    )


# --- Injection Prevention ---

INJECTION_PATTERNS = [
    (r"ignore\s+(previous|all|above|prior)", "Prompt Injection"),
    (r"system\s+prompt", "System Prompt Leak"),
    (r"reveal\s+your\s+instructions", "Instruction Leak"),
    (r"disregard\s+(previous|all|above)", "Instruction Override"),
    (r"new\s+role", "Role Injection"),
    (r"act\s+as", "Role Injection"),
    (r"jailbreak", "Jailbreak Attempt"),
    (r"do\s+anything\s+now", "DAN Attempt"),
    (r"DAN\s+mode", "DAN Mode Attempt"),
    (r"dan\s+mode", "DAN Mode Attempt"),
]


@dataclass
class InjectionCheckResult:
    """Result of injection check."""
    safe: bool
    threats: list[dict[str, str]] = field(default_factory=list)


def check_injection(text: str) -> InjectionCheckResult:
    """Check text for injection attempts."""
    threats = []
    text_lower = text.lower()
    
    for pattern, threat_type in INJECTION_PATTERNS:
        if re.search(pattern, text_lower):
            threats.append({
                "type": threat_type,
                "pattern": pattern,
            })
    
    return InjectionCheckResult(
        safe=len(threats) == 0,
        threats=threats
    )


# --- Input Validation ---

@dataclass
class ValidationResult:
    """Result of input validation."""
    valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    sanitized: str = ""


def validate_input(
    text: str,
    max_length: int = 100000,
    allow_html: bool = False,
    check_secrets: bool = True,
    check_injection_enabled: bool = True,
) -> ValidationResult:
    """Validate and sanitize input text.
    
    Args:
        text: Input text to validate
        max_length: Maximum allowed length
        allow_html: Whether to allow HTML tags
        check_secrets: Whether to scan for secrets
        check_injection_enabled: Whether to check for injection attempts
    
    Returns:
        ValidationResult with validation status and sanitized text
    """
    errors = []
    warnings = []
    sanitized = text
    
    # 1. Length check
    if len(text) > max_length:
        errors.append(f"Input too long: {len(text)} > {max_length}")
        sanitized = text[:max_length]
    
    # 2. HTML check
    if not allow_html:
        html_pattern = r"<[^>]+>"
        if re.search(html_pattern, text):
            warnings.append("HTML tags detected and removed")
            sanitized = re.sub(html_pattern, "", sanitized)
    
    # 3. Secret check
    if check_secrets:
        secret_result = scan_for_secrets(sanitized)
        if secret_result.found:
            warnings.append(f"Found {len(secret_result.secrets)} secrets")
            sanitized = secret_result.redacted_text
    
    # 4. Injection check
    if check_injection_enabled:
        injection_result = check_injection(sanitized)
        if not injection_result.safe:
            errors.append(f"Injection detected: {len(injection_result.threats)} threats")
    
    # 5. Empty check
    if not sanitized.strip():
        warnings.append("Input is empty after sanitization")
    
    return ValidationResult(
        valid=len(errors) == 0,
        errors=errors,
        warnings=warnings,
        sanitized=sanitized
    )


# --- Rate Limiting ---

class RateLimiter:
    """Simple in-memory rate limiter."""
    
    def __init__(self, max_requests: int = 100, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._requests: dict[str, list[float]] = {}
    
    def check(self, key: str) -> bool:
        """Check if request is allowed."""
        now = time.time()
        cutoff = now - self.window_seconds
        
        # Clean old requests
        if key in self._requests:
            self._requests[key] = [t for t in self._requests[key] if t > cutoff]
        else:
            self._requests[key] = []
        
        # Check limit
        if len(self._requests[key]) >= self.max_requests:
            return False
        
        # Record request
        self._requests[key].append(now)
        return True
    
    def get_remaining(self, key: str) -> int:
        """Get remaining requests in window."""
        now = time.time()
        cutoff = now - self.window_seconds
        
        if key not in self._requests:
            return self.max_requests
        
        recent = [t for t in self._requests[key] if t > cutoff]
        return max(0, self.max_requests - len(recent))


# --- Audit Logging ---

@dataclass
class AuditEvent:
    """Security audit event."""
    timestamp: float
    event_type: str
    user_id: str
    action: str
    resource: str
    result: str
    metadata: dict[str, Any] = field(default_factory=dict)


class AuditLogger:
    """Security audit logger."""
    
    def __init__(self):
        self._events: list[AuditEvent] = []
    
    def log(
        self,
        event_type: str,
        user_id: str,
        action: str,
        resource: str,
        result: str,
        metadata: Optional[dict[str, Any]] = None,
    ) -> None:
        """Log a security event."""
        event = AuditEvent(
            timestamp=time.time(),
            event_type=event_type,
            user_id=user_id,
            action=action,
            resource=resource,
            result=result,
            metadata=metadata or {}
        )
        self._events.append(event)
        logger.info(
            "audit_event",
            event_type=event_type,
            user_id=user_id,
            action=action,
            resource=resource,
            result=result
        )
    
    def get_events(
        self,
        user_id: Optional[str] = None,
        event_type: Optional[str] = None,
        limit: int = 100,
    ) -> list[AuditEvent]:
        """Get audit events with optional filters."""
        events = self._events
        
        if user_id:
            events = [e for e in events if e.user_id == user_id]
        
        if event_type:
            events = [e for e in events if e.event_type == event_type]
        
        return events[-limit:]


# --- Password Hashing ---

def hash_password(password: str) -> str:
    """Hash password with salt."""
    salt = hashlib.sha256(str(time.time()).encode()).hexdigest()[:16]
    hashed = hashlib.sha256(f"{salt}{password}".encode()).hexdigest()
    return f"{salt}:{hashed}"


def verify_password(password: str, hashed: str) -> bool:
    """Verify password against hash."""
    try:
        salt, expected_hash = hashed.split(":", 1)
        actual_hash = hashlib.sha256(f"{salt}{password}".encode()).hexdigest()
        return actual_hash == expected_hash
    except Exception:
        return False


# --- Security Headers ---

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "X-XSS-Protection": "1; mode=block",
    "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
    "Content-Security-Policy": "default-src 'self'",
    "Referrer-Policy": "strict-origin-when-cross-origin",
}


def get_security_headers() -> dict[str, str]:
    """Get security headers for HTTP responses."""
    return SECURITY_HEADERS.copy()


# --- Input Sanitization ---

def sanitize_for_log(text: str) -> str:
    """Sanitize text for safe logging."""
    # Remove newlines and control characters
    sanitized = re.sub(r'[\x00-\x1f\x7f-\x9f]', '', text)
    # Truncate if too long
    if len(sanitized) > 1000:
        sanitized = sanitized[:1000] + "...[truncated]"
    return sanitized


def sanitize_filename(filename: str) -> str:
    """Sanitize filename to prevent path traversal."""
    # Remove path separators
    sanitized = filename.replace("/", "").replace("\\", "")
    # Remove null bytes
    sanitized = sanitized.replace("\x00", "")
    # Remove special characters
    sanitized = re.sub(r'[^\w\-.]', '_', sanitized)
    # Limit length
    if len(sanitized) > 255:
        sanitized = sanitized[:255]
    return sanitized