---
title: Module 04 — Projects & Folders
type: module
module: 4
status: done
started: 2026-08-13
finished: 2026-08-13
updated: 2026-08-13
---

# Module 04 — Projects, Project Folders, Members, Assets & Remarks

> **Status: ✅ done.** Revised after implementation.
> Built **without Docker/MinIO** — see the storage decision below.

## Scope
The heart of the dashboard spec: creating a project folder, everything it contains,
collaboration (B.6), reference uploads, and remarks. Still API-only — the UI is Modules 11–12.

---

## The storage decision (ADR-018)

Module 04 needs somewhere to put uploaded blueprints, and MinIO does not exist yet.
Rather than stub the feature or block the module, the upload path was built against an
**outbound port** with two implementations:

| Backend | Use |
|---|---|
| `LocalObjectStorage` | files on disk — development, and the whole test suite |
| `S3ObjectStorage` | MinIO in Docker, any S3-compatible service in production |

Selected by `GV_STORAGE_BACKEND`. A deployed environment **may not** choose `local` —
the settings validator refuses it, because filesystem storage has no replication, no
lifecycle rules, and no real signed URLs.

The payoff is not just unblocking today: **Module 05's image ingest and Module 10's report
writer inherit both backends for free**, because they will depend on the same port.

---

## What shipped

### Domain
| File | Contents |
|---|---|
| `domain/services/status.py` | `ProjectSignals`, `derive_status`, `explain_status` — pure, with an injected "now". Module 10's beat job reuses them unchanged. |
| `domain/services/file_validation.py` | Magic-byte detection and the upload allowlist. |

### Application
| File | Contents |
|---|---|
| `application/ports/storage.py` | The `ObjectStorage` port + `StoredObject` |
| `application/use_cases/projects.py` | `CreateProject`, `GetProjectFolder`, `UpdateProject`, `SetVisibility`, `ArchiveProject`, `ApproveProject` |
| `application/use_cases/members.py` | `InviteMember`, `RespondToInvitation`, `ChangeMemberRole`, `RemoveMember` |
| `application/use_cases/content.py` | `UploadReferenceAsset`, `DeleteAsset`, remark CRUD, `SubmitContactMessage` |

### Infrastructure & API
`infrastructure/storage/{local,s3}.py` · `contact_messages` table (migration `m04`) ·
`api/v1/presenters.py` · routers `projects.py`, `members.py`, `content.py`, `public.py`

## Endpoints

| Method | Path | Permission |
|---|---|---|
| POST/GET | `/api/v1/projects` | authenticated |
| GET | `/api/v1/projects/{id}` | `project:view` (404 if not) |
| PATCH | `/api/v1/projects/{id}` | `project:edit` |
| PATCH | `/api/v1/projects/{id}/visibility` | `project:visibility` (owner) |
| POST | `/api/v1/projects/{id}/approve` | `project:approve` |
| POST | `/api/v1/projects/{id}/archive` | `project:delete` (owner) |
| GET/POST/PATCH/DELETE | `…/members[/{id}]` | `member:manage` |
| GET/POST | `/api/v1/invitations[/{id}]` | the invitee |
| GET/POST/DELETE | `…/assets[/{id}]`, `…/assets/{id}/download` | `asset:upload` / view |
| GET/POST/PATCH/DELETE | `…/remarks[/{id}]` | `remark:write` / view |
| GET | `/api/v1/public/feed` | — |
| GET | `/api/v1/public/projects/{code}[/timeline]` | — |
| GET | `/api/v1/public/search` | — (rate-limited) |
| POST | `/api/v1/public/contact` | — (rate-limited) |

---

## Decisions worth defending

**The public project page is a separate response model, not a filtered one.**
`PublicProjectResponse` simply has no fields for members, devices, assets, worker counts,
or inspection notes. Filtering the internal model would put one forgotten line between a
private field and the open internet; this way a field added later *cannot* leak. A test
asserts each of those keys is absent.

**A hidden project returns 404 — including to anonymous callers.**
Not 401, not 403. Both of those confirm the project exists, which is itself a disclosure.

**Code suggestions are verified free before being offered.**
A 409 returns three alternatives that have been checked against the database, so the
suggestion a user clicks cannot collide in turn.

