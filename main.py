
from fastapi import FastAPI
from database import Base, engine
from routers import annotations

Base.metadata.create_all(bind=engine)

app = FastAPI()
app.include_router(annotations.router)