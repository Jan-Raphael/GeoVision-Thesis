---
title: Module 03 — Auth & Users
type: module
module: 3
status: done
started: 2026-08-13
finished: 2026-08-13
updated: 2026-08-13
---

# Module 03 — Authentication, Users & Profiles

> **Status: ✅ done.** Revised after implementation. The spec was audited first, which
> surfaced four security gaps; all four are fixed and tested.

## Scope
Registration, login, JWT lifecycle, profiles, profile visibility (spec B.5), and the
**permission machinery every later module depends on**.

---

## Audit findings, and what changed

| # | Gap in the original spec | Fix |
|---|---|---|
| 1 | **No token-type separation.** Nothing stopped a refresh token being presented as an access token, so a stolen 7-day credential would have worked wherever a 15-minute one did — making the short access lifetime decorative. | Every token carries a `typ` claim; `verify_token` demands the expected type. ADR-015 |
| 2 | **No `jti`.** | Every access token has a unique `jti`, for correlation now and revocation lists later. |
| 3 | **Per-IP rate limiting only.** An attacker rotating source addresses walks straight through it. | Two independent mechanisms: per-IP (slowapi) **and** a per-account failed-attempt throttle (`core/throttle.py`). ADR-016 |
| 4 | **Avatar upload** needs object storage, which does not exist yet. | Deferred to Module 04, which owns the storage adapter. Shipping a half-wired uploader would mean writing it twice. |

### Future-proofing added for Modules 04–16
- `api/deps.py` is now the **composition root**: providers for all 14 repositories, the audit
  logger, the clock, `CurrentUser`, `OptionalUser`, and `require_permission(...)`.
- `require_permission` resolves project → membership → permissions in one pass and hands the
  handler an `AccessContext`, so routes never re-query authority they were just checked against.
- `infrastructure/audit.py` — Module 04 (approval, visibility) and Module 05 (pairing) both
  need an audit trail; the action vocabulary for all three modules is already enumerated.
- `core/clock.py` — an injectable time source, so Modules 09/10 can test windows and delays
  without sleeping.
- `api/schemas/common.py` — one pagination shape for the whole API.

---

## What shipped

| File | Contents |
|---|---|
| `core/security.py` | Argon2id hash/verify, timing-equalised unknown-user path, transparent rehash-on-login, JWT issue/verify with `typ`+`jti`, opaque refresh tokens hashed at rest |
| `core/throttle.py` | Per-account failed-attempt throttle; in-memory now, Redis-ready interface |
| `core/rate_limit.py` | Per-IP slowapi limiter; `memory://` now, Redis by config later |
| `core/clock.py` | `Clock` protocol, `SystemClock`, `FrozenClock` |
| `domain/services/authorization.py` | `ROLE_PERMISSIONS`, `AccessContext`, `can_view_project`, `can_view_profile` — pure |
| `application/use_cases/auth.py` | `RegisterUser`, `AuthenticateUser`, `RefreshSession`, `LogoutUser` |
| `application/use_cases/users.py` | `GetMyProfile`, `UpdateProfile`, `SetProfileVisibility`, `GetPublicProfile`, `SearchUsers` |
| `api/deps.py` | the composition root (above) |
| `api/error_handlers.py` | HTTP rendering, split out of `core/exceptions.py` — see below |
| `api/v1/routers/` | `auth.py`, `users.py`, `public_users.py` |

## Endpoints

| Method | Path | Auth |
|---|---|---|
| POST | `/api/v1/auth/register` | — |
| POST | `/api/v1/auth/login` | — |
| POST | `/api/v1/auth/refresh` | refresh token |
| POST | `/api/v1/auth/logout` | refresh token |
| GET | `/api/v1/auth/me` | access token |
| GET | `/api/v1/auth/check-username` | — |
| GET/PATCH | `/api/v1/users/me` | access token |
| PATCH | `/api/v1/users/me/visibility` | access token |
| GET | `/api/v1/users/me/projects` | access token |
| GET | `/api/v1/public/users/{username}` | optional |
| GET | `/api/v1/public/users` | — |

---

## Three bugs the tests caught

