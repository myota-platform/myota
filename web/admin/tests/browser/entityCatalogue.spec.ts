import { expect, test } from '@playwright/test';
import type { GeoEntity } from '../../src/types';

// Real Vue, Leaflet and Geoman with isolated HTTP fixtures: no live mutations
// or public tile traffic are used to qualify presentation/state transitions.
const submittedProposals: any[] = [];
const submittedEntityWrites: Array<{ path: string; method: string; payload: any }> = [];

test.beforeEach(async ({ page }) => {
  submittedProposals.length = 0;
  submittedEntityWrites.length = 0;
  const entities: GeoEntity[] = [
    { id: 'park-1', name: 'Parque del Alamillo', website: 'https://alamillo.example', description: 'Riverside park', status: 'CANDIDATE', version: 1,
      entityTypes: ['PARK'], geometry: { type: 'Polygon', coordinates: [[
        [-5.995, 37.415], [-5.985, 37.415], [-5.985, 37.425], [-5.995, 37.415],
      ]] }, location: { country: 'Spain', city: 'Sevilla' } },
    { id: 'park-2', name: 'Parque de María Luisa', status: 'APPROVED', version: 1,
      entityTypes: ['PARK'], geometry: { type: 'Point', coordinates: [-5.986, 37.374] } },
    { id: 'park-3', name: 'Retired park', status: 'RETIRED', version: 1,
      entityTypes: ['PARK'], geometry: { type: 'Point', coordinates: [-5.98, 37.37] } },
  ];
  const jobs = new Map<string, { id: string; entityId: string; status: string; impact: object }>();
  await page.addInitScript(() => localStorage.setItem('myota_admin_access', 'browser-test-token'));
  await page.route('https://tile.openstreetmap.org/**', route => route.abort());
  await page.route('**/v1/**', async route => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    let body: unknown = {};
    if (path === '/v1/identity/me') body = { id: 'test-admin', roles: [{ role: 'GLOBAL_OPERATOR' }] };
    else if (path === '/v1/programmes') body = { items: [] };
    else if (path === '/v1/entity-types') body = { items: [{ code: 'PARK', label: 'Park' }, { code: 'NATURE_RESERVE', label: 'Nature reserve' }] };
    else if (path === '/v1/geodata/location-options') body = { continents: [] };
    else if (path === '/v1/geodata/entities') body = { items: entities, total: entities.length };
    else if (path.startsWith('/v1/geodata/entities/')) {
      const id = path.split('/')[4];
      const entity = entities.find(item => item.id === id)!;
      if (path.endsWith('/audit')) body = { items: [{ action: 'ENTITY_CREATED', note: 'Fixture audit' }] };
      else {
        if (request.method() !== 'GET') {
          expect(request.headers()['if-match']).toBeDefined();
          const payload = request.postDataJSON();
          submittedEntityWrites.push({ path, method: request.method(), payload });
          if (payload.name) entity.name = payload.name;
          if ('website' in payload) entity.website = payload.website;
          if ('description' in payload) entity.description = payload.description;
          if (payload.entityTypes) entity.entityTypes = payload.entityTypes;
          if (payload.geometry) entity.geometry = payload.geometry;
          entity.version = (entity.version || 0) + 1;
        }
        body = entity;
      }
    } else if (path === '/v1/geodata/proposals' && request.method() === 'POST') {
      submittedProposals.push(request.postDataJSON());
      body = { id: 'proposal-1', status: 'COMPLETED' };
    } else if (path === '/v1/geodata/entity-deletion-jobs') {
      const payload = request.postDataJSON();
      const job = { id: `job-${payload.entityId}`, entityId: payload.entityId,
        status: 'AWAITING_CONFIRMATION', impact: { qsoCount: 7, activationCount: 2 } };
      jobs.set(job.id, job);
      body = job;
    } else if (path.startsWith('/v1/geodata/entity-deletion-jobs/')) {
      const job = jobs.get(path.split('/')[4])!;
      if (path.endsWith('/confirm')) {
        job.status = 'COMPLETED';
        entities.splice(entities.findIndex(item => item.id === job.entityId), 1);
      }
      body = job;
    }
    await route.fulfill({ json: body });
  });
  await page.goto('/entity-management');
});

