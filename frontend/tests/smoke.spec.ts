import { test, expect } from '@playwright/test';
test('map, commune navigation, document list, original sources and language continuity', async ({
  page
}) => {
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
  await expect(page.locator('.index-intro h2')).toContainText('Dokumente aus');
  await page.screenshot({ path: 'test-results/home-desktop.png', fullPage: true });
  await page.getByLabel('Gemeinde finden').fill('Wetzikon');
  await page.locator('.suggestions a').first().click();
  await expect(page.getByRole('heading', { name: 'Wetzikon.' })).toBeVisible();
  await expect(page.locator('.document-row .text-link').first()).toHaveAttribute(
    'href',
    /^\/original\/[0-9a-f]{64}\?commune=121$/
  );
  // the first section type with files narrows the list and goes into the URL
  const section = page.getByLabel('Teil', { exact: true });
  const value = await section.locator('option:not([disabled])').nth(1).getAttribute('value');
  await section.selectOption(value!);
  await expect(page).toHaveURL(new RegExp(`/de/gemeinden/121\\?section=${value}$`));
  await expect(page.locator('.document-row').first()).toBeVisible();
  await page.getByRole('link', { name: 'FR', exact: true }).click();
  await expect(page).toHaveURL(new RegExp(`/fr/gemeinden/121\\?section=${value}$`));
  await expect(page.locator('html')).toHaveAttribute('lang', 'fr');
  await expect(page.getByPlaceholder('Rechercher dans les titres …')).toBeVisible();
  await expect(page.getByLabel('Partie', { exact: true })).toHaveValue(value!);
  expect((await page.locator('.mini-map svg').boundingBox())!.width).toBeGreaterThan(200);
  await page.screenshot({ path: 'test-results/commune-desktop.png', fullPage: false });
  await page.getByRole('link', { name: 'IT', exact: true }).click();
  await expect(page.locator('html')).toHaveAttribute('lang', 'it');
  await expect(page.getByLabel('Parte', { exact: true })).toBeVisible();
  await page.goto('/de/suche');
  await expect(page.locator('.document-row .communes').first()).toBeVisible();
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
