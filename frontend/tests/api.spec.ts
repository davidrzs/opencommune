import { test, expect } from '@playwright/test';

test.use({ permissions: ['clipboard-read', 'clipboard-write'] });

test('API page: MCP snippet and a self-hosted reference that sends requests only here', async ({
  page,
  baseURL
}) => {
  const errors: string[] = [];
  const requests: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  page.on('request', (request) => requests.push(request.url()));
  const origin = new URL(baseURL!).origin;

  await page.goto('/de');
  await page.getByRole('link', { name: 'API', exact: true }).click();
  await expect(page).toHaveURL(/\/de\/api$/);
  await expect(page.getByRole('link', { name: 'API', exact: true })).toHaveAttribute(
    'aria-current',
    'page'
  );
  await expect(page.locator('h1')).toHaveText('API');
  await expect(page.locator('.api-page')).toContainText('ohne Schlüssel und ohne Konto');
  await expect(page.locator('.api-page')).toContainText('CC0 1.0');
  await expect(page.locator('.api-page')).toContainText('[name]');

  // the MCP address and a configuration built from this page's origin
  await expect(page.locator('.mcp p code')).toHaveText(`${origin}/mcp`);
  const snippet = JSON.parse((await page.locator('.snippet code').textContent()) ?? '');
  expect(snippet).toEqual({ mcpServers: { tractanda: { url: `${origin}/mcp` } } });
  await page.locator('.snippet button').click();
  await expect(page.locator('.snippet button')).toHaveText('Kopiert');
  expect(JSON.parse(await page.evaluate(() => navigator.clipboard.readText()))).toEqual(snippet);

  // the reference, from /api/openapi.json, with Scalar's German interface
  await expect(page.locator('.scalar-app').getByText('Tractanda API').first()).toBeVisible({
    timeout: 20000
  });
  await expect(page.locator('a[href^="https://client.scalar.com"]:visible')).toHaveCount(0);

  // "try it": the request goes to this origin
  await page.getByRole('button', { name: /Request testen.*get \/api\/documents\)/ }).click();
  const sent = page.waitForRequest((r) => r.url().startsWith(`${origin}/api/documents?`));
  await page.getByRole('button', { name: /get-Anfrage an .*\/api\/documents senden/ }).click();
  await sent;
  await page.waitForLoadState('networkidle');
  expect(requests.filter((url) => !url.startsWith(origin) && !/^(data|blob):/.test(url))).toEqual(
    []
  );
  await page.keyboard.press('Escape');

  // leaving the page: Scalar's styles do not change the site's own tokens
  await page.getByRole('link', { name: 'Gemeinden', exact: true }).click();
  await expect(page.locator('.coverage-count')).toBeVisible();
  const tokens = await page.evaluate(() => {
    const root = getComputedStyle(document.documentElement);
    return ['--brand', '--radius', '--foreground'].map((t) => root.getPropertyValue(t).trim());
  });
  // the built CSS writes 0.5rem as .5rem
  expect(tokens).toEqual(['#b3121c', '.5rem', '#18181b']);
  expect(errors).toEqual([]);
});

test('other pages do not load the reference', async ({ page, request }) => {
  const scripts: string[] = [];
  page.on('request', (r) => {
    if (r.resourceType() === 'script' || r.resourceType() === 'stylesheet') scripts.push(r.url());
  });
  for (const path of ['/de', '/de/gemeinden/121', '/de/suche', '/de/ueber-uns']) {
    await page.goto(path);
    await page.waitForLoadState('networkidle');
  }
  expect(scripts.length).toBeGreaterThan(0);
  for (const url of scripts) {
    expect(await (await request.get(url)).text()).not.toContain('scalar-api-reference');
  }
});

test('API page in French and Italian, and on a phone', async ({ page }) => {
  await page.goto('/fr/api');
  await expect(page.locator('.api-page')).toContainText('sans clé ni compte');
  await expect(page.locator('.scalar-app').getByText('Tractanda API').first()).toBeVisible({
    timeout: 20000
  });
  await page.getByRole('link', { name: 'IT', exact: true }).click();
  await expect(page).toHaveURL(/\/it\/api$/);
  await expect(page.locator('.api-page')).toContainText('senza chiave e senza account');
  await expect(page.locator('.scalar-app').getByText('Tractanda API').first()).toBeVisible({
    timeout: 20000
  });
  await page.setViewportSize({ width: 390, height: 844 });
  expect(
    await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)
  ).toBeTruthy();
});
