"""Fill the ``CHANGE_ME`` placeholders in a local ``.env`` with real secrets.

Creating ``.env`` by hand invites two failure modes: forgetting a value (the app
refuses to start) and, worse, leaving a weak placeholder in place and shipping
it. This script does it correctly and idempotently::

    python scripts/generate_secrets.py            # create/patch ./.env
    python scripts/generate_secrets.py --force    # regenerate every secret

Existing non-placeholder values are preserved, so it is safe to re-run after
``.env.example`` gains new keys.
"""

from __future__ import annotations

import argparse
import secrets
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ENV_EXAMPLE = REPO_ROOT / ".env.example"
ENV_FILE = REPO_ROOT / ".env"

PLACEHOLDER_PREFIX = "CHANGE_ME"

#: key -> generator. Passwords are shorter/alphanumeric because they travel
#: through connection URLs where punctuation needs escaping.
GENERATORS: dict[str, "object"] = {
    "GV_JWT_SECRET_KEY": lambda: secrets.token_urlsafe(64),
    "GV_POSTGRES_PASSWORD": lambda: secrets.token_hex(16),
    "GV_S3_SECRET_KEY": lambda: secrets.token_hex(16),
    # Encrypts every paired camera's HMAC secret at rest (ADR-020). Generated
    # like any other secret, but it is the one with no recovery path: rotate or
    # lose it and every deployed camera must be re-paired by hand, on site.
    "GV_DEVICE_SECRET_KEY": lambda: secrets.token_urlsafe(48),
}


def _parse(text: str) -> list[tuple[str, str, str]]:
    """Split env text into ``(kind, key, raw_line)`` triples.

    ``kind`` is ``"pair"`` for ``KEY=VALUE`` lines and ``"raw"`` for comments
    and blank lines, which are preserved verbatim so the file stays readable.
    """
    parsed: list[tuple[str, str, str]] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            parsed.append(("raw", "", line))
        else:
            key = stripped.split("=", 1)[0].strip()
            parsed.append(("pair", key, line))
    return parsed


def main() -> int:
    """Create or patch ``.env``. Returns a process exit code."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--force",
        action="store_true",
        help="regenerate secrets even if they already hold a real value",
    )
    args = parser.parse_args()

    if not ENV_EXAMPLE.exists():
        print(f"error: {ENV_EXAMPLE} not found", file=sys.stderr)
        return 1

    if not ENV_FILE.exists():
        shutil.copyfile(ENV_EXAMPLE, ENV_FILE)
        print(f"created {ENV_FILE.name} from {ENV_EXAMPLE.name}")

    existing = {
        key: line.split("=", 1)[1].strip()
        for kind, key, line in _parse(ENV_FILE.read_text(encoding="utf-8"))
        if kind == "pair"
    }

    # Rebuild from the template so newly added keys are picked up, while
    # carrying across any value the developer has already customised.
    out_lines: list[str] = []
    generated: list[str] = []
    for kind, key, line in _parse(ENV_EXAMPLE.read_text(encoding="utf-8")):
        if kind == "raw":
            out_lines.append(line)
            continue

        current = existing.get(key, line.split("=", 1)[1].strip())
        needs_secret = key in GENERATORS and (
            args.force or not current or current.startswith(PLACEHOLDER_PREFIX)
        )
        if needs_secret:
            current = GENERATORS[key]()  # type: ignore[operator]
            generated.append(key)
        out_lines.append(f"{key}={current}")

    ENV_FILE.write_text("\n".join(out_lines) + "\n", encoding="utf-8")

    if generated:
        print("generated secrets for: " + ", ".join(generated))
    else:
        print("all secrets already set (use --force to regenerate)")

    remaining = [
        key
        for kind, key, line in _parse(ENV_FILE.read_text(encoding="utf-8"))
        if kind == "pair" and line.split("=", 1)[1].strip().startswith(PLACEHOLDER_PREFIX)
    ]
    if remaining:
        print("\nstill needs a manual value: " + ", ".join(remaining), file=sys.stderr)
        return 1

    print(f"{ENV_FILE.name} is ready. It is git-ignored - never commit it.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
