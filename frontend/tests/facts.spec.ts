import { expect, test, type Page } from '@playwright/test';

// The page as the server sends it: its title and fact sheet for crawlers (server/src/site.rs).
async function asServed(page: Page) {
  await page.route('**/de/gemeinden/261', async (route) => {
    const response = await route.fetch();
    const html = (await response.text())
      .replace(
        '</head>',
        '<title>Zürich: Protokolle — Tractanda</title>' +
          "<script>document.documentElement.classList.add('js')</script>" +
          '<style>.js #oc-facts{display:none}</style></head>'
      )
      .replace(/<body([^>]*)>/, '<body$1><main id="oc-facts"><h1>Zürich</h1><p>Fakten</p></main>');
    await route.fulfill({ response, body: html });
  });
}

test('with the API the app replaces the fact sheet', async ({ page }) => {
  await asServed(page);
  await page.goto('/de/gemeinden/261');
  await expect(page.locator('h1')).toContainText('Zürich');
  await expect(page.locator('#oc-facts')).toHaveCount(0);
});

test('without the API, as for crawlers kept off /api/, the fact sheet and title stay', async ({
  page
}) => {
  await page.route('**/api/**', (route) => route.abort());
  await asServed(page);
  await page.goto('/de/gemeinden/261');
  await expect(page.locator('#oc-facts')).toBeVisible();
  await expect(page.locator('#oc-facts h1')).toHaveText('Zürich');
  await expect(page).toHaveTitle('Zürich: Protokolle — Tractanda');
  await expect(page.locator('.error-page')).toHaveCount(0);
});
