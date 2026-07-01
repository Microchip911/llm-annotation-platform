"""Annotation CRUD endpoints.

Every annotation is attributed to the authenticated reviewer (the prototype
hardcoded ``user_id=1``), and reads are ownership-scoped: an annotator only ever
sees their own work, while an admin sees everything. Non-owner reads return
``404`` rather than ``403`` so we never leak the existence of another reviewer's
annotations (an IDOR-hardening choice).
"""

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status

from app.dependencies import CurrentUser, DbSession
from app.models import Annotation, Label, Role
from app.schemas import AnnotationCreate, AnnotationOut

router = APIRouter(prefix="/annotations", tags=["annotations"])


@router.post("/", response_model=AnnotationOut, status_code=status.HTTP_201_CREATED)
def create_annotation(
    payload: AnnotationCreate,
    db: DbSession,
    current_user: CurrentUser,
) -> Annotation:
    """Submit a new annotation, attributed to the current reviewer."""
    annotation = Annotation(**payload.model_dump(), user_id=current_user.id)
    db.add(annotation)
    db.commit()
    db.refresh(annotation)
    return annotation


@router.get("/", response_model=list[AnnotationOut])
def list_annotations(
    db: DbSession,
    current_user: CurrentUser,
    label: Label | None = None,
    project_id: int | None = None,
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[Annotation]:
    """List annotations with optional filters and server-capped pagination."""
    query = db.query(Annotation)

    # Annotators are scoped to their own rows; admins can see everything.
    if current_user.role != Role.ADMIN.value:
        query = query.filter(Annotation.user_id == current_user.id)
    if label is not None:
        query = query.filter(Annotation.label == label.value)
    if project_id is not None:
        query = query.filter(Annotation.project_id == project_id)

    return query.order_by(Annotation.id.desc()).offset(skip).limit(limit).all()


@router.get("/{annotation_id}", response_model=AnnotationOut)
def get_annotation(
    annotation_id: int,
    db: DbSession,
    current_user: CurrentUser,
) -> Annotation:
    """Fetch a single annotation the caller is allowed to see."""
    annotation = db.get(Annotation, annotation_id)
    if annotation is None or (
        current_user.role != Role.ADMIN.value and annotation.user_id != current_user.id
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Annotation not found",
        )
    return annotation


@router.delete("/{annotation_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_annotation(
    annotation_id: int,
    db: DbSession,
    current_user: CurrentUser,
) -> None:
    """Delete an annotation the caller owns (admins may delete any)."""
    annotation = db.get(Annotation, annotation_id)
    if annotation is None or (
        current_user.role != Role.ADMIN.value and annotation.user_id != current_user.id
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Annotation not found",
        )
    db.delete(annotation)
    db.commit()
