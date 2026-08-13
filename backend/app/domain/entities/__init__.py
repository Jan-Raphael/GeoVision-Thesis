"""Domain entities — business objects as frozen dataclasses.

Pure Python: no ORM, no framework, no torch. Repositories translate between
these and database rows; use cases manipulate these and nothing else.

Grouped by aggregate:

``user``    :class:`User`, :class:`PublicProfile`, :class:`RefreshToken`
``project`` :class:`Project`, :class:`ProjectMember`, :class:`Remark`,
            :class:`ReferenceAsset`, :class:`StageBreakdown`
``device``  :class:`Device`, :class:`PairingToken`, :class:`DeviceEvent`,
            :class:`CaptureSchedule`
``image``   :class:`Image`, :class:`Prediction`, :class:`Detection`,
            :class:`DetectionSummary`, :class:`ProgressSnapshot`,
            :class:`BoundingBox`
``system``  :class:`Report`, :class:`AIModel`, :class:`Notification`,
            :class:`AuditLog`
"""

from __future__ import annotations

from app.domain.entities.device import (
    CaptureSchedule,
    Device,
    DeviceEvent,
    PairingToken,
)
from app.domain.entities.image import (
    BoundingBox,
    Detection,
    DetectionSummary,
    Image,
    Prediction,
    ProgressSnapshot,
)
from app.domain.entities.project import (
    Project,
    ProjectMember,
    ReferenceAsset,
    Remark,
    StageBreakdown,
)
from app.domain.entities.system import (
    AIModel,
    AuditLog,
    ContactMessage,
    Notification,
    Report,
)
from app.domain.entities.user import PublicProfile, RefreshToken, User

__all__ = [
    "AIModel",
    "AuditLog",
    "BoundingBox",
    "CaptureSchedule",
    "ContactMessage",
    "Detection",
    "DetectionSummary",
    "Device",
    "DeviceEvent",
    "Image",
    "Notification",
    "PairingToken",
    "Prediction",
    "ProgressSnapshot",
    "Project",
    "ProjectMember",
    "PublicProfile",
    "ReferenceAsset",
    "RefreshToken",
    "Remark",
    "Report",
    "StageBreakdown",
    "User",
]
