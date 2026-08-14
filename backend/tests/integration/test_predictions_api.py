"""The Module 09 HTTP surface: image detail, history, progress, models, /predict.

The aggregation arithmetic is proved in ``ai/tests/test_aggregator.py`` and its
persistence in ``test_progress_recompute.py``. What is proved here is the part
only a live application shows: that these endpoints return what the contract
says, that authority is enforced at the right level, and — the assertions worth
the most — that they **degrade honestly when no worker is running**, which is
the state the system is in for most of its development.
"""

from __future__ import annotations

import itertools
from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING, Any
from uuid import uuid4

import pytest

from app.application.ports.inference_gateway import (
    AdHocBox,
    AdHocDetection,
    AdHocPrediction,
    AdHocQuality,
    WorkerModelInfo,
    WorkerStatus,
)
from app.core.config import Settings, get_settings
from app.core.security import issue_access_token
from app.domain.entities import (
    AIModel,
    Detection,
    DetectionSummary,
    Device,
    Image,
    Prediction,
    Project,
    ProjectMember,
    User,
)
from app.domain.entities.image import BoundingBox
from app.domain.enums import (
    CameraFace,
    ImageSource,
    ImageStatus,
    MacroStage,
    MembershipRole,
    MembershipStatus,
    ModelKind,
    ProfessionalRole,
    Visibility,
)
from app.domain.value_objects import Confidence, GeoPoint, ProgressPct, ProjectCode
from app.infrastructure.repositories import (
    SqlAlchemyAIModelRepository,
    SqlAlchemyDetectionRepository,
    SqlAlchemyDeviceRepository,
    SqlAlchemyImageRepository,
    SqlAlchemyPredictionRepository,
    SqlAlchemyProjectMemberRepository,
    SqlAlchemyProjectRepository,
    SqlAlchemyUserRepository,
)

if TYPE_CHECKING:
    from fastapi import FastAPI
    from httpx import AsyncClient
    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration

API = "/api/v1"

#: Project codes are globally unique and device names are *derived* from them
#: (`ESP_<CODE>_<FACE>`, enforced by a check constraint), so a random two-digit
#: code would occasionally collide when a test builds two sites. A counter makes
#: it deterministic instead.
_CODES = itertools.count()
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 512
NOT_AN_IMAGE = b"this is plain text, not a photograph"


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


