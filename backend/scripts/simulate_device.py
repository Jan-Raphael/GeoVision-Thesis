"""Pretend to be an ESP32-CAM.

This is how Modules 05 through 14 get tested before any hardware exists — and it
stays useful afterwards, because a simulator can produce failures on demand that
a real camera only produces at 3 a.m. on a roof.

It performs the same three phases as the firmware: claim a pairing code, sign
every request with HMAC-SHA256 over the canonical string, and upload geotagged
JPEGs. The signing code is deliberately independent of the server's — it uses
only ``hmac`` and ``hashlib`` — so a signature that verifies here proves the
protocol is implementable from the spec alone, not just that the server agrees
with itself.

Typical run::

    # 1. as an owner, issue a code in the dashboard or via the API
    # 2. claim it and start uploading
    uv run python -m scripts.simulate_device --code K7M2-9XQF --images ./samples --interval 5

Failure injection, for exercising the rejection paths::

    --bad-signature     sign with the wrong secret        -> expect 401
    --replay            reuse the previous nonce          -> expect 401
    --clock-skew 600    stamp 10 minutes off              -> expect 401
    --tamper            alter the body after signing      -> expect 401
    --fail-rate 0.3     drop 30 % of uploads before send  -> exercises the retry path
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import hashlib
import hmac
import json
import random
import secrets
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx

DEFAULT_BASE_URL = "http://localhost:8000"
INGEST_PATH = "/api/v1/ingest/images"
CONFIG_PATH = "/api/v1/ingest/config"
EVENTS_PATH = "/api/v1/ingest/events"
CLAIM_PATH = "/api/v1/pair/claim"

#: Naga City, matching the seeded projects.
DEFAULT_LAT = 13.6218
DEFAULT_LON = 123.1948


@dataclass
class DeviceIdentity:
    """What the firmware would keep in NVS after pairing."""

    device_id: str
    device_secret: str
    device_name: str
    project_code: str

    @classmethod
    def load(cls, path: Path) -> DeviceIdentity | None:
        """Read a saved identity, or ``None`` if absent."""
        if not path.is_file():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls(**data)

    def save(self, path: Path) -> None:
        """Persist the identity so the simulator survives a restart."""
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.__dict__, indent=2), encoding="utf-8")


@dataclass
class Faults:
    """Deliberate misbehaviour, for exercising the server's rejection paths."""

    bad_signature: bool = False
    replay: bool = False
    clock_skew_seconds: int = 0
    tamper: bool = False
    fail_rate: float = 0.0
    last_nonce: str | None = field(default=None, repr=False)


def sign(secret: str, *, method: str, path: str, timestamp: int, nonce: str, body: bytes) -> str:
    """Compute the request signature.

    Intentionally a standalone implementation using only the standard library:
    the ESP32 does this with mbedTLS, and Module 13 verifies its output against
    a fixed vector from *this* function. If the two ever disagree, the bug is
    findable in minutes rather than through a failing upload on a roof.
    """
    canonical = "\n".join(
        [method.upper(), path, str(timestamp), nonce, hashlib.sha256(body).hexdigest()]
    )
    return hmac.new(secret.encode(), canonical.encode(), hashlib.sha256).hexdigest()


def signed_headers(
    identity: DeviceIdentity,
    *,
    method: str,
    path: str,
    body: bytes,
    faults: Faults,
    now: datetime,
) -> dict[str, str]:
    """Build the four signature headers, applying any requested faults."""
    timestamp = int((now + timedelta(seconds=faults.clock_skew_seconds)).timestamp())

    replaying = faults.replay and faults.last_nonce is not None
    nonce = faults.last_nonce if replaying and faults.last_nonce else secrets.token_hex(8)
    faults.last_nonce = nonce

    secret = identity.device_secret
    if faults.bad_signature:
        secret = "not-the-right-secret"

    return {
        "X-Device-Id": identity.device_id,
        "X-Timestamp": str(timestamp),
        "X-Nonce": nonce,
        "X-Signature": sign(
            secret,
            method=method,
            path=path,
            timestamp=timestamp,
            nonce=nonce,
            body=body,
        ),
    }


async def claim_code(client: httpx.AsyncClient, code: str) -> DeviceIdentity:
    """Exchange a pairing code for a device identity.

    Mirrors the firmware's one-time provisioning step. The secret comes back
    exactly once, which is why the simulator writes it straight to disk.
    """
    response = await client.post(
        CLAIM_PATH,
        json={
            "display_code": code,
            "hardware_id": f"24:0A:C4:{secrets.token_hex(3).upper()}",
            "firmware_version": "sim-1.0.0",
        },
    )
    if response.status_code != 200:
        print(f"pairing failed: {response.status_code} {response.text}", file=sys.stderr)
        raise SystemExit(1)

    body = response.json()
    identity = DeviceIdentity(
        device_id=body["device_id"],
        device_secret=body["device_secret"],
        device_name=body["device_name"],
        project_code=body["project_code"],
    )
    print(f"paired as {identity.device_name} on project {identity.project_code}")
    return identity


