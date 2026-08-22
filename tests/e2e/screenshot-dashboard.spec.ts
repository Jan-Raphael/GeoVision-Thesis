/**
 * Consistent-viewport screenshots of every public page, for the manuscript
 * (`Thesis-Mapping.md`, Figure 12: "Dashboard screenshots (public + owner +
 * pairing modal)").
 *
 * A Playwright *test* rather than a bare script on purpose: it gets the same
 * auto-waiting, retry-on-flake, and trace-on-failure behaviour as every
 * other spec in this directory for free, and `npx playwright test
 * screenshot-dashboard` is one more command to remember, not a second
 * toolchain. The vault's original plan named a Python script
 * (`scripts/screenshot_dashboard.py`) — that would mean installing and
 * maintaining two separate browser-automation stacks (Python Playwright and
 * this one) for the same job; this file does it with the one already here.
 */
import { existsSync, mkdirSync } from 'node:fs';
import path from 'node:path';
import { test } from '@playwright/test';
import { SEEDED_PUBLIC_PROJECT } from './seed-data';

const OUT_DIR = path.resolve(import.meta.dirname, '..', '..', 'documentation', 'screenshots');

test.beforeAll(() => {
  if (!existsSync(OUT_DIR)) mkdirSync(OUT_DIR, { recursive: true });
});

test.describe('manuscript screenshots', () => {
  test.use({ viewport: { width: 1280, height: 800 } });

  const pages: { path: string; file: string }[] = [
    { path: '/', file: 'public-feed.png' },
    { path: `/projects/${SEEDED_PUBLIC_PROJECT.code}`, file: 'public-project-folder.png' },
    { path: '/search', file: 'search.png' },
    { path: '/login', file: 'sign-in.png' },
    { path: '/register', file: 'register.png' },
  ];

  for (const { path: route, file } of pages) {
    test(`captures ${route}`, async ({ page }) => {
      await page.goto(route);
      await page.waitForLoadState('networkidle');
      await page.screenshot({ path: path.join(OUT_DIR, file), fullPage: true });
    });
  }
});
