/**
 * Load test for the ingest path: `POST /api/v1/ingest/images`, HMAC-signed,
 * exactly the way a real ESP32-CAM signs it — this is the same canonical
 * string and the same hand-built multipart body as
 * `backend/scripts/simulate_device.py`, ported to k6 rather than reused,
 * because the signature covers the **raw body bytes**: whatever assembles
 * the multipart body has to be the same thing that hashes it, and k6's own
 * multipart helper does not expose the exact bytes it is about to send.
 *
 * Needs a real paired device (`.\dev.ps1 dev`, pair a camera from the
 * dashboard or `scripts/simulate_device.py --code ...`, then read its
 * `device_id`/`device_secret` — printed once at pairing time and not
 * recoverable afterwards, per `Device-Pairing-Protocol.md`).
 *
 * Run:
 *
 *     k6 run tests/load/ingest.js \
 *       -e GV_BASE_URL=http://localhost:8000 \
 *       -e GV_DEVICE_ID=<uuid> \
 *       -e GV_DEVICE_SECRET=<base64url secret> \
 *       --vus 5 --duration 30s
 *
 * Targets checked against `Master-Architecture.md` §9: ingest accepted
 * (201/200-duplicate) and p95 latency, printed in the end-of-run summary.
 */
import http from 'k6/http';
import crypto from 'k6/crypto';
import { check } from 'k6';
import { Trend } from 'k6/metrics';

const BASE_URL = __ENV.GV_BASE_URL || 'http://localhost:8000';
const DEVICE_ID = __ENV.GV_DEVICE_ID;
const DEVICE_SECRET = __ENV.GV_DEVICE_SECRET;
const PATH = '/api/v1/ingest/images';
const BOUNDARY = 'geovision-loadtest-boundary';

// The fixture is opened once at init time (k6 requires `open()` outside the
// default function) and reused across every iteration — content does not
// matter for a throughput test, only that it is a valid, roughly
// realistic-sized JPEG.
const IMAGE_BYTES = open('./fixtures/sample.jpg', 'b');

const ingestLatency = new Trend('gv_ingest_duration_ms', true);

function assertConfigured() {
  if (!DEVICE_ID || !DEVICE_SECRET) {
    throw new Error(
      'GV_DEVICE_ID and GV_DEVICE_SECRET are required — pair a device first ' +
        '(see the module docstring for how).',
    );
  }
}

/** UTF-8 encode an ASCII-only string into a byte array — every literal part of the body is ASCII. */
function asciiBytes(text) {
  const bytes = new Uint8Array(text.length);
  for (let i = 0; i < text.length; i++) bytes[i] = text.charCodeAt(i);
  return bytes;
}

function concatBytes(chunks) {
  const total = chunks.reduce((sum, chunk) => sum + chunk.byteLength, 0);
  const out = new Uint8Array(total);
  let offset = 0;
  for (const chunk of chunks) {
    out.set(new Uint8Array(chunk), offset);
    offset += chunk.byteLength;
  }
  return out;
}

/**
 * Hand-assembled multipart body — byte-for-byte what `build_multipart` in
 * `simulate_device.py` produces, because the signature has to cover exactly
 * what is sent.
 */
function buildMultipartBody(imageBytes, meta) {
  const metaJson = JSON.stringify(meta);
  const parts = [
    asciiBytes(`--${BOUNDARY}\r\n`),
    asciiBytes('Content-Disposition: form-data; name="meta"\r\n\r\n'),
    asciiBytes(metaJson),
    asciiBytes('\r\n'),
    asciiBytes(`--${BOUNDARY}\r\n`),
    asciiBytes('Content-Disposition: form-data; name="file"; filename="capture.jpg"\r\n'),
    asciiBytes('Content-Type: image/jpeg\r\n\r\n'),
    imageBytes,
    asciiBytes('\r\n'),
    asciiBytes(`--${BOUNDARY}--\r\n`),
  ];
  return concatBytes(parts);
}

function randomNonce() {
  const alphabet = '0123456789abcdef';
  let nonce = '';
  for (let i = 0; i < 16; i++) {
    nonce += alphabet[Math.floor(Math.random() * alphabet.length)];
  }
  return nonce;
}

/** `HMAC_SHA256(device_secret, "METHOD\nPATH\nTIMESTAMP\nNONCE\nsha256(body)")` (Device-Pairing-Protocol.md). */
function signedHeaders(method, path, body) {
  const timestamp = Math.floor(Date.now() / 1000);
  const nonce = randomNonce();
  const bodyHash = crypto.sha256(body.buffer, 'hex');
  const canonical = [method.toUpperCase(), path, String(timestamp), nonce, bodyHash].join('\n');
  const signature = crypto.hmac('sha256', DEVICE_SECRET, canonical, 'hex');

  return {
    'X-Device-Id': DEVICE_ID,
    'X-Timestamp': String(timestamp),
    'X-Nonce': nonce,
    'X-Signature': signature,
  };
}

export const options = {
  thresholds: {
    // Master-Architecture.md §9: ingest -> dashboard update < 10s end to end;
    // this measures only the ingest leg, so it is held to a tighter bound.
    gv_ingest_duration_ms: ['p(95)<2000'],
    http_req_failed: ['rate<0.01'],
  },
};

export default function () {
  assertConfigured();

  const meta = {
    captured_at: new Date().toISOString(),
    sha256: crypto.sha256(IMAGE_BYTES.buffer, 'hex'),
    latitude: 13.6218 + (Math.random() - 0.5) * 1e-4,
    longitude: 123.1948 + (Math.random() - 0.5) * 1e-4,
    gps_accuracy_m: 4.2,
    satellites: 9,
    battery_mv: 3900,
    rssi_dbm: -58,
    seq_hint: __ITER + 1,
  };

  const body = buildMultipartBody(IMAGE_BYTES, meta);
  const headers = {
    ...signedHeaders('POST', PATH, body),
    'Content-Type': `multipart/form-data; boundary=${BOUNDARY}`,
  };

  const response = http.post(`${BASE_URL}${PATH}`, body.buffer, { headers });
  ingestLatency.add(response.timings.duration);

  check(response, {
    'accepted (201) or idempotent duplicate (200)': (r) => r.status === 201 || r.status === 200,
  });
}