def build_multipart(image_bytes: bytes, meta: dict[str, Any], boundary: str) -> tuple[bytes, str]:
    """Assemble the multipart body by hand.

    Built manually rather than with httpx's ``files=`` helper for one reason:
    the signature covers the **raw body bytes**, so the exact bytes that get
    hashed must be the exact bytes that get sent. Letting a library re-encode
    the body after signing is precisely how signature mismatches appear.
    """
    meta_json = json.dumps(meta, separators=(",", ":"))
    parts = [
        f"--{boundary}\r\n".encode(),
        b'Content-Disposition: form-data; name="meta"\r\n\r\n',
        meta_json.encode(),
        b"\r\n",
        f"--{boundary}\r\n".encode(),
        b'Content-Disposition: form-data; name="file"; filename="capture.jpg"\r\n',
        b"Content-Type: image/jpeg\r\n\r\n",
        image_bytes,
        b"\r\n",
        f"--{boundary}--\r\n".encode(),
    ]
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


async def upload_capture(
    client: httpx.AsyncClient,
    identity: DeviceIdentity,
    image_path: Path,
    faults: Faults,
    *,
    jitter_gps: bool,
    captured_at: datetime | None = None,
    gps: tuple[float, float] | None = None,
) -> bool:
    """Upload one image. Returns whether the server accepted it.

    Args:
        client: The HTTP client to send through.
        identity: The paired device signing the request.
        image_path: The JPEG file to upload.
        faults: Deliberate misbehaviour to apply, or a fresh ``Faults()`` for none.
        jitter_gps: Wander the GPS fix slightly, simulating a consumer receiver
            reading a fixed point repeatedly. Ignored when *gps* is given.
        captured_at: Backdate the capture timestamp; defaults to now.
        gps: Override for ``(latitude, longitude)``. Defaults to the seeded
            Naga City coordinates when omitted — used by
            ``capture_and_upload.py`` to pass a photo's real EXIF location
            instead of pretending every capture happened at the same spot.
    """
    # Off the event loop: a multi-megabyte read would otherwise stall every
    # other simulated camera running in the same process.
    image_bytes = await asyncio.to_thread(image_path.read_bytes)
    now = datetime.now(UTC)
    captured = captured_at or now

    latitude, longitude = gps or (DEFAULT_LAT, DEFAULT_LON)
    if jitter_gps:
        # A real GPS fix wanders by a few metres between reads; ~1e-5 degrees
        # is about a metre, which is the right order for consumer hardware.
        latitude += random.uniform(-3e-5, 3e-5)
        longitude += random.uniform(-3e-5, 3e-5)

    meta = {
        "captured_at": captured.isoformat(),
        "sha256": hashlib.sha256(image_bytes).hexdigest(),
        "latitude": round(latitude, 6),
        "longitude": round(longitude, 6),
        "gps_accuracy_m": round(random.uniform(2.5, 6.0), 2),
        "satellites": random.randint(6, 12),
        "battery_mv": random.randint(3450, 4100),
        "rssi_dbm": random.randint(-82, -55),
    }

    boundary = f"----geovision{secrets.token_hex(8)}"
    body, content_type = build_multipart(image_bytes, meta, boundary)

    headers = signed_headers(
        identity, method="POST", path=INGEST_PATH, body=body, faults=faults, now=now
    )
    headers["Content-Type"] = content_type

    if faults.tamper:
        # Flip a byte *after* signing: the signature stays valid-looking, but the
        # body hash inside the canonical string no longer matches what arrives.
        body = body.replace(b"capture.jpg", b"tampered.jpg")

    response = await client.post(INGEST_PATH, content=body, headers=headers)

    if response.status_code == 201:
        payload = response.json()
        marker = " (duplicate)" if payload.get("duplicate") else ""
        print(f"  {image_path.name} -> {payload['filename']}{marker}")
        return True

    print(f"  {image_path.name} -> {response.status_code} {response.text[:160]}")
    return False


async def send_heartbeat(
    client: httpx.AsyncClient, identity: DeviceIdentity, faults: Faults
) -> None:
    """Report telemetry and correct the clock, as the firmware does each wake."""
    payload = json.dumps(
        {
            "event_type": "heartbeat",
            "battery_mv": random.randint(3450, 4100),
            "rssi_dbm": random.randint(-82, -55),
            "free_heap": random.randint(90_000, 180_000),
            "queue_depth": 0,
        }
    ).encode()
    headers = signed_headers(
        identity,
        method="POST",
        path=EVENTS_PATH,
        body=payload,
        faults=faults,
        now=datetime.now(UTC),
    )
    headers["Content-Type"] = "application/json"
    response = await client.post(EVENTS_PATH, content=payload, headers=headers)
    if response.status_code == 202:
        print("  heartbeat ok")


