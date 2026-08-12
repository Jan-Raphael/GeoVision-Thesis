r"""Integration tests require the dev stack (`make up` / `.\dev.ps1 up`).

Real integration coverage lands in Module 02 alongside the repositories. This
placeholder exists so the `integration` marker is exercised and CI proves the
selection works before there is anything substantial to select.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


def test_integration_marker_is_registered() -> None:
    """A no-op that confirms marker configuration is wired correctly."""
    assert True
