---
title: Local Environment Setup (Docker Desktop on Windows)
type: architecture
status: canonical
updated: 2026-08-13
---

# Local Environment Setup — Docker Desktop on Windows 10

Written for the actual dev machine: **Windows 10 Pro, build 19045 (22H2), project on `F:`**.
Follow it in order; every phase ends with a command whose output tells you whether to continue.

**Time:** ~45–60 min, most of it downloading. **Two reboots.**

> **Why Docker at all?** Modules 02–15 need PostgreSQL, Redis, and MinIO, and ADR-013 puts
> the Celery worker in a Linux container. Doing this once removes an entire class of
> "works on my machine" problems and keeps dev identical to the Module 16 deployment.

---

## Alternative — native PostgreSQL, no Docker (what was actually done)

Docker is required from **Module 05** onward (Redis, MinIO, the Celery worker). Modules 02–04
need only PostgreSQL, which has a first-class Windows installer and no WSL2 dependency.

Installed on 2026-08-13, entirely on `F:` to keep `C:` free:

```powershell
# Installer: https://www.enterprisedb.com/downloads/postgres-postgresql-downloads
# Run elevated, unattended, everything on F:
.\postgresql-16-x64.exe --mode unattended --unattendedmodeui minimal `
  --prefix "F:\PostgreSQL\16" --datadir "F:\PostgreSQL\16\data" `
  --serverport 5433 --superpassword <GV_POSTGRES_PASSWORD> `
  --enable-components server,commandlinetools
```

Then create the role, databases, and extensions the Docker init scripts would have created:

```powershell
$env:PGPASSWORD = "<GV_POSTGRES_PASSWORD>"
$psql = "F:\PostgreSQL\16\bin\psql.exe"
& $psql -h localhost -p 5433 -U postgres -c "CREATE ROLE geovision LOGIN PASSWORD '<pw>' CREATEDB"
& "F:\PostgreSQL\16\bin\createdb.exe" -h localhost -p 5433 -U postgres -O geovision geovision
& "F:\PostgreSQL\16\bin\createdb.exe" -h localhost -p 5433 -U postgres -O geovision geovision_test
foreach ($db in @('geovision','geovision_test')) {
  & $psql -h localhost -p 5433 -U postgres -d $db -c "CREATE EXTENSION IF NOT EXISTS pgcrypto; CREATE EXTENSION IF NOT EXISTS citext; CREATE EXTENSION IF NOT EXISTS pg_trgm; CREATE EXTENSION IF NOT EXISTS btree_gin;"
}
```

> Note the installer needs **elevation** (it creates a Windows service); a non-elevated run
> unpacks files and then rolls back with exit code 1.

Result: `GET /health/ready` reports `postgres: ok`, with `redis` and `object_storage` still
`failed` until Docker arrives. That partial-readiness state is correct and expected.

---

## Phase 0 — Pre-flight (5 min)

Two things must be true before you download anything. Checking now avoids a failed install.

### 0.1 Hardware virtualization must be ON

`Ctrl+Shift+Esc` → **Performance** → **CPU** → look for **Virtualization: Enabled**.

If it says *Disabled*, reboot into BIOS/UEFI (usually `Del`, `F2`, or `F10` at boot) and
enable **Intel VT-x** / **AMD-V** (sometimes labelled *SVM Mode* or *Intel Virtualization
Technology*). Nothing below works without it.

### 0.2 Windows must be fully updated

```powershell
winver
```
You need **build 19045 or later**. You are exactly at the current minimum Docker Desktop
supports, so run Windows Update to completion first — an older patch level is a common cause
of "WSL 2 installation is incomplete".

### 0.3 Check for port conflicts

The stack binds **5433**, **6379**, **9000**, **9001**:

```powershell
Get-NetTCPConnection -State Listen |
  Where-Object { $_.LocalPort -in 5433,6379,9000,9001 } |
  Select-Object LocalPort, OwningProcess
