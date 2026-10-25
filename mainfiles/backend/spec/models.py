"""Spec pipeline v2 tables (register on Base.metadata on import).

Kept separate from spec_chain's tables so the v2 pipeline never
migrates or renames the old chain's ledger: old pipelines keep
working, v2 pipelines get TDD evidence, GreenContract verifications,
and review packages of their own.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text

from ..database import Base


def new_spec2_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


class SpecV2Pipeline(Base):
    __tablename__ = "spec_v2_pipelines"

    id = Column(String, primary_key=True)
    title = Column(String, nullable=False)
    goal = Column(Text, nullable=False, default="")
    current_stage = Column(String, nullable=False, default="")
    created_at = Column(DateTime, default=lambda: datetime.now(UTC))


class SpecV2Stage(Base):
    __tablename__ = "spec_v2_stages"

    id = Column(String, primary_key=True)
    pipeline_id = Column(String, ForeignKey("spec_v2_pipelines.id"), nullable=False)
    stage = Column(String, nullable=False)
    artifact = Column(Text, nullable=False, default="")
    position = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, default=lambda: datetime.now(UTC))


class SpecV2TaskEvidence(Base):
    """Per-task TDD evidence: RED output + GREEN output for one command.

    ``tdd_ok`` is set ONLY by validate_tdd_evidence in the route
    layer — never by a caller-supplied flag.
    """
    __tablename__ = "spec_v2_task_evidence"

    id = Column(String, primary_key=True)
    pipeline_id = Column(String, ForeignKey("spec_v2_pipelines.id"), nullable=False)
    task_id = Column(String, nullable=False)
    diff = Column(Text, nullable=False, default="")
    test_command = Column(String, nullable=False, default="")
    red_output = Column(Text, nullable=False, default="")
    green_output = Column(Text, nullable=False, default="")
    tdd_ok = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, default=lambda: datetime.now(UTC))


class SpecV2ReviewPackage(Base):
    __tablename__ = "spec_v2_review_packages"

    id = Column(String, primary_key=True)
    pipeline_id = Column(String, ForeignKey("spec_v2_pipelines.id"), nullable=False)
    base_ref = Column(String, nullable=False, default="")
    head_ref = Column(String, nullable=False, default="")
    diff = Column(Text, nullable=False, default="")
    created_at = Column(DateTime, default=lambda: datetime.now(UTC))


class SpecV2Review(Base):
    __tablename__ = "spec_v2_reviews"

    id = Column(String, primary_key=True)
    pipeline_id = Column(String, ForeignKey("spec_v2_pipelines.id"), nullable=False)
    axis = Column(String, nullable=False)  # spec | quality
    verdict = Column(String, nullable=False)  # pass | fail
    review_package_id = Column(String, nullable=False)
    artifact = Column(Text, nullable=False, default="")
    created_at = Column(DateTime, default=lambda: datetime.now(UTC))


class SpecV2Verification(Base):
    """GreenContract verification record (see backend/qa/greencontract)."""
    __tablename__ = "spec_v2_verifications"

    id = Column(String, primary_key=True)
    pipeline_id = Column(String, ForeignKey("spec_v2_pipelines.id"), nullable=False)
    level = Column(String, nullable=False)  # targeted|package|integration|full
    test_command = Column(String, nullable=False, default="")
    output = Column(Text, nullable=False, default="")
    passed = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, default=lambda: datetime.now(UTC))
