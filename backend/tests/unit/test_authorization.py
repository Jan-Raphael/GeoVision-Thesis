"""The permission matrix, verified against the vault table.

Every access decision in Modules 04-16 flows through these functions, so this
file is the closest thing the project has to a security specification. It runs
in milliseconds with no database, which is exactly why the rules live in the
domain layer.

The reference is ``GeoVision-Vault/02-Domain/Roles-and-Permissions.md``; if that
table and this file ever disagree, one of them is a bug.
"""

from __future__ import annotations

import itertools
from datetime import UTC, date, datetime
from typing import ClassVar
from uuid import uuid4

import pytest

from app.domain.entities import Project, ProjectMember, User
from app.domain.enums import (
    MembershipRole,
    MembershipStatus,
    Permission,
    ProfessionalRole,
    Visibility,
)
from app.domain.services.authorization import (
    ROLE_PERMISSIONS,
    AccessContext,
    can_view_profile,
    can_view_project,
    has_permission,
    permissions_for,
    resolve_permissions,
)
from app.domain.value_objects import GeoPoint, ProjectCode

pytestmark = pytest.mark.unit


def _member(
    role: MembershipRole,
    status: MembershipStatus = MembershipStatus.ACCEPTED,
) -> ProjectMember:
    """Build a membership."""
    return ProjectMember(
        id=uuid4(),
        project_id=uuid4(),
        user_id=uuid4(),
        membership_role=role,
        membership_status=status,
    )


def _project(visibility: Visibility = Visibility.PRIVATE, **kw: object) -> Project:
    """Build a project."""
    values: dict[str, object] = {
        "id": uuid4(),
        "owner_id": uuid4(),
        "name": "Test",
        "code": ProjectCode("NG_00"),
        "location_label": "Naga City",
        "location": GeoPoint(13.6218, 123.1948),
        "start_date": date(2026, 1, 1),
        "deadline_date": date(2026, 12, 31),
        "visibility": visibility,
    }
    values.update(kw)
    return Project(**values)  # type: ignore[arg-type]


class TestPermissionMatrix:
    """Direct transcription of the vault's permission table."""

    #: (role, permission, expected). Read this table against
    #: Roles-and-Permissions.md - they must agree line for line.
    MATRIX: ClassVar[list[tuple[MembershipRole, Permission, bool]]] = [
        # Viewer: read only.
        (MembershipRole.VIEWER, Permission.PROJECT_VIEW, True),
        (MembershipRole.VIEWER, Permission.REPORT_GENERATE, False),
        (MembershipRole.VIEWER, Permission.REMARK_WRITE, False),
        (MembershipRole.VIEWER, Permission.PROJECT_EDIT, False),
        (MembershipRole.VIEWER, Permission.PROJECT_APPROVE, False),
        # Employee: adds reporting.
        (MembershipRole.EMPLOYEE, Permission.REPORT_GENERATE, True),
        (MembershipRole.EMPLOYEE, Permission.ASSET_UPLOAD, False),
        (MembershipRole.EMPLOYEE, Permission.PROJECT_EDIT, False),
        # Collaborator: adds content.
        (MembershipRole.COLLABORATOR, Permission.ASSET_UPLOAD, True),
        (MembershipRole.COLLABORATOR, Permission.IMAGE_UPLOAD, True),
        (MembershipRole.COLLABORATOR, Permission.REMARK_WRITE, True),
        (MembershipRole.COLLABORATOR, Permission.PROJECT_EDIT, False),
        # Editor: adds project editing.
        (MembershipRole.EDITOR, Permission.PROJECT_EDIT, True),
        (MembershipRole.EDITOR, Permission.DEVICE_MANAGE, False),
        # Engineer: adds cameras.
        (MembershipRole.ENGINEER, Permission.DEVICE_MANAGE, True),
        (MembershipRole.ENGINEER, Permission.MEMBER_MANAGE, False),
        (MembershipRole.ENGINEER, Permission.PROJECT_APPROVE, False),
        # Manager: adds membership and the final sign-off.
        (MembershipRole.MANAGER, Permission.MEMBER_MANAGE, True),
        (MembershipRole.MANAGER, Permission.PROJECT_APPROVE, True),
        (MembershipRole.MANAGER, Permission.PROJECT_VISIBILITY, False),
        (MembershipRole.MANAGER, Permission.PROJECT_DELETE, False),
        # Owner: everything.
        (MembershipRole.OWNER, Permission.PROJECT_VISIBILITY, True),
        (MembershipRole.OWNER, Permission.PROJECT_DELETE, True),
        (MembershipRole.OWNER, Permission.PROJECT_APPROVE, True),
    ]

    @pytest.mark.parametrize(("role", "permission", "expected"), MATRIX)
    def test_matrix_entry(
        self, role: MembershipRole, permission: Permission, *, expected: bool
    ) -> None:
        assert has_permission(role, permission) is expected

    def test_every_role_has_an_entry(self) -> None:
        """A new role without a matrix entry must not silently exist."""
        for role in MembershipRole:
            assert role in ROLE_PERMISSIONS, f"{role} is missing from ROLE_PERMISSIONS"

    def test_owner_holds_every_permission(self) -> None:
        """The owner is the ceiling; nothing is defined that they cannot do."""
        owner_permissions = permissions_for(MembershipRole.OWNER)
        assert owner_permissions == set(Permission)

    def test_roles_are_cumulative(self) -> None:
        """Each role is a superset of the one below, so the hierarchy is real."""
        ladder = [
            MembershipRole.VIEWER,
            MembershipRole.EMPLOYEE,
            MembershipRole.COLLABORATOR,
            MembershipRole.EDITOR,
            MembershipRole.ENGINEER,
            MembershipRole.MANAGER,
            MembershipRole.OWNER,
        ]
        for lower, higher in itertools.pairwise(ladder):
            assert permissions_for(lower) < permissions_for(higher), (
                f"{higher} should strictly contain {lower}"
            )

    def test_only_manager_and_owner_may_approve(self) -> None:
        """The final 20 % is the most consequential action in the system."""
        allowed = {
            role for role in MembershipRole if has_permission(role, Permission.PROJECT_APPROVE)
        }
        assert allowed == {MembershipRole.MANAGER, MembershipRole.OWNER}

    def test_only_owner_may_change_visibility_or_delete(self) -> None:
        """Publishing a project and destroying it stay with the owner alone."""
        for permission in (Permission.PROJECT_VISIBILITY, Permission.PROJECT_DELETE):
            allowed = {role for role in MembershipRole if has_permission(role, permission)}
            assert allowed == {MembershipRole.OWNER}, permission


