"""Enterprise Agent OS — Basic Approval Flow.

Human-in-the-loop approval for high-risk operations.
"""
from __future__ import annotations
import uuid
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional
from ..core.models import RunStatus, RiskLevel
from ..core.logging import get_logger

logger = get_logger("approval_flow")


class ApprovalStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"


@dataclass
class ApprovalRequest:
    """A pending approval request."""
    id: str
    run_id: str
    step_id: str
    tool_name: str
    description: str
    params: dict[str, Any]
    risk_level: RiskLevel
    status: ApprovalStatus = ApprovalStatus.PENDING
    requested_at: datetime = field(default_factory=datetime.utcnow)
    expires_at: Optional[datetime] = None
    reviewed_at: Optional[datetime] = None
    reviewer_notes: str = ""


class ApprovalFlow:
    """
    Manages human approval for high-risk operations.

    Flow:
    1. Agent requests action that needs approval
    2. ApprovalRequest created with PENDING status
    3. Human reviews via API/UI
    4. Human approves/rejects
    5. Agent resumes or cancels
    """

    def __init__(self, approval_timeout_minutes: int = 30):
        self.pending: dict[str, ApprovalRequest] = {}
        self.history: list[ApprovalRequest] = []
        self.timeout_minutes = approval_timeout_minutes

    def request_approval(
        self,
        run_id: str,
        step_id: str,
        tool_name: str,
        description: str,
        params: dict[str, Any],
        risk_level: RiskLevel = RiskLevel.MEDIUM,
    ) -> ApprovalRequest:
        """Create an approval request."""
        request = ApprovalRequest(
            id=str(uuid.uuid4()),
            run_id=run_id,
            step_id=step_id,
            tool_name=tool_name,
            description=description,
            params=params,
            risk_level=risk_level,
            expires_at=datetime.utcnow() + timedelta(minutes=self.timeout_minutes),
        )
        self.pending[request.id] = request
        logger.info(
            "approval_requested",
            request_id=request.id,
            tool=tool_name,
            risk=risk_level.value,
        )
        return request

    def approve(
        self,
        request_id: str,
        reviewer_notes: str = "",
    ) -> Optional[ApprovalRequest]:
        """Approve a pending request."""
        request = self.pending.get(request_id)
        if not request:
            return None

        request.status = ApprovalStatus.APPROVED
        request.reviewed_at = datetime.utcnow()
        request.reviewer_notes = reviewer_notes
        self.history.append(request)
        del self.pending[request_id]

        logger.info("approval_granted", request_id=request_id, tool=request.tool_name)
        return request

    def reject(
        self,
        request_id: str,
        reviewer_notes: str = "",
    ) -> Optional[ApprovalRequest]:
        """Reject a pending request."""
        request = self.pending.get(request_id)
        if not request:
            return None

        request.status = ApprovalStatus.REJECTED
        request.reviewed_at = datetime.utcnow()
        request.reviewer_notes = reviewer_notes
        self.history.append(request)
        del self.pending[request_id]

        logger.info("approval_rejected", request_id=request_id, tool=request.tool_name)
        return request

    def check_expired(self) -> list[ApprovalRequest]:
        """Check for expired requests."""
        now = datetime.utcnow()
        expired = []
        for req_id, request in list(self.pending.items()):
            if request.expires_at and request.expires_at < now:
                request.status = ApprovalStatus.EXPIRED
                self.history.append(request)
                expired.append(request)
                del self.pending[req_id]
                logger.info("approval_expired", request_id=req_id)
        return expired

    def get_pending(self, run_id: Optional[str] = None) -> list[ApprovalRequest]:
        """Get pending approval requests."""
        requests = list(self.pending.values())
        if run_id:
            requests = [r for r in requests if r.run_id == run_id]
        return requests

    def get_history(
        self,
        limit: int = 50,
        status: Optional[ApprovalStatus] = None,
    ) -> list[ApprovalRequest]:
        """Get approval history."""
        history = self.history
        if status:
            history = [r for r in history if r.status == status]
        return history[-limit:]
