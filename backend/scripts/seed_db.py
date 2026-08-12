"""Populate the development database with realistic data.

Modules 11 and 12 are built against this seed, so it has to look like a real
system rather than three rows called "test". It creates:

* 3 users — one public profile, one private (spec B.5), one collaborator
* 4 projects covering every interesting state: an active public build, a
  delayed one, a completed one, and a private one
* 2 paired cameras on the flagship project
* ~40 images with predictions across 30 days
* a progress snapshot series that renders as a believable timeline curve

Idempotent: re-running wipes the seeded rows and recreates them, so you can
iterate on it without a migration reset.

    uv run python -m scripts.seed_db
    uv run python -m scripts.seed_db --wipe-only
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import random
import sys
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from sqlalchemy import delete

from app.domain.enums import (
    ApprovalState,
    CameraFace,
    DeviceStatus,
    ImageSource,
    ImageStatus,
    MacroStage,
    MembershipRole,
    MembershipStatus,
    ModelKind,
    ProfessionalRole,
    ProjectStatus,
    RemarkType,
    Severity,
    Visibility,
)
from app.infrastructure.db import models
from app.infrastructure.db.session import dispose_engine, get_session_factory

#: Fixed so a re-seed produces the same data - screenshots stay comparable.
SEED = 42

#: Deterministic ids, so seeded rows can be found and wiped without guessing.
USER_ALICE = UUID("11111111-1111-4111-8111-111111111111")
USER_BRUNO = UUID("22222222-2222-4222-8222-222222222222")
USER_CARLA = UUID("33333333-3333-4333-8333-333333333333")
PROJECT_JOLLI = UUID("aaaaaaaa-0000-4000-8000-000000000001")
PROJECT_DELAYED = UUID("aaaaaaaa-0000-4000-8000-000000000002")
PROJECT_DONE = UUID("aaaaaaaa-0000-4000-8000-000000000003")
PROJECT_PRIVATE = UUID("aaaaaaaa-0000-4000-8000-000000000004")
MODEL_STUB = UUID("bbbbbbbb-0000-4000-8000-000000000001")

SEEDED_USER_IDS = (USER_ALICE, USER_BRUNO, USER_CARLA)
SEEDED_PROJECT_IDS = (PROJECT_JOLLI, PROJECT_DELAYED, PROJECT_DONE, PROJECT_PRIVATE)

#: Argon2 hash of "geovision-dev" - development only, never a real credential.
DEV_PASSWORD_HASH = (
    "$argon2id$v=19$m=65536,t=3,p=4$c2VlZHNlZWRzZWVkc2VlZA$"
    "0000000000000000000000000000000000000000000"
)

FINE_CLASSES = (
    ("site_clearing", 0, MacroStage.FOUNDATION, Decimal("4")),
    ("excavation", 1, MacroStage.FOUNDATION, Decimal("9")),
    ("footings", 2, MacroStage.FOUNDATION, Decimal("14")),
    ("foundation", 3, MacroStage.FOUNDATION, Decimal("20")),
    ("columns", 4, MacroStage.FRAMING, Decimal("28")),
    ("slab", 5, MacroStage.FRAMING, Decimal("34")),
    ("walls", 6, MacroStage.FRAMING, Decimal("40")),
    ("roof", 7, MacroStage.ROOFING, Decimal("60")),
    ("finishing", 8, MacroStage.FINISHING, Decimal("80")),
    ("completed", 9, MacroStage.APPROVAL, Decimal("80")),
)


def _sha(text: str) -> str:
    """Deterministic stand-in for a real image content hash."""
    return hashlib.sha256(text.encode()).hexdigest()


async def wipe() -> None:
    """Remove every seeded row.

    Deleting the users and projects is enough: ON DELETE CASCADE takes the
    devices, images, predictions, snapshots and remarks with them.
    """
    factory = get_session_factory()
    async with factory() as session:
        await session.execute(
            delete(models.ProjectModel).where(models.ProjectModel.id.in_(SEEDED_PROJECT_IDS))
        )
        await session.execute(
            delete(models.UserModel).where(models.UserModel.id.in_(SEEDED_USER_IDS))
        )
        await session.execute(
            delete(models.AIModelModel).where(models.AIModelModel.id == MODEL_STUB)
        )
        await session.commit()
    print("wiped seeded rows")


async def seed() -> None:
    """Create the development dataset."""
    random.seed(SEED)
    factory = get_session_factory()
    today = datetime.now(UTC)

    async with factory() as session:
        # -- users ---------------------------------------------------------
        alice = models.UserModel(
            id=USER_ALICE,
            username="alice_eng",
            email="alice@geovision.test",
            password_hash=DEV_PASSWORD_HASH,
            full_name="Alice Reyes",
            professional_role=ProfessionalRole.ENGINEER,
            profile_visibility=Visibility.PUBLIC,
            company="Reyes Construction",
            bio="Site engineer. Monitoring three builds in Naga City.",
        )
        bruno = models.UserModel(
            id=USER_BRUNO,
            username="bruno_pm",
            email="bruno@geovision.test",
            password_hash=DEV_PASSWORD_HASH,
            full_name="Bruno Santos",
            professional_role=ProfessionalRole.MANAGER,
            # Private profile: searchable by username, but nothing else shown.
            profile_visibility=Visibility.PRIVATE,
            company="Santos Builders",
        )
        carla = models.UserModel(
            id=USER_CARLA,
            username="carla_owner",
            email="carla@geovision.test",
            password_hash=DEV_PASSWORD_HASH,
            full_name="Carla Dela Cruz",
            professional_role=ProfessionalRole.HOME_OWNER,
            profile_visibility=Visibility.PUBLIC,
        )
        session.add_all([alice, bruno, carla])
        await session.flush()

        # -- model registry (stub until Module 07 trains a real one) -------
        session.add(
            models.AIModelModel(
                id=MODEL_STUB,
                name="stub-classifier",
                kind=ModelKind.CLASSIFIER,
                architecture="stub",
                version="0.0.1",
                framework="pytorch",
                weights_key=None,
                class_names=[name for name, *_ in FINE_CLASSES],
                input_size=224,
                metrics={},
                is_active=True,
                trained_at=today,
            )
        )
        await session.flush()

        # -- projects ------------------------------------------------------
        projects = [
            models.ProjectModel(
                id=PROJECT_JOLLI,
                owner_id=USER_ALICE,
                name="Jollibee Branch - Naga",
                project_code="NG_00",
                intended_use="Fast-food restaurant",
                description="Two-storey commercial build with drive-through.",
                location_label="Panganiban Dr, Naga City, Camarines Sur",
                latitude=Decimal("13.621800"),
                longitude=Decimal("123.194800"),
                start_date=date(2026, 5, 1),
                deadline_date=date(2026, 11, 30),
                worker_count=24,
                visibility=Visibility.PUBLIC,
                status=ProjectStatus.ACTIVE,
                progress_pct=Decimal("38.50"),
                macro_stage=MacroStage.FRAMING,
                last_capture_at=today - timedelta(hours=3),
            ),
            models.ProjectModel(
                id=PROJECT_DELAYED,
                owner_id=USER_ALICE,
                name="Barangay Health Center",
                project_code="BM_01",
                intended_use="Public health facility",
                location_label="Brgy. Concepcion Pequena, Naga City",
                latitude=Decimal("13.630500"),
                longitude=Decimal("123.185200"),
                start_date=date(2026, 2, 1),
                deadline_date=date(2026, 8, 1),
                worker_count=12,
                visibility=Visibility.PUBLIC,
                status=ProjectStatus.DELAYED,
                progress_pct=Decimal("31.00"),
                macro_stage=MacroStage.FRAMING,
                last_capture_at=today - timedelta(days=2),
            ),
            models.ProjectModel(
                id=PROJECT_DONE,
                owner_id=USER_CARLA,
                name="Dela Cruz Residence",
                project_code="DC_00",
                intended_use="Two-bedroom family home",
                location_label="Brgy. Pacol, Naga City",
                latitude=Decimal("13.650100"),
                longitude=Decimal("123.220400"),
                start_date=date(2025, 9, 1),
                deadline_date=date(2026, 6, 30),
                worker_count=8,
                visibility=Visibility.PUBLIC,
                status=ProjectStatus.COMPLETED,
                approval_state=ApprovalState.APPROVED,
                progress_pct=Decimal("100.00"),
                macro_stage=MacroStage.APPROVAL,
                completed_at=today - timedelta(days=20),
                approved_by=USER_CARLA,
                approved_at=today - timedelta(days=20),
                inspection_notes="Final walkthrough completed. All punch-list items closed.",
                last_capture_at=today - timedelta(days=21),
            ),
            models.ProjectModel(
                id=PROJECT_PRIVATE,
                owner_id=USER_BRUNO,
                name="Confidential Warehouse Expansion",
                project_code="WH_07",
                location_label="Del Rosario, Naga City",
                latitude=Decimal("13.645000"),
                longitude=Decimal("123.175000"),
                start_date=date(2026, 6, 1),
                deadline_date=date(2027, 3, 31),
                # Private: must never appear in the public feed or search.
                visibility=Visibility.PRIVATE,
                status=ProjectStatus.ACTIVE,
                progress_pct=Decimal("14.00"),
                macro_stage=MacroStage.FOUNDATION,
                last_capture_at=today - timedelta(hours=8),
            ),
        ]
        session.add_all(projects)
        await session.flush()

        # -- memberships ---------------------------------------------------
        memberships = [
            models.ProjectMemberModel(
                project_id=pid,
                user_id=owner,
                membership_role=MembershipRole.OWNER,
                membership_status=MembershipStatus.ACCEPTED,
                responded_at=today,
            )
            for pid, owner in (
                (PROJECT_JOLLI, USER_ALICE),
                (PROJECT_DELAYED, USER_ALICE),
                (PROJECT_DONE, USER_CARLA),
                (PROJECT_PRIVATE, USER_BRUNO),
            )
        ]
        # Collaboration (spec B.6): Bruno manages Alice's flagship project,
        # and Carla has a pending invitation to view it.
        memberships.append(
            models.ProjectMemberModel(
                project_id=PROJECT_JOLLI,
                user_id=USER_BRUNO,
                membership_role=MembershipRole.MANAGER,
                membership_status=MembershipStatus.ACCEPTED,
                invited_by=USER_ALICE,
                invited_at=today - timedelta(days=40),
                responded_at=today - timedelta(days=39),
            )
        )
        memberships.append(
            models.ProjectMemberModel(
                project_id=PROJECT_JOLLI,
                user_id=USER_CARLA,
                membership_role=MembershipRole.VIEWER,
                membership_status=MembershipStatus.PENDING,
                invited_by=USER_ALICE,
                invited_at=today - timedelta(days=2),
            )
        )
        session.add_all(memberships)
        await session.flush()

        # -- devices: two faces on the flagship project --------------------
        devices = [
            models.DeviceModel(
                project_id=PROJECT_JOLLI,
                device_name="ESP_NG_00_FD",
                face=CameraFace.FRONT_DIAGONAL,
                weight=Decimal("1.50"),
                secret_hash="dev-seed-not-a-real-secret",
                status=DeviceStatus.ONLINE,
                firmware_version="1.0.0",
                hardware_id="24:0A:C4:11:11:11",
                capture_schedule={"times": ["07:00", "16:00"], "timezone": "Asia/Manila"},
                last_seen_at=today - timedelta(hours=3),
                last_battery_mv=3980,
                last_rssi_dbm=-62,
                paired_at=today - timedelta(days=45),
            ),
            models.DeviceModel(
                project_id=PROJECT_JOLLI,
                device_name="ESP_NG_00_B",
                face=CameraFace.BACK,
                weight=Decimal("1.00"),
                secret_hash="dev-seed-not-a-real-secret",
                status=DeviceStatus.OFFLINE,
                firmware_version="1.0.0",
                hardware_id="24:0A:C4:22:22:22",
                capture_schedule={"times": ["07:00", "16:00"], "timezone": "Asia/Manila"},
                last_seen_at=today - timedelta(days=3),
                last_battery_mv=3410,
                last_rssi_dbm=-78,
                paired_at=today - timedelta(days=45),
            ),
        ]
        session.add_all(devices)
        await session.flush()

        # -- 30 days of images, predictions, and snapshots -----------------
        # A believable curve: progress climbs from Foundation to Framing with
        # some day-to-day noise, which is exactly what the aggregator exists
        # to smooth.
        ema = 20.0
        displayed = 20.0
        for day_offset in range(30, 0, -1):
            captured = today - timedelta(days=day_offset)
            target = 20.0 + (30 - day_offset) * 0.65
            raw = max(0.0, min(80.0, target + random.uniform(-3.0, 3.0)))
            ema = 0.3 * raw + 0.7 * ema
            displayed = max(displayed, ema)  # monotonic ratchet

            fine_name, fine_idx, macro, nominal = next(
                entry for entry in FINE_CLASSES if entry[3] >= Decimal(str(round(raw)))
            )

            for slot, device in enumerate(devices):
                image = models.ImageModel(
                    project_id=PROJECT_JOLLI,
                    device_id=device.id,
                    filename=(f"NG_00_{captured.strftime('%Y%m%dT%H%M%SZ')}_{slot + 1:03d}.jpg"),
                    storage_key=(
                        f"projects/{PROJECT_JOLLI}/images/"
                        f"{captured:%Y/%m/%d}/{device.face.value}/seed.jpg"
                    ),
                    thumb_key=f"projects/{PROJECT_JOLLI}/thumbs/seed-{day_offset}-{slot}.webp",
                    source=ImageSource.DEVICE,
                    status=ImageStatus.INFERRED,
                    captured_at=captured,
                    seq_number=slot + 1,
                    latitude=Decimal("13.621800"),
                    longitude=Decimal("123.194800"),
                    gps_accuracy_m=Decimal("4.50"),
                    satellites=9,
                    width=800,
                    height=600,
                    size_bytes=412_000,
                    sha256=_sha(f"{day_offset}-{slot}"),
                )
                session.add(image)
                await session.flush()

                confidence = Decimal(str(round(random.uniform(0.62, 0.97), 3)))
                session.add(
                    models.PredictionModel(
                        image_id=image.id,
                        model_id=MODEL_STUB,
                        fine_class_index=fine_idx,
                        fine_class=fine_name,
                        confidence=confidence,
                        macro_stage=macro,
                        raw_progress_pct=nominal,
                        is_eligible=True,
                        low_confidence=False,
                        class_probabilities={fine_name: float(confidence)},
                        inference_ms=random.randint(180, 320),
                    )
                )

            window_start = captured.replace(hour=0, minute=0, second=0, microsecond=0)
            session.add(
                models.ProgressSnapshotModel(
                    project_id=PROJECT_JOLLI,
                    window_start=window_start,
                    window_end=window_start + timedelta(days=1),
                    raw_pct=Decimal(str(round(raw, 2))),
                    ema_pct=Decimal(str(round(ema, 2))),
                    displayed_pct=Decimal(str(round(displayed, 2))),
                    macro_stage=macro,
                    foundation_pct=Decimal("100.00"),
                    framing_pct=Decimal(
                        str(round(min(max((displayed - 20) / 20 * 100, 0), 100), 2))
                    ),
                    eligible_image_count=len(devices),
                    device_weights={d.device_name: float(d.weight) for d in devices},
                    algorithm_version="progress-v1",
                )
            )

        # -- remarks -------------------------------------------------------
        session.add_all(
            [
                models.RemarkModel(
                    project_id=PROJECT_JOLLI,
                    author_id=USER_ALICE,
                    remark_type=RemarkType.MANUAL,
                    severity=Severity.INFO,
                    message="Second-floor slab pour scheduled for next week.",
                    is_public=True,
                ),
                models.RemarkModel(
                    project_id=PROJECT_DELAYED,
                    author_id=None,
                    remark_type=RemarkType.DELAY,
                    severity=Severity.WARNING,
                    message="Progress is 18 pp behind the expected schedule for the set deadline.",
                    is_public=True,
                ),
                models.RemarkModel(
                    project_id=PROJECT_DELAYED,
                    author_id=USER_ALICE,
                    remark_type=RemarkType.WEATHER,
                    severity=Severity.INFO,
                    message="Typhoon warning raised; work suspended for three days.",
                    is_public=True,
                    effective_from=date(2026, 7, 12),
                    effective_to=date(2026, 7, 15),
                ),
            ]
        )

        await session.commit()

    print("seeded:")
    print("  users     3  (alice_eng public, bruno_pm PRIVATE, carla_owner public)")
    print("  projects  4  (NG_00 active, BM_01 delayed, DC_00 completed, WH_07 PRIVATE)")
    print("  devices   2  (ESP_NG_00_FD online, ESP_NG_00_B offline)")
    print("  images   60  with predictions")
    print("  snapshots 30 days of timeline")
    print("\n  login: any username above / password 'geovision-dev' (after Module 03)")


async def main() -> int:
    """Entry point."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wipe-only", action="store_true", help="delete seed data and exit")
    args = parser.parse_args()

    try:
        await wipe()
        if not args.wipe_only:
            await seed()
    finally:
        await dispose_engine()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
