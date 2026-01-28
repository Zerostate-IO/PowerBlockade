from __future__ import annotations

from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.node import Node


def get_node_from_api_key(
    x_powerblockade_node_key: str | None = Header(default=None, alias="X-PowerBlockade-Node-Key"),
    db: Session = Depends(get_db),
) -> Node:
    if not x_powerblockade_node_key:
        raise HTTPException(status_code=401, detail="Missing node API key")

    node = db.query(Node).filter(Node.api_key == x_powerblockade_node_key).one_or_none()
    if not node:
        raise HTTPException(status_code=401, detail="Invalid node API key")
    return node
