"""Pairing and ingest, end to end over HTTP.

This is the module's real test: an owner issues a code, a simulated camera
claims it, signs uploads with the returned secret, and the images land in the
right project under the right names. Everything below the API — HMAC, nonce
cache, advisory-locked sequence allocation, object storage — is exercised for
real rather than mocked, because the failure modes worth catching here are the
ones that only appear when those pieces meet.
"""

from __future__ import annotations

import hashlib
import hmac
import io
import json
import secrets
from datetime import UTC, datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any

import pytest
from PIL import Image as PILImage

from app.domain.enums import CameraFace, ProfessionalRole, Visibility

if TYPE_CHECKING:
    from httpx import AsyncClient

pytestmark = pytest.mark.integration

REGISTER = "/api/v1/auth/register"
PROJECTS = "/api/v1/projects"
CLAIM = "/api/v1/pair/claim"
INGEST = "/api/v1/ingest/images"
CONFIG = "/api/v1/ingest/config"
EVENTS = "/api/v1/ingest/events"


# ---------------------------------------------------------------------------
# Helpers — a minimal, independent client implementation of the protocol
# ---------------------------------------------------------------------------


def make_jpeg(*, size: tuple[int, int] = (640, 480), colour: str = "green") -> bytes:
    """Render a real JPEG.

    Generated rather than committed as a fixture because ingest decodes the
    bytes with Pillow to check dimensions — a hand-written byte string with the
    right magic number would fail that check, and padding one to look real is
    more code than drawing a rectangle.
    """
    buffer = io.BytesIO()
    PILImage.new("RGB", size, colour).save(buffer, format="JPEG", quality=85)
    return buffer.getvalue()


def make_noisy_jpeg(*, size: tuple[int, int] = (640, 480)) -> bytes:
    """Render a JPEG that does not compress away.

    Needed to test the *dimension* check independently of the minimum-size
    check: a flat colour at small dimensions lands under 1 KB and trips the
    truncation guard first.
    """
    buffer = io.BytesIO()
    pixels = bytes(secrets.randbelow(256) for _ in range(size[0] * size[1] * 3))
    PILImage.frombytes("RGB", size, pixels).save(buffer, format="JPEG", quality=95)
    return buffer.getvalue()


def sign(secret: str, *, method: str, path: str, timestamp: int, nonce: str, body: bytes) -> str:
    """Sign as the firmware does, using only the standard library."""
    canonical = "\n".join(
        [method.upper(), path, str(timestamp), nonce, hashlib.sha256(body).hexdigest()]
    )
    return hmac.new(secret.encode(), canonical.encode(), hashlib.sha256).hexdigest()


def multipart(image: bytes, meta: dict[str, Any]) -> tuple[bytes, str]:
    """Build the multipart body by hand.

    The signature covers the raw body bytes, so the bytes that are hashed must
    be exactly the bytes that are sent. Letting httpx re-encode the body after
    signing would make every request fail verification.
    """
    boundary = f"----test{secrets.token_hex(8)}"
    body = b"".join(
        [
            f"--{boundary}\r\n".encode(),
            b'Content-Disposition: form-data; name="meta"\r\n\r\n',
            json.dumps(meta).encode(),
            b"\r\n",
            f"--{boundary}\r\n".encode(),
            b'Content-Disposition: form-data; name="file"; filename="c.jpg"\r\n',
            b"Content-Type: image/jpeg\r\n\r\n",
            image,
            b"\r\n",
            f"--{boundary}--\r\n".encode(),
        ]
    )
    return body, f"multipart/form-data; boundary={boundary}"


