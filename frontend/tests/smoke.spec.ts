import { test, expect } from '@playwright/test';
test('map, commune navigation, original sources and language continuity', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', (e) => errors.push(e.message));
  await page.goto('/de');
  await expect(
    page.getByRole('heading', { name: 'Die Schweiz. Gemeinde für Gemeinde.' })
  ).toBeVisible();
  await expect(page.locator('.atlas-map svg a').first()).toHaveAttribute(
    'href',
    /\/de\/gemeinden\/\d+/
  );
  await page.screenshot({ path: 'test-results/home-desktop.png', fullPage: true });
  await page.getByLabel('Gemeinde finden').fill('Wetzikon');
  await page.locator('.suggestions a').first().click();
  await expect(page.getByRole('heading', { name: 'Wetzikon.' })).toBeVisible();
  await page.locator('.tabs a').nth(1).click();
  await expect(page.locator('.document-row .text-link').first()).toHaveAttribute(
    'href',
    /^https?:.*#page=/
  );
  await page.getByRole('link', { name: 'FR', exact: true }).click();
  await expect(page).toHaveURL(/\/fr\/gemeinden\/121\?tab=decisions/);
  await expect(page.locator('html')).toHaveAttribute('lang', 'fr');
  await expect(page.locator('.tabs a').nth(1)).toContainText('Décisions');
  await page.locator('.tabs a').first().click();
  await expect(page.getByPlaceholder('Rechercher dans les titres …')).toBeVisible();
  expect((await page.locator('.mini-map svg').boundingBox())!.width).toBeGreaterThan(200);
  await page.screenshot({ path: 'test-results/commune-desktop.png', fullPage: false });
  await page.getByRole('link', { name: 'IT', exact: true }).click();
  await expect(page.locator('html')).toHaveAttribute('lang', 'it');
  await expect(page.locator('.tabs a').first()).toContainText('Documenti');
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/it');
  await expect(
    page.getByRole('heading', { name: 'La Svizzera. Comune per comune.' })
  ).toBeVisible();
  expect(
    await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)
  ).toBeTruthy();
  await page.screenshot({ path: 'test-results/home-mobile.png', fullPage: true });
  expect(errors).toEqual([]);
});
