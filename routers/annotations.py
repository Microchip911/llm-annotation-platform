from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from database import get_db
from models import Annotation
from schemas import AnnotationCreate, AnnotationOut
from auth import get_current_user

router = APIRouter(prefix="/annotations", tags=["annotations"])

@router.post("/", response_model=AnnotationOut)
async def create_annotation(
    payload: AnnotationCreate,
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user)
):
    annotation = Annotation(**payload.model_dump(), user_id=1)
    db.add(annotation)
    db.commit()
    db.refresh(annotation)
    return annotation

@router.get("/{annotation_id}", response_model=AnnotationOut)
async def get_annotation(
    annotation_id: int,
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user)
):
    annotation = db.query(Annotation).filter(Annotation.id == annotation_id).first()
    if not annotation:
        raise HTTPException(status_code=404, detail="Annotation not found")
    return annotation