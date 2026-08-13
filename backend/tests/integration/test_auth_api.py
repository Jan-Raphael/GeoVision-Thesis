"""End-to-end authentication and profile flows against a real database.

Covers the behaviours the module spec calls out plus the ones the audit added:
token-type confusion, refresh reuse detection, and the private-profile
guarantee that the response contains *nothing* beyond the username.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from app.domain.enums import ProfessionalRole, Visibility

if TYPE_CHECKING:
    from httpx import AsyncClient

pytestmark = pytest.mark.integration

REGISTER = "/api/v1/auth/register"
LOGIN = "/api/v1/auth/login"
REFRESH = "/api/v1/auth/refresh"
LOGOUT = "/api/v1/auth/logout"
ME = "/api/v1/auth/me"


def _registration(**overrides: Any) -> dict[str, Any]:
    """A valid registration payload."""
    payload: dict[str, Any] = {
        "username": "jan_m",
        "email": "jan@gvmail.com",
        "password": "correct-horse-1",
        "full_name": "Jan Macabulos",
        "professional_role": ProfessionalRole.ENGINEER.value,
    }
    payload.update(overrides)
    return payload


async def _register(client: AsyncClient, **overrides: Any) -> dict[str, Any]:
    """Register and return the session payload."""
    response = await client.post(REGISTER, json=_registration(**overrides))
    assert response.status_code == 201, response.text
    return response.json()


class TestRegistration:
    """The registration form from the dashboard spec."""

    async def test_register_returns_user_and_tokens(self, client: AsyncClient) -> None:
        body = await _register(client)

        assert body["user"]["username"] == "jan_m"
        assert body["user"]["professional_role"] == "engineer"
        assert body["access_token"]
        assert body["refresh_token"]
        assert body["token_type"] == "bearer"
        assert body["expires_in"] == 900

    async def test_company_is_optional(self, client: AsyncClient) -> None:
        """The spec allows skipping it and setting it from the profile later."""
        body = await _register(client)
        assert body["user"]["company"] is None

    async def test_new_accounts_default_to_public(self, client: AsyncClient) -> None:
        body = await _register(client)
        assert body["user"]["profile_visibility"] == "public"

    async def test_password_is_never_echoed(self, client: AsyncClient) -> None:
        response = await client.post(REGISTER, json=_registration())
        assert "correct-horse-1" not in response.text

    async def test_duplicate_username_conflicts(self, client: AsyncClient) -> None:
        await _register(client)
        response = await client.post(REGISTER, json=_registration(email="other@gvmail.com"))
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "USERNAME_TAKEN"

    async def test_duplicate_username_is_case_insensitive(self, client: AsyncClient) -> None:
        await _register(client)
        response = await client.post(
            REGISTER, json=_registration(username="JAN_M", email="other@gvmail.com")
        )
        assert response.status_code == 409

    async def test_duplicate_email_conflicts(self, client: AsyncClient) -> None:
        await _register(client)
        response = await client.post(REGISTER, json=_registration(username="other_user"))
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "EMAIL_TAKEN"

    @pytest.mark.parametrize(
        "bad_username",
        ["ab", "a" * 31, "has space", "has-dash", "has@symbol", ".leading", "trailing."],
    )
    async def test_invalid_usernames_are_rejected(
        self, client: AsyncClient, bad_username: str
    ) -> None:
        response = await client.post(REGISTER, json=_registration(username=bad_username))
        assert response.status_code == 422

    @pytest.mark.parametrize(
        "bad_password",
        [
            "short1",  # too short
            "alllettersonly",  # no digit
            "12345678",  # no letter (and common)
            "password1",  # common
        ],
    )
    async def test_weak_passwords_are_rejected(
        self, client: AsyncClient, bad_password: str
    ) -> None:
        response = await client.post(REGISTER, json=_registration(password=bad_password))
        assert response.status_code == 422

    async def test_password_may_not_equal_the_username(self, client: AsyncClient) -> None:
        response = await client.post(
            REGISTER, json=_registration(username="passw0rd123", password="passw0rd123")
        )
        assert response.status_code == 422

    async def test_unknown_field_is_rejected(self, client: AsyncClient) -> None:
        """`extra="forbid"` stops a typo silently doing nothing."""
        response = await client.post(REGISTER, json=_registration(is_admin=True))
        assert response.status_code == 422

    async def test_error_response_uses_the_standard_envelope(self, client: AsyncClient) -> None:
        await _register(client)
        body = (await client.post(REGISTER, json=_registration(email="x@gvmail.com"))).json()
        assert set(body) == {"error"}
        assert {"code", "message"} <= set(body["error"])


class TestLogin:
    """One identifier field accepts a username or an email."""

    async def test_login_with_username(self, client: AsyncClient) -> None:
        await _register(client)
        response = await client.post(
            LOGIN, json={"identifier": "jan_m", "password": "correct-horse-1"}
        )
        assert response.status_code == 200
        assert response.json()["access_token"]

    async def test_login_with_email(self, client: AsyncClient) -> None:
        await _register(client)
        response = await client.post(
            LOGIN, json={"identifier": "jan@gvmail.com", "password": "correct-horse-1"}
        )
        assert response.status_code == 200

    async def test_wrong_password_is_rejected(self, client: AsyncClient) -> None:
        await _register(client)
        response = await client.post(
            LOGIN, json={"identifier": "jan_m", "password": "wrong-password-1"}
        )
        assert response.status_code == 401

    async def test_unknown_and_wrong_password_give_the_same_message(
        self, client: AsyncClient
    ) -> None:
        """Otherwise the response is a free account-enumeration oracle."""
        await _register(client)
        unknown = await client.post(
            LOGIN, json={"identifier": "nobody_here", "password": "whatever-1"}
        )
        wrong = await client.post(LOGIN, json={"identifier": "jan_m", "password": "whatever-1"})
        assert unknown.status_code == wrong.status_code == 401
        assert unknown.json()["error"]["message"] == wrong.json()["error"]["message"]
        assert unknown.json()["error"]["code"] == wrong.json()["error"]["code"]


class TestCurrentUser:
    """`GET /auth/me` and the bearer guard."""

    async def test_requires_a_token(self, client: AsyncClient) -> None:
        assert (await client.get(ME)).status_code == 401

    async def test_returns_the_signed_in_user(self, client: AsyncClient) -> None:
        session = await _register(client)
        response = await client.get(
            ME, headers={"Authorization": f"Bearer {session['access_token']}"}
        )
        assert response.status_code == 200
        assert response.json()["username"] == "jan_m"

    async def test_garbage_token_is_rejected(self, client: AsyncClient) -> None:
        response = await client.get(ME, headers={"Authorization": "Bearer nonsense"})
        assert response.status_code == 401

    async def test_refresh_token_is_not_accepted_as_a_bearer_token(
        self, client: AsyncClient
    ) -> None:
        """The audit's headline finding, verified end to end."""
        session = await _register(client)
        response = await client.get(
            ME, headers={"Authorization": f"Bearer {session['refresh_token']}"}
        )
        assert response.status_code == 401


