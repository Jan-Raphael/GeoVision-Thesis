---
title: Module 03 — Auth & Users
type: module
module: 3
status: planned
updated: 2026-08-12
---

# Module 03 — Authentication, Users & Profiles

## Scope
Registration, login, JWT lifecycle, profiles, profile visibility (spec B.5), and the
permission machinery every later module depends on.

## Deliverables
- `core/security.py` — Argon2id hash/verify, JWT encode/decode, refresh-token rotation with
  family revocation on reuse.
- `application/use_cases/auth/` — `RegisterUser`, `AuthenticateUser`, `RefreshSession`,
  `LogoutUser`.
- `application/use_cases/users/` — `GetMyProfile`, `UpdateProfile`, `GetPublicProfile`,
  `SetProfileVisibility`, `UploadAvatar`.
- `domain/services/authorization.py` — `ROLE_PERMISSIONS` map and
  `has_permission(membership_role, permission) -> bool`, pure functions
  ([[Roles-and-Permissions]]).
- `api/deps.py` — `get_current_user`, `get_optional_user` (public endpoints that render
  differently when logged in), `require_permission(perm)` factory.
- `api/v1/routers/auth.py`, `users.py`, `public_users.py`.
- Pydantic schemas with strict validation: username `^[a-zA-Z0-9_.]{3,30}$`, `EmailStr`,
  password ≥ 8 chars with at least one letter and one digit, `professional_role` enum.
- Rate limiting on `/auth/login` (5/min/IP) and `/auth/register` (3/hour/IP).

## Registration form contract (spec: username, email, role, password)
```jsonc
POST /api/v1/auth/register
{ "username":"jan_m", "email":"jan@example.com", "password":"…",
  "full_name":"Jan Macabulos", "professional_role":"engineer", "company":"optional" }
→ 201 { "user": {...}, "access_token": "...", "refresh_token": "...", "token_type": "bearer" }
```
`company` is optional at registration and editable from the profile afterwards, exactly as
the spec describes.

## Critical implementation notes
- **Argon2id, never bcrypt-with-defaults or SHA.** Parameters in settings.
- Login accepts **username or email** in one `identifier` field.
- Login failures return one generic message — never "user not found" vs "wrong password".
- Access token 15 min; refresh 7 d, rotating, stored **hashed**; reuse of a rotated token
  revokes the whole family (theft detection).
- Registration and login timing should be roughly constant (hash even on unknown users).
- Private profile response is exactly `{"username": "...", "is_private": true}` — the
  serializer must not be able to leak extra fields (test this).
- Email verification is **out of scope for v1** (documented in [[Open-Questions]]); the
  column exists so it can be added without a migration.

## Dependencies
Module 02. `argon2-cffi`, `python-jose[cryptography]`, `email-validator`, `slowapi`.

## How to run
```bash
uvicorn app.main:app --reload
# then exercise /docs, or:
http POST :8000/api/v1/auth/register username=demo email=demo@x.com password=secret123 \
  full_name="Demo User" professional_role=engineer
```

## Testing procedure
1. Register → 201 with tokens; duplicate username → 409; duplicate email → 409.
2. Weak password / bad username charset → 422.
3. Login by username and by email; wrong password → 401 with the generic message.
4. `GET /auth/me` without a token → 401; with token → the user.
5. Refresh rotates; the old refresh token is rejected; reuse revokes the family.
6. Public profile: public user → full payload; private user → `{username, is_private}` only.
7. `has_permission` unit tests covering the full [[Roles-and-Permissions]] matrix.
8. Rate limit: 6 rapid logins → 429.

## Expected output
A user can register, log in, view and edit their profile, and toggle public/private, with
the private setting provably enforced at the API layer.

## Done criteria
- [ ] Register/login/refresh/logout working
- [ ] Profile read/update + avatar upload
- [ ] Public vs private profile enforced and tested
- [ ] Permission matrix implemented as pure functions with full unit coverage
- [ ] No password or token value ever appears in logs

## Related
[[Roles-and-Permissions]] · [[API-Contract]] · [[Module-04-Projects-and-Folders]]
