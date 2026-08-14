"""Entity → response translation for the project endpoints.

Kept out of the routers so the same folder can be rendered two ways — the full
authenticated view and the redacted public one — without either drifting from
the other, and so the routers stay thin enough to read.

The two public presenters are the enforcement point for what an anonymous
visitor sees. They build a *different response model* rather than filtering
fields off the internal one, so a field added later cannot leak by being
forgotten.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.api.schemas.projects import (
    AssetResponse,
    DeviceSummaryResponse,
    ImageSummaryResponse,
    MemberResponse,
    ProjectFolderResponse,
    ProjectSummaryResponse,
    PublicProjectResponse,
    RemarkResponse,
    StageBreakdownResponse,
    TimelinePointResponse,
)
from app.domain.entities import StageBreakdown
from app.domain.value_objects import GeoPoint

if TYPE_CHECKING:
    from datetime import datetime

    from app.application.use_cases.projects import ProjectFolder
    from app.domain.entities import (
        Device,
        Image,
        ProgressSnapshot,
        Project,
        ProjectMember,
        ReferenceAsset,
        Remark,
        User,
    )
    from app.domain.enums import DeviceStatus

__all__ = [
    "present_asset",
    "present_device",
    "present_folder",
    "present_member",
    "present_public_project",
    "present_remark",
    "present_summary",
]


def _stages(project: Project) -> StageBreakdownResponse:
    """The five progress bars."""
    bars: StageBreakdown = project.stage_breakdown()
    return StageBreakdownResponse(
        foundation_pct=bars.foundation_pct,
        framing_pct=bars.framing_pct,
        roofing_pct=bars.roofing_pct,
        finishing_pct=bars.finishing_pct,
        approval_pct=bars.approval_pct,
    )


def present_member(member: ProjectMember, user: User | None = None) -> MemberResponse:
    """One collaborator, with their profile details where known."""
    return MemberResponse(
        id=member.id,
        user_id=member.user_id,
        username=user.username if user else None,
        full_name=user.full_name if user else None,
        professional_role=user.professional_role if user else None,
        membership_role=member.membership_role,
        membership_status=member.membership_status,
        invited_at=member.invited_at,
        responded_at=member.responded_at,
    )


def _image(image: Image) -> ImageSummaryResponse:
    """A capture with its geotag and a map link."""
    return ImageSummaryResponse(
        id=image.id,
        filename=image.filename,
        captured_at=image.captured_at,
        latitude=image.location.latitude if image.location else None,
        longitude=image.location.longitude if image.location else None,
        thumb_key=image.thumb_key,
        device_id=image.device_id,
        status=image.status.value,
        map_url=(
            image.location.to_maps_url()
            if image.location is not None and image.is_geotagged
            else None
        ),
    )


def present_remark(remark: Remark) -> RemarkResponse:
    """A note, flagged with whether the system wrote it."""
    return RemarkResponse(
        id=remark.id,
        remark_type=remark.remark_type,
        severity=remark.severity,
        message=remark.message,
        author_id=remark.author_id,
        is_system_generated=remark.is_system_generated,
        is_public=remark.is_public,
        effective_from=remark.effective_from,
        effective_to=remark.effective_to,
        created_at=remark.created_at,
    )


def present_asset(asset: ReferenceAsset, download_url: str | None = None) -> AssetResponse:
    """An uploaded reference file."""
    return AssetResponse(
        id=asset.id,
        kind=asset.kind,
        original_filename=asset.original_filename,
        mime_type=asset.mime_type,
        size_bytes=asset.size_bytes,
        notes=asset.notes,
        is_public=asset.is_public,
        created_at=asset.created_at,
        download_url=download_url,
    )


def present_device(
    device: Device, *, liveness: DeviceStatus | None = None
) -> DeviceSummaryResponse:
    """A paired camera, optionally with freshly derived liveness."""
    return DeviceSummaryResponse(
        id=device.id,
        device_name=device.device_name,
        face=device.face,
        status=liveness or device.status,
        weight=device.weight,
        last_seen_at=device.last_seen_at,
        last_battery_mv=device.last_battery_mv,
        last_rssi_dbm=device.last_rssi_dbm,
    )


def _timeline(snapshots: tuple[ProgressSnapshot, ...]) -> list[TimelinePointResponse]:
    """The progress chart series."""
    return [
        TimelinePointResponse(
            window_start=snapshot.window_start,
            displayed_pct=snapshot.displayed_pct.as_float(),
            macro_stage=snapshot.macro_stage,
        )
        for snapshot in snapshots
    ]


def present_summary(project: Project) -> ProjectSummaryResponse:
    """A project card for lists, feeds, and profiles."""
    return ProjectSummaryResponse(
        id=project.id,
        project_code=project.code.value,
        name=project.name,
        intended_use=project.intended_use,
        location_label=project.location_label,
        latitude=project.location.latitude,
        longitude=project.location.longitude,
        progress_pct=project.progress_pct.as_float(),
        macro_stage=project.macro_stage,
        status=project.status,
        visibility=project.visibility,
        deadline_date=project.deadline_date,
        last_capture_at=project.last_capture_at,
        map_url=project.location.to_maps_url(),
    )


def present_folder(
    folder: ProjectFolder,
    *,
    now: datetime,
    member_users: dict[str, User] | None = None,
    asset_urls: dict[str, str] | None = None,
) -> ProjectFolderResponse:
    """Render the authenticated project folder page.

    Args:
        folder: The assembled folder.
        now: Current moment, for the expected-progress figure.
        member_users: ``{str(user_id): User}`` so collaborators show names
            rather than bare ids.
        asset_urls: ``{str(asset_id): url}`` for downloadable assets.

    Returns:
        The complete folder payload, including this caller's permissions.
    """
    project = folder.project
    users = member_users or {}
    urls = asset_urls or {}

    return ProjectFolderResponse(
        id=project.id,
        project_code=project.code.value,
        name=project.name,
        intended_use=project.intended_use,
        description=project.description,
        location_label=project.location_label,
        latitude=project.location.latitude,
        longitude=project.location.longitude,
        map_url=project.location.to_maps_url(),
        osm_url=project.location.to_osm_url(),
        start_date=project.start_date,
        deadline_date=project.deadline_date,
        days_remaining=(project.deadline_date - now.date()).days,
        worker_count=project.worker_count,
        timezone=project.timezone,
        visibility=project.visibility,
        status=project.status,
        status_reason=folder.status_reason,
        approval_state=project.approval_state,
        progress_pct=project.progress_pct.as_float(),
        expected_pct=project.expected_pct_at(now.date()).as_float(),
        macro_stage=project.macro_stage,
        stages=_stages(project),
        owner=next(
            (
                present_member(member, users.get(str(member.user_id)))
                for member in folder.members
                if member.is_owner
            ),
            None,
        ),
        members=[
            present_member(member, users.get(str(member.user_id))) for member in folder.members
        ],
        devices=[present_device(device) for device in folder.devices],
        recent_images=[_image(image) for image in folder.recent_images],
        remarks=[present_remark(remark) for remark in folder.remarks],
        assets=[present_asset(asset, urls.get(str(asset.id))) for asset in folder.assets],
        timeline=_timeline(folder.timeline),
        last_capture_at=project.last_capture_at,
        completed_at=project.completed_at,
        approved_at=project.approved_at,
        inspection_notes=project.inspection_notes,
        permissions=folder.access.to_payload() if folder.access else {},
    )


def present_public_project(folder: ProjectFolder) -> PublicProjectResponse:
    """Render the anonymous view of a project.

    A distinct response model, not a filtered copy of the authenticated one.
    Members, devices, assets, worker counts, and inspection notes are absent by
    construction rather than by omission — so a field added to the internal
    model later cannot leak here.

    The handler's name is shown only if *their* profile is public; a public
    project owned by a private-profile user still appears, with the owner as
    plain text rather than a link.
    """
    project = folder.project
    owner = folder.owner
    owner_is_public = bool(owner and owner.is_public)

    return PublicProjectResponse(
        project_code=project.code.value,
        name=project.name,
        intended_use=project.intended_use,
        description=project.description,
        location_label=project.location_label,
        latitude=project.location.latitude,
        longitude=project.location.longitude,
        map_url=project.location.to_maps_url(),
        osm_url=project.location.to_osm_url(),
        start_date=project.start_date,
        deadline_date=project.deadline_date,
        status=project.status,
        status_reason=folder.status_reason,
        progress_pct=project.progress_pct.as_float(),
        macro_stage=project.macro_stage,
        stages=_stages(project),
        handler_username=owner.username if owner else None,
        handler_name=owner.full_name if (owner is not None and owner_is_public) else None,
        handler_is_public=owner_is_public,
        # Only remarks and captures; the folder was already assembled with
        # `public_only=True`, so nothing private reached this point either.
        recent_images=[_image(image) for image in folder.recent_images],
        remarks=[present_remark(remark) for remark in folder.remarks],
        timeline=_timeline(folder.timeline),
        last_capture_at=project.last_capture_at,
    )


def map_url_for(latitude: float, longitude: float) -> str:
    """Map link for a bare coordinate pair."""
    return GeoPoint(latitude=latitude, longitude=longitude).to_maps_url()
