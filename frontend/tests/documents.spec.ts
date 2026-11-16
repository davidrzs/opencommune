import { test, expect } from '@playwright/test';

// Against the offline fixture (tests/access-fixture.py): Wetzikon (121) has 25 files, one of them
// shared with Hinwil (117).
const sha = (n: number) => n.toString(16).padStart(64, '0');

test('commune page lists files with their contents, strips and data request', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  await page.goto('/de/gemeinden/121');
  await expect(page.locator('h1')).toHaveText('Wetzikon');
  await expect(page.locator('.list-note')).toContainText('nicht von Personen geprüft');
  await expect(page.locator('.result-count')).toHaveText(/^25\s+Ergebnisse/);
  const rows = page.locator('.document-row');
  await expect(rows).toHaveCount(20);

  // a meeting booklet: printed title, body as printed, contents line, strip and linked chips
  const booklet = rows.first();
  await expect(booklet.locator('.document-date')).toHaveText('12. Juni 2025');
  await expect(booklet.locator('.document-meta')).toHaveText(
    'Gemeindeversammlung Wetzikon · 40 Seiten'
  );
  await expect(booklet.locator('h2')).toHaveText('Einladung zur Gemeindeversammlung');
  await expect(booklet.locator('.contains')).toHaveText(
    'Enthält: Einladung und Traktanden, 2 × Antrag, Protokoll, Budget'
  );
  await expect(booklet.locator('.strip .segment')).toHaveCount(5);
  const budget = booklet.locator('.strip .segment').nth(4);
  await expect(budget).toHaveAttribute('title', 'Budget, S. 13–40');
  await expect(budget).toHaveAttribute('href', `/original/${sha(1)}?commune=121&page=13`);
  await expect(budget).toHaveAttribute('style', /left: 30%; width: 70%/);
  await expect(booklet.locator('.sections a')).toHaveText([
    'Einladung und Traktanden S. 1–2',
    'Antrag S. 3–6',
    'Antrag S. 7–10',
    'Protokoll S. 11–12',
    'Budget S. 13–40'
  ]);
  await expect(booklet.locator('.sections a').nth(4)).toHaveClass(/family-money/);
  await expect(booklet.locator('.sections a').first()).toHaveAttribute(
    'href',
    `/original/${sha(1)}?commune=121&page=1`
  );
  await expect(booklet.locator('.text-link')).toHaveAttribute(
    'href',
    `/original/${sha(1)}?commune=121`
  );
  await expect(booklet.locator('.language')).toHaveCount(0);
  await expect(booklet.locator('.match')).toHaveCount(0);

  // a French bulletin: language badge, news left out of the contents line, fiscal year
  const bulletin = rows.nth(1);
  await expect(bulletin.locator('.document-date')).toHaveText('Rechnungsjahr 2024');
  await expect(bulletin.locator('.language')).toHaveText(['FR']);
  await expect(bulletin.locator('.contains')).toHaveText('Enthält: Budget');

  // no printed title: the largest section and the year; two languages; pages not seen
  const accounts = rows.nth(2);
  await expect(accounts.locator('h2')).toHaveText('Jahresrechnung 2024');
  await expect(accounts.locator('.language')).toHaveText(['DE', 'FR']);
  await expect(accounts.locator('.strip .segment.unseen')).toHaveCount(1);
  await expect(accounts.locator('.unseen-mark')).toHaveAttribute('title', /höchstens 150 Seiten/);
  await expect(accounts.locator('.unseen-note')).toContainText('teilweise nicht vom Klassifikator');
  await expect(accounts.locator('.communes')).toHaveText(/Gemeinden: Hinwil\s+ZH, Wetzikon\s+ZH/);

  // one section: no contents line, no strip; a year without a date
  const regulation = rows.nth(3);
  await expect(regulation.locator('.document-date')).toHaveText('2023');
  await expect(regulation.locator('.contains')).toHaveCount(0);
  await expect(regulation.locator('.strip')).toHaveCount(0);
  await expect(regulation.locator('.sections a')).toHaveText(['Reglement S. 1–12']);
  await expect(page.locator('body')).not.toContainText('personal');

  // the request behind the list
  await expect(page.locator('.as-data code')).toHaveText(
    'GET /api/documents?commune=121&offset=0&limit=20'
  );
  await expect(page.getByRole('link', { name: 'JSON ↗' })).toHaveAttribute(
    'href',
    '/api/documents?commune=121&offset=0&limit=20'
  );
  await expect(page.getByRole('link', { name: 'Zur API' })).toHaveAttribute('href', '/de/api');

  // the last page holds the file with nothing read
  await page.getByRole('link', { name: 'Weiter →' }).click();
  await expect(page).toHaveURL(/\?offset=20$/);
  await expect(rows).toHaveCount(5);
  await expect(rows.last().locator('.document-date')).toHaveText('Ohne Datumsangabe');
  await expect(rows.last().locator('h2')).toHaveText('Dokument');
  await page.getByRole('link', { name: '← Zurück' }).click();
  await expect(page).toHaveURL(/\/de\/gemeinden\/121$/);
  expect(errors).toEqual([]);
});