class SimulatedCamera:
    """A paired device that can sign requests."""

    def __init__(self, client: AsyncClient, claim: dict[str, Any]) -> None:
        """Hold the credentials returned by the claim."""
        self._client = client
        self.device_id: str = claim["device_id"]
        self.secret: str = claim["device_secret"]
        self.project_code: str = claim["project_code"]

    def headers(
        self,
        *,
        method: str,
        path: str,
        body: bytes,
        secret: str | None = None,
        timestamp: int | None = None,
        nonce: str | None = None,
    ) -> dict[str, str]:
        """Build the four signature headers."""
        stamp = timestamp if timestamp is not None else int(datetime.now(UTC).timestamp())
        value = nonce or secrets.token_hex(8)
        return {
            "X-Device-Id": self.device_id,
            "X-Timestamp": str(stamp),
            "X-Nonce": value,
            "X-Signature": sign(
                secret or self.secret,
                method=method,
                path=path,
                timestamp=stamp,
                nonce=value,
                body=body,
            ),
        }

    async def upload(
        self,
        image: bytes | None = None,
        *,
        captured_at: datetime | None = None,
        secret: str | None = None,
        timestamp: int | None = None,
        nonce: str | None = None,
        sha_override: str | None = None,
        latitude: float = 13.6218,
        longitude: float = 123.1948,
    ) -> Any:
        """Sign and send one capture."""
        payload = image if image is not None else make_jpeg()
        meta = {
            "captured_at": (captured_at or datetime.now(UTC)).isoformat(),
            "sha256": sha_override or hashlib.sha256(payload).hexdigest(),
            "latitude": latitude,
            "longitude": longitude,
            "battery_mv": 3900,
            "rssi_dbm": -61,
        }
        body, content_type = multipart(payload, meta)
        headers = self.headers(
            method="POST",
            path=INGEST,
            body=body,
            secret=secret,
            timestamp=timestamp,
            nonce=nonce,
        )
        headers["Content-Type"] = content_type
        return await self._client.post(INGEST, content=body, headers=headers)


