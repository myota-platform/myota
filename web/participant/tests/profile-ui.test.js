const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {JSDOM} = require('jsdom');

const WEB = path.resolve(__dirname, '../web');

function response(status, value, type = 'json') {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: `HTTP ${status}`,
    async json() {
      return value;
    },
    async blob() {
      return value;
    },
  };
}

async function createParticipantPage({token = 'profile-test-token'} = {}) {
  const dom = new JSDOM(fs.readFileSync(path.join(WEB, 'index.html'), 'utf8'), {
    runScripts: 'outside-only',
    url: 'https://test.myota.top/',
  });
  const {window} = dom;
  const requests = [];
  const revokedUrls = [];
  const drawCalls = [];
  const blobs = new Map();
  const account = {
    id: 'profile-test-account',
    displayName: 'Profile Test',
    websiteUrl: null,
    biographyMarkdown: null,
    profileImage: null,
  };
  const controls = {failNextImageUpload: false};
  let objectUrlId = 0;

  if (token) window.localStorage.setItem('myota_public_access', token);
  window.URL.createObjectURL = (blob) => {
    const value = `blob:test-${++objectUrlId}`;
    blobs.set(value, blob);
    return value;
  };
  window.URL.revokeObjectURL = (value) => revokedUrls.push(value);
  window.HTMLCanvasElement.prototype.getContext = function getContext() {
    return {
      clearRect() {},
      drawImage(...args) {
        drawCalls.push({canvasWidth: this.canvas.width, args});
      },
      get canvas() {
        return this._canvas;
      },
      _canvas: this,
    };
  };
  window.HTMLCanvasElement.prototype.toBlob = function toBlob(callback, type) {
    callback(new window.Blob([new Uint8Array(256)], {type}));
  };
  window.Image = class FakeImage {
    naturalWidth = 800;
    naturalHeight = 400;

    set src(value) {
      this._src = value;
      queueMicrotask(() => this.onload?.());
    }

    get src() {
      return this._src;
    }
  };
  window.fetch = async (url, options = {}) => {
    const request = {url: String(url), ...options};
    requests.push(request);
    const pathName = new URL(request.url, window.location.origin).pathname;
    if (pathName === '/v1/programmes') {
      return response(200, {
        items: [{
          slug: 'test',
          name: 'Test programme',
          description: 'Testing',
          theme: {primary: '#123456', accent: '#abcdef'},
          rules: {minimumQsos: {activation: 1, hunter: 1}, publicAccessRequired: false},
        }],
      });
    }
    if (pathName === '/v1/geodata/entities') return response(200, {items: []});
    if (pathName === '/v1/awards') return response(200, {items: []});
    if (pathName === '/v1/identity/me') return response(200, account);
    if (pathName === '/v1/identity/me/profile-image' && request.method === 'GET') {
      return response(200, new window.Blob([new Uint8Array([1, 2])], {type: 'image/webp'}), 'blob');
    }
    if (pathName === '/v1/identity/me/profile' && request.method === 'PATCH') {
      Object.assign(account, JSON.parse(request.body));
      return response(200, account);
    }
    if (pathName === '/v1/identity/me/profile-image' && request.method === 'PUT') {
      if (controls.failNextImageUpload) {
        controls.failNextImageUpload = false;
        return response(413, {message: 'profile image upload exceeds 5 MiB'});
      }
      account.profileImage = {
        id: 'normalized-profile-image',
        contentType: 'image/webp',
        width: 512,
        height: 512,
      };
      return response(200, {profileImage: account.profileImage});
    }
    if (pathName === '/v1/identity/me/profile-image' && request.method === 'DELETE') {
      account.profileImage = null;
      return response(200, {profileImage: null});
    }
    return response(404, {message: `Unexpected test request: ${pathName}`});
  };

  window.eval(fs.readFileSync(path.join(WEB, 'profile-utils.js'), 'utf8'));
  window.eval(fs.readFileSync(path.join(WEB, 'app.js'), 'utf8'));
  await new Promise((resolve) => setTimeout(resolve, 20));

  return {dom, window, requests, revokedUrls, drawCalls, blobs, account, controls};
}

