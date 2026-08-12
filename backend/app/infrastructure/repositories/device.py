"""SQLAlchemy implementations of the device and pairing-token repositories."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import delete, func, select, update

from app.domain.entities import Device, PairingToken
from app.domain.enums import CameraFace, DeviceStatus
from app.infrastructure.db import models
from app.infrastructure.repositories._result import affected_rows, to_decimal
from app.infrastructure.repositories.mappers import to_device, to_pairing_token

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

__all__ = ["SqlAlchemyDeviceRepository", "SqlAlchemyPairingTokenRepository"]


def _schedule_to_json(device: Device) -> dict[str, object]:
    """Serialise the capture schedule for the JSONB column."""
    data = asdict(device.capture_schedule)
    data["times"] = list(device.capture_schedule.times)
    return data


class SqlAlchemyDeviceRepository:
    """Paired ESP32-CAM nodes, backed by PostgreSQL."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind the repository to a request-scoped session."""
        self._session = session

    async def get(self, device_id: UUID) -> Device | None:
        """Return a device by id."""
        row = await self._session.get(models.DeviceModel, device_id)
        return to_device(row) if row else None

    async def get_by_name(self, device_name: str) -> Device | None:
        """Return a device by its derived name, e.g. ``ESP_NG_00_FD``."""
        stmt = select(models.DeviceModel).where(models.DeviceModel.device_name == device_name)
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        return to_device(row) if row else None

    async def list_for_project(self, project_id: UUID) -> tuple[Device, ...]:
        """Every device paired to a project."""
        stmt = (
            select(models.DeviceModel)
            .where(models.DeviceModel.project_id == project_id)
            .order_by(models.DeviceModel.created_at)
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        return tuple(to_device(row) for row in rows)

    async def face_taken(self, project_id: UUID, face: CameraFace) -> bool:
        """Whether the project already has an active camera on *face*.

        Revoked devices do not count, so unpairing frees the slot for a
        replacement camera.
        """
        stmt = (
            select(func.count())
            .select_from(models.DeviceModel)
            .where(
                models.DeviceModel.project_id == project_id,
                models.DeviceModel.face == face,
                models.DeviceModel.status != DeviceStatus.REVOKED,
            )
        )
        return bool((await self._session.execute(stmt)).scalar_one())

    async def get_secret_hash(self, device_id: UUID) -> str | None:
        """Return the HMAC secret hash used to verify request signatures."""
        stmt = select(models.DeviceModel.secret_hash).where(models.DeviceModel.id == device_id)
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def list_stale(self, since: datetime) -> tuple[Device, ...]:
        """Paired devices not heard from since *since* — the offline sweep."""
        stmt = select(models.DeviceModel).where(
            models.DeviceModel.status.in_(
                [DeviceStatus.ONLINE, DeviceStatus.PAIRED, DeviceStatus.OFFLINE]
            ),
            models.DeviceModel.last_seen_at.is_not(None),
            models.DeviceModel.last_seen_at < since,
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        return tuple(to_device(row) for row in rows)

    async def add(self, device: Device, secret_hash: str) -> Device:
        """Create a device at pairing time.

        The secret hash is passed separately and stored write-only: the
        plaintext is returned to the firmware exactly once, at claim time, and
        is never retrievable afterwards.
        """
        row = models.DeviceModel(
            id=device.id,
            project_id=device.project_id,
            device_name=device.device_name,
            face=device.face,
            weight=to_decimal(device.weight),
            secret_hash=secret_hash,
            status=device.status,
            firmware_version=device.firmware_version,
            hardware_id=device.hardware_id,
            capture_schedule=_schedule_to_json(device),
            homography=device.homography,
            roi_polygon=device.roi_polygon,
            paired_at=device.paired_at,
        )
        self._session.add(row)
        await self._session.flush()
        await self._session.refresh(row)
        return to_device(row)

    async def update(self, device: Device) -> Device:
        """Persist device settings or telemetry."""
        row = await self._session.get(models.DeviceModel, device.id)
        if row is None:
            msg = f"device {device.id} not found"
            raise LookupError(msg)
        row.weight = to_decimal(device.weight)
        row.status = device.status
        row.firmware_version = device.firmware_version
        row.hardware_id = device.hardware_id
        row.capture_schedule = _schedule_to_json(device)
        row.homography = device.homography
        row.roi_polygon = device.roi_polygon
        row.last_seen_at = device.last_seen_at
        row.last_battery_mv = device.last_battery_mv
        row.last_rssi_dbm = device.last_rssi_dbm
        row.revoked_at = device.revoked_at
        await self._session.flush()
        await self._session.refresh(row)
        return to_device(row)

    async def record_heartbeat(
        self,
        device_id: UUID,
        *,
        seen_at: datetime,
        battery_mv: int | None = None,
        rssi_dbm: int | None = None,
    ) -> None:
        """Update liveness fields without loading the entity.

        Heartbeats are the highest-frequency write in the system, so this is a
        targeted UPDATE rather than a read-modify-write.
        """
        values: dict[str, object] = {
            "last_seen_at": seen_at,
            "status": DeviceStatus.ONLINE,
        }
        if battery_mv is not None:
            values["last_battery_mv"] = battery_mv
        if rssi_dbm is not None:
            values["last_rssi_dbm"] = rssi_dbm
        stmt = update(models.DeviceModel).where(models.DeviceModel.id == device_id).values(**values)
        await self._session.execute(stmt)

    async def revoke(self, device_id: UUID, revoked_at: datetime) -> bool:
        """Unpair a device: revoke it and wipe its secret.

        Historical images and predictions are retained — swapping hardware must
        not rewrite a project's progress history.
        """
        stmt = (
            update(models.DeviceModel)
            .where(models.DeviceModel.id == device_id)
            .values(status=DeviceStatus.REVOKED, revoked_at=revoked_at, secret_hash=None)
        )
        result = await self._session.execute(stmt)
        return bool(affected_rows(result))


class SqlAlchemyPairingTokenRepository:
    """Single-use pairing codes, backed by PostgreSQL."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind the repository to a request-scoped session."""
        self._session = session

    async def add(self, token: PairingToken) -> PairingToken:
        """Issue a token; only the hash of the display code is stored."""
        row = models.PairingTokenModel(
            id=token.id,
            project_id=token.project_id,
            face=token.face,
            token_hash=token.token_hash,
            expires_at=token.expires_at,
            created_by=token.created_by,
        )
        self._session.add(row)
        await self._session.flush()
        await self._session.refresh(row)
        return to_pairing_token(row)

    async def get_by_hash(self, token_hash: str) -> PairingToken | None:
        """Look up a token by the hash of its display code."""
        stmt = select(models.PairingTokenModel).where(
            models.PairingTokenModel.token_hash == token_hash
        )
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        return to_pairing_token(row) if row else None

    async def mark_used(self, token_id: UUID, device_id: UUID, used_at: datetime) -> None:
        """Consume the token, binding it to the device that claimed it."""
        stmt = (
            update(models.PairingTokenModel)
            .where(models.PairingTokenModel.id == token_id)
            .values(used_at=used_at, used_by_device_id=device_id)
        )
        await self._session.execute(stmt)

    async def delete_expired(self, before: datetime) -> int:
        """Purge expired, unclaimed tokens."""
        stmt = delete(models.PairingTokenModel).where(
            models.PairingTokenModel.expires_at < before,
            models.PairingTokenModel.used_at.is_(None),
        )
        result = await self._session.execute(stmt)
        return affected_rows(result)
