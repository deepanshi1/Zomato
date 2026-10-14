"""Request and response models for the recommendation API."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

MAX_LIMIT = 8
MAX_PREFERENCES_CHARS = 300
# Cuisine values that mean "no cuisine filter".
ALL_CUISINES = {"all", "all cuisines", "any"}

Budget = Literal["low", "medium", "high"]


class RecommendationRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    locality: str = Field(min_length=1)
    budget: Budget
    cuisine: str | None = None  # omitted, blank, or "all" means every cuisine
    min_rating: float = Field(ge=0, le=5, allow_inf_nan=False)
    preferences: str | None = Field(default=None, max_length=MAX_PREFERENCES_CHARS)
    limit: int | None = Field(default=None, ge=1, le=MAX_LIMIT)

    @field_validator("locality", mode="before")
    @classmethod
    def _strip(cls, value):
        return value.strip() if isinstance(value, str) else value

    @field_validator("cuisine", mode="before")
    @classmethod
    def _optional_cuisine(cls, value):
        if isinstance(value, str):
            value = " ".join(value.split())
            if not value or value.casefold() in ALL_CUISINES:
                return None
        return value

    @field_validator("budget", mode="before")
    @classmethod
    def _lower_budget(cls, value):
        return value.strip().lower() if isinstance(value, str) else value

    @field_validator("preferences", mode="before")
    @classmethod
    def _blank_preferences(cls, value):
        """Collapse whitespace; blank text means no preferences."""
        if isinstance(value, str):
            value = " ".join(value.split())
            return value or None
        return value


class Recommendation(BaseModel):
    id: str
    rank: int
    name: str
    cuisines: list[str]
    rating: float | None
    cost_for_two: int | None
    explanation: str
    url: str | None


class RuleStat(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    rule: str
    entered: int = Field(alias="in")
    removed: int
    out: int


class FilterStats(BaseModel):
    rules: list[RuleStat]
    matched: int  # rows that passed every rule, before the pool cap
    pool: int     # rows kept for ranking


class RecommendationResponse(BaseModel):
    summary: str | None
    recommendations: list[Recommendation]
    filter_stats: FilterStats


class Facets(BaseModel):
    localities: list[str]
    cuisines: list[str]


class FieldError(BaseModel):
    field: str
    message: str


class ErrorResponse(BaseModel):
    detail: str
    errors: list[FieldError] = []
