/**
 * The anonymous visitor's journey — spec section A, in full, with no account.
 *
 * Runs against a freshly seeded database (`.\dev.ps1 seed`): the assertions
 * below are about *what a visitor is told*, not implementation detail, which
 * is the same principle the component tests in `dashboard/src/app/public.
 * test.tsx` follow — this suite exists to prove the same promises hold true
 * through a real browser, a real network, and a real backend, not just
 * against a mocked API.
 */
import { expect, test } from '@playwright/test';
import { SEEDED_PRIVATE_PROJECT, SEEDED_PUBLIC_PROJECT } from './seed-data';

test.describe('visitor journey', () => {
  test('browses the public feed and finds a seeded project', async ({ page }) => {
    await page.goto('/');
    await expect(page.getByRole('heading', { name: 'Monitored projects' })).toBeVisible();

    const link = page.getByRole('link', { name: SEEDED_PUBLIC_PROJECT.name });
    await expect(link).toBeVisible();
    await expect(link).toHaveAttribute('href', `/projects/${SEEDED_PUBLIC_PROJECT.code}`);
  });

  test('opens a project and sees the progress estimate disclaimer', async ({ page }) => {
    await page.goto(`/projects/${SEEDED_PUBLIC_PROJECT.code}`);

    await expect(page.getByRole('heading', { name: SEEDED_PUBLIC_PROJECT.name })).toBeVisible();
    // The AI-estimate framing is a promise the system makes on every surface
    // that shows a progress figure (ADR-007) — checked here, not just in the
    // component test, because it is the footer's job to always be present,
    // and only a full page render proves the layout actually includes it.
    await expect(page.getByText(/progress figures are estimates/i)).toBeVisible();
  });

  test('a private project reads as unavailable, not as an error', async ({ page }) => {
    const response = await page.goto(`/projects/${SEEDED_PRIVATE_PROJECT.code}`);
    // The API answers 404 for a private project to an anonymous caller
    // (Domain-Model.md — visibility enforcement); the page must not leak
    // that the project exists by rendering its name anywhere.
    expect(response?.status()).toBeLessThan(500);
    await expect(page.getByText(SEEDED_PRIVATE_PROJECT.name)).toHaveCount(0);
    await expect(page.getByText(/not available/i)).toBeVisible();
  });

  test('searches by project name', async ({ page }) => {
    await page.goto('/search');
    await page.getByPlaceholder(/search owners, projects, or locations/i).fill('Jollibee');
    await expect(page.getByRole('link', { name: SEEDED_PUBLIC_PROJECT.name })).toBeVisible();
  });

  test('reaches the contact form without an account', async ({ page }) => {
    await page.goto('/contact');
    await expect(page.getByRole('heading', { name: 'Contact us' })).toBeVisible();
  });
});
