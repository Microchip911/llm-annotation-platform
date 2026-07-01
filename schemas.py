# schemas.py
from pydantic import BaseModel, EmailStr, Field
from typing import Optional

class UserCreate(BaseModel):
    email: EmailStr
    role: str = "annotator"

class UserOut(BaseModel):
    id: int
    email: str
    role: str
    class Config:
        from_attributes = True

class AnnotationCreate(BaseModel):
    project_id: int
    llm_output: str
    score: float = Field(..., ge=1.0, le=5.0)
    label: str  # "hallucination" | "correct" | "partial"
    notes: Optional[str] = None

class AnnotationOut(AnnotationCreate):
    id: int
    user_id: int
    class Config:
        from_attributes = True