class TestRefreshRotation:
    """Single-use refresh tokens with theft detection."""

    async def test_refresh_issues_a_new_pair(self, client: AsyncClient) -> None:
        session = await _register(client)
        response = await client.post(REFRESH, json={"refresh_token": session["refresh_token"]})
        assert response.status_code == 200
        rotated = response.json()
        assert rotated["refresh_token"] != session["refresh_token"]
        assert rotated["access_token"]

    async def test_rotated_token_stops_working(self, client: AsyncClient) -> None:
        session = await _register(client)
        await client.post(REFRESH, json={"refresh_token": session["refresh_token"]})

        replay = await client.post(REFRESH, json={"refresh_token": session["refresh_token"]})
        assert replay.status_code == 401

    async def test_reuse_revokes_the_whole_family(self, client: AsyncClient) -> None:
        """Two parties hold the token and we cannot tell which is calling.

        Revoking the session logs out both — losing a session is far better
        than letting a thief refresh indefinitely.
        """
        session = await _register(client)
        rotated = (
            await client.post(REFRESH, json={"refresh_token": session["refresh_token"]})
        ).json()

        # The attacker replays the old token.
        replay = await client.post(REFRESH, json={"refresh_token": session["refresh_token"]})
        assert replay.status_code == 401
        assert replay.json()["error"]["code"] == "TOKEN_REUSE_DETECTED"

        # The legitimate user's newer token is now dead too.
        after = await client.post(REFRESH, json={"refresh_token": rotated["refresh_token"]})
        assert after.status_code == 401

    async def test_unknown_refresh_token_is_rejected(self, client: AsyncClient) -> None:
        response = await client.post(REFRESH, json={"refresh_token": "x" * 64})
        assert response.status_code == 401


class TestLogout:
    """Ending a session."""

    async def test_logout_revokes_the_session(self, client: AsyncClient) -> None:
        session = await _register(client)
        assert (
            await client.post(LOGOUT, json={"refresh_token": session["refresh_token"]})
        ).status_code == 200

        response = await client.post(REFRESH, json={"refresh_token": session["refresh_token"]})
        assert response.status_code == 401

    async def test_logout_succeeds_for_an_unknown_token(self, client: AsyncClient) -> None:
        """Otherwise logout becomes a probe for which tokens are valid."""
        response = await client.post(LOGOUT, json={"refresh_token": "y" * 64})
        assert response.status_code == 200