async def pull_config(client: httpx.AsyncClient, identity: DeviceIdentity, faults: Faults) -> None:
    """Fetch the schedule and report clock drift, as the firmware does."""
    headers = signed_headers(
        identity,
        method="GET",
        path=CONFIG_PATH,
        body=b"",
        faults=faults,
        now=datetime.now(UTC),
    )
    response = await client.get(CONFIG_PATH, headers=headers)
    if response.status_code != 200:
        print(f"  config -> {response.status_code}")
        return
    config = response.json()
    server_time = datetime.fromisoformat(config["server_time"])
    drift = abs((datetime.now(UTC) - server_time).total_seconds())
    print(
        f"  config: capture at {', '.join(config['capture_times'])} "
        f"({config['timezone']}), clock drift {drift:.1f}s"
    )


def discover_images(directory: Path) -> list[Path]:
    """Collect the JPEGs to cycle through."""
    if not directory.is_dir():
        print(f"no such directory: {directory}", file=sys.stderr)
        raise SystemExit(1)
    images = sorted(
        path
        for path in directory.iterdir()
        if path.suffix.lower() in {".jpg", ".jpeg"} and path.is_file()
    )
    if not images:
        print(f"no .jpg files in {directory}", file=sys.stderr)
        raise SystemExit(1)
    return images


async def run(args: argparse.Namespace) -> int:
    """Drive the simulated camera."""
    identity_path = Path(args.identity)
    faults = Faults(
        bad_signature=args.bad_signature,
        replay=args.replay,
        clock_skew_seconds=args.clock_skew,
        tamper=args.tamper,
        fail_rate=args.fail_rate,
    )

    async with httpx.AsyncClient(base_url=args.server, timeout=30.0) as client:
        identity = DeviceIdentity.load(identity_path)
        if args.code:
            identity = await claim_code(client, args.code)
            identity.save(identity_path)
            print(f"identity saved to {identity_path}")
        if identity is None:
            print(
                "No saved identity. Pass --code with a pairing code from the "
                "dashboard to provision this simulated camera.",
                file=sys.stderr,
            )
            return 1

        await pull_config(client, identity, faults)

        images = discover_images(Path(args.images))
        print(f"{len(images)} image(s); {args.count or 'unlimited'} upload(s)")

        sent = 0
        accepted = 0
        index = 0
        while args.count == 0 or sent < args.count:
            image = images[index % len(images)]
            index += 1
            sent += 1

            # Backfill mode stamps captures into the past, so a whole timeline
            # can be built in seconds rather than over real days.
            captured_at = None
            if args.backfill_days:
                offset = timedelta(days=args.backfill_days * (sent - 1) / max(args.count, 1))
                captured_at = datetime.now(UTC) - timedelta(days=args.backfill_days) + offset

            if faults.fail_rate and random.random() < faults.fail_rate:
                print(f"  {image.name} -> dropped before send (simulated Wi-Fi loss)")
            elif await upload_capture(
                client,
                identity,
                image,
                faults,
                jitter_gps=args.jitter_gps,
                captured_at=captured_at,
            ):
                accepted += 1

            if sent % 5 == 0:
                await send_heartbeat(client, identity, faults)
            if args.count == 0 or sent < args.count:
                await asyncio.sleep(args.interval)

        print(f"\n{accepted}/{sent} accepted")
    return 0


def main() -> int:
    """Parse arguments and run."""
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--server", default=DEFAULT_BASE_URL, help="API base URL")
    parser.add_argument("--code", help="Pairing code; provisions and saves an identity")
    parser.add_argument(
        "--identity",
        default="outputs/simulated-device.json",
        help="Where to keep the device identity (the firmware's NVS)",
    )
    parser.add_argument("--images", default="dataset/raw", help="Directory of .jpg files")
    parser.add_argument("--interval", type=float, default=5.0, help="Seconds between uploads")
    parser.add_argument("--count", type=int, default=5, help="Uploads to send; 0 = forever")
    parser.add_argument("--jitter-gps", action="store_true", help="Wander the GPS fix")
    parser.add_argument(
        "--backfill-days",
        type=int,
        default=0,
        help="Spread captures over this many past days, to build a timeline quickly",
    )

    faults = parser.add_argument_group("failure injection")
    faults.add_argument("--bad-signature", action="store_true", help="Sign with a wrong secret")
    faults.add_argument("--replay", action="store_true", help="Reuse the previous nonce")
    faults.add_argument("--clock-skew", type=int, default=0, help="Offset the timestamp, seconds")
    faults.add_argument("--tamper", action="store_true", help="Alter the body after signing")
    faults.add_argument(
        "--fail-rate", type=float, default=0.0, help="Fraction of uploads to drop (0-1)"
    )

    args = parser.parse_args()
    with contextlib.suppress(KeyboardInterrupt):
        return asyncio.run(run(args))
    return 0


if __name__ == "__main__":
    sys.exit(main())
