from __future__ import annotations

import os
import urllib.request

import sqlalchemy as sa
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.blocklist import Blocklist
from app.models.blocklist_entry import BlocklistEntry
from app.models.manual_entry import ManualEntry
from app.models.settings import get_setting
from app.presets import PRESET_LISTS
from app.routers.auth import get_current_user
from app.services.config_audit import model_to_dict, record_change
from app.services.rpz import parse_blocklist_text, render_rpz_whitelist, render_rpz_zone
from app.template_utils import get_templates

router = APIRouter()
templates = get_templates()


@router.get("/blocklists", response_class=HTMLResponse)
def blocklists_page(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    blocklists = db.query(Blocklist).order_by(Blocklist.created_at.desc()).all()
    timezone = get_setting(db, "timezone") or "UTC"
    return templates.TemplateResponse(
        "blocklists.html",
        {
            "request": request,
            "user": user,
            "blocklists": blocklists,
            "presets": PRESET_LISTS,
            "timezone": timezone,
            "message": None,
        },
    )


@router.get("/blocklists/search", response_class=HTMLResponse)
def blocklists_search(
    request: Request,
    q: str = "",
    db: Session = Depends(get_db),
):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    results: list[dict] = []
    search_query = q.strip().lower()

    if search_query:
        entries = (
            db.query(BlocklistEntry, Blocklist)
            .join(Blocklist, BlocklistEntry.blocklist_id == Blocklist.id)
            .filter(sa.func.lower(BlocklistEntry.domain) == search_query)
            .all()
        )
        for entry, blocklist in entries:
            results.append(
                {
                    "domain": entry.domain,
                    "blocklist_name": blocklist.name,
                    "blocklist_id": blocklist.id,
                    "list_type": blocklist.list_type,
                }
            )

        manual = (
            db.query(ManualEntry).filter(sa.func.lower(ManualEntry.domain) == search_query).all()
        )
        for m in manual:
            results.append(
                {
                    "domain": m.domain,
                    "blocklist_name": "Manual Entry",
                    "blocklist_id": None,
                    "list_type": m.entry_type,
                }
            )

    return templates.TemplateResponse(
        "blocklist_search.html",
        {
            "request": request,
            "user": user,
            "query": q,
            "results": results,
        },
    )


@router.get("/setup", response_class=HTMLResponse)
def setup_page(request: Request, db: Session = Depends(get_db)):
    from datetime import datetime, timedelta, timezone

    from app.models.client import Client
    from app.models.client_resolver_rule import ClientResolverRule
    from app.models.dns_query_event import DNSQueryEvent
    from app.models.forward_zone import ForwardZone

    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    enabled_blocklists = db.query(Blocklist).filter(Blocklist.enabled.is_(True)).count()
    has_blocklists = enabled_blocklists > 0

    recent_cutoff = datetime.now(timezone.utc) - timedelta(hours=1)
    recent_queries = db.query(DNSQueryEvent).filter(DNSQueryEvent.ts >= recent_cutoff).count()
    has_traffic = recent_queries > 0

    client_count = db.query(Client).count()
    has_clients = client_count > 0

    resolver_rules = db.query(ClientResolverRule).count()
    has_resolver_rules = resolver_rules > 0

    forward_zones = db.query(ForwardZone).filter(ForwardZone.enabled.is_(True)).count()
    has_forward_zones = forward_zones > 0

    checklist = {
        "blocklists_enabled": has_blocklists,
        "blocklist_count": enabled_blocklists,
        "traffic_flowing": has_traffic,
        "recent_queries": recent_queries,
        "clients_seen": has_clients,
        "client_count": client_count,
        "resolver_rules_configured": has_resolver_rules,
        "resolver_rule_count": resolver_rules,
        "forward_zones_configured": has_forward_zones,
        "forward_zone_count": forward_zones,
    }

    return templates.TemplateResponse(
        "setup.html", {"request": request, "user": user, "checklist": checklist}
    )


@router.post("/blocklists/add")
def blocklists_add(
    request: Request,
    name: str = Form(...),
    url: str = Form(...),
    format: str = Form(...),
    list_type: str = Form("block"),
    update_frequency_hours: int = Form(24),
    db: Session = Depends(get_db),
):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    b = Blocklist(
        name=name.strip(),
        url=url.strip(),
        format=format.strip(),
        list_type=list_type.strip(),
        update_frequency_hours=update_frequency_hours,
    )
    db.add(b)
    db.flush()
    record_change(
        db,
        entity_type="blocklist",
        entity_id=b.id,
        action="create",
        actor_user_id=user.id,
        after_data=model_to_dict(b, exclude={"manual_entries"}),
    )
    db.commit()
    return RedirectResponse(url="/blocklists", status_code=302)


@router.post("/blocklists/update-frequency")
def blocklists_update_frequency(
    request: Request,
    id: int = Form(...),
    update_frequency_hours: int = Form(...),
    db: Session = Depends(get_db),
):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    b = db.get(Blocklist, id)
    if b:
        before = model_to_dict(b, exclude={"manual_entries"})
        b.update_frequency_hours = update_frequency_hours
        db.add(b)
        record_change(
            db,
            entity_type="blocklist",
            entity_id=b.id,
            action="update_frequency",
            actor_user_id=user.id,
            before_data=before,
            after_data=model_to_dict(b, exclude={"manual_entries"}),
        )
        db.commit()
    return RedirectResponse(url="/blocklists", status_code=302)


@router.post("/blocklists/delete")
def blocklists_delete(
    request: Request,
    id: int = Form(...),
    db: Session = Depends(get_db),
):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    b = db.get(Blocklist, id)
    if b:
        before = model_to_dict(b, exclude={"manual_entries"})
        record_change(
            db,
            entity_type="blocklist",
            entity_id=b.id,
            action="delete",
            actor_user_id=user.id,
            before_data=before,
        )
        db.delete(b)
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
        before = model_to_dict(b, exclude={"manual_entries"})
        b.enabled = not bool(b.enabled)
        db.add(b)
        record_change(
            db,
            entity_type="blocklist",
            entity_id=b.id,
            action="toggle",
            actor_user_id=user.id,
            before_data=before,
            after_data=model_to_dict(b, exclude={"manual_entries"}),
        )
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
    db.flush()
    record_change(
        db,
        entity_type="manual_entry",
        entity_id=e.id,
        action="create",
        actor_user_id=user.id,
        after_data=model_to_dict(e),
    )
    db.commit()
    return RedirectResponse(url="/blocklists", status_code=302)


@router.post("/blocklists/apply")
def blocklists_apply(request: Request, db: Session = Depends(get_db)):
    from datetime import datetime, timezone

    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    enabled = db.query(Blocklist).filter(Blocklist.enabled.is_(True)).all()
    allow = db.query(ManualEntry).filter(ManualEntry.entry_type == "allow").all()
    block = db.query(ManualEntry).filter(ManualEntry.entry_type == "block").all()

    blocked_domains: set[str] = {ent.domain for ent in block}
    allow_domains: set[str] = {a.domain for a in allow}
    now = datetime.now(timezone.utc)

    blocklist_entries_to_add: list[BlocklistEntry] = []

    for bl in enabled:
        try:
            with urllib.request.urlopen(bl.url, timeout=10) as resp:
                text = resp.read().decode("utf-8", errors="ignore")
            domains = parse_blocklist_text(text, bl.format)
            if bl.list_type == "allow":
                allow_domains |= domains
            else:
                blocked_domains |= domains

            db.query(BlocklistEntry).filter(BlocklistEntry.blocklist_id == bl.id).delete()
            for domain in domains:
                blocklist_entries_to_add.append(BlocklistEntry(domain=domain, blocklist_id=bl.id))

            bl.last_update_status = "success"
            bl.last_error = None
            bl.entry_count = len(domains)
            bl.last_updated = now
        except Exception as ex:
            bl.last_update_status = "failed"
            bl.last_error = str(ex)
            bl.last_updated = now

    out_dir = "/shared/rpz"
    os.makedirs(out_dir, exist_ok=True)

    effective_blocked = blocked_domains - allow_domains

    with open(os.path.join(out_dir, "blocklist-combined.rpz"), "w", encoding="utf-8") as f:
        f.write(render_rpz_zone(effective_blocked, policy_name="blocklist-combined"))
    with open(os.path.join(out_dir, "whitelist.rpz"), "w", encoding="utf-8") as f:
        f.write(render_rpz_whitelist(allow_domains))

    db.add_all(enabled)
    if blocklist_entries_to_add:
        db.bulk_save_objects(blocklist_entries_to_add)
    db.commit()

    blocklists = db.query(Blocklist).order_by(Blocklist.created_at.desc()).all()
    timezone = get_setting(db, "timezone") or "UTC"
    removed_count = len(blocked_domains) - len(effective_blocked)
    msg = f"Wrote RPZ: {len(effective_blocked)} blocked, {len(allow_domains)} allow"
    if removed_count > 0:
        msg += f" ({removed_count} removed by whitelist)"
    return templates.TemplateResponse(
        "blocklists.html",
        {
            "request": request,
            "user": user,
            "blocklists": blocklists,
            "presets": PRESET_LISTS,
            "timezone": timezone,
            "message": msg,
        },
    )


@router.post("/blocklists/update-schedule")
def blocklists_update_schedule(
    request: Request,
    id: int = Form(...),
    schedule_enabled: bool = Form(False),
    schedule_start: str = Form(""),
    schedule_end: str = Form(""),
    schedule_days: list[str] = Form([]),
    db: Session = Depends(get_db),
):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    b = db.get(Blocklist, id)
    if b:
        before = model_to_dict(b, exclude={"manual_entries"})
        b.schedule_enabled = schedule_enabled
        b.schedule_start = schedule_start.strip() if schedule_start else None
        b.schedule_end = schedule_end.strip() if schedule_end else None
        b.schedule_days = ",".join(schedule_days) if schedule_days else None
        db.add(b)
        record_change(
            db,
            entity_type="blocklist",
            entity_id=b.id,
            action="update_schedule",
            actor_user_id=user.id,
            before_data=before,
            after_data=model_to_dict(b, exclude={"manual_entries"}),
        )
        db.commit()
    return RedirectResponse(url="/blocklists", status_code=302)