test('edit in place, preserve batch/page and guard unsaved navigation and closing', async ({ page }, testInfo) => {
  const row = page.locator('.geo-row').first();
  await row.getByRole('checkbox').check();
  await row.getByRole('button').click();
  const editor = page.getByRole('dialog', { name: 'Parque del Alamillo', exact: true });
  await expect(editor).toBeVisible();
  await expect(editor.getByLabel('Display name')).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath('catalogue-editor.png') });
  await editor.getByLabel('Display name').fill('Edited park');
  page.once('dialog', dialog => dialog.dismiss());
  await editor.getByRole('button', { name: 'Next entity' }).click();
  await expect(editor.getByLabel('Display name')).toHaveValue('Edited park');
  page.once('dialog', dialog => dialog.dismiss());
  await page.keyboard.press('Escape');
  await expect(editor).toBeVisible();
  await editor.getByRole('button', { name: 'Save details', exact: true }).click();
  await expect(page.getByRole('dialog', { name: 'Edited park', exact: true })).toBeVisible();
  await expect(editor).toHaveCount(0);
  await page.getByRole('dialog').getByRole('button', { name: 'Close', exact: true }).click();
  await expect(page.getByRole('dialog')).toBeHidden();
  await expect(row.getByRole('checkbox')).toBeChecked();
  await expect(page.getByRole('button', { name: /Edited park/ })).toBeFocused();
});

test('geometry map has real vertex controls and replacement drafts remain unsaved until saving', async ({ page }, testInfo) => {
  await page.locator('.geo-row').first().getByRole('button').click();
  const editor = page.getByRole('dialog');
  await editor.getByRole('button', { name: 'Geometry', exact: true }).click();
  await expect(editor.locator('.leaflet-map canvas')).toBeVisible();
  await editor.getByRole('button', { name: 'Edit geometry vertices' }).click();
  await expect(editor.locator('.marker-icon').first()).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath('geometry-editor.png') });
  await editor.getByRole('button', { name: 'Replace with point' }).click();
  await editor.locator('.leaflet-map').click({ position: { x: 240, y: 200 } });
  await expect(editor.locator('.editor-dirty')).toContainText('Geometry');
  await editor.getByRole('button', { name: 'Name & categories' }).click();
  await editor.getByLabel('Display name').fill('Geometry draft park');
  await editor.getByRole('button', { name: 'Save details', exact: true }).click();
  await expect(editor.locator('.editor-dirty')).toContainText('Geometry');
  await editor.getByRole('button', { name: 'Geometry', exact: true }).click();
  await editor.getByRole('button', { name: 'Save geometry', exact: true }).click();
  await expect(editor.locator('.editor-dirty')).toHaveCount(0);
  await editor.getByRole('button', { name: 'Next entity' }).click();
  await editor.getByRole('button', { name: 'Next entity' }).click();
  await editor.getByRole('button', { name: 'Geometry', exact: true }).click();
  await expect(editor.getByRole('button', { name: 'Save geometry', exact: true })).toBeDisabled();
});

test('single deletion confirmation appears above editor and bulk deletion stays operational', async ({ page }) => {
  await page.locator('.geo-row').first().getByRole('button').click();
  const editor = page.getByRole('dialog', { name: 'Parque del Alamillo', exact: true });
  await editor.getByRole('button', { name: 'Audit & deletion' }).click();
  await editor.getByRole('button', { name: 'Permanently delete entity', exact: true }).click();
  const warning = page.getByRole('dialog', { name: 'Delete Parque del Alamillo?', exact: true });
  await expect(warning).toBeVisible();
  await expect(warning).toContainText('7 valid QSO(s)');
  await warning.getByRole('button', { name: 'Close', exact: true }).click();
  await expect(editor).toBeVisible();
  await editor.getByRole('button', { name: 'Close', exact: true }).click();
  await page.getByLabel('Select all', { exact: true }).check();
  await page.getByRole('button', { name: 'Permanently delete entities', exact: true }).click();
  const bulk = page.getByRole('dialog', { name: 'Delete 3 entities?', exact: true });
  await expect(bulk.getByRole('button', { name: 'Permanently delete 3 entities', exact: true })).toBeEnabled();
  await bulk.getByRole('button', { name: 'Permanently delete 3 entities', exact: true }).click();
  await expect(bulk).toBeHidden();
  await expect(page.locator('.geo-row')).toHaveCount(0);
});

test('review decisions remain inline and small-screen editor fits the viewport', async ({ page }, testInfo) => {
  await page.goto('/geodata');
  await page.locator('.geo-row').first().getByRole('button').click();
  await expect(page.getByRole('dialog')).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Save review decision' })).toBeVisible();
  await page.goto('/entity-management');
  await page.setViewportSize({ width: 390, height: 844 });
  await page.locator('.geo-row').first().getByRole('button').click();
  const bounds = await page.getByRole('dialog').boundingBox();
  expect(bounds!.x).toBeGreaterThanOrEqual(0);
  expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(390);
  await page.screenshot({ path: testInfo.outputPath('mobile-editor.png') });
});

