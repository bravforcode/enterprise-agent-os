"""Enterprise Agent OS — Database models."""
from __future__ import annotations
import uuid
from datetime import datetime
from typing import Optional
from sqlalchemy import (
    Column, String, Text, Integer, Float, Boolean, DateTime, JSON,
    ForeignKey, Index, Enum as SAEnum,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, relationship
import enum


class Base(DeclarativeBase):
    pass


class RunStatus(str, enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"
    AWAITING_APPROVAL = "awaiting_approval"


class RiskLevel(str, enum.Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


# --- Agent Run ---
class AgentRun(Base):
    __tablename__ = "agent_runs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id = Column(UUID(as_uuid=True), ForeignKey("sessions.id"), nullable=False)
    parent_run_id = Column(UUID(as_uuid=True), ForeignKey("agent_runs.id"), nullable=True)
    agent_type = Column(String(100), nullable=False)
    status = Column(SAEnum(RunStatus), default=RunStatus.PENDING, nullable=False)
    risk_level = Column(SAEnum(RiskLevel), default=RiskLevel.LOW)

    # Intent
    user_query = Column(Text, nullable=False)
    classified_intent = Column(String(200))
    classified_domain = Column(String(100))
    confidence = Column(Float)

    # Execution
    selected_skills = Column(JSON, default=list)
    selected_tools = Column(JSON, default=list)
    plan = Column(JSON, default=list)
    result = Column(JSON)
    error = Column(Text)

    # Token tracking
    tokens_input = Column(Integer, default=0)
    tokens_output = Column(Integer, default=0)
    cost_usd = Column(Float, default=0.0)
    model_used = Column(String(100))

    # Timing
    started_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime)
    duration_ms = Column(Integer)

    # Metadata
    metadata = Column(JSON, default=dict)
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("ix_agent_runs_session", "session_id"),
        Index("ix_agent_runs_status", "status"),
        Index("ix_agent_runs_created", "created_at"),
    )


# --- Session ---
class Session(Base):
    __tablename__ = "sessions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    tool = Column(String(50), nullable=False)  # claude, codex, gemini, opencode
    status = Column(String(20), default="active")
    total_tokens = Column(Integer, default=0)
    total_cost_usd = Column(Float, default=0.0)
    created_at = Column(DateTime, default=datetime.utcnow)
    last_active = Column(DateTime, default=datetime.utcnow)

    runs = relationship("AgentRun", back_populates="session")


# --- User ---
class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    username = Column(String(100), unique=True, nullable=False)
    email = Column(String(255), unique=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    is_active = Column(Boolean, default=True)
    is_admin = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    sessions = relationship("Session", back_populates="user")


# --- API Key ---
class APIKey(Base):
    __tablename__ = "api_keys"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    key_hash = Column(String(255), unique=True, nullable=False)
    name = Column(String(100), nullable=False)
    prefix = Column(String(10), nullable=False)  # first 8 chars for identification
    scopes = Column(JSON, default=list)
    expires_at = Column(DateTime)
    last_used_at = Column(DateTime)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)


# --- Skill Registry ---
class Skill(Base):
    __tablename__ = "skills"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(200), unique=True, nullable=False)
    description = Column(Text)
    path = Column(String(500), nullable=False)
    tier = Column(Integer, default=2)
    trust_score = Column(Float, default=1.0)
    triggers = Column(JSON, default=list)
    metadata = Column(JSON, default=dict)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


# --- Tool Registry ---
class Tool(Base):
    __tablename__ = "tools"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(200), unique=True, nullable=False)
    description = Column(Text)
    permission_level = Column(Integer, default=0)  # 0=read, 1=write, 2=exec, 3=db, 4=prod
    risk_level = Column(SAEnum(RiskLevel), default=RiskLevel.LOW)
    requires_approval = Column(Boolean, default=False)
    schema_def = Column(JSON)  # JSON Schema for tool parameters
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)


# --- Token Ledger ---
class TokenLedger(Base):
    __tablename__ = "token_ledger"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id = Column(UUID(as_uuid=True), ForeignKey("agent_runs.id"), nullable=False)
    model = Column(String(100), nullable=False)
    tokens_input = Column(Integer, nullable=False)
    tokens_output = Column(Integer, nullable=False)
    cost_usd = Column(Float, nullable=False)
    cached = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("ix_token_ledger_run", "run_id"),
        Index("ix_token_ledger_created", "created_at"),
    )


# --- Memory Entry ---
class MemoryEntry(Base):
    __tablename__ = "memory_entries"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    layer = Column(String(50), nullable=False)  # preference, episodic, semantic, procedural, failure
    content = Column(Text, nullable=False)
    embedding_id = Column(String(100))  # Qdrant point ID
    metadata = Column(JSON, default=dict)
    access_count = Column(Integer, default=0)
    last_accessed = Column(DateTime)
    decay_score = Column(Float, default=1.0)
    created_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime)

    __table_args__ = (
        Index("ix_memory_user_layer", "user_id", "layer"),
    )
