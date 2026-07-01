"""Reporting endpoints.

This router existed in the prototype but was never wired into the app, so
``GET /reports/summary`` was a dead route. It is now registered in ``main.py``
and returns a real aggregate: total volume, a per-label breakdown, and the mean
score: the raw material for metrics like hallucination rate.
"""

from fastapi import APIRouter
from sqlalchemy import func

from app.dependencies import CurrentUser, DbSession
from app.models import Annotation, Label, Role
from app.schemas import SummaryReport

router = APIRouter(prefix="/reports", tags=["reports"])


@router.get("/summary", response_model=SummaryReport)
def get_summary(db: DbSession, current_user: CurrentUser) -> SummaryReport:
    """Aggregate annotation stats, scoped to the caller (admins see everything)."""
    query = db.query(Annotation)
    if current_user.role != Role.ADMIN.value:
        query = query.filter(Annotation.user_id == current_user.id)

    total = query.count()

    by_label = {label.value: 0 for label in Label}
    rows = query.with_entities(Annotation.label, func.count()).group_by(Annotation.label).all()
    for label_value, count in rows:
        by_label[label_value] = count

    avg_score = query.with_entities(func.avg(Annotation.score)).scalar()

    return SummaryReport(
        total_annotations=total,
        by_label=by_label,
        average_score=round(avg_score, 2) if avg_score is not None else None,
        reviewed_by=current_user.email,
    )
