from __future__ import annotations

import logging
import os
import subprocess
import tarfile
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, File, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.routers.auth import get_current_user
from app.template_utils import get_templates

router = APIRouter()
templates = get_templates()
log = logging.getLogger(__name__)

BACKUP_DIR = Path("/backups")
SHARED_DIR = Path("/shared")


def _get_backups() -> list[dict]:
    if not BACKUP_DIR.exists():
        return []

    backups = []
    for f in sorted(BACKUP_DIR.iterdir(), reverse=True):
        if f.suffix in (".sql", ".gz"):
            stat = f.stat()
            backups.append(
                {
                    "name": f.name,
                    "size": stat.st_size,
                    "size_human": _human_size(stat.st_size),
                    "mtime": datetime.fromtimestamp(stat.st_mtime),
                    "type": "database" if f.suffix == ".sql" else "config",
                }
            )
    return backups[:20]


def _human_size(size: int) -> str:
    for unit in ["B", "KB", "MB", "GB"]:
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


@router.get("/backup", response_class=HTMLResponse)
def backup_page(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    backups = _get_backups()
    message = request.query_params.get("message")
    error = request.query_params.get("error")

    return templates.TemplateResponse(
        "backup.html",
        {
            "request": request,
            "user": user,
            "backups": backups,
            "message": message,
            "error": error,
        },
    )


@router.post("/backup/database")
def create_database_backup(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_file = BACKUP_DIR / f"manual-{timestamp}.sql"
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)

    try:
        result = subprocess.run(
            [
                "pg_dump",
                "-h",
                os.environ.get("POSTGRES_HOST", "postgres"),
                "-U",
                os.environ.get("POSTGRES_USER", "powerblockade"),
                "-d",
                os.environ.get("POSTGRES_DB", "powerblockade"),
            ],
            capture_output=True,
            text=True,
            env={**os.environ, "PGPASSWORD": os.environ.get("POSTGRES_PASSWORD", "powerblockade")},
            timeout=120,
        )

        if result.returncode == 0:
            backup_file.write_text(result.stdout)
            return RedirectResponse(url="/backup?message=Database+backup+created", status_code=302)
        else:
            log.error(f"pg_dump failed: {result.stderr}")
            return RedirectResponse(url="/backup?error=Backup+failed", status_code=302)

    except subprocess.TimeoutExpired:
        return RedirectResponse(url="/backup?error=Backup+timed+out", status_code=302)
    except Exception as e:
        log.error(f"Backup error: {e}")
        return RedirectResponse(url=f"/backup?error={str(e)[:50]}", status_code=302)


@router.post("/backup/config")
def create_config_backup(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_file = BACKUP_DIR / f"config-{timestamp}.tar.gz"
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)

    try:
        with tarfile.open(backup_file, "w:gz") as tar:
            rpz_dir = SHARED_DIR / "rpz"
            fz_dir = SHARED_DIR / "forward-zones"

            if rpz_dir.exists():
                tar.add(rpz_dir, arcname="rpz")
            if fz_dir.exists():
                tar.add(fz_dir, arcname="forward-zones")

        return RedirectResponse(url="/backup?message=Config+backup+created", status_code=302)

    except Exception as e:
        log.error(f"Config backup error: {e}")
        return RedirectResponse(url=f"/backup?error={str(e)[:50]}", status_code=302)


@router.get("/backup/download/{filename}")
def download_backup(filename: str, request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    if ".." in filename or "/" in filename:
        return RedirectResponse(url="/backup?error=Invalid+filename", status_code=302)

    backup_file = BACKUP_DIR / filename
    if not backup_file.exists():
        return RedirectResponse(url="/backup?error=File+not+found", status_code=302)

    def iter_file():
        with open(backup_file, "rb") as f:
            yield from f

    media_type = "application/gzip" if filename.endswith(".gz") else "application/sql"
    return StreamingResponse(
        iter_file(),
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/backup/delete/{filename}")
def delete_backup(filename: str, request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    if ".." in filename or "/" in filename:
        return RedirectResponse(url="/backup?error=Invalid+filename", status_code=302)

    backup_file = BACKUP_DIR / filename
    if backup_file.exists():
        backup_file.unlink()
        return RedirectResponse(url="/backup?message=Backup+deleted", status_code=302)

    return RedirectResponse(url="/backup?error=File+not+found", status_code=302)


@router.post("/backup/restore/database")
async def restore_database(
    request: Request,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    if not file.filename or not file.filename.endswith(".sql"):
        return RedirectResponse(url="/backup?error=Invalid+file+type", status_code=302)

    try:
        content = await file.read()

        result = subprocess.run(
            [
                "psql",
                "-h",
                os.environ.get("POSTGRES_HOST", "postgres"),
                "-U",
                os.environ.get("POSTGRES_USER", "powerblockade"),
                "-d",
                os.environ.get("POSTGRES_DB", "powerblockade"),
            ],
            input=content.decode("utf-8"),
            capture_output=True,
            text=True,
            env={**os.environ, "PGPASSWORD": os.environ.get("POSTGRES_PASSWORD", "powerblockade")},
            timeout=300,
        )

        if result.returncode == 0:
            return RedirectResponse(url="/backup?message=Database+restored", status_code=302)
        else:
            log.error(f"psql restore failed: {result.stderr}")
            return RedirectResponse(url="/backup?error=Restore+failed", status_code=302)

    except Exception as e:
        log.error(f"Restore error: {e}")
        return RedirectResponse(url=f"/backup?error={str(e)[:50]}", status_code=302)
