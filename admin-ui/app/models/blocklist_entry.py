from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class BlocklistEntry(Base):
    """Individual domain entries from blocklists, enabling search functionality."""

    __tablename__ = "blocklist_entries"

    id: Mapped[int] = mapped_column(sa.BigInteger(), primary_key=True)
    domain: Mapped[str] = mapped_column(sa.String(255), index=True)
    blocklist_id: Mapped[int] = mapped_column(
        sa.BigInteger(),
        sa.ForeignKey("blocklists.id", ondelete="CASCADE"),
        index=True,
    )
    created_at: Mapped[object] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.text("NOW()")
    )

    __table_args__ = (
        sa.UniqueConstraint("domain", "blocklist_id", name="uq_blocklist_entry_domain_list"),
        sa.Index("ix_blocklist_entries_domain_lower", sa.func.lower(domain)),
    )