test('selectors, content view and holdings chart', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  await page.goto('/de/gemeinden/121');
  const rows = page.locator('.document-row');
  await expect(page.getByLabel('Dokumentart', { exact: true })).toHaveCount(0);
  await expect(page.locator('.document-filters select')).toHaveCount(3);

  // section selector: counts, URL, and the matching sections as lines of their own
  const section = page.getByLabel('Teil', { exact: true });
  await expect(section.locator('option', { hasText: 'Budget' })).toHaveText('Budget (9)');
  await expect(page.getByLabel('Jahr', { exact: true }).locator('option[disabled]')).toHaveText(
    'ohne Angabe (1)'
  );
  await section.selectOption('budget');
  await expect(page).toHaveURL(/\/de\/gemeinden\/121\?section=budget$/);
  await expect(page.locator('.result-count')).toHaveText(/^9\s+Ergebnisse/);
  await expect(rows.first().locator('.match')).toHaveText(
    /Budget · S\. 13–40 · bei S\. 13 öffnen ↗/
  );
  await expect(rows.first().locator('.match a')).toHaveAttribute(
    'href',
    `/original/${sha(1)}?commune=121&page=13`
  );
  await expect(page.locator('.as-data code')).toHaveText(
    'GET /api/documents?commune=121&section=budget&offset=0&limit=20'
  );
  const body = page.getByLabel('Gremium', { exact: true });
  await expect(body.locator('option', { hasText: 'Stimmberechtigte' })).toHaveText(
    'Stimmberechtigte (4)'
  );
  await body.selectOption('citizens_assembly');
  await expect(page).toHaveURL(/section=budget&body=citizens_assembly$/);
  await expect(rows).toHaveCount(4);
  await expect(section.locator('option', { hasText: 'Protokoll' })).toHaveText('Protokoll (8)');
  await page.getByRole('link', { name: 'Filter zurücksetzen' }).first().click();
  await expect(page).toHaveURL(/\/de\/gemeinden\/121$/);

  // the text field matches printed titles
  await page.getByLabel('Dokumenttitel durchsuchen …').fill('reglement');
  await page.getByLabel('Dokumenttitel durchsuchen …').press('Enter');
  await expect(page).toHaveURL(/\?q=reglement$/);
  await expect(rows).toHaveCount(1);

  // holdings: a chart of pages per year, stacked by family; a segment sets year and family
  await page.goto('/de/gemeinden/121');
  await expect(page.locator('.holdings')).toContainText('Seiten pro Jahr');
  await page.locator('.holdings [aria-label^="2024:"] [data-family="money"]').first().click();
  await expect(page).toHaveURL(/\/de\/gemeinden\/121\?year=2024&family=money$/);
  await expect(rows).toHaveCount(2);
  await expect(page.locator('.active-family')).toContainText('Familie: Finanzen');
  await expect(rows.locator('.match')).toHaveText([
    /Budget · S\. 9–12/,
    /Jahresrechnung · S\. 1–150/
  ]);
  // the family stays when another selector changes, and goes with its ×
  await page.getByLabel('Teil', { exact: true }).selectOption('budget');
  await expect(page).toHaveURL(/section=budget&family=money&year=2024$/);
  await expect(rows).toHaveCount(1);
  await page.getByRole('link', { name: 'Filter entfernen' }).click();
  await expect(page).toHaveURL(/\?section=budget&year=2024$/);

  // in documents a column counts each document once, by its first part, and so does the list
  await page.goto('/de/gemeinden/121');
  await page.locator('.holdings').getByRole('button', { name: 'Dokumente' }).click();
  const year = page.locator('.holdings [aria-label^="2024:"]');
  const counted = Number((await year.getAttribute('aria-label'))?.match(/Finanzen (\d+)/)?.[1]);
  await year.locator('[data-family="money"]').first().click();
  await expect(page).toHaveURL(/\/de\/gemeinden\/121\?year=2024&first_family=money$/);
  await expect(page.locator('.active-family')).toContainText('Erster Teil: Finanzen');
  await expect(rows).toHaveCount(counted);

  // a filtered view keeps its query in the other languages
  await page.goto('/de/gemeinden/121?section=budget&year=2025');
  await expect(rows).toHaveCount(1);
  await page.getByRole('link', { name: 'FR', exact: true }).click();
  await expect(page).toHaveURL(/\/fr\/gemeinden\/121\?section=budget&year=2025$/);
  await expect(rows.first().locator('.contains')).toHaveText(
    'Contient : Convocation et ordre du jour, 2 × Préavis, Procès-verbal, Budget'
  );
  await expect(rows.first().locator('.match')).toContainText('ouvrir à la p. 13');
  await expect(page.getByLabel('Partie', { exact: true })).toHaveValue('budget');
  await page.getByRole('link', { name: 'IT', exact: true }).click();
  // the chart's legend in Italian
  await expect(page.locator('.holdings')).toContainText('Sedute e votazioni');
  await expect(page.locator('.as-data span')).toHaveText('Questo elenco come dati:');
  await page.screenshot({ path: 'test-results/documents-commune-desktop.png', fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  expect(
    await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)
  ).toBeTruthy();
  await page.screenshot({ path: 'test-results/documents-commune-mobile.png', fullPage: true });
  expect(errors).toEqual([]);
});

