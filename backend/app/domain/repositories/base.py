"""Shared repository abstractions.

Repositories are declared here as :class:`~typing.Protocol` classes rather than
ABCs. Two reasons: a test fake does not need to inherit from anything to
satisfy one, and the concrete SQLAlchemy implementations stay free of any
inheritance coupling to the domain.

Method names describe *intent* — ``list_public_feed``, ``find_by_project_code``
— never SQL. A repository that exposes ``execute(query)`` has not abstracted
anything.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Generic, Protocol, TypeVar
from uuid import UUID

__all__ = ["Page", "ReadRepository", "WriteRepository"]

EntityT = TypeVar("EntityT")
#: Covariant: a read-only repository of a subtype is usable wherever a
#: repository of the supertype is expected.
EntityT_co = TypeVar("EntityT_co", covariant=True)


@dataclass(frozen=True, slots=True)
class Page(Generic[EntityT]):
    """One page of results, with an opaque cursor for the next.

    Cursor pagination rather than offset: the image feed grows continuously
    while a user is scrolling it, and ``OFFSET`` would silently skip or repeat
    rows as new captures arrive.
    """

    items: tuple[EntityT, ...]
    next_cursor: str | None = None
    total: int | None = None

    @property
    def has_more(self) -> bool:
        """Whether another page exists."""
        return self.next_cursor is not None

    def __len__(self) -> int:
        """Number of items on this page."""
        return len(self.items)

    def __iter__(self) -> Iterator[EntityT]:
        """Iterate the items on this page."""
        return iter(self.items)


class ReadRepository(Protocol[EntityT_co]):
    """Read access to a collection of entities."""

    async def get(self, entity_id: UUID) -> EntityT_co | None:
        """Return the entity with *entity_id*, or ``None`` if absent."""
        ...

    async def exists(self, entity_id: UUID) -> bool:
        """Whether an entity with *entity_id* exists."""
        ...


class WriteRepository(Protocol[EntityT]):
    """Write access to a collection of entities.

    Implementations must **not** commit. Transaction scope belongs to the
    request (see ``app.infrastructure.db.session.get_session``), so that a use
    case touching several repositories either persists everything or nothing.
    """

    async def add(self, entity: EntityT) -> EntityT:
        """Persist a new entity and return it with database defaults applied."""
        ...

    async def update(self, entity: EntityT) -> EntityT:
        """Persist changes to an existing entity."""
        ...

    async def delete(self, entity_id: UUID) -> bool:
        """Delete the entity; returns whether a row was removed."""
        ...
