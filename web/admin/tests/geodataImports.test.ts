import assert from "node:assert/strict";
import { test } from "node:test";
import {
  canCancelPreprocessing,
  fetchPreprocessingQueue,
  importCounts,
  importStatusLabel,
  isPreprocessing,
  isReviewable,
} from "../src/lib/geodataImports.ts";

test("summary uses authoritative worker counts rather than missing legacy UI fields", () => {
  assert.deepEqual(
    importCounts({
      id: "run",
      featureCount: 100,
      candidateCounts: { pending: 40, confirmed: 10, duplicates: 7 },
      stats: {
        preprocessed: 97,
        created: 42,
        updated: 5,
        errors: 3,
        processingErrors: 1,
      },
    }),
    {
      source: 100,
      pending: 40,
      confirmed: 10,
      promoted: 47,
      errors: 4,
      duplicates: 7,
    },
  );
});

test("count fallbacks are finite and support older service responses", () => {
  assert.deepEqual(
    importCounts({
      id: "run",
      entityCount: 10,
      candidateCount: 2,
      processedCount: 8,
      errorCount: 0,
    }),
    {
      source: 10,
      pending: 2,
      confirmed: 0,
      promoted: 8,
      errors: 0,
      duplicates: 0,
    },
  );
  assert.equal(
    importCounts({ id: "run", stats: { created: "invalid", updated: -5 } })
      .promoted,
    0,
  );
});

test("queued and processing imports are visible but not yet reviewable", () => {
  assert.equal(isPreprocessing({ id: "run", status: "QUEUED" }), true);
  assert.equal(isReviewable({ id: "run", status: "PROCESSING" }), false);
  assert.equal(
    isReviewable({ id: "run", status: "PREPROCESSED_WITH_ERRORS" }),
    true,
  );
  assert.equal(
    importStatusLabel({ id: "run", status: "QUEUED" }),
    "Waiting to preprocess",
  );
});

test("cancellation state remains visible while only preprocessed work is protected from cancellation", () => {
  assert.equal(isPreprocessing({ id: "run", status: "CANCELLING" }), true);
  assert.equal(
    importStatusLabel({ id: "run", status: "CANCELLED" }),
    "Cancelled",
  );
  assert.equal(
    canCancelPreprocessing({ id: "run", status: "UPLOAD_PENDING" }),
    true,
  );
  assert.equal(
    canCancelPreprocessing({ id: "run", status: "PROCESSING" }),
    true,
  );
  assert.equal(
    canCancelPreprocessing({ id: "run", status: "PREPROCESSED" }),
    false,
  );
});

test("preprocessing queue includes older active runs beyond the first history page", async () => {
  const paths: string[] = [];
  const result = await fetchPreprocessingQueue(async <T>(path: string) => {
    paths.push(path);
    return (
      path.includes("page=1&")
        ? {
            items: [
              { id: "completed", status: "COMPLETED" },
              { id: "queued", status: "QUEUED" },
            ],
            nextPage: 2,
          }
        : {
            items: [
              { id: "old", status: "PROCESSING" },
              { id: "review", status: "PREPROCESSED" },
            ],
            nextPage: null,
          }
    ) as T;
  });
  assert.deepEqual(
    result.map((run) => run.id),
    ["queued", "old", "review"],
  );
  assert.equal(paths.length, 2);
});
