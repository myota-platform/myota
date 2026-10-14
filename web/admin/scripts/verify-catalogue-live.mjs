import assert from 'node:assert/strict';
import { chromium } from 'playwright';

// Read a short-lived token from stdin, never argv, a saved browser profile or
// output. Only GET API calls are allowed after authentication by the operator.
const origin = new URL(process.argv[2] || 'https://admin.myota.top');
if (origin.protocol !== 'https:') throw new Error('Live checks require HTTPS.');
let input = '';
for await (const chunk of process.stdin) input += chunk;
const { accessToken } = JSON.parse(input);
if (!accessToken) throw new Error('Provide a short-lived accessToken JSON object through stdin.');
input = '';

const browser = await chromium.launch();
try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  const errors = [];
  const blockedWrites = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.addInitScript(({ token, expectedOrigin }) => {
    if (window.location.origin === expectedOrigin) localStorage.setItem('myota_admin_access', token);
  }, { token: accessToken, expectedOrigin: origin.origin });
  await page.route('**/*', route => {
    const request = route.request();
    const url = new URL(request.url());
    // DNS filtering or ingress redirects must never send the authenticated
    // browser to another origin. Tokens are installed on the intended UI only.
    if (request.isNavigationRequest() && url.origin !== origin.origin) return route.abort();
    if (url.hostname === 'tile.openstreetmap.org') return route.abort();
    if (url.pathname.startsWith('/v1/') && request.method() !== 'GET') {
      blockedWrites.push(`${request.method()} ${url.pathname}`);
      return route.abort();
    }
    return route.continue();
  });
  await page.goto(new URL('/entity-management', origin).href);
  const row = page.locator('.geo-row').first();
  await row.waitFor({ state: 'visible' });
  await row.getByRole('button').click();
  const editor = page.getByRole('dialog');
  await editor.getByLabel('Display name').waitFor({ state: 'visible' });
  await editor.getByRole('button', { name: 'Location', exact: true }).click();
  await editor.locator('.info-grid').waitFor({ state: 'visible' });
  await editor.getByRole('button', { name: 'Geometry', exact: true }).click();
  await editor.locator('.leaflet-map').waitFor({ state: 'visible' });
  assert(await editor.locator('.leaflet-control-attribution').isVisible());
  await editor.getByRole('button', { name: 'Source comparison', exact: true }).click();
  await editor.locator('.source-comparison').waitFor({ state: 'visible' });
  await editor.getByRole('button', { name: 'Audit & deletion', exact: true }).click();
  await editor.locator('.audit-list').waitFor({ state: 'visible' });
  await editor.getByRole('button', { name: 'Close', exact: true }).click();
  assert.equal(await page.getByRole('dialog').count(), 0);
  assert.deepEqual(errors, []);
  assert.deepEqual(blockedWrites, []);
  console.log(JSON.stringify({ origin: origin.origin, catalogueEditor: 'passed',
    sections: ['details', 'location', 'geometry', 'source', 'audit'],
    pageErrors: 0, attemptedApiWrites: 0, publicTilesBlocked: true }));
} finally {
  await browser.close();
}
