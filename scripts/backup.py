"""Back up the deployed stack's Postgres database and MinIO bucket.

Module 16's own rule: "an untested backup is not a backup" — this and
``restore.py`` are a matched pair, meant to be exercised together at least
once (`make deploy-backup` then `make deploy-restore` against a scratch
stack) rather than trusted on faith.

    python scripts/backup.py                    # writes to ./backups/<timestamp>/
    python scripts/backup.py --out-dir /mnt/nas  # anywhere else

Requires the deployed stack to be up (`make deploy-up`) — this shells out to
``docker compose`` rather than talking to Postgres/MinIO directly, so it
always backs up exactly what the running containers hold.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
COMPOSE_FILE = REPO_ROOT / "docker" / "docker-compose.yml"
ENV_FILE = REPO_ROOT / ".env"


def _compose(*args: str) -> list[str]:
    return ["docker", "compose", "--env-file", str(ENV_FILE), "-f", str(COMPOSE_FILE), *args]


def _env_value(key: str, default: str) -> str:
    """Read one ``KEY=value`` line from ``.env`` without pulling in a dependency."""
    if not ENV_FILE.exists():
        return default
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        if line.strip().startswith(f"{key}="):
            return line.split("=", 1)[1].strip() or default
    return default


def main() -> int:
    """Dump Postgres and mirror the MinIO bucket into a timestamped directory."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", default=str(REPO_ROOT / "backups"))
    args = parser.parse_args()

    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    backup_dir = Path(args.out_dir) / timestamp
    backup_dir.mkdir(parents=True, exist_ok=True)

    postgres_user = _env_value("GV_POSTGRES_USER", "geovision")
    postgres_db = _env_value("GV_POSTGRES_DB", "geovision")
    bucket = _env_value("GV_S3_BUCKET", "geovision")
    access_key = _env_value("GV_S3_ACCESS_KEY", "geovision")
    secret_key = _env_value("GV_S3_SECRET_KEY", "")

    print(f"backing up to {backup_dir}")

    dump_path = backup_dir / "postgres.sql"
    print("dumping postgres...")
    with dump_path.open("wb") as dump_file:
        result = subprocess.run(
            _compose("exec", "-T", "postgres", "pg_dump", "-U", postgres_user, postgres_db),
            stdout=dump_file,
            check=False,
        )
    if result.returncode != 0 or dump_path.stat().st_size == 0:
        print("postgres dump failed or was empty -- is the stack up? (`make deploy-up`)", file=sys.stderr)
        return 1
    print(f"  {dump_path} ({dump_path.stat().st_size} bytes)")

    minio_dir = backup_dir / "minio"
    minio_dir.mkdir()
    print("mirroring minio bucket...")
    mirror_script = (
        f"mc alias set local http://minio:9000 {access_key} {secret_key} && "
        f"mc mirror local/{bucket} /backup"
    )
    result = subprocess.run(
        _compose(
            "run", "--rm", "--no-deps",
            "--entrypoint", "sh",
            "-v", f"{minio_dir}:/backup",
            "minio-init", "-c", mirror_script,
        ),
        check=False,
    )
    if result.returncode != 0:
        print("minio mirror failed -- is the stack up? (`make deploy-up`)", file=sys.stderr)
        return 1

    print(f"\nbackup complete: {backup_dir}")
    print(f"restore with: python scripts/restore.py {backup_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
