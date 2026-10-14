import assert from 'node:assert/strict';
import { test } from 'node:test';
import { pollDeletionJobs } from '../src/lib/deletionPolling.ts';

test('bulk deletion polling keeps running through transient errors until every job is terminal', async () => {
  const items = [
    { job: { id: 'first', status: 'QUEUED' }, errors: 0 },
    { job: { id: 'second', status: 'PROCESSING' }, errors: 0 },
  ];
  const reads = new Map<string, number>();
  let pauses = 0;

  await pollDeletionJobs({
    items,
    jobFor: item => item.job,
    refresh: async id => {
      const attempt = (reads.get(id) || 0) + 1;
      reads.set(id, attempt);
      if (id === 'second' && attempt <= 2) throw new Error('temporary network issue');
      return {
        id,
        status: attempt >= (id === 'first' ? 65 : 68) ? 'COMPLETED' : 'PROCESSING',
      };
    },
    update: (item, job) => { item.job = job; },
    onError: item => { item.errors += 1; },
    pause: async () => { pauses += 1; },
  });

  assert.equal(items[0].job.status, 'COMPLETED');
  assert.equal(items[1].job.status, 'COMPLETED');
  assert.equal(items[1].errors, 2);
  assert.ok(pauses > 60, `expected long-running jobs to keep polling; paused ${pauses} times`);
});
