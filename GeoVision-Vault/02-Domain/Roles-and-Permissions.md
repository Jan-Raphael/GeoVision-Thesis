---
title: Roles and Permissions
type: domain
status: canonical
updated: 2026-08-12
---

# Roles & Permissions

There are **two independent role axes**. Conflating them is a common mistake.

| Axis | Field | Meaning | Affects permissions? |
|---|---|---|---|
| **Professional role** | `users.professional_role` | What the person *is* — manager, engineer, home owner… Chosen at registration, shown on the profile. | ❌ **No.** Descriptive only. |
| **Membership role** | `project_members.membership_role` | What the person may *do on this specific project*. | ✅ **Yes.** Authoritative. |

A "manager" by profession has zero rights on a project they were never added to.

---

## Actors

1. **Anonymous visitor** — no account.
2. **Authenticated user** — has an account, no relationship to project X.
3. **Project member** — has a `project_members` row for project X with a membership role.
4. **Device** — an ESP32 node authenticated by HMAC. Can *only* ingest and heartbeat.
5. **System/worker** — internal Celery jobs.

## Permission matrix

Legend: ✅ allowed · 🔒 only if project/profile is `public` · ❌ denied

| Capability | Anon | Auth (non-member) | viewer | employee | collaborator | editor | engineer | manager | owner |
|---|---|---|---|---|---|---|---|---|---|
| View homepage public feed | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Search users / locations / projects | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| View public profile | 🔒 | 🔒 | 🔒 | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| View project folder | 🔒 | 🔒 | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| View progress / timeline / images | 🔒 | 🔒 | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Contact Us form | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Register / Login | ✅ | — | — | — | — | — | — | — | — |
| Create a project | ❌ | ✅ | — | — | — | — | — | — | — |
| Upload reference assets | ❌ | ❌ | ❌ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Manual image upload | ❌ | ❌ | ❌ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Write remarks | ❌ | ❌ | ❌ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Edit project details | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ | ✅ | ✅ | ✅ |
| Pair / unpair a device | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ | ✅ | ✅ |
| Set capture schedule / weights | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ | ✅ | ✅ |
| Generate reports | ❌ | ❌ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| **Re-run the AI** (reprocess an image, recompute progress) | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ | ✅ |
| **Approve final 20 %** | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ | ✅ |
| Invite / remove members | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ | ✅ |
| Change project visibility | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ |
| Delete / archive project | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ |
| Transfer ownership | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ |

### Device permissions (HMAC-authenticated, never JWT)
`POST /ingest/images` · `POST /ingest/events` · `GET /ingest/config` · `POST /pair/claim`.
Nothing else. A device token cannot read any project data.

---

## Implementation

Named permissions as a frozen enum in `domain/enums.py`:

```python
class Permission(StrEnum):
    PROJECT_VIEW = "project:view"
    PROJECT_EDIT = "project:edit"
    PROJECT_DELETE = "project:delete"
    PROJECT_VISIBILITY = "project:visibility"
    MEMBER_MANAGE = "member:manage"
    DEVICE_MANAGE = "device:manage"
    ASSET_UPLOAD = "asset:upload"
    IMAGE_UPLOAD = "image:upload"
    PROGRESS_RECOMPUTE = "progress:recompute"
    REMARK_WRITE = "remark:write"
    REPORT_GENERATE = "report:generate"
    PROJECT_APPROVE = "project:approve"

ROLE_PERMISSIONS: dict[MembershipRole, frozenset[Permission]] = { ... }
```

FastAPI guard:

```python
async def require_permission(perm: Permission) -> Callable:
    """Dependency factory: 403 unless the caller's membership grants `perm`."""
```

Used as `Depends(require_permission(Permission.DEVICE_MANAGE))`. **Every** mutating
project route carries one. Rules live in `domain/services/authorization.py` as pure
functions, unit-tested without FastAPI.

## Visibility rules (B.5)

| `profile_visibility` | Anonymous sees |
|---|---|
| `public` | name, professional role, company, bio, **public** projects they own or are a member of, role on each |
| `private` | username only + "This account is private". Still **searchable by username** (so they can be found and invited), nothing else exposed. |

Project visibility is independent: a public profile does not expose that user's private
projects, and a public project owned by a private-profile user still appears in the feed
(with the owner's name rendered as plain text, not a link).

## Related
[[Domain-Model]] · [[API-Contract]] · [[Module-03-Auth-and-Users]] · [[Module-12-Owner-Dashboard]]