async def _account(client: AsyncClient, username: str) -> dict[str, Any]:
    """Register an owner."""
    response = await client.post(
        REGISTER,
        json={
            "username": username,
            "email": f"{username}@gvmail.com",
            "password": "correct-horse-1",
            "full_name": f"{username.title()} Tester",
            "professional_role": ProfessionalRole.ENGINEER.value,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _auth(session: dict[str, Any]) -> dict[str, str]:
    """Authorization header for an owner session."""
    return {"Authorization": f"Bearer {session['access_token']}"}


async def _project(
    client: AsyncClient, session: dict[str, Any], *, initials: str = "NG", number: int = 0
) -> dict[str, Any]:
    """Create a project to pair a camera to."""
    today = datetime.now(UTC).date()
    response = await client.post(
        PROJECTS,
        headers=_auth(session),
        json={
            "name": f"Site {initials}{number}",
            "code_initials": initials,
            "project_number": number,
            "location_label": "Naga City",
            "latitude": 13.6218,
            "longitude": 123.1948,
            "start_date": (today - timedelta(days=10)).isoformat(),
            "deadline_date": (today + timedelta(days=100)).isoformat(),
            "visibility": Visibility.PRIVATE.value,
            "intended_use": "Testing",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _pair(
    client: AsyncClient,
    session: dict[str, Any],
    project_id: str,
    *,
    face: CameraFace = CameraFace.FRONT_DIAGONAL,
) -> SimulatedCamera:
    """Issue a code, claim it, and return a camera that can sign."""
    issued = await client.post(
        f"{PROJECTS}/{project_id}/pairing-tokens",
        headers=_auth(session),
        json={"face": face.value},
    )
    assert issued.status_code == 201, issued.text

    claimed = await client.post(
        CLAIM,
        json={
            "display_code": issued.json()["display_code"],
            "hardware_id": "24:0A:C4:11:22:33",
            "firmware_version": "test-1.0.0",
        },
    )
    assert claimed.status_code == 200, claimed.text
    return SimulatedCamera(client, claimed.json())


@pytest.fixture
async def owner(client: AsyncClient) -> dict[str, Any]:
    """A registered owner."""
    return await _account(client, "device_owner")


@pytest.fixture
async def project(client: AsyncClient, owner: dict[str, Any]) -> dict[str, Any]:
    """A project owned by ``owner``."""
    return await _project(client, owner)


@pytest.fixture
async def camera(
    client: AsyncClient, owner: dict[str, Any], project: dict[str, Any]
) -> SimulatedCamera:
    """A camera paired to ``project``."""
    return await _pair(client, owner, project["id"])


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestPairing:
    """Issuing and claiming a code."""

    async def test_issued_code_can_be_claimed(self, camera: SimulatedCamera) -> None:
        assert camera.secret
        assert camera.project_code == "NG_00"

    async def test_the_code_works_exactly_once(
        self, client: AsyncClient, owner: dict[str, Any], project: dict[str, Any]
    ) -> None:
        """Single-use, or a code read off a shoulder pairs a second camera."""
        issued = await client.post(
            f"{PROJECTS}/{project['id']}/pairing-tokens",
            headers=_auth(owner),
            json={"face": CameraFace.FRONT_DIAGONAL.value},
        )
        code = issued.json()["display_code"]

        first = await client.post(CLAIM, json={"display_code": code})
        second = await client.post(CLAIM, json={"display_code": code})

        assert first.status_code == 200
        assert second.status_code == 409
        assert second.json()["error"]["code"] == "PAIRING_CODE_USED"

    async def test_an_unknown_code_is_refused(self, client: AsyncClient) -> None:
        response = await client.post(CLAIM, json={"display_code": "ZZZZ9999"})
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "INVALID_PAIRING_CODE"

    async def test_the_secret_is_never_returned_again(
        self, client: AsyncClient, owner: dict[str, Any], project: dict[str, Any]
    ) -> None:
        """It exists in plaintext exactly once, in the claim response."""
        camera = await _pair(client, owner, project["id"])
        listed = await client.get(f"{PROJECTS}/{project['id']}/devices", headers=_auth(owner))
        assert listed.status_code == 200
        assert camera.secret not in listed.text

    async def test_pairing_a_face_twice_is_refused(
        self, client: AsyncClient, owner: dict[str, Any], project: dict[str, Any]
    ) -> None:
        """Two cameras on one face would double-count that view in the mean."""
        await _pair(client, owner, project["id"], face=CameraFace.FRONT_DIAGONAL)
        again = await client.post(
            f"{PROJECTS}/{project['id']}/pairing-tokens",
            headers=_auth(owner),
            json={"face": CameraFace.FRONT_DIAGONAL.value},
        )
        assert again.status_code == 409

    async def test_a_second_face_pairs_fine(
        self, client: AsyncClient, owner: dict[str, Any], project: dict[str, Any]
    ) -> None:
        await _pair(client, owner, project["id"], face=CameraFace.FRONT_DIAGONAL)
        second = await _pair(client, owner, project["id"], face=CameraFace.BACK)
        assert second.secret

    async def test_a_stranger_cannot_issue_a_code(
        self, client: AsyncClient, project: dict[str, Any]
    ) -> None:
        stranger = await _account(client, "not_the_owner")
        response = await client.post(
            f"{PROJECTS}/{project['id']}/pairing-tokens",
            headers=_auth(stranger),
            json={"face": CameraFace.BACK.value},
        )
        assert response.status_code in {403, 404}


class TestSignedUpload:
    """The happy path and the naming rules."""

    async def test_a_signed_upload_is_accepted(self, camera: SimulatedCamera) -> None:
        response = await camera.upload()
        assert response.status_code == 201, response.text
        body = response.json()
        assert body["accepted"] is True
        assert body["duplicate"] is False

    async def test_the_server_names_the_file(self, camera: SimulatedCamera) -> None:
        """The device sends no filename; the server derives it (§3)."""
        captured = datetime(2026, 8, 14, 7, 0, tzinfo=UTC)
        response = await camera.upload(captured_at=captured)
        assert response.json()["filename"] == "NG_00_20260814T070000Z_001.jpg"

    async def test_capture_time_is_converted_to_utc(self, camera: SimulatedCamera) -> None:
        """A Manila-stamped capture must not be filed eight hours off.

        07:00 in Manila is 23:00 UTC the previous day. Getting this wrong files
        the image into the wrong aggregation window, and every progress figure
        downstream inherits the error.
        """
        manila = timezone(timedelta(hours=8))
        response = await camera.upload(captured_at=datetime(2026, 8, 14, 7, 0, tzinfo=manila))
        assert response.json()["filename"] == "NG_00_20260813T230000Z_001.jpg"

    async def test_server_time_is_returned_for_clock_correction(
        self, camera: SimulatedCamera
    ) -> None:
        """Without it a drifting RTC eventually locks itself out."""
        response = await camera.upload()
        assert datetime.fromisoformat(response.json()["server_time"]).tzinfo is not None

    async def test_sequence_numbers_increment_within_a_day(self, camera: SimulatedCamera) -> None:
        day = datetime(2026, 8, 14, 7, 0, tzinfo=UTC)
        names = []
        for index in range(3):
            response = await camera.upload(
                image=make_jpeg(colour=f"rgb({index * 40}, 10, 10)"),
                captured_at=day + timedelta(minutes=index),
            )
            names.append(response.json()["filename"])
        assert [name[-7:-4] for name in names] == ["001", "002", "003"]

    async def test_sequence_resets_the_next_day(self, camera: SimulatedCamera) -> None:
        """Numbering is per project per UTC day, so it stays readable.

        Both days are in the past: the future is capped at 24 hours, and a
        fixed-date test would otherwise start failing the moment the calendar
        moved past it.
        """
        now = datetime.now(UTC)
        first = await camera.upload(
            image=make_jpeg(colour="red"), captured_at=now - timedelta(days=3)
        )
        second = await camera.upload(
            image=make_jpeg(colour="blue"), captured_at=now - timedelta(days=2)
        )
        assert first.json()["filename"].endswith("_001.jpg")
        assert second.json()["filename"].endswith("_001.jpg")

    async def test_the_capture_appears_in_the_project_folder(
        self,
        client: AsyncClient,
        owner: dict[str, Any],
        project: dict[str, Any],
        camera: SimulatedCamera,
    ) -> None:
        """The point of the whole module: it lands where the owner can see it.

        Asserted against the folder's ``recent_images`` because the gallery
        endpoint itself is Module 07 — this is the earliest place the capture
        becomes visible to a person.
        """
        response = await camera.upload()
        folder = await client.get(f"{PROJECTS}/{project['id']}", headers=_auth(owner))

        assert folder.status_code == 200
        images = folder.json()["recent_images"]
        assert len(images) == 1
        assert images[0]["filename"] == response.json()["filename"]
        assert images[0]["latitude"] == pytest.approx(13.6218)
        assert folder.json()["last_capture_at"] is not None


class TestIdempotency:
    """A lost ACK must not double-count a capture."""

    async def test_identical_bytes_are_stored_once(self, camera: SimulatedCamera) -> None:
        image = make_jpeg(colour="purple")
        first = await camera.upload(image=image)
        second = await camera.upload(image=image)

        assert first.status_code == 201
        assert second.status_code == 201
        assert second.json()["duplicate"] is True
        assert second.json()["image_id"] == first.json()["image_id"]

    async def test_a_duplicate_does_not_consume_a_sequence_number(
        self, camera: SimulatedCamera
    ) -> None:
        """Otherwise a flaky link would punch gaps in the day's numbering."""
        day = datetime(2026, 8, 14, 7, tzinfo=UTC)
        image = make_jpeg(colour="orange")
        await camera.upload(image=image, captured_at=day)
        await camera.upload(image=image, captured_at=day)
        third = await camera.upload(image=make_jpeg(colour="cyan"), captured_at=day)
        assert third.json()["filename"].endswith("_002.jpg")


class TestAuthenticationFailures:
    """Every rejection path in Device-Pairing-Protocol.md §4."""

    async def test_a_bad_signature_is_rejected(self, camera: SimulatedCamera) -> None:
        response = await camera.upload(secret="not-the-real-secret")
        assert response.status_code == 401

    async def test_a_replayed_nonce_is_rejected(self, camera: SimulatedCamera) -> None:
        """A captured request must not be resendable."""
        nonce = secrets.token_hex(8)
        first = await camera.upload(image=make_jpeg(colour="red"), nonce=nonce)
        second = await camera.upload(image=make_jpeg(colour="blue"), nonce=nonce)
        assert first.status_code == 201
        assert second.status_code == 401

    async def test_a_stale_timestamp_is_rejected(self, camera: SimulatedCamera) -> None:
        stale = int((datetime.now(UTC) - timedelta(hours=1)).timestamp())
        response = await camera.upload(timestamp=stale)
        assert response.status_code == 401

    async def test_a_future_timestamp_is_rejected(self, camera: SimulatedCamera) -> None:
        ahead = int((datetime.now(UTC) + timedelta(hours=1)).timestamp())
        response = await camera.upload(timestamp=ahead)
        assert response.status_code == 401

    async def test_missing_headers_are_rejected(
        self, client: AsyncClient, camera: SimulatedCamera
    ) -> None:
        body, content_type = multipart(make_jpeg(), {"captured_at": "x", "sha256": "y"})
        response = await client.post(INGEST, content=body, headers={"Content-Type": content_type})
        assert response.status_code == 401

    async def test_an_unknown_device_id_is_rejected(
        self, client: AsyncClient, camera: SimulatedCamera
    ) -> None:
        camera.device_id = "00000000-0000-4000-8000-000000000000"
        response = await camera.upload()
        assert response.status_code == 401

    async def test_failures_do_not_reveal_which_check_failed(self, camera: SimulatedCamera) -> None:
        """Distinguishing them would tell an attacker how to fix a forgery."""
        bad_secret = await camera.upload(secret="wrong")
        stale = await camera.upload(
            timestamp=int((datetime.now(UTC) - timedelta(hours=1)).timestamp())
        )
        assert bad_secret.json()["error"]["message"] == stale.json()["error"]["message"]


class TestTamperingAndIntegrity:
    """The body hash is inside the signature for a reason."""

    async def test_a_tampered_body_is_rejected(
        self, client: AsyncClient, camera: SimulatedCamera
    ) -> None:
        """Sign one image, send another: the headers look perfect, the hash does not."""
        image = make_jpeg(colour="green")
        meta = {
            "captured_at": datetime.now(UTC).isoformat(),
            "sha256": hashlib.sha256(image).hexdigest(),
        }
        body, content_type = multipart(image, meta)
        headers = camera.headers(method="POST", path=INGEST, body=body)
        headers["Content-Type"] = content_type

        swapped = body.replace(b'filename="c.jpg"', b'filename="x.jpg"')
        response = await client.post(INGEST, content=swapped, headers=headers)
        assert response.status_code == 401

    async def test_a_mismatched_hash_is_rejected(self, camera: SimulatedCamera) -> None:
        """Signed correctly, but the reported hash is not the bytes sent."""
        response = await camera.upload(sha_override="0" * 64)
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "HASH_MISMATCH"

    async def test_a_non_jpeg_is_rejected(self, camera: SimulatedCamera) -> None:
        response = await camera.upload(image=b"MZ\x90\x00" + b"x" * 2000)
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "NOT_A_JPEG"

    async def test_a_tiny_frame_is_rejected(self, camera: SimulatedCamera) -> None:
        """A sensor that failed to warm up should not reach inference.

        Deliberately noisy: a flat 64x48 rectangle compresses below the
        minimum-bytes threshold and would be rejected as truncated instead,
        leaving the dimension check itself untested.
        """
        response = await camera.upload(image=make_noisy_jpeg(size=(64, 48)))
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "IMAGE_TOO_SMALL"

    async def test_a_truncated_frame_is_rejected(self, camera: SimulatedCamera) -> None:
        response = await camera.upload(image=make_jpeg()[:400])
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "IMAGE_TRUNCATED"

    async def test_an_implausible_capture_time_is_rejected(self, camera: SimulatedCamera) -> None:
        """A corrupt RTC would otherwise park an image ahead of the timeline."""
        response = await camera.upload(captured_at=datetime.now(UTC) + timedelta(days=30))
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "CLOCK_IMPLAUSIBLE"

    async def test_a_backlog_upload_is_accepted(self, camera: SimulatedCamera) -> None:
        """The past is unbounded — a camera offline for days uploads its backlog."""
        response = await camera.upload(captured_at=datetime.now(UTC) - timedelta(days=5))
        assert response.status_code == 201


class TestIsolationBetweenProjects:
    """A camera can only ever write to the project it was paired to."""

    async def test_a_camera_cannot_target_another_project(
        self, client: AsyncClient, camera: SimulatedCamera
    ) -> None:
        """The request carries no project at all — it comes from the device row.

        This is the structural defence: there is no field to tamper with.
        """
        other_owner = await _account(client, "other_owner")
        other = await _project(client, other_owner, initials="AB", number=1)

        await camera.upload()
        folder = await client.get(f"{PROJECTS}/{other['id']}", headers=_auth(other_owner))
        assert folder.json()["recent_images"] == []

    async def test_an_unpaired_camera_is_locked_out(
        self,
        client: AsyncClient,
        owner: dict[str, Any],
        project: dict[str, Any],
        camera: SimulatedCamera,
    ) -> None:
        """Revocation is immediate; its existing captures stay."""
        accepted = await camera.upload()
        assert accepted.status_code == 201

        unpaired = await client.post(
            f"{PROJECTS}/{project['id']}/devices/{camera.device_id}/unpair",
            headers=_auth(owner),
        )
        assert unpaired.status_code == 200

        rejected = await camera.upload(image=make_jpeg(colour="blue"))
        assert rejected.status_code in {401, 403}

        kept = await client.get(f"{PROJECTS}/{project['id']}", headers=_auth(owner))
        assert len(kept.json()["recent_images"]) == 1, "unpairing must not delete history"


class TestConfigAndEvents:
    """The two supporting endpoints a camera calls on every wake."""

    async def test_config_returns_the_schedule_and_clock(
        self, client: AsyncClient, camera: SimulatedCamera
    ) -> None:
        headers = camera.headers(method="GET", path=CONFIG, body=b"")
        response = await client.get(CONFIG, headers=headers)

        assert response.status_code == 200
        body = response.json()
        assert body["project_code"] == "NG_00"
        assert body["capture_times"]
        assert datetime.fromisoformat(body["server_time"]).tzinfo is not None

    async def test_config_requires_a_signature(self, client: AsyncClient) -> None:
        assert (await client.get(CONFIG)).status_code == 401

    async def test_a_heartbeat_is_recorded(
        self, client: AsyncClient, camera: SimulatedCamera
    ) -> None:
        """Accepted even with nothing captured — a camera that woke, found no
        Wi-Fi, and slept again is exactly the event worth knowing about."""
        payload = json.dumps(
            {"event_type": "heartbeat", "battery_mv": 3820, "rssi_dbm": -67}
        ).encode()
        headers = camera.headers(method="POST", path=EVENTS, body=payload)
        headers["Content-Type"] = "application/json"

        response = await client.post(EVENTS, content=payload, headers=headers)
        assert response.status_code == 202

    async def test_telemetry_reaches_the_owner_dashboard(
        self,
        client: AsyncClient,
        owner: dict[str, Any],
        project: dict[str, Any],
        camera: SimulatedCamera,
    ) -> None:
        await camera.upload()
        listed = await client.get(f"{PROJECTS}/{project['id']}/devices", headers=_auth(owner))
        device = next(item for item in listed.json() if item["id"] == camera.device_id)
        assert device["last_battery_mv"] == 3900
        assert device["last_seen_at"] is not None
