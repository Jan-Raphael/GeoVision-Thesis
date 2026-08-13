"""End-to-end project, collaboration, and public-surface flows.

The visibility assertions are the important ones: they prove an anonymous
visitor sees exactly and only what was published, and that a private project is
**invisible** (404) rather than merely forbidden (403).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import pytest

from app.domain.enums import MembershipRole, ProfessionalRole, Visibility

if TYPE_CHECKING:
    from httpx import AsyncClient

pytestmark = pytest.mark.integration

REGISTER = "/api/v1/auth/register"
PROJECTS = "/api/v1/projects"

PDF = b"%PDF-1.7\n" + b"x" * 300
EXE = b"MZ\x90\x00" + b"x" * 300


async def _account(client: AsyncClient, username: str) -> dict[str, Any]:
    """Register a user and return their session."""
    response = await client.post(
        REGISTER,
        json={
            "username": username,
            "email": f"{username}@gvmail.com",
            "password": "correct-horse-1",
            "full_name": f"{username.title()} Tester",
            "professional_role": ProfessionalRole.ENGINEER.value,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _auth(session: dict[str, Any]) -> dict[str, str]:
    """Authorization header for a session."""
    return {"Authorization": f"Bearer {session['access_token']}"}


def _project_payload(**overrides: Any) -> dict[str, Any]:
    """A valid Create Project form submission."""
    today = datetime.now(UTC).date()
    payload: dict[str, Any] = {
        "name": "Jollibee Naga Branch",
        "code_initials": "NG",
        "project_number": 0,
        "location_label": "Panganiban Dr, Naga City",
        "latitude": 13.6218,
        "longitude": 123.1948,
        "start_date": (today - timedelta(days=30)).isoformat(),
        "deadline_date": (today + timedelta(days=120)).isoformat(),
        "visibility": Visibility.PRIVATE.value,
        "intended_use": "Fast-food restaurant",
    }
    payload.update(overrides)
    return payload


async def _create(client: AsyncClient, session: dict[str, Any], **overrides: Any) -> dict[str, Any]:
    """Create a project and return the response body."""
    response = await client.post(
        PROJECTS, headers=_auth(session), json=_project_payload(**overrides)
    )
    assert response.status_code == 201, response.text
    return response.json()


class TestCreateProject:
    """The Create Project form from the dashboard spec."""

    async def test_creates_with_a_generated_code(self, client: AsyncClient) -> None:
        session = await _account(client, "alice_eng")
        body = await _create(client, session)

        assert body["project_code"] == "NG_00"
        assert body["name"] == "Jollibee Naga Branch"
        assert body["map_url"].startswith("https://www.google.com/maps/")

    async def test_creator_becomes_owner(self, client: AsyncClient) -> None:
        """Every authority check has one source of truth: the members table."""
        session = await _account(client, "alice_eng")
        project = await _create(client, session)

        members = (
            await client.get(f"{PROJECTS}/{project['id']}/members", headers=_auth(session))
        ).json()
        assert len(members) == 1
        assert members[0]["membership_role"] == MembershipRole.OWNER.value
        assert members[0]["membership_status"] == "accepted"

    async def test_worker_count_may_be_skipped(self, client: AsyncClient) -> None:
        session = await _account(client, "alice_eng")
        project = await _create(client, session, worker_count=None)
        folder = (await client.get(f"{PROJECTS}/{project['id']}", headers=_auth(session))).json()
        assert folder["worker_count"] is None

    async def test_duplicate_code_returns_free_suggestions(self, client: AsyncClient) -> None:
        """The suggestion a user clicks must not collide in turn."""
        session = await _account(client, "alice_eng")
        await _create(client, session)

        response = await client.post(
            PROJECTS, headers=_auth(session), json=_project_payload(name="Another")
        )
        assert response.status_code == 409
        error = response.json()["error"]
        assert error["code"] == "PROJECT_CODE_TAKEN"
        suggestions = error["details"]["suggestions"]
        assert len(suggestions) == 3
        assert "NG_00" not in suggestions

        # And a suggested code really is free.
        follow_up = await client.post(
            PROJECTS,
            headers=_auth(session),
            json=_project_payload(
                name="Another",
                code_initials=suggestions[0].split("_")[0],
                project_number=int(suggestions[0].split("_")[1]),
            ),
        )
        assert follow_up.status_code == 201

    @pytest.mark.parametrize(
        "overrides",
        [
            {"code_initials": "N1"},  # digits are not initials
            {"code_initials": "TOOLONGX"},
            {"project_number": 100},
            {"project_number": -1},
            {"latitude": 95.0},
        ],
    )
    async def test_invalid_input_is_rejected(
        self, client: AsyncClient, overrides: dict[str, Any]
    ) -> None:
        session = await _account(client, "alice_eng")
        response = await client.post(
            PROJECTS, headers=_auth(session), json=_project_payload(**overrides)
        )
        assert response.status_code in {400, 422}

    async def test_lowercase_initials_are_normalised_not_rejected(
        self, client: AsyncClient
    ) -> None:
        """The form is free text, so "ng" becomes "NG" rather than an error."""
        session = await _account(client, "alice_eng")
        body = await _create(client, session, code_initials="ng")
        assert body["project_code"] == "NG_00"

    async def test_deadline_before_start_is_rejected(self, client: AsyncClient) -> None:
        session = await _account(client, "alice_eng")
        response = await client.post(
            PROJECTS,
            headers=_auth(session),
            json=_project_payload(start_date="2026-06-01", deadline_date="2026-01-01"),
        )
        assert response.status_code == 422

    async def test_requires_authentication(self, client: AsyncClient) -> None:
        assert (await client.post(PROJECTS, json=_project_payload())).status_code == 401


class TestProjectFolder:
    """The folder page payload."""

    async def test_contains_every_section(self, client: AsyncClient) -> None:
        session = await _account(client, "alice_eng")
        project = await _create(client, session)

        folder = (await client.get(f"{PROJECTS}/{project['id']}", headers=_auth(session))).json()

        for field in (
            "progress_pct",
            "stages",
            "deadline_date",
            "status",
            "status_reason",
            "devices",
            "members",
            "recent_images",
            "remarks",
            "assets",
            "timeline",
            "permissions",
            "map_url",
        ):
            assert field in folder, f"folder payload is missing {field}"

        assert set(folder["stages"]) == {
            "foundation_pct",
            "framing_pct",
            "roofing_pct",
            "finishing_pct",
            "approval_pct",
        }

    async def test_permissions_block_reflects_the_caller(self, client: AsyncClient) -> None:
        """The dashboard renders its buttons from this, so it must be truthful."""
        owner = await _account(client, "alice_eng")
        project = await _create(client, owner)

        folder = (await client.get(f"{PROJECTS}/{project['id']}", headers=_auth(owner))).json()
        assert folder["permissions"]["project:delete"] is True
        assert folder["permissions"]["project:approve"] is True
        assert folder["permissions"]["project:visibility"] is True

    async def test_status_reason_is_human_readable(self, client: AsyncClient) -> None:
        session = await _account(client, "alice_eng")
        project = await _create(client, session)
        folder = (await client.get(f"{PROJECTS}/{project['id']}", headers=_auth(session))).json()
        assert folder["status_reason"]


class TestVisibility:
    """Private projects are invisible, not merely forbidden."""

    async def test_private_project_is_404_for_a_stranger(self, client: AsyncClient) -> None:
        """404, never 403 - a 403 would confirm the project exists."""
        owner = await _account(client, "alice_eng")
        stranger = await _account(client, "bruno_pm")
        project = await _create(client, owner, visibility=Visibility.PRIVATE.value)

        response = await client.get(f"{PROJECTS}/{project['id']}", headers=_auth(stranger))
        assert response.status_code == 404

    async def test_private_project_is_404_for_anonymous(self, client: AsyncClient) -> None:
        """404, not 401.

        The folder route accepts anonymous callers (a *public* project is
        readable without a token), so the visibility check is what rejects
        this - and it must not distinguish "you need to log in" from "there is
        nothing here", since the first answer confirms the project exists.
        """
        owner = await _account(client, "alice_eng")
        project = await _create(client, owner, visibility=Visibility.PRIVATE.value)
        assert (await client.get(f"{PROJECTS}/{project['id']}")).status_code == 404

    async def test_public_feed_excludes_private_projects(self, client: AsyncClient) -> None:
        owner = await _account(client, "alice_eng")
        await _create(client, owner, visibility=Visibility.PUBLIC.value)
        await _create(
            client,
            owner,
            code_initials="PV",
            project_number=1,
            visibility=Visibility.PRIVATE.value,
        )

        feed = (await client.get("/api/v1/public/feed")).json()
        codes = {item["project_code"] for item in feed["items"]}
        assert "NG_00" in codes
        assert "PV_01" not in codes

    async def test_public_project_page_hides_private_projects(self, client: AsyncClient) -> None:
        owner = await _account(client, "alice_eng")
        await _create(client, owner, visibility=Visibility.PRIVATE.value)
        assert (await client.get("/api/v1/public/projects/NG_00")).status_code == 404

    async def test_public_project_page_omits_internal_fields(self, client: AsyncClient) -> None:
        """A separate response model, so a new internal field cannot leak."""
        owner = await _account(client, "alice_eng")
        await _create(client, owner, visibility=Visibility.PUBLIC.value)

        body = (await client.get("/api/v1/public/projects/NG_00")).json()
        for internal in (
            "members",
            "devices",
            "assets",
            "worker_count",
            "inspection_notes",
            "permissions",
            "visibility",
        ):
            assert internal not in body, f"{internal} leaked to the public view"

    async def test_only_the_owner_can_publish(self, client: AsyncClient) -> None:
        owner = await _account(client, "alice_eng")
        helper = await _account(client, "bruno_pm")
        project = await _create(client, owner)

        await client.post(
            f"{PROJECTS}/{project['id']}/members",
            headers=_auth(owner),
            json={"identifier": "bruno_pm", "membership_role": MembershipRole.MANAGER.value},
        )
        invitations = (await client.get("/api/v1/invitations", headers=_auth(helper))).json()
        await client.post(
            f"/api/v1/invitations/{invitations[0]['id']}",
            headers=_auth(helper),
            json={"accept": True},
        )

        # A manager may do a great deal, but not publish.
        response = await client.patch(
            f"{PROJECTS}/{project['id']}/visibility",
            headers=_auth(helper),
            json={"visibility": Visibility.PUBLIC.value},
        )
        assert response.status_code == 403


class TestCollaboration:
    """Spec B.6."""

    async def test_pending_invitation_grants_nothing(self, client: AsyncClient) -> None:
        """The invitee can see the invitation but not the project."""
        owner = await _account(client, "alice_eng")
        invitee = await _account(client, "carla_owner")
        project = await _create(client, owner, visibility=Visibility.PRIVATE.value)

        await client.post(
            f"{PROJECTS}/{project['id']}/members",
            headers=_auth(owner),
            json={"identifier": "carla_owner", "membership_role": "viewer"},
        )

        before = await client.get(f"{PROJECTS}/{project['id']}", headers=_auth(invitee))
        assert before.status_code == 404

        invitations = (await client.get("/api/v1/invitations", headers=_auth(invitee))).json()
        assert len(invitations) == 1

        await client.post(
            f"/api/v1/invitations/{invitations[0]['id']}",
            headers=_auth(invitee),
            json={"accept": True},
        )

        after = await client.get(f"{PROJECTS}/{project['id']}", headers=_auth(invitee))
        assert after.status_code == 200

    async def test_viewer_cannot_edit(self, client: AsyncClient) -> None:
        owner = await _account(client, "alice_eng")
        viewer = await _account(client, "carla_owner")
        project = await _create(client, owner)

        await client.post(
            f"{PROJECTS}/{project['id']}/members",
            headers=_auth(owner),
            json={"identifier": "carla_owner", "membership_role": "viewer"},
        )
        invitations = (await client.get("/api/v1/invitations", headers=_auth(viewer))).json()
        await client.post(
            f"/api/v1/invitations/{invitations[0]['id']}",
            headers=_auth(viewer),
            json={"accept": True},
        )

        response = await client.patch(
            f"{PROJECTS}/{project['id']}",
            headers=_auth(viewer),
            json={"name": "Renamed by a viewer"},
        )
        assert response.status_code == 403

    async def test_owner_cannot_be_invited(self, client: AsyncClient) -> None:
        """Ownership is transferred deliberately, never handed out."""
        owner = await _account(client, "alice_eng")
        await _account(client, "bruno_pm")
        project = await _create(client, owner)

        response = await client.post(
            f"{PROJECTS}/{project['id']}/members",
            headers=_auth(owner),
            json={"identifier": "bruno_pm", "membership_role": "owner"},
        )
        assert response.status_code == 403

    async def test_inviting_an_unknown_user_is_404(self, client: AsyncClient) -> None:
        owner = await _account(client, "alice_eng")
        project = await _create(client, owner)
        response = await client.post(
            f"{PROJECTS}/{project['id']}/members",
            headers=_auth(owner),
            json={"identifier": "nobody_here", "membership_role": "viewer"},
        )
        assert response.status_code == 404

    async def test_last_owner_cannot_be_removed(self, client: AsyncClient) -> None:
        """A project with nobody able to administer it is unrecoverable."""
        owner = await _account(client, "alice_eng")
        project = await _create(client, owner)
        members = (
            await client.get(f"{PROJECTS}/{project['id']}/members", headers=_auth(owner))
        ).json()

        response = await client.delete(
            f"{PROJECTS}/{project['id']}/members/{members[0]['id']}",
            headers=_auth(owner),
        )
        assert response.status_code == 403

    async def test_declining_removes_the_invitation(self, client: AsyncClient) -> None:
        owner = await _account(client, "alice_eng")
        invitee = await _account(client, "carla_owner")
        project = await _create(client, owner)

        await client.post(
            f"{PROJECTS}/{project['id']}/members",
            headers=_auth(owner),
            json={"identifier": "carla_owner", "membership_role": "viewer"},
        )
        invitations = (await client.get("/api/v1/invitations", headers=_auth(invitee))).json()
        await client.post(
            f"/api/v1/invitations/{invitations[0]['id']}",
            headers=_auth(invitee),
            json={"accept": False},
        )

        assert (await client.get("/api/v1/invitations", headers=_auth(invitee))).json() == []


class TestApproval:
    """The final 20 % (ADR-007)."""

    async def test_cannot_approve_a_project_that_is_not_ready(self, client: AsyncClient) -> None:
        """The AI must reach 80 % before a human can sign off."""
        owner = await _account(client, "alice_eng")
        project = await _create(client, owner)

        response = await client.post(
            f"{PROJECTS}/{project['id']}/approve",
            headers=_auth(owner),
            json={"inspection_notes": "Looks finished to me."},
        )
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "NOT_AWAITING_INSPECTION"

    async def test_notes_are_required(self, client: AsyncClient) -> None:
        owner = await _account(client, "alice_eng")
        project = await _create(client, owner)
        response = await client.post(
            f"{PROJECTS}/{project['id']}/approve",
            headers=_auth(owner),
            json={"inspection_notes": ""},
        )
        assert response.status_code == 422


class TestAssets:
    """Reference uploads."""

    async def test_upload_and_download_a_pdf(self, client: AsyncClient) -> None:
        owner = await _account(client, "alice_eng")
        project = await _create(client, owner)

        response = await client.post(
            f"{PROJECTS}/{project['id']}/assets",
            headers=_auth(owner),
            files={"file": ("ground-floor.pdf", PDF, "application/pdf")},
            data={"kind": "blueprint"},
        )
        assert response.status_code == 201, response.text
        asset = response.json()
        assert asset["mime_type"] == "application/pdf"
        assert asset["original_filename"] == "ground-floor.pdf"

        download = await client.get(
            f"{PROJECTS}/{project['id']}/assets/{asset['id']}/download",
            headers=_auth(owner),
        )
        assert download.status_code == 200
        assert download.content == PDF
        assert download.headers["content-disposition"].startswith("attachment")

    async def test_executable_renamed_as_pdf_is_rejected(self, client: AsyncClient) -> None:
        """The filename says PDF; the magic bytes say otherwise."""
        owner = await _account(client, "alice_eng")
        project = await _create(client, owner)

        response = await client.post(
            f"{PROJECTS}/{project['id']}/assets",
            headers=_auth(owner),
            files={"file": ("blueprint.pdf", EXE, "application/pdf")},
            data={"kind": "blueprint"},
        )
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "INVALID_FILE"

    async def test_viewer_cannot_upload(self, client: AsyncClient) -> None:
        owner = await _account(client, "alice_eng")
        viewer = await _account(client, "carla_owner")
        project = await _create(client, owner)

        await client.post(
            f"{PROJECTS}/{project['id']}/members",
            headers=_auth(owner),
            json={"identifier": "carla_owner", "membership_role": "viewer"},
        )
        invitations = (await client.get("/api/v1/invitations", headers=_auth(viewer))).json()
        await client.post(
            f"/api/v1/invitations/{invitations[0]['id']}",
            headers=_auth(viewer),
            json={"accept": True},
        )

        response = await client.post(
            f"{PROJECTS}/{project['id']}/assets",
            headers=_auth(viewer),
            files={"file": ("plan.pdf", PDF, "application/pdf")},
            data={"kind": "blueprint"},
        )
        assert response.status_code == 403


class TestRemarks:
    """Notes on a project."""

    async def test_create_and_list(self, client: AsyncClient) -> None:
        owner = await _account(client, "alice_eng")
        project = await _create(client, owner)

        created = await client.post(
            f"{PROJECTS}/{project['id']}/remarks",
            headers=_auth(owner),
            json={"message": "Second-floor slab pour next week.", "is_public": True},
        )
        assert created.status_code == 201

        listed = (
            await client.get(f"{PROJECTS}/{project['id']}/remarks", headers=_auth(owner))
        ).json()
        assert len(listed) == 1
        assert listed[0]["is_system_generated"] is False

    async def test_weather_remark_carries_its_window(self, client: AsyncClient) -> None:
        owner = await _account(client, "alice_eng")
        project = await _create(client, owner)

        response = await client.post(
            f"{PROJECTS}/{project['id']}/remarks",
            headers=_auth(owner),
            json={
                "message": "Typhoon warning; work suspended.",
                "remark_type": "weather",
                "severity": "warning",
                "effective_from": "2026-07-12",
                "effective_to": "2026-07-15",
            },
        )
        assert response.status_code == 201
        assert response.json()["effective_to"] == "2026-07-15"

    async def test_public_project_shows_only_public_remarks(self, client: AsyncClient) -> None:
        owner = await _account(client, "alice_eng")
        project = await _create(client, owner, visibility=Visibility.PUBLIC.value)

        await client.post(
            f"{PROJECTS}/{project['id']}/remarks",
            headers=_auth(owner),
            json={"message": "Visible to everyone.", "is_public": True},
        )
        await client.post(
            f"{PROJECTS}/{project['id']}/remarks",
            headers=_auth(owner),
            json={"message": "Internal note about costs.", "is_public": False},
        )

        public = (await client.get("/api/v1/public/projects/NG_00")).json()
        messages = {remark["message"] for remark in public["remarks"]}
        assert "Visible to everyone." in messages
        assert "Internal note about costs." not in messages


class TestContact:
    """The public Contact Us form."""

    async def test_message_is_accepted(self, client: AsyncClient) -> None:
        response = await client.post(
            "/api/v1/public/contact",
            json={
                "name": "Site Visitor",
                "email": "visitor@gvmail.com",
                "subject": "Question about a project",
                "message": "How often are the photos taken?",
            },
        )
        assert response.status_code == 202

    async def test_short_message_is_rejected(self, client: AsyncClient) -> None:
        response = await client.post(
            "/api/v1/public/contact",
            json={
                "name": "Site Visitor",
                "email": "visitor@gvmail.com",
                "subject": "Hi",
                "message": "hello",
            },
        )
        assert response.status_code == 422


class TestSearch:
    """One search box over projects and profiles."""

    async def test_finds_a_public_project_by_name(self, client: AsyncClient) -> None:
        owner = await _account(client, "alice_eng")
        await _create(client, owner, visibility=Visibility.PUBLIC.value)

        results = (await client.get("/api/v1/public/search", params={"q": "Jollibee"})).json()
        assert any(item["project_code"] == "NG_00" for item in results["projects"])

    async def test_does_not_find_private_projects(self, client: AsyncClient) -> None:
        owner = await _account(client, "alice_eng")
        await _create(client, owner, visibility=Visibility.PRIVATE.value)

        results = (await client.get("/api/v1/public/search", params={"q": "Jollibee"})).json()
        assert results["projects"] == []
