const test = require('node:test');
const assert = require('node:assert/strict');
const {
  renderSafeMarkdown,
  cropGeometry,
  safeLink,
  validateProfileImage,
} = require('../web/profile-utils.js');

test('biography Markdown escapes HTML and permits only safe external links', () => {
  const rendered = renderSafeMarkdown(
    '<img src=x onerror=alert(1)>\n\n[Unsafe](javascript:alert(1)) [Safe](https://example.test/path?a=1&b=2)',
  );
  assert.match(rendered, /&lt;img src=x onerror=alert\(1\)&gt;/);
  assert.doesNotMatch(rendered, /<img|<a[^>]+javascript:/i);
  assert.match(rendered, /<a href="https:\/\/example\.test\/path\?a=1&amp;b=2"/);
  assert.match(rendered, /rel="noopener noreferrer"/);
});

test('square crop geometry fills the preview, clamps position, and supports zoom', () => {
  const centered = cropGeometry(800, 400, 240, 1);
  assert.deepEqual(centered, {
    x: -120,
    y: 0,
    width: 480,
    height: 240,
    panX: 0,
    panY: 0,
  });
  const zoomed = cropGeometry(800, 400, 240, 2, 1000, 0);
  assert.equal(zoomed.width, 960);
  assert.equal(zoomed.height, 480);
  assert.equal(zoomed.panX, 360);
  assert.equal(zoomed.x, 0);
});

test('safe links reject unsafe protocols and embedded credentials', () => {
  assert.equal(safeLink('javascript:alert(1)'), null);
  assert.equal(safeLink('https://user:secret@example.test'), null);
  assert.equal(safeLink('https://example.test'), 'https://example.test/');
});

test('profile image client checks enforce MIME, byte, and dimension bounds', () => {
  assert.equal(
    validateProfileImage(
      {type: 'image/png', size: 1024},
      2048,
      1024,
    ),
    true,
  );
  assert.throws(
    () => validateProfileImage({type: 'image/svg+xml', size: 20}, 20, 20),
    /JPEG, PNG, or WebP/,
  );
  assert.throws(
    () => validateProfileImage({type: 'image/jpeg', size: 5 * 1024 * 1024 + 1}, 10, 10),
    /5 MiB/,
  );
  assert.throws(
    () => validateProfileImage({type: 'image/webp', size: 100}, 4097, 10),
    /4,096/,
  );
});
