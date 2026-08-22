"""Export the live FastAPI schema to `documentation/openapi.json`.

Module 15's evaluation artifact list calls for `documentation/openapi.json`
plus a generated API reference: this is the one command that produces the
first and lets any standard tool (Redoc, Swagger UI, openapi-typescript)
produce the second, so the reference is always derived from the actual
routes rather than hand-maintained prose that drifts from `API-Contract.md`
the first time an endpoint changes.

No live services required: `create_app()` builds the router tree and Pydantic
schemas needed for `.openapi()` from pure Python introspection — nothing here
opens a database connection or hits the network. That is deliberate; the
lifespan (which does need Postgres/Redis/MinIO) never runs for a plain
import, only when a server or `TestClient` context manager actually starts.

Run::

    uv run python -m scripts.export_openapi
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from app.main import create_app

# backend/scripts/ -> backend -> repo root
_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = _REPO_ROOT / "documentation" / "openapi.json"


def export(output: Path = DEFAULT_OUTPUT) -> tuple[Path, int]:
    """Write the current OpenAPI schema to *output*.

    Returns the path written and the number of documented paths, so the CLI
    can report something more useful than "done".
    """
    schema = create_app().openapi()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(schema, indent=2, sort_keys=True), encoding="utf-8")
    return output, len(schema["paths"])


def main() -> int:
    """CLI entrypoint."""
    output, n_paths = export()
    print(f"Wrote {output} ({n_paths} paths)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
