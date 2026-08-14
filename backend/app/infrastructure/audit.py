"""Audit logging for security-relevant actions.

Built here in Module 03 because Modules 04 and 05 both need it and neither
should invent its own: project approval awards the final 20 % of a building's
recorded progress, device pairing grants a camera the right to write into a
project, and visibility changes expose or hide data. All three must be
attributable to a named actor at a known time.

Writes go through the caller's session, so an audit row is committed in the
same transaction as the action it describes — an action can never be recorded
without its audit entry, or vice versa.
"""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING, Any
from uuid import UUID

from app.infrastructure.db import models

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

__all__ = ["AuditAction", "AuditLogger"]


class AuditAction(StrEnum):
    """Actions worth recording.

    Kept as an enum so the log is queryable — free-text action names become
    unsearchable within a month.
    """

    # Module 03
    USER_REGISTERED = "user.registered"
    USER_LOGGED_IN = "user.logged_in"
    USER_LOGIN_FAILED = "user.login_failed"
    USER_LOGGED_OUT = "user.logged_out"
    TOKEN_REUSE_DETECTED = "token.reuse_detected"  # noqa: S105 - an action name
    PROFILE_UPDATED = "user.profile_updated"
    PROFILE_VISIBILITY_CHANGED = "user.visibility_changed"

    # Module 04
    PROJECT_CREATED = "project.created"
    PROJECT_VISIBILITY_CHANGED = "project.visibility_changed"
    PROJECT_APPROVED = "project.approved"
    PROJECT_ARCHIVED = "project.archived"
    MEMBER_INVITED = "member.invited"
    MEMBER_ROLE_CHANGED = "member.role_changed"
    MEMBER_REMOVED = "member.removed"

    # Module 05
    PAIRING_TOKEN_ISSUED = "device.pairing_token_issued"  # noqa: S105 - an action name
    DEVICE_PAIRED = "device.paired"
    DEVICE_UNPAIRED = "device.unpaired"
    DEVICE_AUTH_FAILED = "device.auth_failed"

    # Module 09
    #: Both rewrite numbers the project is judged on, from data that is already
    #: stored. Auditing them answers "why did this figure change on Tuesday?"
    #: without anyone having to guess.
    IMAGE_REPROCESSED = "image.reprocessed"
    PROGRESS_RECOMPUTE_REQUESTED = "progress.recompute_requested"

    # Module 10
    #: A report may be shown to a client or attached to a claim, so who asked
    #: for one and who took a copy are both worth being able to answer later.
    REPORT_REQUESTED = "report.requested"
    REPORT_DOWNLOADED = "report.downloaded"


class AuditLogger:
    """Appends audit entries to the caller's transaction."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind to a request-scoped session."""
        self._session = session

    async def record(
        self,
        action: AuditAction,
        *,
        entity_type: str,
        entity_id: UUID,
        actor_user_id: UUID | None = None,
        actor_device_id: UUID | None = None,
        metadata: dict[str, Any] | None = None,
        ip_address: str | None = None,
    ) -> None:
        """Record one action.

        Args:
            action: What happened.
            entity_type: The kind of thing acted upon, e.g. ``"project"``.
            entity_id: Its id.
            actor_user_id: The human responsible, if any.
            actor_device_id: The device responsible, if any.
            metadata: Extra context. **Must never contain credentials** —
                no passwords, tokens, or secrets. Audit logs are widely read.
            ip_address: Caller address, where known.
        """
        self._session.add(
            models.AuditLogModel(
                action=action.value,
                entity_type=entity_type,
                entity_id=entity_id,
                actor_user_id=actor_user_id,
                actor_device_id=actor_device_id,
                audit_metadata=metadata or {},
                ip_address=ip_address,
            )
        )
        # Deliberately no flush: the entry lands with the surrounding
        # transaction, so it cannot survive an action that was rolled back.
