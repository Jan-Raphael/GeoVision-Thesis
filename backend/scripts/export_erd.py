"""Export a Mermaid ERD from the live SQLAlchemy metadata.

`Domain-Model.md` carries a hand-written Mermaid ERD as the canonical
*design*. This script exports a second one from `Base.metadata` — the
schema as Alembic has actually built it — so the two can be diffed. They
are expected to agree; the value of generating this one is that a forgotten
migration or a renamed column shows up as a diff instead of staying
invisible until someone reads both by eye and happens to notice.

Run::

    uv run python -m scripts.export_erd
"""

from __future__ import annotations

import sys
from pathlib import Path

from sqlalchemy import MetaData, Table

# Importing the models module is what populates Base.metadata — SQLAlchemy
# only knows about a table once its model class has been imported somewhere.
from app.infrastructure.db import models  # noqa: F401
from app.infrastructure.db.base import Base

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = _REPO_ROOT / "documentation" / "erd.mmd"

# Association/log tables render as a wall of foreign keys with little design
# information; the entity boxes for the tables that matter to the domain
# model stay readable if these are represented as relationships only,
# matching the abbreviated ERD already in `Domain-Model.md`.
_OMIT_FROM_BOXES = {"audit_logs", "refresh_tokens"}


def _column_lines(table: Table) -> list[str]:
    lines = []
    for column in table.columns:
        marks = []
        if column.primary_key:
            marks.append("PK")
        if column.foreign_keys:
            marks.append("FK")
        mark = " ".join(marks)
        type_name = str(column.type).split("(")[0].lower()
        lines.append(f"        {type_name} {column.name} {mark}".rstrip())
    return lines


def build_erd(metadata: MetaData = Base.metadata) -> str:
    """Render every table and foreign-key relationship as Mermaid `erDiagram` syntax."""
    lines = ["erDiagram"]

    for name in sorted(metadata.tables):
        if name in _OMIT_FROM_BOXES:
            continue
        table = metadata.tables[name]
        lines.append(f"    {name} {{")
        lines.extend(_column_lines(table))
        lines.append("    }")

    seen: set[tuple[str, str]] = set()
    for name in sorted(metadata.tables):
        table = metadata.tables[name]
        for fk in table.foreign_keys:
            target = fk.column.table.name
            pair = (target, name)
            if pair in seen:
                continue
            seen.add(pair)
            # `o{` (zero-or-many) is the safe default for a plain FK — nothing
            # in SQLAlchemy's reflected metadata distinguishes an optional
            # child from a required one at this level, and overstating the
            # cardinality would be worse than the generic version.
            lines.append(f'    {target} ||--o{{ {name} : "has"')

    return "\n".join(lines) + "\n"


def export(output: Path = DEFAULT_OUTPUT) -> Path:
    """Write the rendered ERD to *output* and return the path."""
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(build_erd(), encoding="utf-8")
    return output


def main() -> int:
    """CLI entrypoint."""
    output = export()
    n_tables = len(Base.metadata.tables)
    print(f"Wrote {output} ({n_tables} tables)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
