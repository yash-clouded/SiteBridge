"""SiteBridge FastAPI application (Phase 1: WBS / project structure)."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .db import init_db
from .routers import auth, intake, matching, projects, review, rollup, status, wbs

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


app = FastAPI(title="SiteBridge", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    # `frontend_origin` holds one origin or a comma-separated list, so the
    # Vercel domain and localhost can both talk to this API from a browser.
    allow_origins=[o.strip() for o in settings.frontend_origin.split(",") if o.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(projects.router)
app.include_router(wbs.router)
app.include_router(intake.router)
app.include_router(matching.router)
app.include_router(review.router)
app.include_router(rollup.router)
app.include_router(status.router)


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "app": settings.app_name}
