from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.db.session import SessionLocal, get_db
from app.routers.auth import get_current_user
from app.services.retention import run_retention_job
from app.services.rollups import get_dashboard_stats, run_rollup_job

router = APIRouter()


def _run_rollup_background() -> None:
    db = SessionLocal()
    try:
        run_rollup_job(db)
    finally:
        db.close()


def _run_retention_background() -> None:
    db = SessionLocal()
    try:
        run_retention_job(db)
    finally:
        db.close()


@router.post("/jobs/rollup")
def trigger_rollup(
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    background_tasks.add_task(_run_rollup_background)
    return {"ok": True, "message": "Rollup job queued"}


@router.post("/jobs/retention")
def trigger_retention(
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    background_tasks.add_task(_run_retention_background)
    return {"ok": True, "message": "Retention cleanup job queued"}


@router.get("/api/stats")
def api_stats(
    request: Request,
    hours: int = 24,
    db: Session = Depends(get_db),
):
    user = get_current_user(request, db)
    if not user:
        return {"error": "unauthorized"}

    stats = get_dashboard_stats(db, hours=hours)
    return stats