class TestMembershipResolution:
    """Only an accepted membership confers authority."""

    def test_no_membership_grants_nothing(self) -> None:
        assert resolve_permissions(None) == frozenset()

    def test_pending_invitation_grants_nothing(self) -> None:
        """An invitee can see the invitation, but holds no authority yet."""
        pending = _member(MembershipRole.OWNER, MembershipStatus.PENDING)
        assert resolve_permissions(pending) == frozenset()

    def test_revoked_membership_grants_nothing(self) -> None:
        revoked = _member(MembershipRole.MANAGER, MembershipStatus.REVOKED)
        assert resolve_permissions(revoked) == frozenset()

    def test_accepted_membership_grants_its_role(self) -> None:
        accepted = _member(MembershipRole.ENGINEER)
        assert resolve_permissions(accepted) == permissions_for(MembershipRole.ENGINEER)


class TestProjectVisibility:
    """Who may read a project at all."""

    def test_public_project_is_readable_by_anyone(self) -> None:
        assert can_view_project(_project(Visibility.PUBLIC), membership=None) is True

    def test_private_project_is_hidden_from_non_members(self) -> None:
        assert can_view_project(_project(Visibility.PRIVATE), membership=None) is False

    def test_private_project_is_readable_by_a_member(self) -> None:
        member = _member(MembershipRole.VIEWER)
        assert can_view_project(_project(Visibility.PRIVATE), membership=member) is True

    def test_private_project_is_hidden_from_a_pending_invitee(self) -> None:
        pending = _member(MembershipRole.VIEWER, MembershipStatus.PENDING)
        assert can_view_project(_project(Visibility.PRIVATE), membership=pending) is False

    def test_archived_public_project_is_not_public(self) -> None:
        archived = _project(Visibility.PUBLIC, archived_at=datetime.now(UTC))
        assert can_view_project(archived, membership=None) is False


class TestAccessContext:
    """The per-request snapshot handed to handlers."""

    def test_public_project_grants_view_to_anonymous(self) -> None:
        context = AccessContext.build(_project(Visibility.PUBLIC), user_id=None, membership=None)
        assert context.allows(Permission.PROJECT_VIEW) is True
        assert context.allows(Permission.PROJECT_EDIT) is False
        assert context.is_member is False

    def test_member_permissions_are_additive_to_public_view(self) -> None:
        context = AccessContext.build(
            _project(Visibility.PUBLIC),
            user_id=uuid4(),
            membership=_member(MembershipRole.ENGINEER),
        )
        assert context.allows(Permission.DEVICE_MANAGE) is True
        assert context.is_member is True

    def test_private_project_grants_nothing_to_anonymous(self) -> None:
        context = AccessContext.build(_project(Visibility.PRIVATE), user_id=None, membership=None)
        assert context.permissions == frozenset()

    def test_payload_covers_every_permission(self) -> None:
        """The dashboard renders its buttons from this; a missing key hides one."""
        context = AccessContext.build(
            _project(Visibility.PRIVATE),
            user_id=uuid4(),
            membership=_member(MembershipRole.OWNER),
        )
        payload = context.to_payload()
        assert set(payload) == {permission.value for permission in Permission}
        assert all(payload.values()), "owner should be allowed everything"


class TestProfileVisibility:
    """Spec B.5 — public and private accounts."""

    @staticmethod
    def _user(visibility: Visibility, *, active: bool = True) -> User:
        return User(
            id=uuid4(),
            username="alice",
            email="alice@example.test",
            full_name="Alice",
            professional_role=ProfessionalRole.ENGINEER,
            profile_visibility=visibility,
            is_active=active,
        )

    def test_public_profile_is_viewable(self) -> None:
        assert can_view_profile(self._user(Visibility.PUBLIC), viewer_id=None) is True

    def test_private_profile_is_not_viewable_by_others(self) -> None:
        assert can_view_profile(self._user(Visibility.PRIVATE), viewer_id=uuid4()) is False

    def test_you_can_always_see_your_own_profile(self) -> None:
        user = self._user(Visibility.PRIVATE)
        assert can_view_profile(user, viewer_id=user.id) is True

    def test_deactivated_public_profile_is_hidden(self) -> None:
        user = self._user(Visibility.PUBLIC, active=False)
        assert can_view_profile(user, viewer_id=None) is False


class TestProfessionalRoleGrantsNothing:
    """The two role axes must not be conflated."""

    def test_professional_role_is_absent_from_the_matrix(self) -> None:
        """A 'manager' by profession has no authority on a project.

        Authority comes only from `MembershipRole`. If `ProfessionalRole` ever
        appears in `ROLE_PERMISSIONS`, the two axes have been confused.
        """
        for key in ROLE_PERMISSIONS:
            assert isinstance(key, MembershipRole)
            assert not isinstance(key, ProfessionalRole)