test('profile UI edits private details and renders Markdown as safe text', async () => {
  const page = await createParticipantPage();
  const {window, requests} = page;
  const document = window.document;

  assert.equal(document.getElementById('profile-form').hidden, false);
  assert.equal(document.getElementById('profile-image-editor').hidden, false);
  document.getElementById('profile-biography').value =
    '<script>alert(1)</script>\n\n[Safe](https://example.test)';
  document.getElementById('profile-biography').dispatchEvent(
    new window.Event('input', {bubbles: true}),
  );
  const preview = document.getElementById('profile-biography-preview');
  assert.equal(preview.querySelector('script'), null);
  assert.match(preview.textContent, /<script>alert\(1\)<\/script>/);
  assert.equal(preview.querySelector('a').getAttribute('rel'), 'noopener noreferrer');

  document.getElementById('profile-website').value = 'https://profile.example.test';
  document.getElementById('profile-form').onsubmit({preventDefault() {}});
  await new Promise((resolve) => setTimeout(resolve, 0));
  const patch = requests.find((request) => request.method === 'PATCH');
  assert.ok(patch);
  assert.equal(patch.headers.Authorization, 'Bearer profile-test-token');
  assert.deepEqual(JSON.parse(patch.body), {
    websiteUrl: 'https://profile.example.test',
    biographyMarkdown: '<script>alert(1)</script>\n\n[Safe](https://example.test)',
  });
  page.dom.window.close();
});

test('profile picture UI previews a crop, reports upload failure, then saves and removes it', async () => {
  const page = await createParticipantPage();
  const {window, requests, drawCalls, revokedUrls} = page;
  const document = window.document;
  const input = document.getElementById('profile-image-file');
  Object.defineProperty(input, 'files', {
    configurable: true,
    value: [new window.File([new Uint8Array(128)], 'avatar.png', {type: 'image/png'})],
  });

  input.onchange();
  await new Promise((resolve) => setTimeout(resolve, 0));
  assert.equal(document.getElementById('profile-crop-tools').hidden, false);
  assert.ok(drawCalls.length >= 1);
  const centeredCrop = drawCalls.at(-1).args.slice(1);

  document.querySelector('[data-crop-pan="right"]').click();
  const pannedCrop = drawCalls.at(-1).args.slice(1);
  assert.notDeepEqual(pannedCrop, centeredCrop);
  const zoom = document.getElementById('profile-crop-zoom');
  zoom.value = '200';
  zoom.oninput({target: zoom});
  assert.ok(drawCalls.at(-1).args[3] > pannedCrop[2]);

  page.controls.failNextImageUpload = true;
  await document.getElementById('profile-image-upload').onclick();
  assert.match(document.getElementById('profile-status').textContent, /exceeds 5 MiB/);
  assert.equal(document.getElementById('profile-image-current').hidden, true);

  await document.getElementById('profile-image-upload').onclick();
  const upload = requests.filter((request) => request.method === 'PUT').at(-1);
  assert.ok(upload.body instanceof window.Blob);
  assert.equal(upload.body.type, 'image/webp');
  assert.equal(upload.headers.Authorization, 'Bearer profile-test-token');
  assert.equal(document.getElementById('profile-image-current').hidden, false);
  assert.equal(document.getElementById('profile-image-delete').hidden, false);
  assert.match(document.getElementById('profile-status').textContent, /saved/);

  await document.getElementById('profile-image-delete').onclick();
  assert.equal(document.getElementById('profile-image-current').hidden, true);
  assert.equal(document.getElementById('profile-image-delete').hidden, true);
  assert.ok(revokedUrls.some((value) => value.startsWith('blob:test-')));
  assert.ok(requests.some((request) => request.method === 'DELETE'));
  page.dom.window.close();
});

test('profile editor stays hidden when there is no authenticated session', async () => {
  const page = await createParticipantPage({token: ''});
  const {window, requests} = page;
  assert.equal(window.document.getElementById('profile-form').hidden, true);
  assert.equal(window.document.getElementById('profile-image-editor').hidden, true);
  assert.equal(requests.some((request) => request.url.includes('/v1/identity/me')), false);
  page.dom.window.close();
});
