"""m09 predictions kept not deleted

Revision ID: c3f7a1b92e04
Revises: 69cb08707dee
Create Date: 2026-08-28 12:00:00.000000+00:00

Every revision must be reversible: `downgrade()` is not optional. A migration
that cannot be rolled back is a migration you cannot safely deploy.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c3f7a1b92e04"
down_revision: str | None = "69cb08707dee"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Keep every prediction instead of deleting the old one on reprocess (Open-Questions Q11).

    Three changes, together:

    1. `predictions.image_id` drops its plain `UNIQUE` constraint — the whole point is to allow
       a second row per image once the first is superseded.
    2. `superseded_at` is added. `NULL` means "this is the image's current prediction";
       reprocessing sets it instead of deleting the row.
    3. A **partial** unique index replaces the constraint: at most one row per `image_id` may
       have `superseded_at IS NULL`. This is what `list_eligible_in_window` and every reader
       that expects "the" prediction for an image rely on — a plain unique constraint cannot
       express "unique among current rows only", which is exactly why a real column is needed
       here rather than reusing `created_at` ordering at query time.

    Also fixed in the same migration, found while touching this table: the `fine_class_index`
    check constraint still allowed `0..9`, the retired 10-class range from before ADR-036/
    ADR-038 narrowed the classifier to 4 classes. Left alone, it would have silently accepted
    an out-of-range index from a checkpoint trained against the wrong `classes.yaml`.
    """
    op.drop_constraint(op.f("uq_predictions_image_id"), "predictions", type_="unique")
    op.add_column("predictions", sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index(
        op.f("uq_predictions_image_id_current"),
        "predictions",
        ["image_id"],
        unique=True,
        postgresql_where=sa.text("superseded_at IS NULL"),
    )
    # Any row with an index outside 0..3 predates ADR-036/ADR-038 (the retired 10-class
    # scheme) and cannot be reinterpreted under the current `classes.yaml` — index 3 alone
    # meant a different class ("Foundation", old scheme) than it does now ("Finishing").
    # Found on this project's own dev database: 60 rows, all seed/test artifacts, none
    # newer than the rescope. Deleting them is data loss in the abstract, but keeping them
    # would violate the tightened constraint below while being actively wrong, not just
    # out of range — `scripts/seed_db.py` regenerates equivalent fresh rows on demand.
    op.execute("DELETE FROM predictions WHERE fine_class_index NOT BETWEEN 0 AND 3")
    op.drop_constraint(op.f("ck_predictions_fine_class_index_range"), "predictions", type_="check")
    op.create_check_constraint(
        op.f("ck_predictions_fine_class_index_range"), "predictions", "fine_class_index BETWEEN 0 AND 3"
    )


def downgrade() -> None:
    """Restore the one-row-per-image shape.

    Reversible in shape only: if any image has accumulated superseded predictions by the time
    this runs, re-adding a plain `UNIQUE(image_id)` will fail outright (Postgres refuses a
    unique constraint the existing data already violates). Delete the superseded rows first
    (`DELETE FROM predictions WHERE superseded_at IS NOT NULL`) if a genuine rollback is needed
    — which also means downgrading discards exactly the history this migration was written to
    keep. That is inherent to reverting this feature, not an oversight in the migration.
    """
    op.drop_constraint(op.f("ck_predictions_fine_class_index_range"), "predictions", type_="check")
    op.create_check_constraint(
        op.f("ck_predictions_fine_class_index_range"), "predictions", "fine_class_index BETWEEN 0 AND 9"
    )
    op.drop_index(op.f("uq_predictions_image_id_current"), table_name="predictions")
    op.drop_column("predictions", "superseded_at")
    op.create_unique_constraint(op.f("uq_predictions_image_id"), "predictions", ["image_id"])
