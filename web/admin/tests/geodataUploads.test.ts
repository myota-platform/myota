import assert from 'node:assert/strict';
import { test } from 'node:test';
import { discardGeodataUpload, uploadGeodataFile } from '../src/lib/geodataUploads.ts';
import type { UploadMetadata, UploadRequest, UploadStorage } from '../src/lib/geodataUploads.ts';

class MemoryStorage implements UploadStorage {
  items = new Map<string, string>();
  getItem(key: string): string | null { return this.items.get(key) ?? null; }
  setItem(key: string, value: string): void { this.items.set(key, value); }
  removeItem(key: string): void { this.items.delete(key); }
}

const metadata: UploadMetadata = {
  adapter: 'MANUAL', format: 'GEOJSON', entityTypes: ['PARK'],
  source: { name: 'Test dataset', license: 'CC0', retrievedAt: '2026-10-07' },
};
const PART_SIZE = 5 * 1024 * 1024;
function fixture(content = 'dataset'): File {
  return new File([content], 'parks.geojson', { lastModified: 1 });
}
function httpError(status: number, message: string): Error {
  return Object.assign(new Error(message), { status });
}
function requestMock(handler: (path: string, options: RequestInit) => unknown): UploadRequest {
  return async <T>(path: string, options: RequestInit = {}) => await handler(path, options) as T;
}

function server(storage = new MemoryStorage()) {
  const sessions = new Map<string, {
    uploadId: string; status: string; expectedSize: number; importRunId?: string;
    parts: Array<{ partNumber: number; sizeBytes: number; sha256: string }>;
  }>();
  const attemptKeys: string[] = [];
  const partNumbers: number[] = [];
  const methods: string[] = [];
  const handler = async (path: string, options: RequestInit): Promise<unknown> => {
    const method = options.method || 'GET';
    methods.push(`${method} ${path}`);
    if (path === '/v1/geodata/import-uploads') {
      const key = new Headers(options.headers).get('Idempotency-Key')!;
      attemptKeys.push(key);
      let session = sessions.get(key);
      if (!session) {
        session = { uploadId: String(sessions.size + 1), status: 'UPLOADING',
          expectedSize: JSON.parse(String(options.body)).expectedSize, parts: [] };
        sessions.set(key, session);
      }
      return { ...session, partSizeBytes: PART_SIZE };
    }
    const id = path.split('/')[4];
    const session = [...sessions.values()].find(item => item.uploadId === id);
    if (!session) throw httpError(404, 'not found');
    if (method === 'DELETE') { session.status = 'ABORTED'; return {}; }
    if (path.endsWith('/complete')) {
      session.status = 'COMPLETED'; session.importRunId = `run-${id}`;
      return { importRun: { id: session.importRunId } };
    }
    if (path.includes('/parts/')) {
      const partNumber = Number(path.split('/').at(-1));
      partNumbers.push(partNumber);
      session.parts.push({ partNumber, sizeBytes: (options.body as Blob).size,
        sha256: new Headers(options.headers).get('X-Part-SHA256')! });
      return {};
    }
    return { ...session, parts: [...session.parts] };
  };
  return { storage, sessions, attemptKeys, partNumbers, methods, handler,
    request: requestMock(handler), ownerId: 'account-1' };
}

test('submitting the same completed file again creates a fresh import', async () => {
  const api = server();
  const first = await uploadGeodataFile(fixture(), metadata, api);
  const second = await uploadGeodataFile(fixture(), metadata, api);
  assert.notEqual(first.importRunId, second.importRunId);
  assert.notEqual(api.attemptKeys[0], api.attemptKeys[1]);
  assert.equal(api.storage.items.size, 0);
});

test('a lost creation response retains the attempt key and does not create another upload', async () => {
  const api = server();
  let lost = false;
  const request = requestMock(async (path, options) => {
    const response = await api.handler(path, options);
    if (!lost && options.method === 'POST' && path.endsWith('import-uploads')) {
      lost = true; throw new Error('Network disconnected');
    }
    return response;
  });
  await assert.rejects(uploadGeodataFile(fixture(), metadata, { ...api, request }), /Network/);
  await uploadGeodataFile(fixture(), metadata, { ...api, request });
  assert.equal(api.sessions.size, 1);
  assert.equal(api.attemptKeys[0], api.attemptKeys[1]);
});

