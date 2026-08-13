"""Profile use cases: read, update, visibility, search.

Avatar upload is deliberately **not** here. It needs the object-storage adapter,
which Module 04 owns; adding a half-wired uploader now would mean a second
implementation later. Recorded in the Module 03 note.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING
from uuid import UUID

from app.core.exceptions import NotFoundError
from app.domain.entities import PublicProfile, User
from app.domain.enums import ProfessionalRole, Visibility

if TYPE_CHECKING:
    from app.domain.entities import Project
    from app.domain.repositories import ProjectRepository, UserRepository

__all__ = [
    "GetMyProfile",
    "GetPublicProfile",
    "PublicProfileView",
    "SearchUsers",
    "SetProfileVisibility",
    "UpdateProfile",
]


@dataclass(frozen=True, slots=True)
class PublicProfileView:
    """A public profile plus the public projects the person is involved in.

    For a private account ``profile.is_private`` is true and ``projects`` is
    empty — the caller cannot learn what they are working on.
    """

    profile: PublicProfile
    projects: tuple[Project, ...] = ()


class GetMyProfile:
    """Fetch the caller's own full profile."""

    def __init__(self, users: UserRepository) -> None:
        """Wire the use case to its collaborators."""
        self._users = users

    async def execute(self, user_id: UUID) -> User:
        """Return the user.

        Raises:
            NotFoundError: If the account no longer exists.
        """
        user = await self._users.get(user_id)
        if user is None:
            msg = "User not found."
            raise NotFoundError(msg)
        return user


class UpdateProfile:
    """Edit the caller's own profile."""

    def __init__(self, users: UserRepository) -> None:
        """Wire the use case to its collaborators."""
        self._users = users

    async def execute(
        self,
        user_id: UUID,
        *,
        full_name: str | None = None,
        company: str | None = None,
        bio: str | None = None,
        professional_role: ProfessionalRole | None = None,
        profile_visibility: Visibility | None = None,
        clear_company: bool = False,
        clear_bio: bool = False,
    ) -> User:
        """Apply a partial update.

        ``None`` means "leave unchanged", which is why clearing an optional
        field needs its own explicit flag — otherwise there would be no way to
        remove a company once set.

        Args:
            user_id: Whose profile to edit.
            full_name: New display name, if changing.
            company: New company, if changing.
            bio: New bio, if changing.
            professional_role: New declared role, if changing.
            profile_visibility: Public/private toggle (spec B.5).
            clear_company: Explicitly unset the company.
            clear_bio: Explicitly unset the bio.

        Returns:
            The updated user.

        Raises:
            NotFoundError: If the account no longer exists.
        """
        user = await self._users.get(user_id)
        if user is None:
            msg = "User not found."
            raise NotFoundError(msg)

        updated = replace(
            user,
            full_name=full_name if full_name is not None else user.full_name,
            company=None if clear_company else (company if company is not None else user.company),
            bio=None if clear_bio else (bio if bio is not None else user.bio),
            professional_role=(
                professional_role if professional_role is not None else user.professional_role
            ),
            profile_visibility=(
                profile_visibility if profile_visibility is not None else user.profile_visibility
            ),
        )
        return await self._users.update(updated)


class SetProfileVisibility:
    """Toggle a profile between public and private (spec B.5)."""

    def __init__(self, users: UserRepository) -> None:
        """Wire the use case to its collaborators."""
        self._users = users

    async def execute(self, user_id: UUID, visibility: Visibility) -> User:
        """Set the visibility flag.

        Raises:
            NotFoundError: If the account no longer exists.
        """
        user = await self._users.get(user_id)
        if user is None:
            msg = "User not found."
            raise NotFoundError(msg)
        return await self._users.update(replace(user, profile_visibility=visibility))


class GetPublicProfile:
    """Fetch a profile as an anonymous visitor sees it."""

    def __init__(self, users: UserRepository, projects: ProjectRepository) -> None:
        """Wire the use case to its collaborators."""
        self._users = users
        self._projects = projects

    async def execute(self, username: str, *, viewer_id: UUID | None = None) -> PublicProfileView:
        """Return the public view of *username*.

        A private account yields ``{username, is_private: true}`` and no
        projects — but still resolves rather than 404ing, because the profile
        page needs to render "this account is private" and the person must stay
        findable so they can be invited to a project.

        Viewing your own profile always shows the full version, regardless of
        the visibility setting.

        Args:
            username: The profile to look up.
            viewer_id: The caller, if authenticated.

        Returns:
            The profile view.

        Raises:
            NotFoundError: If no such account exists.
        """
        user = await self._users.get_by_username(username)
        if user is None:
            msg = "User not found."
            raise NotFoundError(msg)

        is_self = viewer_id is not None and viewer_id == user.id
        if not is_self and not user.is_public:
            return PublicProfileView(profile=PublicProfile(username=user.username, is_private=True))

        projects = await self._projects.list_public_for_user(user.id)
        # `to_public_profile()` redacts a private account by design, so viewing
        # your own private profile needs the explicit unredacted form.
        profile = user.to_full_profile() if is_self else user.to_public_profile()
        return PublicProfileView(profile=profile, projects=projects)


class SearchUsers:
    """Search public profiles by username or name."""

    def __init__(self, users: UserRepository) -> None:
        """Wire the use case to its collaborators."""
        self._users = users

    async def execute(self, query: str, *, limit: int = 20) -> tuple[PublicProfile, ...]:
        """Return matching **public** profiles.

        Private accounts are excluded from fuzzy search but remain reachable by
        exact username, which is the balance the spec asks for: findable enough
        to invite, not browsable.
        """
        cleaned = query.strip()
        if len(cleaned) < 2:
            return ()
        found = await self._users.search(cleaned, limit=limit)
        return tuple(user.to_public_profile() for user in found)