**Ownership is transferred, never granted.**
`InviteMember` and `ChangeMemberRole` both refuse to create an owner, and the last owner
cannot be demoted or removed — a project nobody can administer is unrecoverable through
the UI.

**System remarks are immutable.**
They record what the system observed. Letting a user rewrite "progress regression detected"
would destroy the audit value of the whole feed.

**Contact messages are persisted, not emailed.**
v1 has no mail delivery. A contact form that silently discards submissions is broken, not
deferred — so `contact_messages` exists and the owner reads it from the database.

**Status is recomputed on folder read, persisted only when it changes.**
The stored column keeps project *lists* cheap; recomputing on read keeps it honest between
runs of the Module 10 beat job, without a write on every request.

---

## Deviations from the original spec

| Spec said | Built | Why |
|---|---|---|
| separate `assets.py` and `remarks.py` routers | one `content.py` | Both are "things attached to a project" with identical guards; two files of six endpoints added no clarity. |
| separate `search.py` and `contact.py` routers | folded into `public.py` | They are the anonymous surface, and belong with the feed they sit beside. |
| `domain/services/project_code.py` | `ProjectCode` value object (Module 02) + `CreateProject._free_suggestions` | The validation already lived in the value object; a second module would have duplicated it. |
| avatar upload (deferred from Module 03) | **still deferred** | Now unblocked by the storage port — scheduled with the Module 12 profile UI. |

---

## How to run

```powershell
uv run alembic upgrade head
uv run uvicorn app.main:app --reload
# http://localhost:8000/docs
```

Uploads land in `outputs/storage/` with the default local backend. No object store required.

## Testing procedure & results

| # | Check | Result |
|---|---|---|
| 1 | Create project → 201, code generated, owner membership created | ✅ |
| 2 | Duplicate code → 409 with three **verified-free** suggestions | ✅ |
| 3 | Invalid initials / number / latitude → 400 or 422 | ✅ |
| 4 | Lowercase initials are **normalised**, not rejected | ✅ |
| 5 | Anonymous `/public/feed` → public, non-archived only | ✅ |
| 6 | Private project → **404** for strangers *and* anonymous callers | ✅ |
| 7 | Public project page omits every internal field | ✅ |
| 8 | Viewer `PATCH` → 403 | ✅ |
| 9 | Pending invite → 404 on the project; after accepting → 200 | ✅ |
| 10 | `.exe` renamed `.pdf` → 400 `INVALID_FILE` | ✅ |
| 11 | Upload → download round trip, `Content-Disposition: attachment` | ✅ |
| 12 | Owner cannot be invited or promoted; last owner cannot be removed | ✅ |
| 13 | Approve before 80 % → 409 `NOT_AWAITING_INSPECTION` | ✅ |
| 14 | Public project shows only public remarks | ✅ |
| 15 | Search finds public projects, never private ones | ✅ |
| 16 | Every branch of [[Project-Status-Rules]] | ✅ 24 unit tests |
| 17 | Contact message accepted (202); too short → 422 | ✅ |

**413 backend tests** (278 unit + 135 integration), ruff + mypy clean, 4 import contracts kept.

## Bugs and near-misses

- **A layering violation, caught while writing it.** The first `SubmitContactMessage` took a
  session and imported `app.infrastructure.db.models` directly — which the
  `application-independence` contract forbids. Rebuilt behind a `ContactMessageRepository`.
- **Two of my own test expectations were wrong**, not the code: lowercase initials are
  *intentionally* normalised, and an anonymous caller on a private project correctly gets
  404 rather than 401. Both tests now assert the right thing and say why.
- **Module 03's config tests broke** when the "no local storage in production" rule landed —
  correctly, since they built production settings without naming a backend. Updated.

## Done criteria

- [x] Create / read / update / archive project + immutable code
- [x] Full folder payload with a caller-specific `permissions` block
- [x] Collaboration invite / accept / decline / role change / remove
- [x] Reference asset upload with magic-byte validation, download, delete
- [x] Remarks CRUD, with system remarks immutable
- [x] Public feed, public folder, public timeline, search, contact
- [x] Private resources invisible (404), proven by tests
- [ ] Avatar upload — deferred to Module 12 (now unblocked by the storage port)

## Related
[[Domain-Model]] · [[Roles-and-Permissions]] · [[Project-Status-Rules]] · [[ADR-Index]] · [[Module-05-Device-Pairing-and-Ingestion]]
