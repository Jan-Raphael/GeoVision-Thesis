"""m05 device secret encrypted

Revision ID: 69cb08707dee
Revises: a9f1f2a2df41
Create Date: 2026-08-14 01:16:29.414565+00:00

Every revision must be reversible: `downgrade()` is not optional. A migration
that cannot be rolled back is a migration you cannot safely deploy.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "69cb08707dee"
down_revision: str | None = "a9f1f2a2df41"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Replace the device secret hash with an encrypted secret.

    This is deliberately a drop-and-add rather than a rename, because the old
    values could never have worked. `secret_hash` held a SHA-256 digest, but
    verifying an HMAC requires the *key itself* - you cannot recompute a MAC
    from a hash of its key. Any device paired before this migration therefore
    has an unusable credential and must be re-paired; carrying the old column
    forward would only preserve the illusion that it meant something. See
    ADR-020.

    In practice nothing is lost: no device had been paired when this shipped.
    """
    op.add_column("devices", sa.Column("secret_encrypted", sa.Text(), nullable=True))
    op.drop_column("devices", "secret_hash")


def downgrade() -> None:
    """Restore the (unusable) hash column.

    Reversible in shape only: devices paired after the upgrade will not
    authenticate on the old schema, because their credentials no longer have
    anywhere to live. That is inherent to reverting a fix for an impossible
    design, not an oversight in this migration.
    """
    op.add_column(
        "devices", sa.Column("secret_hash", sa.TEXT(), autoincrement=False, nullable=True)
    )
    op.drop_column("devices", "secret_encrypted")
