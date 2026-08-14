"""Who may do what, as pure functions.

This is the executable form of the permission matrix in
``GeoVision-Vault/02-Domain/Roles-and-Permissions.md``. It is the single
authority for every access decision from Module 04 onward, so it lives in the
domain layer with **no framework, no ORM, no I/O** — the whole matrix is
testable in milliseconds without a database.

Two independent role axes, which are easy to conflate:

* ``ProfessionalRole`` is what a person *is* (engineer, manager, home owner).
  Self-declared at registration, shown on their profile, and **grants nothing**.
* ``MembershipRole`` is what they may *do on one specific project*. This is the
  only thing consulted here.

A "manager" by profession has zero authority on a project they were never added
to. That distinction is the reason ``ProfessionalRole`` does not appear
anywhere in this file.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID

from app.domain.enums import MembershipRole, MembershipStatus, Permission, Visibility

if TYPE_CHECKING:
    from app.domain.entities import Project, ProjectMember, User

__all__ = [
    "ROLE_PERMISSIONS",
    "AccessContext",
    "can_view_profile",
    "can_view_project",
    "has_permission",
    "permissions_for",
    "resolve_permissions",
]


# ---------------------------------------------------------------------------
# The matrix
#
# Built cumulatively so the hierarchy is visible rather than transcribed by
# hand: each role adds to the one below it. Copy-pasted permission sets drift
# the moment somebody adds a permission and updates four of the seven rows.
# ---------------------------------------------------------------------------

_VIEWER: frozenset[Permission] = frozenset({Permission.PROJECT_VIEW})

_EMPLOYEE: frozenset[Permission] = _VIEWER | {Permission.REPORT_GENERATE}

_COLLABORATOR: frozenset[Permission] = _EMPLOYEE | {
    Permission.ASSET_UPLOAD,
    Permission.IMAGE_UPLOAD,
    Permission.REMARK_WRITE,
}

_EDITOR: frozenset[Permission] = _COLLABORATOR | {Permission.PROJECT_EDIT}

_ENGINEER: frozenset[Permission] = _EDITOR | {Permission.DEVICE_MANAGE}

_MANAGER: frozenset[Permission] = _ENGINEER | {
    Permission.MEMBER_MANAGE,
    Permission.PROJECT_APPROVE,
    Permission.PROGRESS_RECOMPUTE,
}

_OWNER: frozenset[Permission] = _MANAGER | {
    Permission.PROJECT_VISIBILITY,
    Permission.PROJECT_DELETE,
}

#: Authoritative mapping. Anything not listed for a role is denied.
ROLE_PERMISSIONS: dict[MembershipRole, frozenset[Permission]] = {
    MembershipRole.VIEWER: _VIEWER,
    MembershipRole.EMPLOYEE: _EMPLOYEE,
    MembershipRole.COLLABORATOR: _COLLABORATOR,
    MembershipRole.EDITOR: _EDITOR,
    MembershipRole.ENGINEER: _ENGINEER,
    MembershipRole.MANAGER: _MANAGER,
    MembershipRole.OWNER: _OWNER,
}


def permissions_for(role: MembershipRole) -> frozenset[Permission]:
    """Return every permission granted by *role*.

    Args:
        role: A project membership role.

    Returns:
        The granted permissions; empty for an unrecognised role, so a new enum
        member added without a matrix entry fails closed rather than open.
    """
    return ROLE_PERMISSIONS.get(role, frozenset())


def has_permission(role: MembershipRole, permission: Permission) -> bool:
    """Whether *role* grants *permission*."""
    return permission in permissions_for(role)


def resolve_permissions(membership: ProjectMember | None) -> frozenset[Permission]:
    """Return the permissions an actual membership confers.

    A **pending invitation grants nothing**: the invitee can see that they were
    invited, but has no authority on the project until they accept. Revoked
    memberships likewise grant nothing.

    Args:
        membership: The caller's membership, or ``None`` if they have none.

    Returns:
        The effective permission set.
    """
    if membership is None:
        return frozenset()
    if membership.membership_status is not MembershipStatus.ACCEPTED:
        return frozenset()
    return permissions_for(membership.membership_role)


@dataclass(frozen=True, slots=True)
class AccessContext:
    """The resolved answer to "what may this caller do with this project?".

    Built once per request by the API layer and handed to the use case, so a
    handler never re-queries membership and every decision in that request is
    made from one consistent snapshot.

    Attributes:
        user_id: The caller, or ``None`` for an anonymous visitor.
        project_id: The project in question.
        membership: The caller's membership, if any.
        permissions: What they may actually do.
        project_is_public: Whether anonymous read is allowed.
    """

    project_id: UUID
    permissions: frozenset[Permission]
    user_id: UUID | None = None
    membership: ProjectMember | None = None
    project_is_public: bool = False

    @classmethod
    def build(
        cls,
        project: Project,
        *,
        user_id: UUID | None,
        membership: ProjectMember | None,
    ) -> AccessContext:
        """Assemble the context for one caller against one project."""
        permissions = resolve_permissions(membership)
        # A public project is readable by anyone, member or not.
        if project.is_public:
            permissions = permissions | {Permission.PROJECT_VIEW}
        return cls(
            project_id=project.id,
            permissions=permissions,
            user_id=user_id,
            membership=membership,
            project_is_public=project.is_public,
        )

    def allows(self, permission: Permission) -> bool:
        """Whether the caller holds *permission*."""
        return permission in self.permissions

    @property
    def is_member(self) -> bool:
        """Whether the caller has an accepted membership."""
        return (
            self.membership is not None
            and self.membership.membership_status is MembershipStatus.ACCEPTED
        )

    def to_payload(self) -> dict[str, bool]:
        """Render as the ``permissions`` block of the project folder response.

        The dashboard shows and hides controls from this, so the UI never
        re-derives authority client-side. Hiding a button is presentation, not
        security — the API enforces the same rules regardless.
        """
        return {permission.value: permission in self.permissions for permission in Permission}


def can_view_project(
    project: Project,
    *,
    membership: ProjectMember | None,
) -> bool:
    """Whether a caller may read this project at all.

    Public projects are readable by everyone. Private projects require an
    accepted membership.

    .. note::
       When this returns ``False`` the API answers **404, never 403**. A 403
       confirms the project exists, which is itself a disclosure about a
       resource the caller is not allowed to know about.
    """
    if project.is_public:
        return True
    return Permission.PROJECT_VIEW in resolve_permissions(membership)


def can_view_profile(profile_owner: User, *, viewer_id: UUID | None) -> bool:
    """Whether a caller may see a user's full profile (spec B.5).

    A private account is still findable by exact username — so they can be
    invited to a project — but discloses nothing beyond that. Users can always
    see their own profile regardless of the setting.
    """
    if viewer_id is not None and profile_owner.id == viewer_id:
        return True
    return profile_owner.profile_visibility is Visibility.PUBLIC and profile_owner.is_active