test('optional catalogue map and manual candidate drawing remain usable', async ({ page }) => {
  await page.locator('.catalogue-map summary').click();
  await expect(page.locator('.catalogue-map .leaflet-map canvas')).toBeVisible();
  await page.getByRole('button', { name: 'New Candidate', exact: true }).click();
  const proposal = page.locator('article').filter({ has: page.getByRole('heading', { name: 'New Candidate', exact: true }) });
  await proposal.getByLabel('Name', { exact: true }).fill('Manual fixture candidate');
  await proposal.locator('input[type="url"]').fill('https://manual.example');
  await proposal.locator('textarea[maxlength="2000"]').first().fill('Manual candidate description');
  await proposal.getByLabel('Park', { exact: true }).check();
  await proposal.getByRole('button', { name: 'Draw point on map' }).click();
  await page.locator('.map-panel .leaflet-map').click({ position: { x: 220, y: 180 } });
  const geometry = JSON.parse(await proposal.getByLabel(/^GeoJSON geometry/).inputValue());
  expect(geometry.type).toBe('Point');
  expect(geometry.coordinates).not.toEqual([-5.99, 37.39]);
  await proposal.getByRole('button', { name: 'Submit candidate' }).click();
  await expect(proposal).toHaveCount(0);
  expect(submittedProposals[0].feature.properties.website).toBe('https://manual.example');
  expect(submittedProposals[0].feature.properties.description).toBe('Manual candidate description');
});

test('website and plain-text description display and save with optimistic concurrency', async ({ page }) => {
  await page.locator('.geo-row').first().getByRole('button').click();
  const editor = page.getByRole('dialog');
  await expect(editor.getByRole('heading', { name: 'Website and description', exact: true })).toBeVisible();
  const website = editor.getByRole('textbox', { name: 'Website', exact: true });
  const description = editor.getByRole('textbox', { name: 'Description', exact: true });
  await expect(website).toBeVisible();
  await expect(website).toHaveValue('https://alamillo.example');
  await expect(description).toBeVisible();
  await expect(description).toHaveValue('Riverside park');
  await expect(editor.locator('.entity-details-section h3')).toHaveText([
    'Entity name', 'Entity categories', 'Website and description',
  ]);
  await website.fill('https://new.example');
  await description.fill('New plain text');
  await website.fill('javascript:alert(1)');
  await editor.getByRole('button', { name: 'Save details', exact: true }).click();
  await expect(editor.getByRole('alert')).toContainText('absolute HTTP or HTTPS');
  expect(submittedEntityWrites).toHaveLength(0);
  await editor.getByLabel('Display name').fill('Updated park details');
  await editor.getByLabel('Nature reserve', { exact: true }).check();
  await website.fill('https://new.example');
  await editor.getByRole('button', { name: 'Save details', exact: true }).click();
  await expect(website).toHaveValue('https://new.example');
  await expect(description).toHaveValue('New plain text');
  await expect(editor.getByLabel('Display name')).toHaveValue('Updated park details');
  await expect(editor.locator('.editor-dirty')).toHaveCount(0);
  expect(submittedEntityWrites.map(write => [write.method, write.path])).toEqual([
    ['PATCH', '/v1/geodata/entities/park-1'],
    ['PUT', '/v1/geodata/entities/park-1/categories'],
  ]);
  expect(submittedEntityWrites[0].payload).toMatchObject({
    name: 'Updated park details', website: 'https://new.example', description: 'New plain text',
  });
  expect(submittedEntityWrites[1].payload.entityTypes).toEqual(['PARK', 'NATURE_RESERVE']);
  await editor.getByRole('button', { name: 'Close', exact: true }).click();
  await page.locator('.geo-row').nth(1).getByRole('button').click();
  const legacyManagement = page.getByRole('dialog');
  await expect(legacyManagement.getByRole('textbox', { name: 'Website', exact: true })).toHaveValue('');
  await expect(legacyManagement.getByRole('textbox', { name: 'Description', exact: true })).toHaveValue('');
  await legacyManagement.getByRole('button', { name: 'Close', exact: true }).click();

  await page.goto('/geodata');
  await page.locator('.geo-row').first().getByRole('button').click();
  const reviewer = page.locator('.editor-panel');
  await expect(reviewer.getByRole('link', { name: 'https://new.example' })).toHaveAttribute('rel', 'noopener noreferrer');
  await expect(reviewer).toContainText('New plain text');
  await page.locator('.geo-row').nth(1).getByRole('button').click();
  await expect(reviewer).toContainText('Website: Not provided');
  await expect(reviewer).toContainText('Description: Not provided');
});
