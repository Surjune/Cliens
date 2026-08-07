"""Plain-English report generation request/response schemas."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import Field

from app.schemas.common import SchemaBase


class ReportRequest(SchemaBase):
    """Request a plain-English report for a computed score."""

    score_id: uuid.UUID = Field(description="Identifier of the score to explain.")


class ReportResponse(SchemaBase):
    """A generated report.

    ``prompt_version`` and ``model_name`` are always returned so a report can be
    traced to the exact instructions and model that produced it.
    """

    id: uuid.UUID
    score_id: uuid.UUID
    content: str = Field(description="The report text, in Markdown.")
    prompt_version: str = Field(description="Version of the version-controlled prompt used.")
    model_name: str = Field(description="Gemini model that generated the text.")
    created_at: datetime
