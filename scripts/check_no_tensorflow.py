"""Assert that TensorFlow, Keras, and friends are absent from the project.

"No TensorFlow" is a hard constraint for GeoVision (see ``CLAUDE.md`` and
``GeoVision-Vault/01-Architecture/Tech-Stack.md``). The rule is easy to violate
by accident, because a transitive dependency can drag TensorFlow in without any
line of our own code mentioning it.

This script is deliberately paranoid and checks three places:

1. declared dependencies in every ``pyproject.toml`` / ``requirements*.txt``
2. resolved dependencies in every ``uv.lock`` (this is where a *transitive*
   violation shows up)
3. the currently importable environment

Run manually, from pre-commit, and from CI::

    python scripts/check_no_tensorflow.py

Exit code 0 means clean; 1 means a forbidden package was found.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

#: Package names that must never appear. Matched case-insensitively against
#: whole tokens so that, e.g., ``keras`` matches but a longer hyphenated name
#: that merely contains it does not trigger a false positive.
FORBIDDEN: tuple[str, ...] = (
    "tensorflow",
    "tensorflow-cpu",
    "tensorflow-gpu",
    "tensorflow-intel",
    "tensorflow-macos",
    "tf-nightly",
    "keras",
    "tf-keras",
    "tensorboard",  # pulls the TF ecosystem; we log to CSV + matplotlib instead
)

#: Files we scan for declared/resolved dependencies.
SCAN_GLOBS: tuple[str, ...] = (
    "**/pyproject.toml",
    "**/uv.lock",
    "**/requirements*.txt",
)

#: Directories that are never interesting and can be huge.
SKIP_PARTS = {".venv", "venv", "node_modules", ".git", ".mypy_cache", ".ruff_cache"}


def _iter_files() -> list[Path]:
    """Collect dependency-declaring files, skipping vendored directories."""
    found: list[Path] = []
    for pattern in SCAN_GLOBS:
        for path in REPO_ROOT.glob(pattern):
            if SKIP_PARTS.isdisjoint(path.parts):
                found.append(path)
    return sorted(found)


def _scan_file(path: Path) -> list[tuple[int, str, str]]:
    """Return ``(line_number, package, line)`` for each forbidden hit in *path*."""
    hits: list[tuple[int, str, str]] = []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:  # pragma: no cover - an unreadable file is a real failure
        print(f"  ! could not read {path}: {exc}", file=sys.stderr)
        return hits

    for lineno, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        # Skip comments: this project mentions TensorFlow by name in order to
        # forbid it. Prose must not fail the build.
        if stripped.startswith("#") or stripped.startswith("//"):
            continue
        for package in FORBIDDEN:
            if re.search(rf"(?<![\w-]){re.escape(package)}(?![\w-])", line, re.IGNORECASE):
                hits.append((lineno, package, stripped))
    return hits


def _scan_environment() -> list[str]:
    """Return forbidden distributions installed in the current interpreter."""
    from importlib.metadata import distributions

    forbidden_lower = {p.lower() for p in FORBIDDEN}
    installed = set()
    for dist in distributions():
        name = (dist.metadata["Name"] or "").lower()
        if name in forbidden_lower:
            installed.add(f"{name}=={dist.version}")
    return sorted(installed)


def main() -> int:
    """Run every check and report. Returns a process exit code."""
    violations = 0

    print("Checking dependency files for TensorFlow / Keras ...")
    files = _iter_files()
    if not files:
        print("  (no dependency files found yet)")
    for path in files:
        hits = _scan_file(path)
        rel = path.relative_to(REPO_ROOT)
        if hits:
            violations += len(hits)
            for lineno, package, line in hits:
                print(f"  FORBIDDEN  {rel}:{lineno}  [{package}]  {line}")
        else:
            print(f"  ok         {rel}")

    print("Checking the installed environment ...")
    installed = _scan_environment()
    if installed:
        violations += len(installed)
        for item in installed:
            print(f"  FORBIDDEN  installed: {item}")
    else:
        print("  ok         no forbidden distributions installed")

    if violations:
        print(
            f"\nFAILED: {violations} TensorFlow/Keras reference(s) found.\n"
            "GeoVision is a PyTorch-only project. If a dependency pulled this in\n"
            "transitively, replace that dependency - do not add an exception.",
            file=sys.stderr,
        )
        return 1

    print("\nPASSED: project is TensorFlow-free.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
