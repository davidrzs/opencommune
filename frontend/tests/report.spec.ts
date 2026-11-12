import { test, expect } from '@playwright/test';

test('report opens a contextual draft without exposing the address in initial HTML', async ({
  page,
  request
}) => {
  const html = await (await request.get('/de/gemeinden/121')).text();
  expect(html).not.toContain('zdavid@ethz.ch');
  expect(html).not.toContain('mailto:');
  await page.goto('/de/gemeinden/121');
  await page.evaluate(() => {
    // Allow the link handler to prepare the draft, but never launch a mail client.
    window.addEventListener('click', (event) => {
      if ((event.target as Element).closest('[data-report-email]')) event.preventDefault();
    });
  });
  const report = page.locator('.document-row [data-report-email]').first();
  await expect(report).toHaveAttribute('aria-disabled', 'false');
  await report.click();
  const draft = new URL((await report.getAttribute('href'))!);
  expect(draft.protocol).toBe('mailto:');
  expect(draft.pathname).toBe('zdavid@ethz.ch');
  expect(draft.searchParams.get('subject')).toBe('OpenCommune: Problem melden');
  expect(draft.searchParams.get('body')).toContain('/de/gemeinden/121');
  expect(draft.searchParams.get('body')).toContain('Eintrag:');
  expect(draft.searchParams.get('body')).toContain('Quelle:');
  await expect(page.locator('.report-address')).toContainText('zdavid@ethz.ch');
});

test('landing coverage matches all communes with archived PDFs', async ({ page, request }) => {
  const communes = await (await request.get('/api/archive/communes')).json();
  const count = communes.filter((c: { documents: number }) => c.documents > 0).length;
  await page.goto('/de');
  await expect(page.locator('.coverage-count')).toContainText(
    new Intl.NumberFormat('de-CH').format(count)
  );
  await expect(page.locator('.coverage-count')).toContainText('Gemeinden mit Dokumenten im Archiv');
  await page.goto('/?q=Schule');
  await expect(page).toHaveURL(/\/de\/suche\?q=Schule$/);
});
