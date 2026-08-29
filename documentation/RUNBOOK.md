# Runbook

What to do when something goes wrong with the deployed stack. Each entry: how you'd
notice, what's actually happening, what to do about it.

## Check overall health first

```bash
make deploy-ps                       # every container's state + healthcheck status
curl -k https://localhost/health/ready
```

`/health/ready` probes postgres, redis, and object storage individually and reports each
one's latency — the fastest way to tell "which one" from "something's wrong."

## The worker queue backs up

**Symptom**: uploads appear in the dashboard as "pending" and never resolve to a
prediction; `/health/ready` is fine.

1. `docker compose -f docker/docker-compose.yml logs worker` — is it even running? A crash
   loop shows up here immediately.
2. `docker compose -f docker/docker-compose.yml exec worker celery -A app.worker.celery_app
   inspect active` — nothing active for a while, with items queued, usually means the
   worker process died without restarting cleanly. `docker compose restart worker`.
3. If restarts don't help, check the worker's memory — a torch forward pass on a
   memory-constrained container (< 2 GB) can get OOM-killed silently; `docker stats`
   during an upload will show it.

## A device stops reporting

**Symptom**: a paired camera's "last seen" goes stale in the dashboard.

This is expected and already handled by the system, not necessarily a deployment problem:
Module 10's offline-device sweep (run by `beat`) marks a device offline and notifies the
owner after its configured check-in window lapses. Confirm `beat` is actually running
first (`docker compose ps beat`) — if beat is down, *no* periodic job runs, not just this
one, which is a good first thing to rule out before assuming it's the camera or the network.

If `beat` is healthy and the device still never gets marked, check the device's own last
successful ingest in the logs (`docker compose logs backend | grep <device-id>`) — a
device that never got as far as ingest (bad HMAC secret, clock skew past
`GV_DEVICE_CLOCK_SKEW_SECONDS`) is a pairing/firmware problem, not a server one.

## Disk fills up

**Symptom**: writes start failing; `docker compose ps` may show postgres or minio as
unhealthy.

- `docker system df` — Docker's own layer cache and unused images are the most common
  silent consumer on a long-lived deployment. `docker image prune` (safe) or `docker
  system prune` (more aggressive) reclaims space.
- Postgres and MinIO both write to named volumes (`geovision_prod_postgres_data`,
  `geovision_prod_minio_data`) — `docker system df -v` shows each volume's real size.
  Growth here means real data (images, predictions), which is a capacity-planning
  conversation, not a bug — take a backup (`make deploy-backup`) before doing anything
  that touches these volumes.
- Report PDFs accumulate under retention rules already built in Module 10
  (`GV_REPORT_RETENTION_DAYS` — see `.env.example`); confirm `beat`'s cleanup job is
  actually running before assuming retention is broken.

## A model needs replacing

Drop the new checkpoint at `backend/models/classifier/resnet18/v1/best.pt` (or a new
versioned path — update `GV_CLASSIFIER_WEIGHTS` in `.env` if the path changes), then:

```bash
docker compose -f docker/docker-compose.yml restart worker
```

No image rebuild needed — the model directory is a read-only volume mount, not baked into
the image (see [DEPLOYMENT.md](DEPLOYMENT.md#model-placement)). Confirm the swap took by
checking `/api/v1/model/status` (or the dashboard's model-status panel) for the new
checkpoint's reported version/architecture.

## The database needs restoring

```bash
make deploy-restore DIR=backups/<timestamp>
make deploy-migrate   # only if the backup predates a schema change since
```

See [DEPLOYMENT.md](DEPLOYMENT.md#backup-and-restore) for what this actually does — it is
destructive, and asks for confirmation for exactly that reason.

## WebSocket / live updates stop working

Almost always a proxy problem, not an application one: confirm you're reaching the system
through nginx (`https://localhost`), not the backend container directly. `docker compose
logs nginx` will show a failed upgrade if the `Upgrade`/`Connection` headers ever stop
reaching it (e.g. after an nginx.conf edit) — this exact trap is called out in
[Module-16-Deployment.md](../GeoVision-Vault/03-Modules/Module-16-Deployment.md)'s own
critical notes for a reason: it works in dev (no proxy in the way) and silently breaks
only once fronted by nginx.

## Related

[[Module-16-Deployment]] · [DEPLOYMENT.md](DEPLOYMENT.md) · [DEMO.md](DEMO.md)
