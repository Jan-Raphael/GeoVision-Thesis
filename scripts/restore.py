"""Restore a backup written by ``backup.py`` into the deployed stack.

    python scripts/restore.py backups/20260829T120000Z

Destructive: drops and recreates every table in the target database before
loading the dump. Intended for disaster recovery or standing up a fresh
environment from a known-good backup — never run this against a stack you
did not mean to overwrite.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
COMPOSE_FILE = REPO_ROOT / "docker" / "docker-compose.yml"
ENV_FILE = REPO_ROOT / ".env"


def _compose(*args: str) -> list[str]:
    return ["docker", "compose", "--env-file", str(ENV_FILE), "-f", str(COMPOSE_FILE), *args]


def _env_value(key: str, default: str) -> str:
    if not ENV_FILE.exists():
        return default
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        if line.strip().startswith(f"{key}="):
            return line.split("=", 1)[1].strip() or default
    return default


def main() -> int:
    """Load a backup directory's postgres dump and minio mirror back into the stack."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("backup_dir", help="a directory written by scripts/backup.py")
    parser.add_argument(
        "--yes", action="store_true", help="skip the confirmation prompt (for scripted use)"
    )
    args = parser.parse_args()

    backup_dir = Path(args.backup_dir)
    dump_path = backup_dir / "postgres.sql"
    minio_dir = backup_dir / "minio"

    if not dump_path.exists():
        print(f"{dump_path} not found -- is this a directory scripts/backup.py wrote?", file=sys.stderr)
        return 1

    if not args.yes:
        answer = input(
            f"This will DROP AND RECREATE every table in the target database "
            f"and overwrite the minio bucket with {backup_dir}. Continue? [y/N] "
        )
        if answer.strip().lower() != "y":
            print("aborted")
            return 1

    postgres_user = _env_value("GV_POSTGRES_USER", "geovision")
    postgres_db = _env_value("GV_POSTGRES_DB", "geovision")
    bucket = _env_value("GV_S3_BUCKET", "geovision")
    access_key = _env_value("GV_S3_ACCESS_KEY", "geovision")
    secret_key = _env_value("GV_S3_SECRET_KEY", "")

    print("dropping and recreating the schema...")
    subprocess.run(
        _compose(
            "exec", "-T", "postgres", "psql", "-U", postgres_user, "-d", postgres_db,
            "-c", "DROP SCHEMA public CASCADE; CREATE SCHEMA public;",
        ),
        check=True,
    )

    print(f"restoring {dump_path}...")
    with dump_path.open("rb") as dump_file:
        result = subprocess.run(
            _compose("exec", "-T", "postgres", "psql", "-U", postgres_user, "-d", postgres_db),
            stdin=dump_file,
            check=False,
        )
    if result.returncode != 0:
        print("postgres restore failed", file=sys.stderr)
        return 1

    if minio_dir.exists():
        print("restoring minio bucket...")
        mirror_script = (
            f"mc alias set local http://minio:9000 {access_key} {secret_key} && "
            f"mc mirror /backup local/{bucket}"
        )
        result = subprocess.run(
            _compose(
                "run", "--rm", "--no-deps",
                "--entrypoint", "sh",
                "-v", f"{minio_dir}:/backup:ro",
                "minio-init", "-c", mirror_script,
            ),
            check=False,
        )
        if result.returncode != 0:
            print("minio restore failed", file=sys.stderr)
            return 1

    print("\nrestore complete. Run `make deploy-migrate` if this backup predates a schema change.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