class Site:
    """A project with one camera, one scored image, and its owner logged in."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind repositories to the test session."""
        self.session = session
        self.projects = SqlAlchemyProjectRepository(session)
        self.images = SqlAlchemyImageRepository(session)
        self.predictions = SqlAlchemyPredictionRepository(session)
        self.detections = SqlAlchemyDetectionRepository(session)
        self.members = SqlAlchemyProjectMemberRepository(session)
        self.owner: User
        self.project: Project
        self.device: Device
        self.image: Image
        self.model_id = uuid4()

    async def setup(self) -> Site:
        """Create everything an endpoint test needs."""
        users = SqlAlchemyUserRepository(self.session)
        self.owner = await users.add(
            User(
                id=uuid4(),
                username=f"own_{uuid4().hex[:8]}",
                email=f"own_{uuid4().hex[:8]}@gvmail.com",
                full_name="Site Owner",
                professional_role=ProfessionalRole.ENGINEER,
            ),
            password_hash="x",
        )
        self.project = await self.projects.add(
            Project(
                id=uuid4(),
                owner_id=self.owner.id,
                name="Prediction Site",
                code=ProjectCode(f"PR_{next(_CODES) % 100:02d}"),
                location_label="Naga City",
                location=GeoPoint(13.6218, 123.1948),
                start_date=date(2026, 1, 1),
                deadline_date=date(2026, 12, 31),
                visibility=Visibility.PRIVATE,
            )
        )
        self.device = await SqlAlchemyDeviceRepository(self.session).add(
            Device(
                id=uuid4(),
                project_id=self.project.id,
                device_name=Device.build_name(self.project.code, CameraFace.FRONT_DIAGONAL),
                face=CameraFace.FRONT_DIAGONAL,
                weight=1.0,
            ),
            secret_encrypted="unused",
        )
        # The registry allows exactly one active model per kind, system-wide —
        # a model is not a property of a project. A second site in the same test
        # therefore joins the existing classifier rather than registering a
        # rival one, which is also what really happens in production.
        models = SqlAlchemyAIModelRepository(self.session)
        active = await models.get_active(ModelKind.CLASSIFIER)
        if active is None:
            active = await models.add(
                AIModel(
                    id=self.model_id,
                    name="stub-classifier",
                    kind=ModelKind.CLASSIFIER,
                    architecture="stub",
                    version="stub-v1",
                    class_names=("walls",),
                    input_size=224,
                    is_active=True,
                )
            )
        self.model_id = active.id
        await self.members.add(
            ProjectMember(
                id=uuid4(),
                project_id=self.project.id,
                user_id=self.owner.id,
                membership_role=MembershipRole.OWNER,
                membership_status=MembershipStatus.ACCEPTED,
            )
        )
        self.image = await self.add_image(status=ImageStatus.INFERRED, with_prediction=True)
        return self

    async def add_image(
        self,
        *,
        status: ImageStatus = ImageStatus.INFERRED,
        with_prediction: bool = True,
        captured_at: datetime | None = None,
        confidence: float = 0.94,
    ) -> Image:
        """Store one image, optionally with a prediction and detections."""
        image = await self.images.add(
            Image(
                id=uuid4(),
                project_id=self.project.id,
                device_id=self.device.id,
                filename=f"{self.project.code.value}_{uuid4().hex[:8]}.jpg",
                storage_key=f"projects/{self.project.id}/{uuid4().hex}.jpg",
                captured_at=captured_at or datetime(2026, 8, 1, 4, 0, tzinfo=UTC),
                sha256=uuid4().hex * 2,
                source=ImageSource.DEVICE,
                status=status,
                seq_number=1,
                location=GeoPoint(13.6218, 123.1948),
            )
        )
        if with_prediction:
            await self.predictions.add(
                Prediction(
                    id=uuid4(),
                    image_id=image.id,
                    model_id=self.model_id,
                    fine_class_index=6,
                    fine_class="walls",
                    confidence=Confidence.from_float(confidence),
                    macro_stage=MacroStage.FRAMING,
                    raw_progress_pct=ProgressPct.from_float(40.0),
                    class_probabilities={"walls": confidence, "slab": 1 - confidence},
                    inference_ms=180,
                )
            )
            await self.detections.add(
                Detection(
                    id=uuid4(),
                    image_id=image.id,
                    model_id=self.model_id,
                    class_name="wall",
                    confidence=Confidence.from_float(0.88),
                    bbox=BoundingBox(x=0.1, y=0.2, width=0.3, height=0.4),
                )
            )
            await self.detections.add_summary(
                DetectionSummary(
                    id=uuid4(),
                    image_id=image.id,
                    counts={"wall": 1},
                    total_objects=1,
                    inference_ms=40,
                )
            )
        return image

    async def add_member(self, role: MembershipRole) -> User:
        """Add an accepted collaborator with *role* and return them."""
        user = await SqlAlchemyUserRepository(self.session).add(
            User(
                id=uuid4(),
                username=f"mem_{uuid4().hex[:8]}",
                email=f"mem_{uuid4().hex[:8]}@gvmail.com",
                full_name="Collaborator",
                professional_role=ProfessionalRole.ENGINEER,
            ),
            password_hash="x",
        )
        await self.members.add(
            ProjectMember(
                id=uuid4(),
                project_id=self.project.id,
                user_id=user.id,
                membership_role=role,
                membership_status=MembershipStatus.ACCEPTED,
            )
        )
        return user


@pytest.fixture
async def site(session: AsyncSession) -> Site:
    """A project with one scored image."""
    return await Site(session).setup()


def _settings_of(app: FastAPI) -> Settings:
    """The settings this app was built with.

    ``create_app`` registers them as a ``get_settings`` override rather than
    stashing them on ``app.state``, so this is where the test's settings — test
    database, no broker, cheap Argon2 — actually live.
    """
    return app.dependency_overrides[get_settings]()


def _token(app: FastAPI, user: User) -> dict[str, str]:
    """Mint an access token for *user*, bypassing the login round trip.

    Registering and logging in through HTTP would work, but it costs two extra
    requests and an Argon2 hash per test for something none of these tests are
    about.
    """
    access, _ = issue_access_token(user.id, _settings_of(app))
    return {"Authorization": f"Bearer {access}"}


