/**
 * Load test for the anonymous read path: the public feed and a project
 * folder. No pairing, no signing, no auth — runnable the moment the stack
 * and a seeded database are up, unlike `ingest.js`. Exists because the
 * ingest path is not the only one with a latency target
 * (`Master-Architecture.md` §9's "API p50/p95 latency" is general), and it
 * is also the highest-traffic path in practice: every anonymous visitor to
 * the homepage hits exactly this.
 *
 * Run:
 *
 *     k6 run tests/load/api-read.js -e GV_BASE_URL=http://localhost:8000 --vus 20 --duration 30s
 */
import http from 'k6/http';
import { check, sleep } from 'k6';

const BASE_URL = __ENV.GV_BASE_URL || 'http://localhost:8000';
// Matches `scripts/seed_db.py` — see `tests/e2e/seed-data.ts` for the same constant on the TS side.
const SEEDED_PROJECT_CODE = 'NG_00';

export const options = {
  thresholds: {
    http_req_duration: ['p(50)<200', 'p(95)<800'],
    http_req_failed: ['rate<0.01'],
  },
};

export default function () {
  const feed = http.get(`${BASE_URL}/api/v1/public/feed`);
  check(feed, { 'feed: 200': (r) => r.status === 200 });

  const project = http.get(`${BASE_URL}/api/v1/public/projects/${SEEDED_PROJECT_CODE}`);
  check(project, { 'project folder: 200': (r) => r.status === 200 });

  sleep(1);
}
