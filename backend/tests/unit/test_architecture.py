"""Executable checks on the architectural constraints.

``lint-imports`` enforces the full layer contract, but it is a separate command
that is easy to skip locally. These tests put the two most consequential rules
into the ordinary test run, where they cannot be forgotten:

* ``domain/`` stays framework-free (ADR: Clean Architecture)
* the API process never imports torch (ADR-011)

See ``backend/.importlinter`` for the complete set of contracts.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

APP_ROOT = Path(__file__).resolve().parents[2] / "app"

FORBIDDEN_IN_DOMAIN = {
    "fastapi",
    "starlette",
    "sqlalchemy",
    "alembic",
    "asyncpg",
    "celery",
    "redis",
    "boto3",
    "torch",
    "torchvision",
    "cv2",
    "ai",
}


def _iter_python_files(package: Path) -> list[Path]:
    """Return every ``.py`` file under *package*."""
    return sorted(package.rglob("*.py"))


def _imported_roots(path: Path) -> set[str]:
    """Return the top-level module names imported by the file at *path*."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.add(node.module.split(".")[0])
    return roots


def test_domain_layer_is_framework_free() -> None:
    """``app.domain`` must not import any framework, ORM, or ML library.

    This is what keeps the permission matrix and the progress rules testable
    without a database, a broker, or a GPU.
    """
    domain = APP_ROOT / "domain"
    violations: list[str] = []

    for path in _iter_python_files(domain):
        offending = _imported_roots(path) & FORBIDDEN_IN_DOMAIN
        if offending:
            rel = path.relative_to(APP_ROOT.parent)
            violations.append(f"{rel}: {', '.join(sorted(offending))}")

    assert not violations, "domain/ must stay pure:\n  " + "\n  ".join(violations)


def test_domain_does_not_import_outer_layers() -> None:
    """Dependencies point inward: domain may not reach api/application/infra."""
    domain = APP_ROOT / "domain"
    violations: list[str] = []
    forbidden_prefixes = ("app.api", "app.application", "app.infrastructure")

    for path in _iter_python_files(domain):
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.ImportFrom)
                and node.module
                and node.module.startswith(forbidden_prefixes)
            ):
                rel = path.relative_to(APP_ROOT.parent)
                violations.append(f"{rel}: {node.module}")

    assert not violations, "domain/ imports an outer layer:\n  " + "\n  ".join(violations)


def test_api_layer_does_not_import_torch() -> None:
    """The API process must stay free of torch and OpenCV (ADR-011).

    Those belong to the Celery worker. A violation here silently adds ~2 GB to
    the API image and a slow cold start.
    """
    api = APP_ROOT / "api"
    heavy = {"torch", "torchvision", "cv2", "ultralytics"}
    violations: list[str] = []

    for path in _iter_python_files(api):
        offending = _imported_roots(path) & heavy
        if offending:
            rel = path.relative_to(APP_ROOT.parent)
            violations.append(f"{rel}: {', '.join(sorted(offending))}")

    assert not violations, "api/ must not import ML libraries:\n  " + "\n  ".join(violations)


def test_torch_is_not_loaded_by_importing_the_app() -> None:
    """Importing the FastAPI app must not pull torch into memory.

    Catches the transitive case that static analysis misses, e.g. an
    ``app.api`` module importing something that itself imports torch.
    """
    import app.main  # noqa: F401

    assert "torch" not in sys.modules, (
        "importing app.main loaded torch - the API process must stay torch-free"
    )


def test_every_layer_package_exists() -> None:
    """The Clean Architecture skeleton is present and importable."""
    for layer in ("core", "domain", "application", "infrastructure", "api"):
        assert (APP_ROOT / layer / "__init__.py").is_file(), f"missing app/{layer}"
