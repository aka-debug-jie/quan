"""Small public request models for the local API."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class CompareRequest(BaseModel):
    """Experiments selected for a compatibility check."""

    artifact_ids: list[str] = Field(min_length=2, max_length=4)


class ExportRequest(BaseModel):
    """Safe aggregate export request."""

    artifact_ids: list[str] = Field(min_length=1, max_length=100)
    format: Literal["csv", "json"] = "csv"
