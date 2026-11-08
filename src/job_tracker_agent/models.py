"""Domain data models for the Job Tracker Agent.

Reflects the canonical language defined in CONTEXT.md.
"""

from datetime import datetime
from enum import Enum
from typing import Any, Optional
from pydantic import BaseModel, Field, field_validator


class ApplicationStage(str, Enum):
    """The current milestone in an application's hiring pipeline."""

    APPLIED = "Applied"
    SCREENING = "Screening"
    INTERVIEW = "Interview"
    OFFER = "Offer"
    REJECTED = "Rejected"
    ARCHIVED = "Archived"


class IngestionProvider(str, Enum):
    """Supported email providers."""

    GMAIL = "gmail"
    OUTLOOK = "outlook"


class EmailMessage(BaseModel):
    """Normalized email payload ingested from a mailbox."""

    account_id: str
    message_id: str
    thread_id: str
    provider: IngestionProvider
    sender_name: Optional[str] = None
    sender_email: str
    subject: str
    received_at: datetime
    body_text: str
    body_snippet: str = ""


class ExtractedApplication(BaseModel):
    """Structured hiring data extracted from an email by an LLM."""

    is_job_application: bool = Field(
        ...,
        description="True if this email is directly related to a job application or hiring process.",
    )
    company: str = Field(
        default="Unknown Company",
        description="The hiring company or employer name (not the ATS vendor like Greenhouse/Lever).",
    )
    role: str = Field(
        default="Unknown Role",
        description="The job title or role pursued.",
    )
    stage: ApplicationStage = Field(
        default=ApplicationStage.APPLIED,
        description="The current hiring milestone indicated by this email.",
    )
    confidence: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Confidence score between 0.0 and 1.0.",
    )
    review_flag: bool = Field(
        default=False,
        description="Set to true if there is ambiguity, uncertainty, or a human should verify.",
    )
    summary: str = Field(
        ...,
        description="A concise 1 to 2 sentence summary of what this email communicates.",
    )
    action_items: list[str] = Field(
        default_factory=list,
        description="Any immediate next steps or requested actions (e.g. scheduling links, take-homes).",
    )
    interview_date: Optional[str] = Field(
        default=None,
        description="Date and time of an upcoming interview if explicitly mentioned, formatted as ISO 8601 or text.",
    )

    @field_validator("role", mode="before")
    @classmethod
    def _coerce_role(cls, v: Any) -> str:
        return v if (v and isinstance(v, str)) else "Unknown Role"

    @field_validator("company", mode="before")
    @classmethod
    def _coerce_company(cls, v: Any) -> str:
        return v if (v and isinstance(v, str)) else "Unknown Company"


class TimelineCallout(BaseModel):
    """Collapsible block data to be appended to a Notion Application page body."""

    timestamp: datetime
    subject: str
    summary: str
    action_items: list[str]
    stage_transition: Optional[str] = None
    review_flag: bool = False
