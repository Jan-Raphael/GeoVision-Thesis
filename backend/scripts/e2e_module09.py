r"""End-to-end check for Module 09: upload → prediction → progress → demo endpoint.

Drives the running API over HTTP against live PostgreSQL, Redis, MinIO, and a
real Celery worker. **Nothing is mocked.** The test suite covers each piece in
isolation; this covers the one thing it cannot — that the pieces are actually
wired to each other in a running system.

It is also the defense rehearsal script (P2-9): if this passes, the demo works.

Prerequisites::

    .\\dev.ps1 up          # redis + minio  (postgres is native on 5433)
    .\\dev.ps1 migrate
    .\\dev.ps1 api
    .\\dev.ps1 worker      # must be running, or /predict has nobody to ask

Then::

    uv run python -m scripts.e2e_module09

Exit code is 0 only if every check passed.
"""

from __future__ import annotations

import argparse
import random
import string
import subprocess
import sys
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx

REPO_ROOT = Path(__file__).resolve().parent.parent

#: The API commits its transaction in a `yield`-dependency's exit code, which
#: FastAPI runs *after* the response is delivered — so a real network client can
#: read its own write a few milliseconds too early and get a 404. Measured at
#: ~7 ms. See Open-Questions Q12; this pause is a workaround, not a fix, and it
#: should be deleted when Q12 is.
WRITE_SETTLE_SECONDS = 0.5


@dataclass
class Report:
    """Tally of checks, so the exit code means something."""

    passed: int = 0
    failed: list[str] = field(default_factory=list)

    def check(self, label: str, ok: bool, detail: str = "") -> bool:
        """Record one assertion and print it."""
        if ok:
            self.passed += 1
            print(f"  PASS  {label}" + (f"  [{detail}]" if detail else ""))
        else:
            self.failed.append(label)
            print(f"  FAIL  {label}  {detail}")
        return ok


def make_samples(directory: Path, count: int = 4) -> Path:
    """Write synthetic site captures.

    Textured on purpose: the quality gate measures Laplacian variance, so a flat
    frame would be correctly rejected as blurred and the run would prove nothing.
    """
    from PIL import Image, ImageDraw

    directory.mkdir(parents=True, exist_ok=True)
    rng = random.Random(42)
    for n in range(count):
        img = Image.new("RGB", (640, 480), (150 + n * 10, 150, 145))
        draw = ImageDraw.Draw(img)
        for _ in range(4000):
            value = rng.randrange(60, 230)
            draw.point((rng.randrange(640), rng.randrange(480)), fill=(value, value, value))
        for i in range(6 + n):
            left = 40 + i * 90
            draw.rectangle([left, 200 - i * 8, left + 55, 460], outline=(40, 40, 40), width=3)
        draw.rectangle([0, 440, 640, 480], fill=(90, 80, 70))
        img.save(directory / f"capture_{n:03d}.jpg", quality=88)
    return directory


