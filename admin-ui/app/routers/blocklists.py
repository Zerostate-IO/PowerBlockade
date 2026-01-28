from __future__ import annotations

import os
import urllib.request

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.user import User
from app.models.blocklist import Blocklist
from app.models.manual_entry import ManualEntry
from app.services.rpz import parse_blocklist_text, render_rpz_zone, render_rpz_whitelist
from app.presets import PRESET_LISTS
from app.routers.auth import get_current_user


router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/blocklists", response_class=HTMLResponse)
def blocklists_page(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    blocklists = db.query(Blocklist).order_by(Blocklist.created_at.desc()).all()
    return templates.TemplateResponse(
        "blocklists.html",
        {
            "request": request,
            "user": user,
            "blocklists": blocklists,
            "presets": PRESET_LISTS,
            "message": None,
        },
    )


@router.get("/setup", response_class=HTMLResponse)
def setup_page(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    return templates.TemplateResponse("setup.html", {"request": request, "user": user})


@router.post("/blocklists/add")
def blocklists_add(
    request: Request,
    name: str = Form(...),
    url: str = Form(...),
    format: str = Form(...),
    list_type: str = Form("block"),
    db: Session = Depends(get_db),
):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    b = Blocklist(
        name=name.strip(), url=url.strip(), format=format.strip(), list_type=list_type.strip()
    )
    db.add(b)
    db.commit()
    return RedirectResponse(url="/blocklists", status_code=302)


@router.post("/blocklists/add-preset")
def blocklists_add_preset(
    request: Request,
    name: str = Form(...),
    url: str = Form(...),
    format: str = Form(...),
    list_type: str = Form("block"),
    db: Session = Depends(get_db),
):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    b = Blocklist(
        name=name.strip(), url=url.strip(), format=format.strip(), list_type=list_type.strip()
    )
    db.add(b)
    try:
        db.commit()
    except Exception:
        db.rollback()
    return RedirectResponse(url="/blocklists", status_code=302)


@router.post("/blocklists/toggle")
def blocklists_toggle(
    request: Request,
    id: int = Form(...),
    db: Session = Depends(get_db),
):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    b = db.get(Blocklist, id)
    if b:
        b.enabled = not bool(b.enabled)
        db.add(b)
        db.commit()
    return RedirectResponse(url="/blocklists", status_code=302)


@router.post("/entries/add")
def entries_add(
    request: Request,
    domain: str = Form(...),
    entry_type: str = Form(...),
    db: Session = Depends(get_db),
):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    e = ManualEntry(domain=domain.strip().lower().rstrip("."), entry_type=entry_type)
    db.add(e)
    db.commit()
    return RedirectResponse(url="/blocklists", status_code=302)


@router.post("/blocklists/apply")
def blocklists_apply(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    enabled = db.query(Blocklist).filter(Blocklist.enabled.is_(True)).all()
    allow = db.query(ManualEntry).filter(ManualEntry.entry_type == "allow").all()
    block = db.query(ManualEntry).filter(ManualEntry.entry_type == "block").all()

    blocked_domains: set[str] = {ent.domain for ent in block}
    allow_domains: set[str] = {a.domain for a in allow}

    for bl in enabled:
        try:
            with urllib.request.urlopen(bl.url, timeout=10) as resp:
                text = resp.read().decode("utf-8", errors="ignore")
            domains = parse_blocklist_text(text, bl.format)
            if bl.list_type == "allow":
                allow_domains |= domains
            else:
                blocked_domains |= domains
            bl.last_update_status = "success"
            bl.last_error = None
            bl.entry_count = len(domains)
        except Exception as ex:
            bl.last_update_status = "failed"
            bl.last_error = str(ex)

    out_dir = "/shared/rpz"
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "blocklist-combined.rpz"), "w", encoding="utf-8") as f:
        f.write(render_rpz_zone(blocked_domains, policy_name="blocklist-combined"))
    with open(os.path.join(out_dir, "whitelist.rpz"), "w", encoding="utf-8") as f:
        f.write(render_rpz_whitelist(allow_domains))

    db.add_all(enabled)
    db.commit()

    blocklists = db.query(Blocklist).order_by(Blocklist.created_at.desc()).all()
    msg = f"Wrote RPZ: {len(blocked_domains)} blocked, {len(allow_domains)} allow"
    return templates.TemplateResponse(
        "blocklists.html",
        {
            "request": request,
            "user": user,
            "blocklists": blocklists,
            "presets": PRESET_LISTS,
            "message": msg,
        },
    )
