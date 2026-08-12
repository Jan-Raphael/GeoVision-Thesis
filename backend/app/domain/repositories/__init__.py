"""Abstract repository interfaces (Module 02).

Methods are named for intent (`list_public_feed`, `find_by_project_code`), not
for SQL. Concrete implementations live in `app.infrastructure.repositories`,
and tests inject fakes that satisfy the same Protocol.
"""

from __future__ import annotations

from app.domain.repositories.base import Page, ReadRepository, WriteRepository
from app.domain.repositories.protocols import (
    AIModelRepository,
    DeviceRepository,
    ImageRepository,
    NotificationRepository,
    PairingTokenRepository,
    PredictionRepository,
    ProjectMemberRepository,
    ProjectRepository,
    ReferenceAssetRepository,
    RefreshTokenRepository,
    RemarkRepository,
    ReportRepository,
    SnapshotRepository,
    UserRepository,
)

__all__ = [
    "AIModelRepository",
    "DeviceRepository",
    "ImageRepository",
    "NotificationRepository",
    "Page",
    "PairingTokenRepository",
    "PredictionRepository",
    "ProjectMemberRepository",
    "ProjectRepository",
    "ReadRepository",
    "ReferenceAssetRepository",
    "RefreshTokenRepository",
    "RemarkRepository",
    "ReportRepository",
    "SnapshotRepository",
    "UserRepository",
    "WriteRepository",
]
