/**
 * The signed-in owner's journey: sign in, create a project, open the pairing
 * modal, sign out. The camera itself is never involved — `scripts/
 * simulate_device.py` is what stands in for hardware end to end (see
 * `Module-13-Firmware.md`); this test only proves the *human* half of
 * pairing works, up to and including the code being generated and shown.
 */
import { expect, test } from '@playwright/test';
import { SEEDED_USER } from './seed-data';

/** A random, low-collision project code — `^[A-Z]{2,5}_[0-9]{2}$` (Naming-Conventions.md). */
function randomProjectCode(): { initials: string; number: string } {
  const letters = Array.from({ length: 4 }, () =>
    String.fromCharCode(65 + Math.floor(Math.random() * 26)),
  ).join('');
  const number = String(Math.floor(Math.random() * 100)).padStart(2, '0');
  return { initials: letters, number };
}

test.describe('owner journey', () => {
  test('signs in, creates a project, and can open the pairing modal', async ({ page }) => {
    await page.goto('/login');
    await page.getByLabel(/username or email/i).fill(SEEDED_USER.username);
    await page.getByLabel(/^password$/i).fill(SEEDED_USER.password);
    await page.getByRole('button', { name: /sign in/i }).click();

    await expect(page).toHaveURL(/\/me$/);
    await expect(page.getByRole('heading', { name: 'My projects' })).toBeVisible();

    await page.getByRole('link', { name: 'Create project' }).click();
    await expect(page.getByRole('heading', { name: 'Create a project' })).toBeVisible();

    const { initials, number } = randomProjectCode();
    const projectName = `E2E Test Site ${initials}`;
    await page.getByLabel('Project name').fill(projectName);
    await page.getByLabel('Location').fill('Naga City');
    await page.getByLabel('Initials').fill(initials);
    await page.getByLabel('Number').fill(number);
    await page.getByLabel('Start date').fill('2026-01-01');
    await page.getByLabel('Deadline').fill('2026-12-31');
    await expect(page.getByText(`${initials}_${number}`)).toBeVisible(); // the live code preview

    await page.getByRole('button', { name: 'Create project' }).click();
    await expect(page).toHaveURL(/\/projects\/.+\/manage$/);
    await expect(page.getByRole('heading', { name: projectName })).toBeVisible();

    await page.getByRole('button', { name: /pair a camera/i }).click();
    await expect(page.getByRole('dialog', { name: /pair an esp32 camera/i })).toBeVisible();
    await expect(page.getByText(/which face of the site/i)).toBeVisible();
    await page.getByRole('button', { name: /close/i }).click();
  });

  test('signs out and loses access to the owner surface', async ({ page }) => {
    await page.goto('/login');
    await page.getByLabel(/username or email/i).fill(SEEDED_USER.username);
    await page.getByLabel(/^password$/i).fill(SEEDED_USER.password);
    await page.getByRole('button', { name: /sign in/i }).click();
    await expect(page).toHaveURL(/\/me$/);

    await page.getByRole('button', { name: /sign out/i }).click();
    await page.goto('/me');
    await expect(page).toHaveURL(/\/login$/);
  });
});
