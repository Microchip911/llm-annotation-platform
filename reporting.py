from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from database import get_db
from models import Annotation
from auth import get_current_user

router = APIRouter(prefix="/reports", tags=["reports"])

@router.get("/summary")
async def get_summary(db: Session = Depends(get_db), current_user: str = Depends(get_current_user)):
    total = db.query(Annotation).count()
    return {"total_annotations": total, "reviewed_by": current_user}