**1. A TYPE_CHECKING-only import silently disabled authentication.**
`deps.py` declared `OptionalUser = Annotated["User | None", Depends(...)]` while importing
`User` only under `TYPE_CHECKING`. FastAPI resolves endpoint annotations with
`get_type_hints()` **in the router's namespace**, where that name does not exist — so the
forward reference failed to resolve, the parameter was dropped, and every authenticated
caller on `/public/users/{username}` was treated as **anonymous**. No exception, no log
line. The same alias is what Module 11 will use to decide what a signed-in visitor sees.
`AsyncSession` had the identical defect. Both are now runtime imports, and
`tests/unit/test_dependency_annotations.py` asserts every endpoint and dependency
annotation resolves.

**2. The per-identifier rate-limit key could never have worked.**
slowapi evaluates its key function *before* the endpoint runs, so the request body — and
therefore the login identifier — is not available. The original implementation read
`request.state.rate_limit_identifier`, which the handler set afterwards; the state was
always empty and every request silently fell back to the IP key. It looked like a working
defence and was not one. Replaced by `core/throttle.py`, which runs inside the use case
where the identifier exists.

**3. `to_public_profile()` redacted the owner's own profile.**
The redaction is deliberately structural (a new field cannot leak by being forgotten), but
that meant a user with a private profile could not see their own. Added an explicitly named
`to_full_profile()` so redaction stays the default and the unredacted view has to be asked
for.

## One architecture violation, caught by the import contract

`core/exceptions.py` imported FastAPI for its exception handlers, so the **application layer
transitively depended on the web framework**. Split: exception *types* stay in
`core/exceptions.py` (framework-free, `http.HTTPStatus` for codes), HTTP *rendering* moved
to `api/error_handlers.py`. All four contracts pass.

---

## How to run

```powershell
uv run uvicorn app.main:app --reload
# http://localhost:8000/docs
```

```bash
curl -X POST localhost:8000/api/v1/auth/register -H "Content-Type: application/json" \
  -d '{"username":"jan_m","email":"jan@gvmail.com","password":"correct-horse-1",
       "full_name":"Jan Macabulos","professional_role":"engineer"}'
```

> Note: `email-validator` rejects RFC 2606 reserved domains (`.test`, `example.com`). That is
> correct production behaviour; use a real-shaped domain when testing by hand.

## Testing procedure & results

| # | Check | Result |
|---|---|---|
| 1 | Register → 201 + tokens; duplicate username/email → 409 | ✅ |
| 2 | Weak password, bad username charset, unknown field → 422 | ✅ |
| 3 | Login by username **and** by email | ✅ |
| 4 | Unknown user and wrong password return an **identical** code and message | ✅ |
| 5 | `/auth/me` 401 without a token, 200 with one | ✅ |
| 6 | **Refresh token rejected as a bearer token** | ✅ |
| 7 | Refresh rotates; the old token stops working | ✅ |
| 8 | **Reuse of a rotated token revokes the whole family** | ✅ |
| 9 | Logout revokes; logout of an unknown token still 200 | ✅ |
| 10 | Private profile discloses **only** the username (asserted field by field) | ✅ |
| 11 | Owner sees their own private profile in full | ✅ |
| 12 | Private accounts excluded from search, findable by exact username | ✅ |
| 13 | Full permission matrix vs [[Roles-and-Permissions]] | ✅ 24 parametrised cases |
| 14 | Roles are strictly cumulative; only owner may delete/change visibility | ✅ |
| 15 | Pending invitation grants **nothing** | ✅ |
| 16 | 6th failed login → 429; a different account still served | ✅ |
| 17 | Every endpoint/dependency annotation resolves | ✅ |

**327 backend tests** (283 unit + 44 integration), ruff + mypy clean, 4 import contracts kept.

## Done criteria

- [x] Register / login / refresh / logout
- [x] Profile read, update, public-private toggle
- [x] Public vs private profile enforced **and** proven field by field
- [x] Permission matrix as pure functions with full coverage
- [x] No password or token value in any response, log, or repr
- [x] Token-type confusion impossible
- [x] Per-account **and** per-IP throttling
- [ ] Avatar upload — **deferred to Module 04** (needs object storage)

## Related
[[Roles-and-Permissions]] · [[API-Contract]] · [[ADR-Index]] · [[Module-04-Projects-and-Folders]]
