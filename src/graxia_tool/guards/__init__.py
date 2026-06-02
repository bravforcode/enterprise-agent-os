"""Enterprise Agent OS — Guardrails module.

Input validation, output sanitization, safety checks.
"""
from __future__ import annotations
import re
from dataclasses import dataclass, field
from typing import Any, Optional
from ..core.logging import get_logger

logger = get_logger("guards")


@dataclass
class GuardrailResult:
    """Result of a guardrail check."""
    passed: bool
    reason: str
    severity: str = "info"  # "info", "warning", "block"
    metadata: dict[str, Any] = field(default_factory=dict)


# --- Input Guards ---
INJECTION_PATTERNS = [
    r"ignore\s+(previous|all|above|prior)",
    r"system\s+prompt",
    r"reveal\s+your\s+instructions",
    r"disregard\s+(previous|all|above)",
    r"new\s+role",
    r"act\s+as",
    r"jailbreak",
    r"do\s+anything\s+now",
    r"DAN\s+mode",
]

HARMFUL_PATTERNS = [
    r"how\s+to\s+(make|build|create)\s+(a\s+)?(bomb|explosive|weapon|poison)",
    r"hack\s+into",
    r"steal\s+(password|credentials|account)",
    r"bypass\s+(auth|security|login)",
    r"phishing\s+email",
]


def check_injection(text: str) -> GuardrailResult:
    """Check for prompt injection attempts."""
    text_lower = text.lower()
    for pattern in INJECTION_PATTERNS:
        if re.search(pattern, text_lower):
            return GuardrailResult(
                passed=False,
                reason=f"Potential prompt injection detected: {pattern}",
                severity="block",
                metadata={"pattern": pattern},
            )
    return GuardrailResult(passed=True, reason="No injection detected")


def check_harmful(text: str) -> GuardrailResult:
    """Check for harmful content requests."""
    text_lower = text.lower()
    for pattern in HARMFUL_PATTERNS:
        if re.search(pattern, text_lower):
            return GuardrailResult(
                passed=False,
                reason=f"Potentially harmful request: {pattern}",
                severity="block",
                metadata={"pattern": pattern},
            )
    return GuardrailResult(passed=True, reason="No harmful content detected")


def check_length(text: str, max_chars: int = 50000) -> GuardrailResult:
    """Check input length."""
    if len(text) > max_chars:
        return GuardrailResult(
            passed=False,
            reason=f"Input too long: {len(text)} chars (max {max_chars})",
            severity="block",
        )
    return GuardrailResult(passed=True, reason="Length OK")


def check_input(text: str) -> GuardrailResult:
    """Run all input guardrails."""
    # Length
    r = check_length(text)
    if not r.passed:
        return r
    # Injection
    r = check_injection(text)
    if not r.passed:
        return r
    # Harmful
    r = check_harmful(text)
    if not r.passed:
        return r
    return GuardrailResult(passed=True, reason="All input checks passed")


# --- Output Guards ---
def check_pii(text: str) -> GuardrailResult:
    """Check for PII in output."""
    # Email
    if re.search(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b", text):
        return GuardrailResult(
            passed=False,
            reason="Email address detected in output",
            severity="warning",
        )
    # Phone
    if re.search(r"\b\d{3}[-.]?\d{3}[-.]?\d{4}\b", text):
        return GuardrailResult(
            passed=False,
            reason="Phone number detected in output",
            severity="warning",
        )
    # SSN
    if re.search(r"\b\d{3}-\d{2}-\d{4}\b", text):
        return GuardrailResult(
            passed=False,
            reason="SSN detected in output",
            severity="block",
        )
    return GuardrailResult(passed=True, reason="No PII detected")


def redact_pii(text: str) -> str:
    """Redact PII from text."""
    # Email
    text = re.sub(
        r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b",
        "[EMAIL]",
        text,
    )
    # Phone
    text = re.sub(r"\b\d{3}[-.]?\d{3}[-.]?\d{4}\b", "[PHONE]", text)
    # SSN
    text = re.sub(r"\b\d{3}-\d{2}-\d{4}\b", "[SSN]", text)
    return text


def check_output(text: str) -> GuardrailResult:
    """Run all output guardrails."""
    r = check_pii(text)
    if not r.passed:
        return r
    return GuardrailResult(passed=True, reason="All output checks passed")
