"""Enterprise Agent OS — Output Validation.

Validates agent outputs before returning to user.
Checks for: safety, format, completeness, token limits.
"""
from __future__ import annotations
import re
from dataclasses import dataclass
from typing import Any, Optional
from ..core.logging import get_logger

logger = get_logger("output_validator")


@dataclass
class ValidationResult:
    """Result of output validation."""
    valid: bool
    errors: list[str]
    warnings: list[str]
    sanitized_output: str
    truncated: bool = False
    safety_blocked: bool = False


class OutputValidator:
    """
    Validates agent outputs before returning to user.
    Enforces safety, format, and completeness rules.
    """

    # Patterns that should never appear in output
    DANGEROUS_PATTERNS = [
        r"(?i)rm\s+-rf\s+/",
        r"(?i)DROP\s+TABLE",
        r"(?i)DELETE\s+FROM.*WHERE\s+1",
        r"(?i)TRUNCATE\s+TABLE",
        r"(?i)password\s*=\s*['\"][^'\"]+['\"]",
        r"(?i)secret\s*=\s*['\"][^'\"]+['\"]",
        r"(?i)api[_-]?key\s*=\s*['\"][^'\"]+['\"]",
        r"(?i)BEGIN\s+(RSA|DSA|EC)\s+PRIVATE\s+KEY",
    ]

    # Patterns that indicate leaked secrets
    SECRET_PATTERNS = [
        r"sk-[a-zA-Z0-9]{20,}",  # OpenAI
        r"ghp_[a-zA-Z0-9]{36}",  # GitHub
        r"AKIA[A-Z0-9]{16}",  # AWS
        r"xox[bpsa]-[a-zA-Z0-9-]+",  # Slack
    ]

    def __init__(self, max_tokens: int = 4096, max_output_chars: int = 50000):
        self.max_tokens = max_tokens
        self.max_output_chars = max_output_chars

    def validate(
        self,
        output: str,
        intent: str = "",
        context: Optional[dict[str, Any]] = None,
    ) -> ValidationResult:
        """
        Validate agent output.

        Args:
            output: The agent's output text
            intent: The original intent (for context-aware validation)
            context: Additional context (tool used, etc.)

        Returns:
            ValidationResult with validity, errors, warnings, sanitized output
        """
        errors = []
        warnings = []
        sanitized = output
        truncated = False
        safety_blocked = False

        # 1. Safety check - dangerous commands
        for pattern in self.DANGEROUS_PATTERNS:
            if re.search(pattern, output):
                safety_blocked = True
                errors.append(f"Output contains dangerous pattern: {pattern[:30]}...")
                logger.warning("safety_blocked", pattern=pattern[:30])

        # 2. Secret detection
        for pattern in self.SECRET_PATTERNS:
            if re.search(pattern, output):
                # Redact the secret
                sanitized = re.sub(pattern, "[REDACTED]", sanitized)
                warnings.append("Output contained a secret - redacted")
                logger.warning("secret_redacted", pattern=pattern[:20])

        # 3. Length check
        if len(output) > self.max_output_chars:
            truncated = True
            sanitized = output[:self.max_output_chars] + "\n\n[... truncated ...]"
            warnings.append(f"Output truncated from {len(output)} to {self.max_output_chars} chars")

        # 4. Empty output check
        if not output or not output.strip():
            warnings.append("Output is empty")

        # 5. Format checks based on intent
        if intent == "code":
            # Code should have some structure
            if len(output.strip().split("\n")) < 2:
                warnings.append("Code output is very short (< 2 lines)")

        elif intent == "test":
            # Tests should have assertions
            if "assert" not in output.lower() and "expect" not in output.lower():
                warnings.append("Test output may be missing assertions")

        # 6. JSON format check
        if context and context.get("format") == "json":
            import json
            try:
                json.loads(output)
            except json.JSONDecodeError:
                errors.append("Output is not valid JSON")

        valid = len(errors) == 0 and not safety_blocked

        result = ValidationResult(
            valid=valid,
            errors=errors,
            warnings=warnings,
            sanitized_output=sanitized,
            truncated=truncated,
            safety_blocked=safety_blocked,
        )

        logger.info(
            "output_validated",
            valid=valid,
            errors=len(errors),
            warnings=len(warnings),
            truncated=truncated,
            safety_blocked=safety_blocked,
        )
        return result

    def validate_tool_output(
        self,
        tool_name: str,
        output: Any,
        success: bool,
    ) -> ValidationResult:
        """Validate output from a tool execution."""
        output_str = str(output) if output else ""
        return self.validate(
            output_str,
            context={"tool": tool_name, "success": success},
        )