class TestProfiles:
    """Profile read, update, and visibility (spec B.5)."""

    @staticmethod
    def _auth(session: dict[str, Any]) -> dict[str, str]:
        return {"Authorization": f"Bearer {session['access_token']}"}

    async def test_update_profile(self, client: AsyncClient) -> None:
        session = await _register(client)
        response = await client.patch(
            "/api/v1/users/me",
            headers=self._auth(session),
            json={"company": "Reyes Construction", "bio": "Site engineer."},
        )
        assert response.status_code == 200
        assert response.json()["company"] == "Reyes Construction"

    async def test_clearing_an_optional_field_needs_an_explicit_flag(
        self, client: AsyncClient
    ) -> None:
        """`None` means 'unchanged', so clearing needs its own signal."""
        session = await _register(client)
        await client.patch(
            "/api/v1/users/me",
            headers=self._auth(session),
            json={"company": "Acme"},
        )
        unchanged = await client.patch(
            "/api/v1/users/me", headers=self._auth(session), json={"bio": "hello"}
        )
        assert unchanged.json()["company"] == "Acme"

        cleared = await client.patch(
            "/api/v1/users/me", headers=self._auth(session), json={"clear_company": True}
        )
        assert cleared.json()["company"] is None

    async def test_public_profile_shows_details(self, client: AsyncClient) -> None:
        await _register(client)
        response = await client.get("/api/v1/public/users/jan_m")
        assert response.status_code == 200
        body = response.json()
        assert body["is_private"] is False
        assert body["full_name"] == "Jan Macabulos"

    async def test_private_profile_discloses_only_the_username(self, client: AsyncClient) -> None:
        """The core guarantee of spec B.5.

        Asserted field by field rather than just checking ``is_private``: a new
        field added to the response later must not quietly start leaking.
        """
        session = await _register(client)
        await client.patch(
            "/api/v1/users/me",
            headers=self._auth(session),
            json={"profile_visibility": Visibility.PRIVATE.value},
        )

        body = (await client.get("/api/v1/public/users/jan_m")).json()
        assert body["username"] == "jan_m"
        assert body["is_private"] is True
        for field in ("full_name", "professional_role", "company", "bio", "avatar_key"):
            assert body[field] is None, f"{field} leaked from a private profile"
        assert body["projects"] == []

    async def test_owner_sees_their_own_private_profile_in_full(self, client: AsyncClient) -> None:
        session = await _register(client)
        await client.patch(
            "/api/v1/users/me",
            headers=self._auth(session),
            json={"profile_visibility": Visibility.PRIVATE.value},
        )
        body = (await client.get("/api/v1/public/users/jan_m", headers=self._auth(session))).json()
        assert body["is_private"] is False
        assert body["full_name"] == "Jan Macabulos"

    async def test_unknown_profile_is_404(self, client: AsyncClient) -> None:
        assert (await client.get("/api/v1/public/users/nobody")).status_code == 404

    async def test_private_account_is_excluded_from_search(self, client: AsyncClient) -> None:
        session = await _register(client, username="alicia_r", email="a@gvmail.com")
        await _register(client, username="alicja_k", email="b@gvmail.com")
        await client.patch(
            "/api/v1/users/me",
            headers=self._auth(session),
            json={"profile_visibility": Visibility.PRIVATE.value},
        )

        found = (await client.get("/api/v1/public/users", params={"q": "alic"})).json()
        usernames = {entry["username"] for entry in found}
        assert "alicja_k" in usernames
        assert "alicia_r" not in usernames


class TestUsernameAvailability:
    """Live check for the registration form."""

    async def test_available_username(self, client: AsyncClient) -> None:
        response = await client.get("/api/v1/auth/check-username", params={"username": "brand_new"})
        assert response.json() == {
            "username": "brand_new",
            "available": True,
            "reason": None,
        }

    async def test_taken_username(self, client: AsyncClient) -> None:
        await _register(client)
        body = (
            await client.get("/api/v1/auth/check-username", params={"username": "jan_m"})
        ).json()
        assert body["available"] is False

    async def test_response_is_not_cacheable(self, client: AsyncClient) -> None:
        """Availability changes; a cached 'available' would be misleading."""
        response = await client.get("/api/v1/auth/check-username", params={"username": "someone"})
        assert response.headers["Cache-Control"] == "no-store"
