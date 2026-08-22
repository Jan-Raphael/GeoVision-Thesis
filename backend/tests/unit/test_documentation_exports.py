"""`scripts/export_openapi.py` and `scripts/export_erd.py` produce what they promise.

Both are pure introspection over already-imported Python objects — no
database, no network — so these run as fast unit tests, not integration
tests, even though what they describe (the API surface, the schema) is
usually integration-tested territory.
"""

from __future__ import annotations

import json

import pytest

from scripts.export_erd import build_erd
from scripts.export_erd import export as export_erd
from scripts.export_openapi import export as export_openapi

pytestmark = pytest.mark.unit


class TestExportOpenAPI:
    def test_writes_valid_json_with_paths(self, tmp_path) -> None:
        output, n_paths = export_openapi(tmp_path / "openapi.json")
        assert output.exists()
        schema = json.loads(output.read_text(encoding="utf-8"))
        assert schema["paths"]
        assert n_paths == len(schema["paths"])

    def test_includes_a_known_ingest_endpoint(self, tmp_path) -> None:
        _, _ = export_openapi(tmp_path / "openapi.json")
        schema = json.loads((tmp_path / "openapi.json").read_text(encoding="utf-8"))
        assert any("/ingest/images" in path for path in schema["paths"])


class TestExportERD:
    def test_build_erd_includes_every_non_omitted_table(self) -> None:
        text = build_erd()
        assert "erDiagram" in text
        assert "projects {" in text
        assert "images {" in text
        # Deliberately omitted for legibility (see `_OMIT_FROM_BOXES`).
        assert "audit_logs {" not in text

    def test_marks_primary_and_foreign_keys(self) -> None:
        text = build_erd()
        assert "uuid id PK" in text
        assert "FK" in text

    def test_export_writes_the_file(self, tmp_path) -> None:
        output = export_erd(tmp_path / "erd.mmd")
        assert output.exists()
        assert output.read_text(encoding="utf-8").startswith("erDiagram")
