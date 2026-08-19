"""Repoint stored precache warming settings at the dnsdist edge

Data-only migration (no schema changes). The P7 warming upgrade
(commit e8ec9b0) changed the DEFAULTS for precache_dns_server /
precache_dns_port from recursor / 5300 to dnsdist / 53 so each warming
pass refreshes the dnsdist edge packet cache, but get_setting() prefers
stored rows over DEFAULTS. Deployments that ever saved the precache
settings form (the pre-upgrade form defaulted its server field to
"recursor") therefore keep warming via recursor:5300 and silently
bypass the edge cache — the exact behavior the upgrade exists to fix.

Semantics (deliberate, per the P7 handoff):

- Only rows still equal to the exact old default values are flipped:
  precache_dns_server 'recursor' -> 'dnsdist' and
  precache_dns_port '5300' -> '53'. Rows explicitly set to anything
  else (user overrides) are left untouched.
- Each key migrates independently; the two rows are NOT treated as a
  unit. Mixed combos such as server='recursor' with port='53', or a
  custom server with a leftover port='5300', resolve per-key against
  the rule above and any row not equal to its old default stays as-is.
- Because every UPDATE is conditioned on the exact old value, re-running
  the migration is a no-op (idempotent).

updated_at is bumped alongside the value so the audit semantics match
an application-level set_setting() (whose ORM onupdate would fire).

Downgrade is the symmetric revert keyed on the exact new values. It
cannot distinguish rows this migration flipped from rows a user later
saved as dnsdist/53 on purpose; both revert. That is the accepted
trade-off for a data migration and downgrades are not part of normal
roll-forward operations.

Revision ID: 0019_precache_warming_dnsdist
Revises: 0018_is_internal
Create Date: 2026-08-18
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "0019_precache_warming_dnsdist"
down_revision = "0018_is_internal"
branch_labels = None
depends_on = None

# (key, pre-P7 default, post-P7 default)
_FLIPS = [
    ("precache_dns_server", "recursor", "dnsdist"),
    ("precache_dns_port", "5300", "53"),
]


def _flip(key: str, old: str, new: str) -> None:
    op.execute(
        sa.text(
            "UPDATE settings SET value = :new, updated_at = CURRENT_TIMESTAMP "
            "WHERE key = :key AND value = :old"
        ).bindparams(key=key, old=old, new=new)
    )


def upgrade() -> None:
    for key, old, new in _FLIPS:
        _flip(key, old, new)


def downgrade() -> None:
    for key, old, new in _FLIPS:
        _flip(key, new, old)
