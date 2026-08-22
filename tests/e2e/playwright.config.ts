/**
 * Playwright config for the two journeys `Module-15-Testing-and-Evaluation.md`
 * asks for: the anonymous visitor's, and the signed-in owner's.
 *
 * Deliberately does **not** start the stack itself (`webServer` is unset).
 * A visitor journey needs the dashboard; an owner journey needs the dashboard,
 * the API, a worker, and a seeded database — orchestrating four processes
 * from one config would just reimplement `.\dev.ps1 dev` worse. Instead this
 * assumes the stack is already up (`.\dev.ps1 dev`, then `.\dev.ps1 seed`)
 * and fails fast with a clear connection error if it is not, rather than
 * hanging on a `webServer` health check that can never succeed without a
 * database behind it anyway.
 */
import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: '.',
  fullyParallel: true,
  forbidOnly: !!process.env['CI'],
  retries: process.env['CI'] ? 2 : 0,
  workers: process.env['CI'] ? 1 : undefined,
  reporter: [['html', { open: 'never' }], ['list']],
  timeout: 30_000,

  use: {
    baseURL: process.env['GV_E2E_BASE_URL'] ?? 'http://localhost:5173',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
  },

  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
});
