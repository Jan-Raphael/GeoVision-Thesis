"""Concrete SQLAlchemy repository implementations + ORM<->entity mappers.

Each class satisfies the corresponding Protocol in `app.domain.repositories`
structurally - no inheritance, so a test fake needs only matching method
signatures.

None of these commit. Transaction scope belongs to the request (see
`app.infrastructure.db.session.get_session`), so a use case touching several
repositories either persists everything or nothing.
"""

from __future__ import annotations

from app.infrastructure.repositories.device import (
    SqlAlchemyDeviceRepository,
    SqlAlchemyPairingTokenRepository,
)
from app.infrastructure.repositories.image import (
    SqlAlchemyDetectionRepository,
    SqlAlchemyImageRepository,
    SqlAlchemyPredictionRepository,
    SqlAlchemySnapshotRepository,
)
from app.infrastructure.repositories.member import SqlAlchemyProjectMemberRepository
from app.infrastructure.repositories.project import SqlAlchemyProjectRepository
from app.infrastructure.repositories.system import (
    SqlAlchemyAIModelRepository,
    SqlAlchemyContactMessageRepository,
    SqlAlchemyNotificationRepository,
    SqlAlchemyReferenceAssetRepository,
    SqlAlchemyRemarkRepository,
    SqlAlchemyReportRepository,
)
from app.infrastructure.repositories.user import (
    SqlAlchemyRefreshTokenRepository,
    SqlAlchemyUserRepository,
)

__all__ = [
    "SqlAlchemyAIModelRepository",
    "SqlAlchemyContactMessageRepository",
    "SqlAlchemyDetectionRepository",
    "SqlAlchemyDeviceRepository",
    "SqlAlchemyImageRepository",
    "SqlAlchemyNotificationRepository",
    "SqlAlchemyPairingTokenRepository",
    "SqlAlchemyPredictionRepository",
    "SqlAlchemyProjectMemberRepository",
    "SqlAlchemyProjectRepository",
    "SqlAlchemyReferenceAssetRepository",
    "SqlAlchemyRefreshTokenRepository",
    "SqlAlchemyRemarkRepository",
    "SqlAlchemyReportRepository",
    "SqlAlchemySnapshotRepository",
    "SqlAlchemyUserRepository",
]