test('pause and resume preserve a non-default server part size and skip verified parts', async () => {
  const api = server();
  const file = new File([new Uint8Array(PART_SIZE + 7)], 'large.geojson', { lastModified: 2 });
  const controller = new AbortController();
  await assert.rejects(uploadGeodataFile(file, metadata, {
    ...api, signal: controller.signal,
    onProgress: progress => {
      if (progress.stage === 'UPLOADING' && progress.uploadedBytes === PART_SIZE) controller.abort();
    },
  }), { name: 'AbortError' });
  assert.deepEqual(api.partNumbers, [1]);
  assert.equal(api.storage.items.size, 1);
  const result = await uploadGeodataFile(file, metadata, api);
  assert.equal(result.resumed, true);
  assert.deepEqual(api.partNumbers, [1, 2]);
  assert.equal(api.sessions.size, 1);
});

async function interrupted(api: ReturnType<typeof server>, file = fixture()): Promise<void> {
  const request = requestMock(async (path, options) => {
    if (path.endsWith('/complete')) throw new Error('Network disconnected');
    return api.handler(path, options);
  });
  await assert.rejects(uploadGeodataFile(file, metadata, { ...api, request }), /Network/);
}

test('temporary session lookup errors preserve resumable browser state', async () => {
  const api = server();
  await interrupted(api);
  const saved = [...api.storage.items];
  await assert.rejects(uploadGeodataFile(fixture(), metadata, {
    ...api, request: requestMock(() => { throw httpError(503, 'unavailable'); }),
  }), /unavailable/);
  assert.deepEqual([...api.storage.items], saved);
  assert.equal(api.attemptKeys.length, 1);
});

test('same file metadata but changed bytes cannot skip previously uploaded parts', async () => {
  const api = server();
  await interrupted(api);
  await assert.rejects(uploadGeodataFile(fixture('changed'), metadata, api), /differs from/);
  assert.deepEqual(api.partNumbers, [1]);
  assert.equal(api.storage.items.size, 1);
});

test('completion retry retrieves the existing import without another transfer', async () => {
  const api = server();
  await interrupted(api);
  const session = [...api.sessions.values()][0];
  session.status = 'COMPLETED'; session.importRunId = 'existing-run';
  const result = await uploadGeodataFile(fixture(), metadata, api);
  assert.equal(result.importRunId, 'existing-run');
  assert.deepEqual(api.partNumbers, [1]);
  assert.equal(api.storage.items.size, 0);
});

test('COMPLETING sessions retry verification without transferring parts', async () => {
  const api = server();
  await interrupted(api);
  [...api.sessions.values()][0].status = 'COMPLETING';
  await uploadGeodataFile(fixture(), metadata, api);
  assert.deepEqual(api.partNumbers, [1]);
});

test('expired sessions create a fresh attempt', async () => {
  const api = server();
  await interrupted(api);
  const request = requestMock((path, options) => {
    if (path.endsWith('/1') && !options.method) throw httpError(400, 'upload session has expired');
    return api.handler(path, options);
  });
  await uploadGeodataFile(fixture(), metadata, { ...api, request });
  assert.equal(api.sessions.size, 2);
  assert.notEqual(api.attemptKeys[0], api.attemptKeys[1]);
});

test('discard aborts incomplete upload but never deletes a completed import', async () => {
  for (const completed of [false, true]) {
    const api = server();
    await interrupted(api);
    if (completed) [...api.sessions.values()][0].status = 'COMPLETED';
    await discardGeodataUpload(fixture(), metadata, api);
    assert.equal(api.methods.some(method => method.startsWith('DELETE')), !completed);
    assert.equal(api.storage.items.size, 0);
  }
});

test('discard preserves state while server verification is in flight', async () => {
  const api = server();
  await interrupted(api);
  [...api.sessions.values()][0].status = 'COMPLETING';
  await assert.rejects(discardGeodataUpload(fixture(), metadata, api), /Resume it/);
  assert.equal(api.storage.items.size, 1);
  assert.equal(api.methods.some(method => method.startsWith('DELETE')), false);
});

test('browser resume records are isolated between signed-in accounts', async () => {
  const api = server();
  await interrupted(api);
  await uploadGeodataFile(fixture(), metadata, { ...api, ownerId: 'account-2' });
  assert.equal(api.sessions.size, 2);
  assert.equal(api.storage.items.size, 1);
});

test('empty and oversized files are rejected before contacting the API', async () => {
  const api = server();
  await assert.rejects(uploadGeodataFile(fixture(''), metadata, api), /non-empty file/);
  const oversized = fixture();
  Object.defineProperty(oversized, 'size', { value: 1024 ** 3 + 1 });
  await assert.rejects(uploadGeodataFile(oversized, metadata, api), /1 GiB/);
  assert.equal(api.methods.length, 0);
});
