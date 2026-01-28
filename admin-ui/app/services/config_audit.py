from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.models.config_change import ConfigChange


def record_change(
    db: Session,
    *,
    entity_type: str,
    entity_id: int | None,
    action: str,
    actor_user_id: int | None = None,
    before_data: dict[str, Any] | None = None,
    after_data: dict[str, Any] | None = None,
    comment: str | None = None,
) -> ConfigChange:
    change = ConfigChange(
        entity_type=entity_type,
        entity_id=entity_id,
        action=action,
        actor_user_id=actor_user_id,
        before_data=before_data,
        after_data=after_data,
        comment=comment,
    )
    db.add(change)
    return change


def get_entity_history(
    db: Session,
    entity_type: str,
    entity_id: int | None = None,
    limit: int = 50,
) -> list[ConfigChange]:
    query = db.query(ConfigChange).filter(ConfigChange.entity_type == entity_type)
    if entity_id is not None:
        query = query.filter(ConfigChange.entity_id == entity_id)
    return query.order_by(ConfigChange.created_at.desc()).limit(limit).all()


def get_recent_changes(db: Session, limit: int = 100) -> list[ConfigChange]:
    return db.query(ConfigChange).order_by(ConfigChange.created_at.desc()).limit(limit).all()


def model_to_dict(obj: Any, exclude: set[str] | None = None) -> dict[str, Any]:
    exclude = exclude or set()
    exclude.add("_sa_instance_state")

    result = {}
    for key in dir(obj):
        if key.startswith("_") or key in exclude:
            continue
        val = getattr(obj, key, None)
        if callable(val):
            continue
        if hasattr(val, "__table__"):
            continue
        result[key] = val
    return result