test('search lists every commune; the start page gives no document total', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  await page.goto('/de/suche');
  await expect(page.locator('.result-count')).toHaveText(/^25\s+Ergebnisse/);
  const rows = page.locator('.document-row');
  await expect(rows.first().locator('.communes')).toHaveText(/Gemeinde: Wetzikon\s+ZH/);
  await expect(rows.nth(2).locator('.communes')).toHaveText(
    /Gemeinden: Hinwil\s+ZH, Wetzikon\s+ZH/
  );
  // the same file at the first commune's address
  await expect(rows.nth(2).locator('.text-link')).toHaveAttribute(
    'href',
    `/original/${sha(2)}?commune=117`
  );
  await expect(page.locator('.holdings')).toHaveCount(0);
  await expect(page.locator('.as-data code')).toHaveText('GET /api/documents?offset=0&limit=20');
  await page.getByLabel('Jahr', { exact: true }).selectOption('2024');
  await expect(page).toHaveURL(/\/de\/suche\?year=2024$/);
  await expect(rows).toHaveCount(2);
  await page.screenshot({ path: 'test-results/documents-search-desktop.png', fullPage: true });

  // the start page counts communes only, below a thousand exactly
  await page.goto('/de');
  await expect(page.locator('h1 + p')).toContainText('aus 2 Gemeinden');
  await expect(page.locator('main section').first()).not.toContainText(/\d Dokumente/);
  await page.goto('/fr');
  await expect(page.locator('h1 + p')).toContainText('de 2 communes');
  expect(errors).toEqual([]);
});
