import { test, expect } from '@playwright/test';

test('coverage counts, hatching, keyboard access and empty commune pages', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  await page.goto('/de');
  // Hinwil and Wetzikon have files; the hatching is the register's blocked_robots
  await expect(page.locator('.coverage-count strong')).toHaveText('2');
  const empty = page.locator('.atlas-map a[href="/de/gemeinden/1"]');
  await expect(empty.locator('path[fill^="url"]')).toHaveCount(1);
  await expect(
    page.locator('.atlas-map a[href="/de/gemeinden/121"] path[fill^="url"]')
  ).toHaveCount(1);
  await expect(page.locator('.atlas-map a[href="/de/gemeinden/2"] path[fill^="url"]')).toHaveCount(
    0
  );
  await expect(page.locator('.atlas-map a[href="/de/gemeinden/3"] path[fill^="url"]')).toHaveCount(
    0
  );
  await empty.focus();
  await expect(page.locator('.map-caption')).toContainText('Sammlung teilweise eingeschränkt');
  await page.screenshot({ path: 'test-results/access-home-desktop.png', fullPage: true });
  await page.keyboard.press('Enter');
  await expect(page.locator('h1')).toHaveText('Aeugst am Albis.');
  await expect(page.locator('.access-notice')).toContainText('robots.txt');
  await page.locator('.access-notice summary').click();
  await expect(page.locator('.access-notice a').last()).toHaveAttribute(
    'href',
    'https://commune.example/robots.txt'
  );
  await expect(page.locator('.empty-state')).toContainText('noch keine Dokumente');
  await page.getByRole('link', { name: 'FR', exact: true }).click();
  await expect(page.locator('.access-notice')).toContainText('collecte automatique');
  await page.getByRole('link', { name: 'IT', exact: true }).click();
  await expect(page.locator('.access-notice')).toContainText('raccolta automatica');
  await page.setViewportSize({ width: 390, height: 844 });
  await page.locator('.access-notice summary').click();
  await page.screenshot({ path: 'test-results/access-commune-mobile.png', fullPage: true });
  expect(
    await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)
  ).toBeTruthy();
  await page.goto('/de/gemeinden/2');
  await page.locator('.access-notice summary').click();
  await expect(page.locator('.access-notice')).toContainText('begrenzt zurzeit die Anfragen');
  await page.goto('/de/gemeinden/3');
  await page.locator('.access-notice summary').click();
  await expect(page.locator('.access-notice')).toContainText('älter als sieben Tage');
  expect(errors).toEqual([]);
});

test('about page keeps language, explains limits and offers email contact', async ({ page }) => {
  await page.goto('/de/ueber-uns');
  await expect(page.locator('h1')).toHaveText('Über OpenCommune');
  await expect(page.locator('.about-page')).toContainText('ein Projekt von David Zollikofer');
  await expect(page.locator('#klassifikation')).toContainText(
    'Wie die Dokumente eingeordnet werden'
  );
  await expect(page.locator('#run-classify-65e415a748e2')).toContainText('at most 150 pages');
  await expect(page.locator('#run-classify-65e415a748e2 .run-meta')).toHaveText(
    'Modell: model-x · 25 Dokumente'
  );
  const contact = page.locator('.about-page [data-report-email]');
  await expect(contact).toHaveAttribute('href', '#report');
  await page.evaluate(() =>
    document.addEventListener('click', (event) => {
      if ((event.target as Element).closest('[data-report-email]')) event.preventDefault();
    })
  );
  await contact.click();
  await expect(contact).toHaveAttribute('href', /^mailto:.*subject=OpenCommune/);
  await expect(page.locator('.about-page .report-address')).toBeVisible();
  for (const language of ['FR', 'IT']) {
    await page.getByRole('link', { name: language, exact: true }).click();
    await expect(page).toHaveURL(new RegExp(`/${language.toLowerCase()}/ueber-uns$`));
    await expect(page.locator('.about-page')).toContainText('David Zollikofer');
  }
  await page.setViewportSize({ width: 390, height: 844 });
  expect(
    await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)
  ).toBeTruthy();
  await page.screenshot({ path: 'test-results/about-mobile.png', fullPage: true });
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto('/de/ueber-uns');
  await page.screenshot({ path: 'test-results/about-desktop.png', fullPage: true });
});
