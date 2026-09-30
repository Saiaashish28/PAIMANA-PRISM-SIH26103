"""Pydantic request/response models for the PRISM REST API."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

RAG = Literal["Red", "Amber", "Green", "Completed"]


class Health(BaseModel):
    status: Literal["ready", "warming_up", "error"]
    detail: str | None = None
    as_of: str | None = None
    build_seconds: float | None = None
    llm: dict | None = None
    data_source: str | None = None
    building: bool = False
    fingerprint: str | None = None
    watching: dict | None = None


class ProjectSummary(BaseModel):
    project_id: str
    project_name: str
    ministry: str
    sector: str
    state: str
    status: str
    rag: RAG
    trajectory: str
    risk_composite: float
    risk_cost: float
    risk_schedule: float
    risk_implementation: float
    risk_velocity: float
    priority_index: float
    progress: float
    cost_growth_pct: float
    slip_months: float
    original_cost_cr: float
    revised_cost_cr: float
    data_confidence: float
    confidence_grade: str
    n_warnings: int
    latitude: float | None = None
    longitude: float | None = None


class ProjectPage(BaseModel):
    total: int
    items: list[ProjectSummary]


class AskRequest(BaseModel):
    question: str = Field(min_length=2, max_length=1000)
    project_id: str | None = None
    history: list[dict] = Field(default_factory=list, description="previous turns: [{role, content}]")


class InterventionCreate(BaseModel):
    project_id: str
    action_type: Literal["pmg_review", "funds_released", "state_coordination", "contractor_action",
                         "clearance_expedited", "site_inspection", "other"]
    description: str = Field(min_length=3, max_length=2000)
    authority: str | None = Field(default=None, max_length=200)
    intervention_month: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}$",
                                           description="YYYY-MM; defaults to the latest reporting month")
