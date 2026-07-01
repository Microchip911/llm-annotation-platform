"""FastAPI application entrypoint.

Wires the routers together, configures CORS, and creates the database schema on
startup via a lifespan handler. The prototype called ``create_all`` at import
time against an async engine (which crashes); doing it inside ``lifespan`` runs
it once, at the right moment, after the models are imported.
"""

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from app import __version__, models  # noqa: F401  (import models so create_all sees them)
from app.config import settings
from app.database import Base, engine
from app.routers import annotations, auth, reports

logger = logging.getLogger("llm_annotation_platform")


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.secret_key_is_ephemeral:
        logger.warning(
            "SECRET_KEY is unset or blank; using an ephemeral random key. Issued "
            "tokens will not survive a restart. Set SECRET_KEY in any real deployment."
        )
    # For this reference implementation we create tables on startup. A real
    # deployment would manage schema with Alembic migrations instead.
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(
    title=settings.project_name,
    version=__version__,
    summary="Review, score, and label LLM outputs for quality and hallucinations.",
    lifespan=lifespan,
)

# A wildcard origin cannot be combined with credentials per the Fetch spec, so we
# only enable credentials when an explicit origin allowlist is configured. This is
# a header-token API (no cookies), so wildcard-without-credentials is the norm.
_allow_all_origins = settings.cors_origins == ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=not _allow_all_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(annotations.router)
app.include_router(reports.router)


@app.get("/health", tags=["meta"])
def health() -> dict[str, str]:
    """Liveness probe."""
    return {"status": "ok"}


# --- Reviewer UI (static single-page console, no build step) -----------------
_UI_DIR = Path(__file__).parent / "static" / "ui"


@app.get("/", include_in_schema=False)
def root() -> RedirectResponse:
    """Redirect the site root to the reviewer UI."""
    return RedirectResponse(url="/ui/")


@app.get("/ui", include_in_schema=False)
def ui_trailing_slash() -> RedirectResponse:
    """Normalise /ui -> /ui/ so the page's relative asset URLs resolve."""
    return RedirectResponse(url="/ui/")


# Mounted LAST so it can never shadow /auth, /annotations, /reports, /docs, /health.
# `html=True` serves index.html at /ui/ and its co-located assets at /ui/app.css and
# /ui/app.js. index.html links those assets with RELATIVE paths, so the page renders
# correctly both when served here and when the file is opened directly in an editor
# preview. It never appears unstyled.
app.mount("/ui", StaticFiles(directory=_UI_DIR, html=True), name="ui")
