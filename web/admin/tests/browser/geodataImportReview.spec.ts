import { expect, test } from "@playwright/test";

const promotionTargets: string[] = [];
const concurrentRemoval = { enabled: false };
const manyCandidates = { enabled: false };

interface FixtureCandidate {
  id: string;
  ordinal: number;
  name: string;
  validationStatus: string;
  geometry: { type: string; coordinates: number[][] };
}

test.beforeEach(async ({ page }) => {
  promotionTargets.length = 0;
  concurrentRemoval.enabled = false;
  manyCandidates.enabled = false;
  const candidates: FixtureCandidate[] = [
    {
      id: "candidate-1",
      ordinal: 0,
      name: "First trail",
      validationStatus: "PENDING",
      geometry: {
        type: "LineString",
        coordinates: [
          [-5.99, 37.39],
          [-5.98, 37.4],
        ],
      },
    },
    {
      id: "candidate-2",
      ordinal: 1,
      name: "Second trail",
      validationStatus: "PENDING",
      geometry: {
        type: "LineString",
        coordinates: [
          [-5.97, 37.39],
          [-5.96, 37.4],
        ],
      },
    },
  ];
  let failedAttempt = true;
  let queueSequence = 0;
  const run = {
    id: "import-1",
    filename: "trails.geojson",
    format: "GEOJSON",
    adapter: "MANUAL",
    status: "PREPROCESSED",
    featureCount: 2,
    candidateCounts: { total: 2, pending: 2, confirmed: 0, processed: 0 },
  };

  await page.addInitScript(() =>
    localStorage.setItem("myota_admin_access", "browser-test-token"),
  );
  await page.route("https://tile.openstreetmap.org/**", (route) =>
    route.abort(),
  );
  await page.route("**/v1/**", async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    let body: unknown = {};
    if (path === "/v1/identity/me")
      body = { id: "reviewer-1", roles: [{ role: "GLOBAL_OPERATOR" }] };
    else if (path === "/v1/programmes") body = { items: [] };
    else if (path === "/v1/entity-types")
      body = { items: [{ code: "TRAIL", label: "Trail" }] };
    else if (path === "/v1/geodata/imports")
      body = { items: [run], total: 1, nextPage: null };
    else if (path === "/v1/geodata/imports/import-1") body = run;
    else if (path === "/v1/geodata/imports/import-1/candidates") {
      if (manyCandidates.enabled && candidates.length === 2) {
        for (let ordinal = 2; ordinal < 22; ordinal += 1) {
          candidates.push({
            id: `candidate-${ordinal + 1}`,
            ordinal,
            name: `Extra trail ${ordinal + 1}`,
            validationStatus: "PENDING",
            geometry: {
              type: "LineString",
              coordinates: [
                [-5.97, 37.39],
                [-5.96, 37.4],
              ],
            },
          });
        }
      }
      const pending = candidates
        .filter((candidate) => candidate.validationStatus === "PENDING")
        .sort((left, right) => left.ordinal - right.ordinal);
      const url = new URL(request.url());
      const requestedPage = Number(url.searchParams.get("page") || "1");
      const pageSize = Number(url.searchParams.get("pageSize") || "20");
      const start = (requestedPage - 1) * pageSize;
      body = {
        items: pending.slice(start, start + pageSize),
        total: pending.length,
        nextPage: start + pageSize < pending.length ? requestedPage + 1 : null,
      };
    } else if (
      path === "/v1/geodata/imports/import-1/candidates/validate" &&
      request.method() === "POST"
    ) {
      const { candidateIds } = request.postDataJSON();
      for (const id of candidateIds) {
        const candidate = candidates.find((item) => item.id === id);
        if (candidate) candidate.validationStatus = "REJECTED";
      }
      if (concurrentRemoval.enabled) {
        const other = candidates.find(
          (candidate) => candidate.id === "candidate-2",
        );
        if (other) other.validationStatus = "REJECTED";
      }
      body = { updated: candidateIds.length };
    } else if (
      path === "/v1/geodata/imports/import-1/process" &&
      request.method() === "POST"
    ) {
      queueSequence += 1;
      promotionTargets.push(request.postDataJSON().targetStatus);
      body = { id: `queue-${queueSequence}`, status: "QUEUED" };
    } else if (
      path.startsWith("/v1/geodata/imports/import-1/processing-queues/")
    ) {
      const queueId = path.split("/").at(-1)!;
      if (failedAttempt) {
        failedAttempt = false;
        body = {
          id: queueId,
          status: "FAILED",
          result: {
            errors: [
              {
                candidateId: "candidate-1",
                message: "Temporary promotion failure",
              },
            ],
          },
        };
      } else {
        candidates[0].validationStatus = "PROCESSED";
        body = {
          id: queueId,
          status: "COMPLETED",
          result: { created: ["entity-1"], errors: [] },
        };
      }
    }
    await route.fulfill({ json: body });
  });
  await page.goto("/geodata-imports");
  await page
    .getByRole("button", { name: /trails\.geojson/ })
    .first()
    .click();
  await expect(page.getByRole("button", { name: "First trail" })).toBeVisible();
});

