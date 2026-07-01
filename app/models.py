"""SQLAlchemy ORM models.

This is the module the original prototype was missing entirely — every router
did ``from models import Annotation`` against a file that did not exist, so the
app could never import. Models use SQLAlchemy 2.0's typed ``Mapped`` /
``mapped_column`` style, and enforce value constraints at the database layer
(defense in depth) in addition to the Pydantic validation at the edge.
"""

from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Role(StrEnum):
    """Authorization roles. Annotators see their own work; admins see all."""

    ANNOTATOR = "annotator"
    ADMIN = "admin"


class Label(StrEnum):
    """The reviewer's categorical verdict on an LLM output."""

    HALLUCINATION = "hallucination"
    CORRECT = "correct"
    PARTIAL = "partial"


class User(Base):
    """A human reviewer (or an admin) who submits annotations."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(32), default=Role.ANNOTATOR.value)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    annotations: Mapped[list["Annotation"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class Annotation(Base):
    """A single human judgment about one LLM output, scoped to a project."""

    __tablename__ = "annotations"
    __table_args__ = (
        CheckConstraint("score >= 1.0 AND score <= 5.0", name="ck_annotations_score_range"),
        CheckConstraint(
            "label IN ('hallucination', 'correct', 'partial')",
            name="ck_annotations_label",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(index=True)
    llm_output: Mapped[str] = mapped_column(Text)
    score: Mapped[float] = mapped_column(Float)
    label: Mapped[str] = mapped_column(String(32), index=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    user: Mapped["User"] = relationship(back_populates="annotations")