class FakeGateway:
    """A worker that is always up, for the paths that need one."""

    def __init__(self, *, prediction: AdHocPrediction | None = None) -> None:
        """Bind the canned reply."""
        self.calls = 0
        self._prediction = prediction or _stub_prediction()

    async def predict(
        self, image_bytes: bytes, *, timeout_s: float | None = None
    ) -> AdHocPrediction:
        """Return the canned prediction."""
        _ = image_bytes, timeout_s
        self.calls += 1
        return self._prediction

    async def status(self, *, timeout_s: float | None = None) -> WorkerStatus:
        """Report a loaded stub classifier."""
        _ = timeout_s
        return WorkerStatus(
            classifier=WorkerModelInfo(
                name="stub-classifier",
                architecture="stub",
                version="stub-v1",
                class_names=("walls",),
                input_size=224,
                is_stub=True,
                preprocessing_fingerprint="abc123",
            ),
            detector=None,
            preprocessing_fingerprint="abc123",
            loaded_at="2026-08-14T12:00:00Z",
            mean_latency_ms=181.5,
            images_processed=4,
        )

    async def queue_depth(self) -> dict[str, int]:
        """A quiet broker."""
        return {"ingest": 0, "inference": 2, "interactive": 0}


def _stub_prediction(*, rejected: bool = False) -> AdHocPrediction:
    """One canned ad-hoc result."""
    if rejected:
        return AdHocPrediction(
            rejected=True,
            quality=AdHocQuality(passed=False, flags=("blurred",), blur_score=8.2),
            rejection_reason="blurred",
            model_name="stub-classifier",
            model_version="stub-v1",
        )
    return AdHocPrediction(
        rejected=False,
        quality=AdHocQuality(passed=True, blur_score=142.0, brightness=0.51),
        stage="walls",
        class_index=6,
        confidence=0.94,
        macro_stage="roofing",
        progress_pct=40.0,
        probabilities={"walls": 0.94},
        detections=(
            AdHocDetection(
                class_name="wall",
                confidence=0.88,
                bbox=AdHocBox(x=0.1, y=0.2, width=0.3, height=0.4),
            ),
        ),
        counts={"wall": 1},
        inference_ms=180,
        total_ms=268,
        model_name="stub-classifier",
        model_version="stub-v1",
        model_is_stub=True,
    )


def _use_gateway(app: FastAPI, gateway: object) -> None:
    """Point the app's inference gateway at *gateway*."""
    from app.api.deps import get_gateway

    app.dependency_overrides[get_gateway] = lambda: gateway


# ---------------------------------------------------------------------------
# image detail
# ---------------------------------------------------------------------------


