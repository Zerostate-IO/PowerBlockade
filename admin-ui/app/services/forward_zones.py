from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.forward_zone import ForwardZone


def generate_forward_zones_config(db: Session) -> str:
    """Generate PowerDNS Recursor forward-zones config from database.

    Resolution precedence (documented):
    - Most specific per-node override → most specific global → normal recursion

    For now: writes all enabled zones (global only).
    """
    zones = (
        db.query(ForwardZone)
        .filter(ForwardZone.enabled.is_(True), ForwardZone.node_id.is_(None))
        .all()
    )

    lines = ["# Forward zones for PowerDNS Recursor"]
    lines.append("# Generated automatically - do not edit manually\n")

    for zone in zones:
        lines.append(f"{zone.domain}={zone.servers}")

    return "\n".join(lines)


def write_forward_zones_config(db: Session, out_path: str = "/shared/forward-zones.conf") -> str:
    """Write forward-zones config to file."""
    content = generate_forward_zones_config(db)

    import os

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(content)

    return content