```
Empty output is what you want. (5432 is deliberately avoided — a locally installed PostgreSQL
usually holds it, which is why the project maps **5433**.)

---

## Phase 1 — Install WSL2 (10 min + reboot)

Docker Desktop runs its Linux containers inside WSL2. Install it first, separately, so any
failure is unambiguous.

Open **PowerShell as Administrator**:

```powershell
wsl --install
```

This enables the *Virtual Machine Platform* and *Windows Subsystem for Linux* features,
installs the WSL2 kernel, and sets WSL2 as the default. Then:

```powershell
Restart-Computer
```

### Verify after reboot

```powershell
wsl --status
wsl --version
```
Expect `Default Version: 2`. If `wsl --version` is not recognised, update the kernel:

```powershell
wsl --update
```

> You do **not** need to install Ubuntu or any Linux distribution. Docker Desktop creates its
> own `docker-desktop` WSL instance. If `wsl --install` pulled Ubuntu in anyway, that is
> harmless — leave it.

---

## Phase 2 — Install Docker Desktop (15 min + reboot)

1. Download **Docker Desktop for Windows (AMD64)** from
   <https://www.docker.com/products/docker-desktop/>
2. Run the installer. On the configuration screen:
   - ✅ **Use WSL 2 instead of Hyper-V** ← must be checked
   - ✅ Add shortcut to desktop
3. Let it finish, then **sign out of Windows and back in** (or reboot).
4. Launch **Docker Desktop**. Accept the service agreement.
5. **Skip the sign-in prompt** — an account is not required for local development.
6. Wait for the whale icon in the system tray to stop animating and the dashboard to read
   **Engine running**.

### Verify

```powershell
docker --version
docker compose version
docker run --rm hello-world
```

`hello-world` printing *"This message shows that your installation appears to be working
correctly"* is the real proof: it means the daemon, WSL2 backend, and image pull all work.

---

## Phase 3 — Constrain resource usage (5 min, strongly recommended)

WSL2 will otherwise claim up to ~50–80 % of your RAM and not readily give it back. Create
`C:\Users\<you>\.wslconfig`:

```ini
[wsl2]
memory=4GB          # plenty for postgres + redis + minio
processors=4
swap=2GB
localhostForwarding=true
```

Apply it:

```powershell
wsl --shutdown
```
Docker Desktop restarts its VM automatically. Raise `memory` later if you train models inside
containers — for the dev stack, 4 GB is comfortable.

---

## Phase 4 — Start the GeoVision stack (5 min)

```powershell
cd F:\GeoVision-Project

# .env must exist first — compose reads the passwords from it
python scripts/generate_secrets.py