def run(base_url: str, samples: Path) -> int:
    """Execute the whole scenario. Returns a process exit code."""
    api = f"{base_url.rstrip('/')}/api/v1"
    client = httpx.Client(timeout=60.0)
    report = Report()
    tag = uuid.uuid4().hex[:8]

    print("\n=== 1. owner signs in and creates a project ===")
    creds = {"username": "e2e_owner", "password": "correct-horse-1"}
    registered = client.post(
        f"{api}/auth/register",
        json={
            **creds,
            "email": "e2e_owner@gvmail.com",
            "full_name": "E2E Owner",
            "professional_role": "engineer",
        },
    )
    if registered.status_code == 201:
        session = registered.json()
        report.check("register", True, "new account")
    else:
        # Registration is rate-limited to 3/hour per IP, so re-runs sign in.
        login = client.post(
            f"{api}/auth/login",
            json={"identifier": creds["username"], "password": creds["password"]},
        )
        if not report.check("sign in", login.status_code == 200, login.text[:200]):
            return 1
        session = login.json()
    auth = {"Authorization": f"Bearer {session['access_token']}"}

    today = datetime.now(UTC).date()
    created = client.post(
        f"{api}/projects",
        headers=auth,
        json={
            "name": "E2E Monitoring Site",
            "code_initials": "".join(random.choices(string.ascii_uppercase, k=2)),
            "project_number": random.randrange(100),
            "location_label": "Naga City",
            "latitude": 13.6218,
            "longitude": 123.1948,
            "start_date": (today - timedelta(days=30)).isoformat(),
            "deadline_date": (today + timedelta(days=120)).isoformat(),
            "visibility": "private",
        },
    )
    if not report.check("create project", created.status_code == 201, created.text[:200]):
        return 1
    project_id = created.json()["id"]
    time.sleep(WRITE_SETTLE_SECONDS)

    print("\n=== 2. progress before any capture ===")
    before = client.get(f"{api}/projects/{project_id}/progress", headers=auth).json()
    report.check(
        "has_data is false with no captures",
        before.get("has_data") is False,
        f"displayed={before.get('displayed_pct')}",
    )

    print("\n=== 3. pair a simulated camera and upload ===")
    token = client.post(
        f"{api}/projects/{project_id}/pairing-tokens",
        headers=auth,
        json={"face": "front_diagonal"},
    )
    if not report.check("issue pairing token", token.status_code in (200, 201), token.text[:200]):
        return 1

    identity = Path(tempfile.gettempdir()) / f"gv_e2e_device_{tag}.json"
    simulator = subprocess.run(  # noqa: S603 - fixed argv, no shell
        [  # noqa: S607 - `uv` is how every command in this repo is run
            "uv",
            "run",
            "python",
            "-m",
            "scripts.simulate_device",
            "--server",
            base_url,
            "--code",
            token.json()["display_code"],
            "--images",
            str(samples),
            "--identity",
            str(identity),
            "--count",
            "4",
            "--interval",
            "0.5",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    report.check(
        "simulator uploaded 4 captures",
        simulator.returncode == 0,
        (simulator.stdout[-200:] + simulator.stderr[-200:]).replace("\n", " | ")[:300],
    )

    print("\n=== 4. the worker scores them ===")
    inferred: list[dict] = []
    deadline = time.time() + 120
    while time.time() < deadline:
        history = client.get(f"{api}/projects/{project_id}/history", headers=auth)
        if history.status_code == 200:
            inferred = [i for i in history.json()["items"] if i["status"] == "inferred"]
            if len(inferred) >= 4:
                break
        time.sleep(2)

    rows = client.get(f"{api}/projects/{project_id}/history", headers=auth).json()["items"]
    tally: dict[str, int] = {}
    for row in rows:
        tally[row["status"]] = tally.get(row["status"], 0) + 1
    report.check("all 4 captures reached status=inferred", len(inferred) >= 4, f"statuses={tally}")
    if not inferred:
        print("\nNo image was scored. Is the worker running? (.\\dev.ps1 worker)")
        return 1
    report.check(
        "history rows carry a stage and confidence",
        inferred[0]["stage"] is not None and inferred[0]["confidence"] is not None,
        f"stage={inferred[0]['stage']} conf={inferred[0]['confidence']}",
    )

    print("\n=== 5. image detail ===")
    image_id = inferred[0]["image_id"]
    detail = client.get(f"{api}/projects/{project_id}/images/{image_id}", headers=auth).json()
    report.check(
        "prediction embedded with its full distribution",
        bool(detail.get("prediction", {}).get("class_probabilities")),
        f"stage={detail.get('prediction', {}).get('stage')}",
    )
    report.check("signed URL issued for the original", bool(detail.get("original_url")))
    report.check(
        "detections present",
        isinstance(detail.get("detections"), list),
        f"counts={detail.get('counts')}",
    )
    report.check(
        "GET /prediction -> 200",
        client.get(
            f"{api}/projects/{project_id}/images/{image_id}/prediction", headers=auth
        ).status_code
        == 200,
    )
    report.check(
        "an image reached through a foreign project id is 404, never 403",
        client.get(f"{api}/projects/{uuid.uuid4()}/images/{image_id}", headers=auth).status_code
        == 404,
    )

    print("\n=== 6. progress moved ===")
    after = client.get(f"{api}/projects/{project_id}/progress", headers=auth).json()
    report.check(
        "has_data is now true",
        after.get("has_data") is True,
        f"displayed={after.get('displayed_pct')} macro={after.get('macro_stage')} "
        f"eligible={after.get('eligible_image_count')} devices={after.get('devices_reporting')}",
    )
    report.check("five stage bars", len(after.get("stages", {})) == 5, str(after.get("stages")))
    timeline = client.get(f"{api}/projects/{project_id}/timeline", headers=auth).json()
    report.check(
        "timeline has a stored snapshot",
        len(timeline.get("points", [])) >= 1,
        f"points={len(timeline.get('points', []))}",
    )

    print("\n=== 7. recompute is idempotent ===")
    recompute = client.post(f"{api}/projects/{project_id}/recompute", headers=auth)
    report.check("POST /recompute -> 202", recompute.status_code == 202, recompute.text[:150])
    time.sleep(6)
    again = client.get(f"{api}/projects/{project_id}/progress", headers=auth).json()
    report.check(
        "progress unchanged after recompute",
        again.get("displayed_pct") == after.get("displayed_pct"),
        f"{after.get('displayed_pct')} -> {again.get('displayed_pct')}",
    )
    timeline2 = client.get(f"{api}/projects/{project_id}/timeline", headers=auth).json()
    report.check(
        "no duplicate snapshot rows",
        len(timeline2.get("points", [])) == len(timeline.get("points", [])),
    )

    print("\n=== 8. /model/status and /models ===")
    status = client.get(f"{api}/model/status", headers=auth).json()
    report.check("worker reachable", status.get("worker_reachable") is True)
    report.check(
        "live model reported",
        bool(status.get("live_classifier")),
        f"device={status.get('live_classifier', {}).get('device')} "
        f"mean_latency_ms={status.get('mean_latency_ms')}",
    )
    report.check(
        "using_stubs surfaced",
        status.get("using_stubs") is not None,
        f"using_stubs={status.get('using_stubs')}",
    )
    report.check(
        "queue depth read from the broker",
        isinstance(status.get("queue_depth"), dict),
        str(status.get("queue_depth")),
    )
    models = client.get(f"{api}/models", headers=auth).json()
    report.check("registry lists the active classifier", len(models.get("models", [])) >= 1)

    print("\n=== 9. POST /predict (stateless demo path) ===")
    rows_before = len(
        client.get(f"{api}/projects/{project_id}/history", headers=auth).json()["items"]
    )
    sample = sorted(samples.glob("*.jpg"))[0]
    started = time.perf_counter()
    predicted = client.post(
        f"{api}/predict",
        headers=auth,
        files={"file": (sample.name, sample.read_bytes(), "image/jpeg")},
    )
    round_trip = int((time.perf_counter() - started) * 1000)
    body = predicted.json() if predicted.status_code == 200 else {}
    if not report.check("POST /predict -> 200", predicted.status_code == 200, predicted.text[:200]):
        print("  (is the worker running? /predict has nobody to ask otherwise)")
    report.check(
        "returns a stage and confidence",
        bool(body.get("stage")),
        f"stage={body.get('stage')} conf={body.get('confidence')} "
        f"progress={body.get('progress')} round_trip_ms={round_trip}",
    )
    report.check("marked as not persisted", body.get("persisted") is False)
    rows_after = len(
        client.get(f"{api}/projects/{project_id}/history", headers=auth).json()["items"]
    )
    report.check(
        "/predict stored nothing",
        rows_after == rows_before,
        f"history {rows_before} -> {rows_after} rows",
    )
    report.check(
        "a non-image is refused before it reaches the broker",
        client.post(
            f"{api}/predict",
            headers=auth,
            files={"file": ("notes.jpg", b"not a photograph", "image/jpeg")},
        ).status_code
        == 400,
    )

    print("\n=== 10. reprocess round trip ===")
    reprocessed = client.post(
        f"{api}/projects/{project_id}/images/{image_id}/reprocess", headers=auth
    )
    report.check("POST /reprocess -> 202", reprocessed.status_code == 202, reprocessed.text[:150])
    report.check(
        "returned image is back to pending with no prediction",
        reprocessed.status_code == 202
        and reprocessed.json()["status"] == "pending"
        and reprocessed.json()["prediction"] is None,
    )
    deadline = time.time() + 90
    rescored = False
    while time.time() < deadline:
        current = client.get(f"{api}/projects/{project_id}/images/{image_id}", headers=auth).json()
        if current.get("prediction"):
            rescored = True
            break
        time.sleep(2)
    report.check("the worker re-scored it", rescored)
    final = len(client.get(f"{api}/projects/{project_id}/history", headers=auth).json()["items"])
    report.check(
        "still one row per image after reprocess", final == rows_after, f"{rows_after} -> {final}"
    )

    print(f"\n===== {report.passed} passed, {len(report.failed)} failed =====")
    for label in report.failed:
        print(f"  - {label}")
    return 0 if not report.failed else 1


def main() -> int:
    """Parse arguments and run the scenario."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--server", default="http://127.0.0.1:8000", help="API base URL")
    parser.add_argument(
        "--images",
        default=None,
        help="Directory of .jpg captures; synthetic ones are generated if omitted",
    )
    args = parser.parse_args()

    samples = (
        Path(args.images)
        if args.images
        else make_samples(Path(tempfile.gettempdir()) / "geovision-e2e-samples")
    )
    try:
        return run(args.server, samples)
    except httpx.ConnectError:
        print(f"Could not reach {args.server}. Start the API with `.\\dev.ps1 api`.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