test("rejection advances across pending items and offers explicit close after the last one", async ({
  page,
}) => {
  await page.getByRole("button", { name: "First trail" }).click();
  const dialog = page.getByRole("dialog", { name: "First trail" });
  await expect(
    dialog.getByRole("button", { name: "Close", exact: true }),
  ).toBeFocused();
  await dialog.getByRole("button", { name: "Reject entity" }).click();
  await expect(
    page.getByRole("dialog", { name: "Second trail" }),
  ).toBeVisible();
  await page
    .getByRole("dialog", { name: "Second trail" })
    .getByRole("button", { name: "Reject entity" })
    .click();
  const complete = page.getByRole("dialog", { name: "Second trail" });
  await expect(complete.getByRole("status")).toContainText("last pending item");
  await expect(
    complete.getByRole("button", { name: "Close review" }),
  ).toBeVisible();
  await complete.getByRole("button", { name: "Close review" }).click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
});

test("failed asynchronous promotion remains on the item and retry advances only after success", async ({
  page,
}) => {
  await page.getByRole("button", { name: "First trail" }).click();
  let dialog = page.getByRole("dialog", { name: "First trail" });
  await dialog.getByRole("button", { name: "Promote to candidate" }).click();
  await expect(dialog.getByRole("alert")).toContainText(
    "Temporary promotion failure",
  );
  await expect(
    dialog.getByRole("button", { name: "Promote to candidate" }),
  ).toBeEnabled();
  await dialog.getByRole("button", { name: "Promote to candidate" }).click();
  await expect(
    page.getByRole("dialog", { name: "Second trail" }),
  ).toBeVisible();
});

test("approved promotion sends the selected terminal target and retains the item after failure", async ({
  page,
}) => {
  await page.getByRole("button", { name: "First trail" }).click();
  const dialog = page.getByRole("dialog", { name: "First trail" });
  await dialog.getByRole("button", { name: "Promote to approved" }).click();
  await expect(dialog.getByRole("alert")).toContainText(
    "Temporary promotion failure",
  );
  expect(promotionTargets).toEqual(["APPROVED"]);
  await expect(
    dialog.getByRole("button", { name: "Promote to approved" }),
  ).toBeEnabled();
});

test("a concurrent reviewer removing the next item leads to completion without skipping a pending record", async ({
  page,
}) => {
  concurrentRemoval.enabled = true;
  await page.getByRole("button", { name: "First trail" }).click();
  const dialog = page.getByRole("dialog", { name: "First trail" });
  await dialog.getByRole("button", { name: "Reject entity" }).click();
  await expect(dialog.getByRole("status")).toContainText("last pending item");
  await expect(
    dialog.getByRole("button", { name: "Close review" }),
  ).toBeVisible();
});

test("review advances correctly from the second candidate page", async ({
  page,
}) => {
  manyCandidates.enabled = true;
  await page
    .getByRole("button", { name: /trails\.geojson/ })
    .first()
    .click();
  await expect(page.getByText("Page 1 · 22 pending records")).toBeVisible();
  await page
    .locator(".import-detail-panel .pagination")
    .getByRole("button", { name: "Next", exact: true })
    .click();
  await expect(page.getByText("Page 2 · 22 pending records")).toBeVisible();
  await page.getByRole("button", { name: "Extra trail 21" }).click();
  const dialog = page.getByRole("dialog", { name: "Extra trail 21" });
  await dialog.getByRole("button", { name: "Reject entity" }).click();
  await expect(
    page.getByRole("dialog", { name: "Extra trail 22" }),
  ).toBeVisible();
  await page
    .getByRole("dialog", { name: "Extra trail 22" })
    .getByRole("button", { name: "Close", exact: true })
    .click();
  await expect(page.getByText("Page 2 · 21 pending records")).toBeVisible();
});

test("Escape closes the modal and restores focus to its invoking candidate", async ({
  page,
}) => {
  const invoker = page.getByRole("button", { name: "First trail" });
  await invoker.click();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(invoker).toBeFocused();
});