.\dev.ps1 up
```

Expected: three images pull (~400 MB the first time), then:

```
NAME                    STATUS
geovision-postgres      Up (healthy)
geovision-redis         Up (healthy)
geovision-minio         Up (healthy)
geovision-minio-init    Exited (0)
```

> **`minio-init` showing `Exited (0)` is correct, not a failure.** It is a one-shot container
> that creates the bucket and stops. Without it, the first image upload in Module 05 would
> fail with `NoSuchBucket`.

### First boot does two things you only get once

The `postgres_data` volume is empty on first start, so `docker/postgres/init/` runs:
`pgcrypto`, `citext`, `pg_trgm`, `btree_gin`, plus the `geovision_test` database. **These
scripts never run again** while the volume exists — if you need to re-run them, use
`.\dev.ps1 nuke` (destroys all local data) and `up` again.

---

## Phase 5 — Verify each service (5 min)

### PostgreSQL
```powershell
docker exec -it geovision-postgres psql -U geovision -d geovision -c "\dx"
```
Expect `btree_gin`, `citext`, `pg_trgm`, `pgcrypto`, `plpgsql`. Confirm the test database too:
```powershell
docker exec -it geovision-postgres psql -U geovision -l
```

### Redis
```powershell
docker exec -it geovision-redis redis-cli ping
```
→ `PONG`

### MinIO
Open <http://localhost:9001>. Log in with `GV_S3_ACCESS_KEY` / `GV_S3_SECRET_KEY` from your
`.env`. You should see buckets **`geovision`** and **`geovision-test`**.

### The whole stack, from the application's point of view

```powershell
.\dev.ps1 api
```
then in a second terminal:
```powershell
Invoke-RestMethod http://localhost:8000/health/ready | ConvertTo-Json
```

This is the payoff, and the single check that matters:

```json
{
  "status": "ready",
  "checks": {
    "postgres":       { "status": "ok", "latency_ms": 3.1 },
    "redis":          { "status": "ok", "latency_ms": 0.9 },
    "object_storage": { "status": "ok", "latency_ms": 6.4 }
  }
}
```

**`"status": "ready"` with HTTP 200 means the environment is done.** Before Docker this
endpoint returned `503`; that transition is the proof.

---

## Phase 6 — Daily workflow

| Task | Command |
|---|---|
| Start services | `.\dev.ps1 up` |
| Stop services (keep data) | `.\dev.ps1 down` |
| Service status | `.\dev.ps1 ps` |
| Tail logs | `.\dev.ps1 logs` |
| Run the API | `.\dev.ps1 api` |
| Run the dashboard | `.\dev.ps1 dashboard` |
| Migrations (Module 02+) | `.\dev.ps1 migrate` |
| Everything CI runs | `.\dev.ps1 check` |
| **Wipe all local data** | `.\dev.ps1 nuke` (asks for confirmation) |

Set Docker Desktop to **not** start on boot (Settings → General) unless you want it always
resident; `.\dev.ps1 up` will start the engine on demand.

Data lives in named volumes (`geovision_postgres_data`, `geovision_redis_data`,
`geovision_minio_data`) and survives `down`, restarts, and reboots. Only `nuke` removes it.

---

## Troubleshooting

| Symptom | Cause & fix |
|---|---|
| *"WSL 2 installation is incomplete"* | `wsl --update`, then `wsl --shutdown`, then restart Docker Desktop |
| *"Hardware assisted virtualization … not enabled"* | Phase 0.1 — enable VT-x/AMD-V in BIOS |
| Docker Desktop hangs on "Starting…" | `wsl --shutdown` in an admin PowerShell, then relaunch. If it persists, Settings → **Troubleshoot** → *Clean / Purge data* |
| `bind: address already in use` | Something holds 5433/6379/9000. Find it with the Phase 0.3 command, or change the host port in `.env` (`GV_POSTGRES_PORT`) |
| `variable is not set` / `GV_POSTGRES_PASSWORD` error | `.env` missing → run `python scripts/generate_secrets.py`. (`dev.ps1` passes `--env-file` explicitly, because Compose otherwise looks for `.env` next to the compose file.) |
| `password authentication failed` after changing `.env` | The password is baked into the volume on first init. `.\dev.ps1 nuke` then `up` |
| Postgres healthy but `/health/ready` shows failed | You are likely connecting to a *local* PostgreSQL on 5432. Confirm `GV_POSTGRES_PORT=5433` |
| `minio-init` shows `Exited (1)` | Read `docker logs geovision-minio-init`; usually MinIO was not healthy yet — `.\dev.ps1 down` then `up` |
| VirtualBox/VMware stops working | Hyper-V and WSL2 claim the hypervisor. Recent VirtualBox ≥ 7 coexists; older versions do not |
| Everything is slow | Raise `memory` in `.wslconfig`; exclude `F:\GeoVision-Project` from real-time antivirus scanning |
| Reset everything | `wsl --shutdown`, Docker Desktop → Troubleshoot → *Clean / Purge data*, then Phase 4 |

---

## What this unblocks

| Module | Now available |
|---|---|
| [[Module-02-Database-Schema]] | PostgreSQL + Alembic migrations |
| [[Module-03-Auth-and-Users]] | — |
| [[Module-04-Projects-and-Folders]] | + MinIO for reference assets |
| [[Module-05-Device-Pairing-and-Ingestion]] | + Redis for the HMAC nonce cache |
| [[Module-09-Inference-Service]] | + Celery worker in a Linux container (ADR-013) |
| [[Module-14-Realtime]] | + Redis pub/sub fan-out |
| [[Module-16-Deployment]] | the full containerised stack |

## Related
[[Tech-Stack]] · [[Module-01-Foundation-Setup]] · [[Module-02-Database-Schema]] · [[ADR-Index]] · [[Open-Questions]]
