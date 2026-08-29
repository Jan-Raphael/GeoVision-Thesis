r"""Manual capture uploader — phone/webcam photos into the same signed ingest path.

For collecting real dataset images now that there is no ESP32-CAM in hand (Open-Questions Q2,
2026-08-27). Reuses ``simulate_device.py``'s pairing, HMAC signing, and upload code directly
rather than reimplementing it — a second signing implementation is exactly the kind of thing
that quietly drifts and produces a 401 nobody can explain months later.

Three ways to feed it a photo::

    # One frame from a local webcam (needs opencv-python, not a project dependency —
    # installed ad hoc so the base project never gains an unwanted import):
    uv run --with opencv-python python -m scripts.capture_and_upload \\
        --code K7M2-9XQF --source webcam

    # One existing image file, uploaded once:
    uv run python -m scripts.capture_and_upload --code K7M2-9XQF --source file --path photo.jpg

    # Watch a folder and upload every new image that appears in it — the practical way to
    # turn "phone photos synced to a folder" (cloud sync, USB, Bluetooth transfer) into
    # automatic uploads without a companion mobile app:
    uv run python -m scripts.capture_and_upload --code K7M2-9XQF --source watch --path ./inbox

GPS is read from the photo's own EXIF when present — most phone cameras embed it
automatically — and falls back to ``--latitude``/``--longitude`` (default: the same seeded
Naga City coordinates ``simulate_device.py`` uses) when it is not, which is always the case for
a plain webcam frame.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from collections.abc import Iterator
from pathlib import Path

import httpx

from scripts.simulate_device import (
    DEFAULT_BASE_URL,
    DEFAULT_LAT,
    DEFAULT_LON,
    DeviceIdentity,
    Faults,
    claim_code,
    pull_config,
    upload_capture,
)

IMAGE_SUFFIXES = (".jpg", ".jpeg", ".png")


def read_exif_gps(path: Path) -> tuple[float, float] | None:
    """Decimal-degree ``(latitude, longitude)`` from a photo's EXIF, or ``None``.

    Most phone cameras embed GPS automatically when location services are on; a webcam frame
    or a phone with location off will simply have no ``GPSInfo`` tag, which is common enough
    to handle quietly rather than treat as an error.
    """
    from PIL import ExifTags, Image

    def to_degrees(value: tuple) -> float:
        degrees, minutes, seconds = (float(part) for part in value)
        return degrees + minutes / 60 + seconds / 3600

    try:
        exif = Image.open(path).getexif()
        gps_ifd = exif.get_ifd(ExifTags.IFD.GPSInfo)
    except Exception:
        return None
    if not gps_ifd:
        return None

    try:
        lat = to_degrees(gps_ifd[2])
        if gps_ifd[1] == "S":
            lat = -lat
        lon = to_degrees(gps_ifd[4])
        if gps_ifd[3] == "W":
            lon = -lon
    except (KeyError, ValueError, TypeError):
        return None
    return round(lat, 6), round(lon, 6)


def capture_webcam_frame(camera_index: int, out_path: Path) -> Path:
    """Grab one JPEG frame from a local webcam. Requires ``opencv-python``.

    Raises:
        RuntimeError: If no camera answers at *camera_index*, or the frame cannot be read —
            both point at the same fix (check the index, check nothing else has the camera
            open), so one message covers both.
    """
    try:
        import cv2
    except ImportError as exc:
        msg = (
            "opencv-python is not installed. Run this with: "
            "uv run --with opencv-python python -m scripts.capture_and_upload --source webcam ..."
        )
        raise RuntimeError(msg) from exc

    capture = cv2.VideoCapture(camera_index)
    try:
        if not capture.isOpened():
            msg = f"no webcam answered at index {camera_index}"
            raise RuntimeError(msg)
        # Discard the first few frames: many webcams need a handful of reads to finish
        # auto-exposure/auto-white-balance, and the very first frame is often too dark.
        for _ in range(5):
            capture.read()
        ok, frame = capture.read()
        if not ok:
            msg = f"could not read a frame from webcam {camera_index}"
            raise RuntimeError(msg)
    finally:
        capture.release()

    out_path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out_path), frame)
    return out_path


def watch_folder(directory: Path, poll_seconds: float) -> Iterator[Path]:
    """Yield each new image file that appears in *directory*, oldest first, forever.

    Polling rather than a filesystem-events library (`watchdog` etc.): this only ever needs to
    notice a phone-synced file within a few seconds, not sub-second latency, and polling needs
    no extra dependency for something that runs occasionally on a laptop.
    """
    seen: set[Path] = set(directory.iterdir()) if directory.is_dir() else set()
    while True:
        if directory.is_dir():
            current = {
                p for p in directory.iterdir() if p.is_file() and p.suffix.casefold() in IMAGE_SUFFIXES
            }
            new = sorted(current - seen, key=lambda p: p.stat().st_mtime)
            for path in new:
                seen.add(path)
                yield path
        time.sleep(poll_seconds)


async def _upload_one(
    client: httpx.AsyncClient, identity: DeviceIdentity, path: Path, args: argparse.Namespace
) -> bool:
    gps = read_exif_gps(path)
    if gps is None:
        gps = (args.latitude, args.longitude)
        overridden = (args.latitude, args.longitude) != (DEFAULT_LAT, DEFAULT_LON)
        source = "provided default" if overridden else "seeded default (no EXIF GPS found)"
    else:
        source = "photo EXIF"
    print(f"  {path.name}: GPS {gps[0]:.6f}, {gps[1]:.6f} ({source})")
    return await upload_capture(client, identity, path, Faults(), jitter_gps=False, gps=gps)


async def run(args: argparse.Namespace) -> int:
    """Provision (if needed) and upload from whichever source was chosen."""
    identity_path = Path(args.identity)

    async with httpx.AsyncClient(base_url=args.server, timeout=30.0) as client:
        identity = DeviceIdentity.load(identity_path)
        if args.code:
            identity = await claim_code(client, args.code)
            identity.save(identity_path)
            print(f"identity saved to {identity_path}")
        if identity is None:
            print(
                "No saved identity. Pass --code with a pairing code from the "
                "dashboard to provision this camera.",
                file=sys.stderr,
            )
            return 1

        await pull_config(client, identity, Faults())

        if args.source == "file":
            if not args.path:
                print("--source file needs --path <image>", file=sys.stderr)
                return 1
            accepted = await _upload_one(client, identity, Path(args.path), args)
            print("accepted" if accepted else "rejected")
            return 0 if accepted else 1

        if args.source == "webcam":
            accepted_count = 0
            sent = 0
            while args.count == 0 or sent < args.count:
                sent += 1
                frame_path = Path(args.identity).parent / "webcam_capture.jpg"
                try:
                    capture_webcam_frame(args.camera_index, frame_path)
                except RuntimeError as exc:
                    print(f"capture failed: {exc}", file=sys.stderr)
                    return 1
                if await _upload_one(client, identity, frame_path, args):
                    accepted_count += 1
                if args.count == 0 or sent < args.count:
                    await asyncio.sleep(args.interval)
            print(f"\n{accepted_count}/{sent} accepted")
            return 0

        if args.source == "watch":
            if not args.path:
                print("--source watch needs --path <directory>", file=sys.stderr)
                return 1
            print(f"watching {args.path} — Ctrl+C to stop")
            for new_path in watch_folder(Path(args.path), args.interval):
                await _upload_one(client, identity, new_path, args)
            return 0

    print(f"unknown --source {args.source}", file=sys.stderr)
    return 1


def main() -> int:
    """Parse arguments and run."""
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--server", default=DEFAULT_BASE_URL, help="API base URL")
    parser.add_argument("--code", help="Pairing code; provisions and saves an identity")
    parser.add_argument(
        "--identity",
        default="outputs/manual-capture-device.json",
        help="Where to keep the device identity",
    )
    parser.add_argument("--source", choices=["webcam", "file", "watch"], default="webcam")
    parser.add_argument("--path", help="Image file (--source file) or folder (--source watch)")
    parser.add_argument("--camera-index", type=int, default=0, help="OpenCV camera index")
    parser.add_argument("--interval", type=float, default=30.0, help="Seconds between webcam shots or folder polls")
    parser.add_argument("--count", type=int, default=1, help="Webcam shots to take; 0 = forever")
    parser.add_argument("--latitude", type=float, default=DEFAULT_LAT)
    parser.add_argument("--longitude", type=float, default=DEFAULT_LON)

    args = parser.parse_args()
    try:
        return asyncio.run(run(args))
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())
