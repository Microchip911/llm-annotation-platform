"""Pydantic v2 request/response schemas: the API's public data contract.

These are deliberately separate from the ORM models: the ORM describes how data
is *stored*, these describe what the API *accepts and returns*. Keeping them
apart is what lets us, for example, accept a plaintext ``password`` on input
while never exposing ``hashed_password`` on output.
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models import Label, Role


class UserCreate(BaseModel):
    """Registration payload.

    Note there is deliberately no ``role`` field: self-registration always
    yields an annotator. Privileged accounts are provisioned out-of-band (a DB
    seed / CLI step), never by a client choosing their own role; otherwise
    anyone could mint an admin and bypass every ownership scope.
    """

    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class UserOut(BaseModel):
    """Public representation of a user (note the absence of any password)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    email: EmailStr
    role: Role
    created_at: datetime


class Token(BaseModel):
    """OAuth2 bearer-token response returned by the login endpoint."""

    access_token: str
    token_type: str = "bearer"


class AnnotationCreate(BaseModel):
    """Payload for submitting a new annotation.

    ``use_enum_values`` makes ``label`` serialize to its plain string value
    (``"correct"``) on the way into the ORM, keeping the stored column tidy.
    """

    model_config = ConfigDict(use_enum_values=True)

    project_id: int = Field(ge=1, description="Identifier of the evaluation project / dataset")
    llm_output: str = Field(min_length=1, description="The raw model output under review")
    score: float = Field(ge=1.0, le=5.0, description="Quality score from 1 (worst) to 5 (best)")
    label: Label = Field(description="Reviewer verdict for this output")
    notes: str | None = Field(default=None, max_length=2000)


class AnnotationOut(AnnotationCreate):
    """Annotation as returned to clients, including server-assigned fields."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    created_at: datetime


class SummaryReport(BaseModel):
    """Aggregate reporting payload for the ``/reports/summary`` endpoint."""

    total_annotations: int
    by_label: dict[str, int]
    average_score: float | None
    reviewed_by: str
