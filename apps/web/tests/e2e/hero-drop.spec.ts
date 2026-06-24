import { fileURLToPath } from 'node:url';
import { expect, test } from '@playwright/test';

// Hero-dropzone browser e2e (P1.16). The dropzone component renders publicly on
// /design-preview (the hero on the landing was redesigned to a CTA after P1.8,
// and the live dropzone sandbox is the preview route) — no auth, runs in CI.
// Component-level branches are unit-tested (HeroDropzone.test.tsx); this asserts
// the file/error flows survive in a real browser. (The paste-a-link path was
// removed — YouTube blocks our server IP — so there is no link e2e anymore.)
const SAMPLE_MP4 = fileURLToPath(new URL('../fixtures/sample.mp4', import.meta.url));
const NOT_A_VIDEO = fileURLToPath(new URL('../fixtures/not-a-video.txt', import.meta.url));

test.beforeEach(async ({ page }) => {
  await page.goto('/design-preview');
  await expect(page.locator('[data-slot="hero-dropzone"]')).toBeVisible();
});

test('dropping a video file into hero shows file chip and enables flip', async ({ page }) => {
  await page.locator('input[type="file"]').setInputFiles(SAMPLE_MP4);

  await expect(page.locator('[data-slot="file-chip"]')).toContainText('sample.mp4');

  await page.locator('[data-slot="prompt-input-submit"]').click();

  // submitted → streaming on the next tick once a valid file is flipped.
  await expect(page.locator('[data-slot="hero-dropzone"]')).toHaveAttribute(
    'data-status',
    'streaming',
  );
});

test('non-video drop shows error state', async ({ page }) => {
  await page.locator('input[type="file"]').setInputFiles(NOT_A_VIDEO);

  // Scope to the dropzone's own alert — Next renders a separate empty
  // role="alert" route announcer that would make a bare getByRole ambiguous.
  await expect(
    page.locator('[data-slot="hero-dropzone"]').getByRole('alert'),
  ).toContainText('видеофайл');
  await expect(page.locator('[data-slot="hero-dropzone"]')).toHaveAttribute(
    'data-status',
    'error',
  );
});
