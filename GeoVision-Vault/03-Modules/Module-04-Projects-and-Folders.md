---
title: Module 04 — Projects & Folders
type: module
module: 4
status: planned
updated: 2026-08-12
---

# Module 04 — Projects, Project Folders, Members, Assets & Remarks

## Scope
The heart of the dashboard spec: creating a project folder, everything it contains,
collaboration (B.6), reference uploads, and remarks. Still API-only — the UI is Modules 11–12.

## Deliverables
- `application/use_cases/projects/` — `CreateProject`, `GetProjectFolder`, `UpdateProject`,
  `SetVisibility`, `ArchiveProject`, `ApproveProject`, `ListMyProjects`, `GetPublicFeed`,
  `GetPublicProject`, `SearchProjects`.
- `application/use_cases/members/` — `InviteMember`, `RespondToInvitation`,
  `ChangeMemberRole`, `RemoveMember`, `ListMembers`.
- `application/use_cases/assets/` — `UploadReferenceAsset`, `ListAssets`, `DeleteAsset`.
- `application/use_cases/remarks/` — `CreateRemark`, `ListRemarks`, `UpdateRemark`, `DeleteRemark`.
- `domain/services/project_code.py` — build + validate a code from initials + number,
  suggest alternatives on collision.
- `domain/services/status.py` — `derive_status()` from [[Project-Status-Rules]] (pure).
- `infrastructure/storage/` — MinIO/S3 adapter: `put_object`, `get_signed_url`,
  `delete_object`, magic-byte + size validation.
- Routers: `projects.py`, `members.py`, `assets.py`, `remarks.py`, `public.py`, `search.py`,
  `contact.py`.

## Create-Project contract (the spec's form, exactly)
```jsonc
POST /api/v1/projects
{
  "name": "Jollibee Naga Branch",
  "intended_use": "Fast-food restaurant",
  "location_label": "Panganiban Dr, Naga City",
  "latitude": 13.6218, "longitude": 123.1948,
  "code_initials": "NG", "project_number": 0,     // → project_code "NG_00"
  "start_date": "2026-08-15",
  "deadline_date": "2027-02-28",
  "worker_count": null,                            // skippable, editable later
  "visibility": "public",
  "timezone": "Asia/Manila"
}
→ 201 { "id": "...", "project_code": "NG_00", ... }
→ 409 { "error": { "code": "PROJECT_CODE_TAKEN",
        "details": { "suggestions": ["NG_01","NG_02","NGV_00"] } } }
```
On creation the server also inserts the owner's `project_members` row with role `owner`.

## Project folder payload (`GET /projects/{id}`)
Everything the spec lists on the folder page:
`progress` · `stages[]` (five bars) · `deadline_date` · `status` · `devices[]` ·
`members[]` · `recent_images[]` (thumb + GPS + timestamp) · `remarks[]` · `assets[]` ·
`timeline_summary` · `latest_report` · `permissions` (what *this* caller may do — the UI
renders buttons from this, it never re-derives permissions client-side).

## Critical implementation notes
- `project_code` is **immutable** after creation (filenames and device names embed it).
- Every mutating route carries `Depends(require_permission(...))` per [[Roles-and-Permissions]].
- Public endpoints use the visibility-scoped repository methods — never a generic
  `get_by_id` followed by an if-statement.
- Asset upload: max 25 MB, allowlist `image/jpeg|png|webp`, `application/pdf`; validate by
  **magic bytes**, not by extension or client-supplied MIME; store under a generated key,
  never the user's filename.
- Invitations are `pending` until accepted; a pending member has **no** permissions.
- An owner cannot remove themselves or be demoted; ownership moves only via explicit transfer.
- Search must be safely parameterized (trigram `%` similarity, no raw string interpolation)
  and rate-limited.
- `map_url` for the "click through to the coordinates" link:
  `https://www.google.com/maps/search/?api=1&query={lat},{lon}` (plus an OSM alternative).

## Dependencies
Module 03. `boto3`, `python-multipart`, `pillow`.

## How to run
```bash
uvicorn app.main:app --reload
python -m scripts.seed_db     # gives you browsable public + private projects
```

## Testing procedure
1. Create project → 201, code generated, owner membership row created.
2. Duplicate code → 409 with 3 suggestions.
3. Invalid code initials (`ng`, `TOOLONGX`, number `100`) → 422.
4. Anonymous `GET /public/feed` → only public, non-archived projects.
5. Anonymous `GET` of a private project → **404** (not 403).
6. Viewer attempting `PATCH /projects/{id}` → 403.
7. Invite → pending; before acceptance the invitee gets 404 on the project; after
   acceptance they get 200.
8. Upload a `.exe` renamed to `.pdf` → 400 (magic-byte check).
9. `derive_status` unit tests: every branch of [[Project-Status-Rules]].
10. Search by owner name, by location, by project name → correct typed results.

## Expected output
A logged-in user creates a project folder, invites a collaborator, uploads a blueprint,
writes a remark, and toggles public/private — and an anonymous visitor sees exactly and only
what was made public.

## Done criteria
- [ ] Create/read/update/archive project + immutable code
- [ ] Full folder payload including a caller-specific `permissions` block
- [ ] Collaboration invite/accept/role-change/remove
- [ ] Reference asset upload with real validation
- [ ] Remarks CRUD
- [ ] Public feed, public folder, public profile, search, contact
- [ ] Private resources are invisible (404), proven by tests

## Related
[[Domain-Model]] · [[Roles-and-Permissions]] · [[Project-Status-Rules]] · [[Module-05-Device-Pairing-and-Ingestion]]
