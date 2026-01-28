from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(sa.String(100), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    created_at: Mapped[object] = mapped_column(sa.DateTime(), server_default=sa.text("NOW()"))
    last_login: Mapped[object | None] = mapped_column(sa.DateTime(), nullable=True)
