"""SQLAlchemy implementations of the user and session repositories."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import delete, func, select, update

from app.domain.entities import RefreshToken, User
from app.domain.enums import Visibility
from app.infrastructure.db import models
from app.infrastructure.repositories._result import affected_rows
from app.infrastructure.repositories.mappers import to_refresh_token, to_user

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

__all__ = ["SqlAlchemyRefreshTokenRepository", "SqlAlchemyUserRepository"]

#: Minimum trigram similarity for a search hit. Tuned low enough that a partial
#: name matches, high enough that unrelated names do not.
SEARCH_SIMILARITY_THRESHOLD = 0.2


class SqlAlchemyUserRepository:
    """Accounts and profiles, backed by PostgreSQL."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind the repository to a request-scoped session."""
        self._session = session

    async def get(self, user_id: UUID) -> User | None:
        """Return a user by id."""
        row = await self._session.get(models.UserModel, user_id)
        return to_user(row) if row else None

    async def get_by_username(self, username: str) -> User | None:
        """Return a user by username. ``citext`` makes this case-insensitive."""
        stmt = select(models.UserModel).where(models.UserModel.username == username)
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        return to_user(row) if row else None

    async def get_by_email(self, email: str) -> User | None:
        """Return a user by email (case-insensitive)."""
        stmt = select(models.UserModel).where(models.UserModel.email == email)
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        return to_user(row) if row else None

    async def get_by_identifier(self, identifier: str) -> User | None:
        """Return a user by username **or** email — the login form's one field."""
        stmt = select(models.UserModel).where(
            (models.UserModel.username == identifier) | (models.UserModel.email == identifier)
        )
        row = (await self._session.execute(stmt)).scalars().first()
        return to_user(row) if row else None

    async def get_public_profile(self, username: str) -> User | None:
        """Return a user **only if** their profile is public and active.

        The visibility filter is part of the query, so this method physically
        cannot return a private profile. A private account yields ``None`` and
        the caller renders "this account is private".
        """
        stmt = select(models.UserModel).where(
            models.UserModel.username == username,
            models.UserModel.profile_visibility == Visibility.PUBLIC,
            models.UserModel.is_active.is_(True),
        )
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        return to_user(row) if row else None

    async def exists(self, user_id: UUID) -> bool:
        """Whether a user exists."""
        stmt = (
            select(func.count()).select_from(models.UserModel).where(models.UserModel.id == user_id)
        )
        return bool((await self._session.execute(stmt)).scalar_one())

    async def username_exists(self, username: str) -> bool:
        """Whether a username is taken."""
        stmt = (
            select(func.count())
            .select_from(models.UserModel)
            .where(models.UserModel.username == username)
        )
        return bool((await self._session.execute(stmt)).scalar_one())

    async def email_exists(self, email: str) -> bool:
        """Whether an email is already registered."""
        stmt = (
            select(func.count())
            .select_from(models.UserModel)
            .where(models.UserModel.email == email)
        )
        return bool((await self._session.execute(stmt)).scalar_one())

    async def search(self, query: str, *, limit: int = 20) -> tuple[User, ...]:
        """Fuzzy-search **public** profiles by username or full name.

        Uses trigram similarity, so "macabulos" finds "Jan Macabulos" and a
        typo still matches. Private accounts are excluded here; they remain
        findable by exact username through :meth:`get_by_username`, which is
        what lets a user be invited without exposing their profile.
        """
        similarity = func.greatest(
            func.similarity(models.UserModel.username, query),
            func.similarity(models.UserModel.full_name, query),
        )
        stmt = (
            select(models.UserModel)
            .where(
                models.UserModel.is_active.is_(True),
                models.UserModel.profile_visibility == Visibility.PUBLIC,
                similarity > SEARCH_SIMILARITY_THRESHOLD,
            )
            .order_by(similarity.desc())
            .limit(limit)
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        return tuple(to_user(row) for row in rows)

    async def add(self, user: User, password_hash: str) -> User:
        """Create an account.

        The password hash is passed separately because :class:`User` carries no
        credential material — an entity that cannot hold a hash cannot leak one
        through a serialiser.
        """
        row = models.UserModel(
            id=user.id,
            username=user.username,
            email=user.email,
            password_hash=password_hash,
            full_name=user.full_name,
            professional_role=user.professional_role,
            profile_visibility=user.profile_visibility,
            company=user.company,
            bio=user.bio,
            avatar_key=user.avatar_key,
            is_active=user.is_active,
        )
        self._session.add(row)
        await self._session.flush()
        await self._session.refresh(row)
        return to_user(row)

    async def update(self, user: User) -> User:
        """Persist profile changes."""
        row = await self._session.get(models.UserModel, user.id)
        if row is None:
            msg = f"user {user.id} not found"
            raise LookupError(msg)
        row.full_name = user.full_name
        row.professional_role = user.professional_role
        row.profile_visibility = user.profile_visibility
        row.company = user.company
        row.bio = user.bio
        row.avatar_key = user.avatar_key
        row.is_active = user.is_active
        row.email_verified_at = user.email_verified_at
        await self._session.flush()
        await self._session.refresh(row)
        return to_user(row)

    async def get_password_hash(self, user_id: UUID) -> str | None:
        """Return the stored password hash for verification."""
        stmt = select(models.UserModel.password_hash).where(models.UserModel.id == user_id)
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def set_password_hash(self, user_id: UUID, password_hash: str) -> None:
        """Replace the stored password hash."""
        stmt = (
            update(models.UserModel)
            .where(models.UserModel.id == user_id)
            .values(password_hash=password_hash)
        )
        await self._session.execute(stmt)


class SqlAlchemyRefreshTokenRepository:
    """Rotating refresh tokens, backed by PostgreSQL."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind the repository to a request-scoped session."""
        self._session = session

    async def add(self, token: RefreshToken) -> RefreshToken:
        """Store a token; only the hash is persisted."""
        row = models.RefreshTokenModel(
            id=token.id,
            user_id=token.user_id,
            token_hash=token.token_hash,
            family_id=token.family_id,
            expires_at=token.expires_at,
            user_agent=token.user_agent,
            ip_address=token.ip_address,
        )
        self._session.add(row)
        await self._session.flush()
        await self._session.refresh(row)
        return to_refresh_token(row)

    async def get_by_hash(self, token_hash: str) -> RefreshToken | None:
        """Look up a token by its hash."""
        stmt = select(models.RefreshTokenModel).where(
            models.RefreshTokenModel.token_hash == token_hash
        )
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        return to_refresh_token(row) if row else None

    async def revoke_family(self, family_id: UUID) -> int:
        """Revoke every unrevoked token in a family.

        Called when an already-rotated token is presented again: that means
        someone replayed a stolen token, so the whole family is burned rather
        than just the one credential.
        """
        stmt = (
            update(models.RefreshTokenModel)
            .where(
                models.RefreshTokenModel.family_id == family_id,
                models.RefreshTokenModel.revoked_at.is_(None),
            )
            .values(revoked_at=func.now())
        )
        result = await self._session.execute(stmt)
        return affected_rows(result)

    async def delete_expired(self, before: datetime) -> int:
        """Purge tokens that expired before *before*."""
        stmt = delete(models.RefreshTokenModel).where(models.RefreshTokenModel.expires_at < before)
        result = await self._session.execute(stmt)
        return affected_rows(result)