class TestImageDetail:
    """One capture with its prediction and detections."""

    async def test_returns_prediction_and_detections(
        self, client: AsyncClient, app: FastAPI, site: Site
    ) -> None:
        response = await client.get(
            f"{API}/projects/{site.project.id}/images/{site.image.id}",
            headers=_token(app, site.owner),
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["prediction"]["stage"] == "walls"
        assert body["prediction"]["confidence"] == pytest.approx(0.94)
        assert body["prediction"]["is_eligible"] is True
        assert body["detections"][0]["class_name"] == "wall"
        assert body["detections"][0]["bbox"]["width"] == pytest.approx(0.3)
        assert body["counts"] == {"wall": 1}
        assert body["map_url"].startswith("http")

    async def test_image_from_another_project_is_not_found(
        self, client: AsyncClient, app: FastAPI, site: Site, session: AsyncSession
    ) -> None:
        """404, never 403 — the error must not confirm the image exists."""
        other = await Site(session).setup()
        response = await client.get(
            f"{API}/projects/{site.project.id}/images/{other.image.id}",
            headers=_token(app, site.owner),
        )
        assert response.status_code == 404

    async def test_non_member_cannot_read(
        self, client: AsyncClient, app: FastAPI, site: Site, session: AsyncSession
    ) -> None:
        stranger = await SqlAlchemyUserRepository(session).add(
            User(
                id=uuid4(),
                username=f"str_{uuid4().hex[:8]}",
                email=f"str_{uuid4().hex[:8]}@gvmail.com",
                full_name="Stranger",
                professional_role=ProfessionalRole.OTHER,
            ),
            password_hash="x",
        )
        response = await client.get(
            f"{API}/projects/{site.project.id}/images/{site.image.id}",
            headers=_token(app, stranger),
        )
        assert response.status_code == 404


class TestImagePrediction:
    """The prediction on its own."""

    async def test_returns_the_stored_prediction(
        self, client: AsyncClient, app: FastAPI, site: Site
    ) -> None:
        response = await client.get(
            f"{API}/projects/{site.project.id}/images/{site.image.id}/prediction",
            headers=_token(app, site.owner),
        )
        assert response.status_code == 200, response.text
        assert response.json()["macro_stage"] == MacroStage.FRAMING.value

    async def test_pending_image_has_no_prediction(
        self, client: AsyncClient, app: FastAPI, site: Site
    ) -> None:
        """404 rather than an empty prediction: 'not yet' is not 'no stage'."""
        pending = await site.add_image(status=ImageStatus.PENDING, with_prediction=False)
        response = await client.get(
            f"{API}/projects/{site.project.id}/images/{pending.id}/prediction",
            headers=_token(app, site.owner),
        )
        assert response.status_code == 404
        assert response.json()["error"]["details"]["image_status"] == "pending"


# ---------------------------------------------------------------------------
# history
# ---------------------------------------------------------------------------


class TestHistory:
    """Captures joined to their verdicts."""

    async def test_includes_captures_without_predictions(
        self, client: AsyncClient, app: FastAPI, site: Site
    ) -> None:
        """A rejected frame stays in the history — the rejection rate is data."""
        await site.add_image(status=ImageStatus.REJECTED, with_prediction=False)
        response = await client.get(
            f"{API}/projects/{site.project.id}/history",
            headers=_token(app, site.owner),
        )
        assert response.status_code == 200, response.text
        items = response.json()["items"]
        assert len(items) == 2
        by_status = {item["status"]: item for item in items}
        assert by_status["inferred"]["stage"] == "walls"
        assert by_status["rejected"]["stage"] is None

    async def test_filters_by_status(self, client: AsyncClient, app: FastAPI, site: Site) -> None:
        await site.add_image(status=ImageStatus.REJECTED, with_prediction=False)
        response = await client.get(
            f"{API}/projects/{site.project.id}/history?status=rejected",
            headers=_token(app, site.owner),
        )
        assert response.status_code == 200, response.text
        items = response.json()["items"]
        assert [item["status"] for item in items] == ["rejected"]

    async def test_paginates_with_a_cursor(
        self, client: AsyncClient, app: FastAPI, site: Site
    ) -> None:
        base = datetime(2026, 8, 2, 4, 0, tzinfo=UTC)
        for offset in range(3):
            await site.add_image(captured_at=base + timedelta(hours=offset))

        first = await client.get(
            f"{API}/projects/{site.project.id}/history?limit=2",
            headers=_token(app, site.owner),
        )
        assert first.status_code == 200, first.text
        page = first.json()
        assert len(page["items"]) == 2
        assert page["has_more"] is True

        second = await client.get(
            f"{API}/projects/{site.project.id}/history?limit=2&cursor={page['next_cursor']}",
            headers=_token(app, site.owner),
        )
        assert second.status_code == 200
        seen = {item["image_id"] for item in page["items"]}
        assert not seen & {item["image_id"] for item in second.json()["items"]}


# ---------------------------------------------------------------------------
# reprocess
# ---------------------------------------------------------------------------


class TestReprocess:
    """Re-running the AI over a stored image."""

    async def test_clears_the_old_prediction_and_requeues(
        self, client: AsyncClient, app: FastAPI, site: Site
    ) -> None:
        """The old row must go: two predictions would both vote in aggregation."""
        response = await client.post(
            f"{API}/projects/{site.project.id}/images/{site.image.id}/reprocess",
            headers=_token(app, site.owner),
        )
        assert response.status_code == 202, response.text
        body = response.json()
        assert body["status"] == ImageStatus.PENDING.value
        assert body["prediction"] is None
        assert body["detections"] == []
        assert await site.predictions.get_for_image(site.image.id) is None

    async def test_pending_image_is_a_conflict(
        self, client: AsyncClient, app: FastAPI, site: Site
    ) -> None:
        pending = await site.add_image(status=ImageStatus.PENDING, with_prediction=False)
        response = await client.post(
            f"{API}/projects/{site.project.id}/images/{pending.id}/reprocess",
            headers=_token(app, site.owner),
        )
        assert response.status_code == 409

    async def test_editor_is_not_allowed(
        self, client: AsyncClient, app: FastAPI, site: Site
    ) -> None:
        """Reprocessing rewrites the headline number, so it sits at manager+."""
        editor = await site.add_member(MembershipRole.EDITOR)
        response = await client.post(
            f"{API}/projects/{site.project.id}/images/{site.image.id}/reprocess",
            headers=_token(app, editor),
        )
        assert response.status_code == 403

    async def test_manager_is_allowed(self, client: AsyncClient, app: FastAPI, site: Site) -> None:
        manager = await site.add_member(MembershipRole.MANAGER)
        response = await client.post(
            f"{API}/projects/{site.project.id}/images/{site.image.id}/reprocess",
            headers=_token(app, manager),
        )
        assert response.status_code == 202, response.text


# ---------------------------------------------------------------------------
# progress
# ---------------------------------------------------------------------------


class TestProgress:
    """Reading the stored progress figure."""

    async def test_no_snapshot_reports_has_data_false(
        self, client: AsyncClient, app: FastAPI, site: Site
    ) -> None:
        """0 % with no data must be distinguishable from a measured 0 %."""
        response = await client.get(
            f"{API}/projects/{site.project.id}/progress",
            headers=_token(app, site.owner),
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["has_data"] is False
        assert body["displayed_pct"] == pytest.approx(0.0)
        assert set(body["stages"]) == {
            "foundation_pct",
            "framing_pct",
            "roofing_pct",
            "finishing_pct",
            "approval_pct",
        }

    async def test_reports_the_stored_snapshot(
        self, client: AsyncClient, app: FastAPI, site: Site, session: AsyncSession
    ) -> None:
        from app.domain.entities import ProgressSnapshot
        from app.infrastructure.repositories import SqlAlchemySnapshotRepository

        await SqlAlchemySnapshotRepository(session).upsert(
            ProgressSnapshot(
                id=uuid4(),
                project_id=site.project.id,
                window_start=datetime(2026, 8, 1, tzinfo=UTC),
                window_end=datetime(2026, 8, 2, tzinfo=UTC),
                raw_pct=ProgressPct.from_float(40.0),
                ema_pct=ProgressPct.from_float(38.0),
                displayed_pct=ProgressPct.from_float(38.5),
                macro_stage=MacroStage.FRAMING,
                roofing_pct=92.5,
                eligible_image_count=3,
                device_weights={"ESP_PR_00_FD": 1.0},
            )
        )
        response = await client.get(
            f"{API}/projects/{site.project.id}/progress",
            headers=_token(app, site.owner),
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["has_data"] is True
        assert body["displayed_pct"] == pytest.approx(38.5)
        assert body["stages"]["roofing_pct"] == pytest.approx(92.5)
        assert body["devices_reporting"] == 1
        assert body["algorithm_version"] == "progress-v1"


class TestRecompute:
    """Asking for the timeline to be rebuilt."""

    async def test_manager_can_queue_a_recompute(
        self, client: AsyncClient, app: FastAPI, site: Site
    ) -> None:
        response = await client.post(
            f"{API}/projects/{site.project.id}/recompute",
            headers=_token(app, site.owner),
        )
        assert response.status_code == 202, response.text
        assert response.json()["status"] == "queued"

    async def test_editor_cannot(self, client: AsyncClient, app: FastAPI, site: Site) -> None:
        editor = await site.add_member(MembershipRole.EDITOR)
        response = await client.post(
            f"{API}/projects/{site.project.id}/recompute",
            headers=_token(app, editor),
        )
        assert response.status_code == 403


# ---------------------------------------------------------------------------
# /predict and /model/status
# ---------------------------------------------------------------------------


class TestAdHocPredict:
    """The stateless demo endpoint."""

    async def test_returns_the_stage_and_marks_it_unpersisted(
        self, client: AsyncClient, app: FastAPI, site: Site
    ) -> None:
        _use_gateway(app, FakeGateway())
        response = await client.post(
            f"{API}/predict",
            headers=_token(app, site.owner),
            files={"file": ("capture.jpg", JPEG, "image/jpeg")},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["stage"] == "walls"
        assert body["progress"] == pytest.approx(40.0)
        assert body["persisted"] is False
        assert body["model_is_stub"] is True
        assert body["detections"][0]["class_name"] == "wall"

    async def test_a_rejected_frame_is_a_200_not_an_error(
        self, client: AsyncClient, app: FastAPI, site: Site
    ) -> None:
        """The gate firing is the answer, not a failure to answer."""
        _use_gateway(app, FakeGateway(prediction=_stub_prediction(rejected=True)))
        response = await client.post(
            f"{API}/predict",
            headers=_token(app, site.owner),
            files={"file": ("blurry.jpg", JPEG, "image/jpeg")},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["rejected"] is True
        assert body["stage"] is None
        assert body["rejection_reason"] == "blurred"

    async def test_non_image_is_refused_before_the_broker(
        self, client: AsyncClient, app: FastAPI, site: Site
    ) -> None:
        """Checked by magic number, so a mislabelled content type cannot pass."""
        gateway = FakeGateway()
        _use_gateway(app, gateway)
        response = await client.post(
            f"{API}/predict",
            headers=_token(app, site.owner),
            files={"file": ("notes.jpg", NOT_AN_IMAGE, "image/jpeg")},
        )
        assert response.status_code == 400
        assert gateway.calls == 0

    async def test_oversized_upload_is_refused(
        self, client: AsyncClient, app: FastAPI, site: Site
    ) -> None:
        gateway = FakeGateway()
        _use_gateway(app, gateway)
        limit = _settings_of(app).max_image_upload_bytes
        oversized = JPEG + b"\x00" * (limit + 1)
        response = await client.post(
            f"{API}/predict",
            headers=_token(app, site.owner),
            files={"file": ("huge.jpg", oversized, "image/jpeg")},
        )
        assert response.status_code == 413
        assert gateway.calls == 0

    async def test_requires_authentication(self, client: AsyncClient, app: FastAPI) -> None:
        _use_gateway(app, FakeGateway())
        response = await client.post(
            f"{API}/predict", files={"file": ("capture.jpg", JPEG, "image/jpeg")}
        )
        assert response.status_code == 401

    async def test_no_worker_yields_503(
        self, client: AsyncClient, app: FastAPI, site: Site
    ) -> None:
        """The default in tests: no broker configured, so no worker to ask."""
        response = await client.post(
            f"{API}/predict",
            headers=_token(app, site.owner),
            files={"file": ("capture.jpg", JPEG, "image/jpeg")},
        )
        assert response.status_code == 503


class TestModelStatus:
    """Registry reconciled with a live worker probe."""

    async def test_reports_registry_when_no_worker_answers(
        self, client: AsyncClient, app: FastAPI, site: Site
    ) -> None:
        """Must not fail when the worker is down — that is when it is needed."""
        response = await client.get(f"{API}/model/status", headers=_token(app, site.owner))
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["worker_reachable"] is False
        assert body["classifier"]["name"] == "stub-classifier"
        assert body["live_classifier"] is None
        assert body["using_stubs"] is True

    async def test_reports_live_worker_facts(
        self, client: AsyncClient, app: FastAPI, site: Site
    ) -> None:
        _use_gateway(app, FakeGateway())
        response = await client.get(f"{API}/model/status", headers=_token(app, site.owner))
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["worker_reachable"] is True
        assert body["live_classifier"]["device"] == "cpu"
        assert body["mean_latency_ms"] == pytest.approx(181.5)
        assert body["queue_depth"]["inference"] == 2
        # Fingerprints agree in the fake, so the pipeline is the trained one.
        assert body["preprocessing_matches"] is True

    async def test_lists_registered_models(
        self, client: AsyncClient, app: FastAPI, site: Site
    ) -> None:
        response = await client.get(f"{API}/models", headers=_token(app, site.owner))
        assert response.status_code == 200, response.text
        models: list[dict[str, Any]] = response.json()["models"]
        assert any(model["architecture"] == "stub" and model["is_stub"] for model in models)
