"""Pydantic request/response models for the AI Travel Planner API."""

import re
from datetime import date
from typing import Any

from pydantic import BaseModel, Field, field_validator

from regions import REGIONS


class TripRequest(BaseModel):
    start_date: date
    end_date: date
    travelers: int = Field(gt=0)
    budget_per_person: float = Field(gt=0)
    currency: str = "USD"
    regions: list[str] = Field(default_factory=lambda: list(REGIONS))

    @field_validator("regions")
    @classmethod
    def _validate_regions(cls, value: list[str]) -> list[str]:
        if not value:
            return list(REGIONS)
        if len(value) > len(REGIONS):
            raise ValueError(f"At most {len(REGIONS)} regions can be selected.")
        unknown = [r for r in value if r not in REGIONS]
        if unknown:
            raise ValueError(f"Unknown region(s): {', '.join(unknown)}")
        if len(set(value)) != len(value):
            raise ValueError("Duplicate regions are not allowed.")
        return value


class RegionSummary(BaseModel):
    region: str
    verdict: str


class Recommendation(BaseModel):
    recommended_region: str
    destination: str
    reasoning: str
    itinerary: list | dict | str | None = None
    estimated_total_cost_per_person: float | None = None
    region_summaries: list[RegionSummary] = Field(default_factory=list)

    @field_validator("estimated_total_cost_per_person", mode="before")
    @classmethod
    def _coerce_cost(cls, value: Any) -> Any:
        """The supervisor LLM sometimes returns "$1,920 USD" instead of a
        plain number - observed in practice with Gemini. Extract the number."""
        if value is None or isinstance(value, (int, float)):
            return value
        if isinstance(value, str):
            match = re.search(r"[-+]?\d[\d,]*\.?\d*", value)
            if match:
                return float(match.group().replace(",", ""))
        return None

    @field_validator("region_summaries", mode="before")
    @classmethod
    def _normalize_summaries(cls, value: Any) -> Any:
        """The supervisor LLM sometimes returns {"region": "verdict", ...}
        instead of the requested [{"region": ..., "verdict": ...}, ...] -
        observed in practice with Gemini. Accept both shapes."""
        if isinstance(value, dict):
            return [{"region": region, "verdict": verdict} for region, verdict in value.items()]
        return value


class PlanTripResponse(BaseModel):
    run_id: str
    recommendation: Recommendation


class TraceEvent(BaseModel):
    type: str
    agent: str | None = None
    thought: str | None = None
    tool: str | None = None
    tool_input: str | None = None
    output: str | None = None
    timestamp: str


class TraceResponse(BaseModel):
    run_id: str
    trace: list[TraceEvent]
