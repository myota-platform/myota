import { expect, test, type Page } from "@playwright/test";

test.use({ timezoneId: "Europe/Madrid" });

const png =
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=";

async function fixtures(page: Page) {
  const programme = {
    slug: "sevilla-ota",
    name: "Sevilla OTA",
    description: "Existing programme",
    rules: {
      minimumQsos: { activation: 10, hunter: 3, special: 7 },
      activationValidityDays: null,
      customRule: true,
    },
    theme: { primary: "#116b63", accent: "#efaa39", logo: "keep-this.svg" },
    entityTypes: [{ code: "PARK", label: "Park" }],
  };
  const elements = [
    "AWARD_NAME",
    "CALLSIGN",
    "PERSON_NAME",
    "DATE_OBTAINED",
    "MANAGER_NAME",
    "MANAGER_SIGNATURE",
  ].map((kind, index) => ({
    kind,
    x: 0.1,
    y: 0.1 + index * 0.12,
    width: 0.8,
    height: 0.07,
    style: { align: "center" },
  }));
  const assets: any[] = [
    {
      id: "background-1",
      kind: "BACKGROUND",
      name: "Existing background",
      objectKey: "art/existing.png",
      mediaType: "image/png",
      widthPx: 2481,
      heightPx: 3508,
    },
    {
      id: "signature-1",
      kind: "SIGNATURE",
      name: "Existing manager",
      objectKey: "art/signature.png",
      mediaType: "image/png",
      widthPx: 300,
      heightPx: 100,
    },
  ];
  const award: any = {
    id: "award-1",
    programmeSlug: programme.slug,
    code: "LOCAL-10",
    name: "Existing award",
    status: "DRAFT",
    category: "ACTIVATOR",
    achievementMetric: "QSO_COUNT",
    description: "Keep the description",
    condition: { kind: "QSO_COUNT", operator: "GTE", value: 10 },
    levels: [{ id: "10", threshold: 10 }],
    backgroundAsset: assets[0],
    printSpec: { page: "LETTER", orientation: "LANDSCAPE", dpi: 150 },
    template: { elements, layoutVersion: 2 },
    effectiveFrom: "2026-10-09T12:45:30Z",
    managerName: "Original manager",
    signatureAssetId: "signature-1",
  };
  const saved: any[] = [];
  const uploads: any[] = [];
  const previews: any[] = [];
  const pageErrors: string[] = [];
  const policy = {
    id: "policy-1",
    type: "RULES",
    name: "Fixture policy",
    status: "APPROVED",
    schema: {},
    effectiveFrom: "2026-10-09T15:00:00+02:00",
  };
  const content = {
    id: "content-1",
    key: "fixture.title",
    locale: "en",
    value: "Fixture content",
    status: "APPROVED",
    effectiveFrom: "2026-10-09T15:00:00+02:00",
  };
  page.on("pageerror", (error) => pageErrors.push(error.message));
  await page.addInitScript(() =>
    localStorage.setItem("myota_admin_access", "fixture-token"),
  );
  await page.route("**/v1/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
    let result: any = {};
    if (path === "/v1/identity/me")
      result = { id: "admin", roles: [{ role: "GLOBAL_OPERATOR" }] };
    else if (path === "/v1/programmes") result = { items: [programme] };
    else if (path === `/v1/programmes/${programme.slug}`) {
      if (request.method() === "PATCH") {
        Object.assign(programme, request.postDataJSON());
        saved.push(request.postDataJSON());
      }
      result = programme;
    } else if (path === `/v1/programmes/${programme.slug}/policy-drafts`)
      result = { items: [policy] };
    else if (path === `/v1/programmes/${programme.slug}/content`)
      result = { items: [content] };
    else if (path === `/v1/programmes/${programme.slug}/content/coverage`)
      result = { locales: [] };
    else if (
      path.endsWith("/policy-drafts/policy-1") ||
      path.endsWith("/content/content-1")
    ) {
      const record = path.endsWith("policy-1") ? policy : content;
      if (request.method() === "PATCH") {
        saved.push(request.postDataJSON());
        Object.assign(record, request.postDataJSON());
      }
      result = record;
    } else if (path === "/v1/entity-types") {
      await new Promise((resolve) => setTimeout(resolve, 100));
      result = { items: programme.entityTypes };
    } else if (path === "/v1/awards") {
      if (request.method() === "POST") {
        saved.push(request.postDataJSON());
        Object.assign(award, request.postDataJSON());
        result = award;
      } else
        result = {
          items: [
            {
              id: award.id,
              name: award.name,
              code: award.code,
              programmeSlug: award.programmeSlug,
              status: award.status,
            },
          ],
        };
    } else if (path === "/v1/awards/award-1") {
      if (request.method() === "PATCH") {
        saved.push(request.postDataJSON());
        Object.assign(award, request.postDataJSON());
      }
      result = award;
    } else if (path === "/v1/awards/assets") {
      if (request.method() === "POST") {
        const asset = { ...request.postDataJSON(), id: `new-${assets.length}` };
        assets.push(asset);
        result = asset;
      } else result = { items: assets, nextPage: null };
    } else if (/\/v1\/awards\/assets\/[^/]+\/content$/.test(path)) {
      const asset = assets.find((item) => item.id === path.split("/")[4]);
      if (request.method() === "PUT") {
        uploads.push({
          mediaType: request.headers()["content-type"],
          size: request.postDataBuffer()!.length,
        });
        result = { ...asset, contentStatus: "STORED" };
      } else result = { asset, mediaType: "image/png", contentBase64: png };
    } else if (path === "/v1/awards/previews") {
      previews.push(request.postDataJSON());
      result = {
        mediaType: "application/pdf",
        contentBase64: Buffer.from("%PDF-1.4\n%%EOF").toString("base64"),
      };
    } else if (path.startsWith("/v1/awards/")) result = { items: [] };
    await route.fulfill({ json: result });
  });
  return { programme, award, saved, uploads, previews, pageErrors };
}

test("programme identifier/name load aligned and edits preserve custom rules/theme", async ({
  page,
}, testInfo) => {
  const state = await fixtures(page);
  await page.goto("/programmes");
  await page.getByRole("button", { name: /Sevilla OTA/ }).click();
  const identifier = page.getByLabel(/^Programme identifier/);
  const name = page.getByLabel("Programme name", { exact: true });
  await expect(identifier).toHaveValue("sevilla-ota");
  await expect(identifier).toHaveAttribute("readonly", "");
  await expect(name).toHaveValue("Sevilla OTA");
  expect(
    Math.abs(
      (await identifier.boundingBox())!.y - (await name.boundingBox())!.y,
    ),
  ).toBeLessThan(2);
  await page.screenshot({ path: testInfo.outputPath("programme-editor.png") });
  await name.fill("Renamed Sevilla initiative");
  await page
    .getByRole("button", { name: "Save programme", exact: true })
    .click();
  await expect(name).toHaveValue("Renamed Sevilla initiative");
  expect(state.saved[0].rules.customRule).toBe(true);
  expect(state.saved[0].rules.minimumQsos.special).toBe(7);
  expect(state.saved[0].theme.logo).toBe("keep-this.svg");
  expect(state.pageErrors).toEqual([]);
});

for (const screen of [
  { route: "/policies", row: "Fixture policy" },
  { route: "/content", row: "fixture.title" },
]) {
  test(`${screen.route} publication inputs remain UTC in a Madrid browser`, async ({
    page,
  }) => {
    const state = await fixtures(page);
    await page.goto(screen.route);
    await page.getByRole("button", { name: new RegExp(screen.row) }).click();
    await expect(page.getByLabel("Effective from (UTC)")).toHaveValue(
      "2026-10-09T13:00",
    );
    await page.getByLabel("Effective from (UTC)").fill("2026-10-09T14:10");
    await page.getByRole("button", { name: "Publish", exact: true }).click();
    await expect
      .poll(() => state.saved.at(-1)?.effectiveFrom)
      .toBe("2026-10-09T14:10:00.000Z");
    expect(state.pageErrors).toEqual([]);
  });
}

test("award defaults, existing layout, editable fields and custom text survive saves", async ({
  page,
}, testInfo) => {
  const state = await fixtures(page);
  await page.goto("/awards");
  await expect(page.locator(".award-canvas-element")).toHaveCount(6);
  await page.getByRole("button", { name: /Existing award/ }).click();
  await expect(page.getByLabel("Code", { exact: true })).toHaveValue(
    "LOCAL-10",
  );
  await expect(page.getByLabel("Name", { exact: true })).toHaveValue(
    "Existing award",
  );
  await expect(
    page.getByRole("combobox", { name: "Category", exact: true }),
  ).toHaveValue("ACTIVATOR");
  await expect(
    page.getByRole("combobox", { name: "Orientation", exact: true }),
  ).toHaveValue("LANDSCAPE");
  await expect(page.getByLabel("Effective from (UTC)")).toHaveValue(
    "2026-10-09T12:45",
  );
  const box = await page.locator(".award-canvas").boundingBox();
  expect(box!.width).toBeGreaterThan(box!.height);
  await expect(page.getByAltText("Selected award background")).toBeVisible();
  await page.getByRole("button", { name: "Add text element" }).click();
  await page
    .getByLabel("Custom text", { exact: true })
    .fill("Programme-owned certificate");
  await page.getByLabel("Name", { exact: true }).fill("Updated award");
  await page.getByLabel("Award manager name").fill("New manager");
  await page
    .getByRole("button", { name: "Save award draft", exact: true })
    .click();
  await expect(page.getByRole("status")).toContainText("Award draft saved");
  expect(state.saved[0].template.layoutVersion).toBe(2);
  expect(state.saved[0].effectiveFrom).toBe("2026-10-09T12:45:30.000Z");
  expect(state.saved[0].template.elements[0].x).toBe(0.1);
  expect(state.saved[0].template.elements[0].style.align).toBe("center");
  expect(state.saved[0].template.elements.at(-1).label).toBe(
    "Programme-owned certificate",
  );
  await expect(page.getByLabel("Award manager name")).toHaveValue(
    "New manager",
  );
  await page.locator(".award-canvas").scrollIntoViewIfNeeded();
  await page.screenshot({ path: testInfo.outputPath("award-designer.png") });
  expect(state.pageErrors).toEqual([]);
});

test("named PNG and JPG uploads populate background/signature selectors", async ({
  page,
}) => {
  const state = await fixtures(page);
  await page.goto("/awards");
  const panel = page.locator("article").filter({
    has: page.getByRole("heading", {
      name: "Upload signature or background",
    }),
  });
  const jpeg = await page.evaluate(() => {
    const canvas = document.createElement("canvas");
    canvas.width = 4;
    canvas.height = 2;
    canvas.getContext("2d")!.fillRect(0, 0, 4, 2);
    return canvas.toDataURL("image/jpeg").split(",")[1];
  });
  for (const [kind, type, content] of [
    ["BACKGROUND", "image/png", png],
    ["SIGNATURE", "image/jpeg", jpeg],
  ]) {
    await panel.getByLabel("Asset type").selectOption(kind);
    await panel.getByLabel("Display name").fill(`Named ${kind.toLowerCase()}`);
    await panel.getByLabel("Image file").setInputFiles({
      name: kind === "BACKGROUND" ? "image.png" : "image.jpg",
      mimeType: type,
      buffer: Buffer.from(content, "base64"),
    });
    await panel
      .getByRole("button", { name: "Upload image asset", exact: true })
      .click();
    await expect(
      panel.getByRole("button", { name: "Upload image asset", exact: true }),
    ).toHaveText("Upload image asset");
    await expect(
      panel.getByRole("button", { name: "Upload image asset", exact: true }),
    ).toBeDisabled();
  }
  expect(state.uploads.map((item) => item.mediaType)).toEqual([
    "image/png",
    "image/jpeg",
  ]);
  await expect(
    page
      .getByLabel("Background object key")
      .locator("option", { hasText: "Named background" }),
  ).toHaveCount(1);
  await expect(
    page
      .getByLabel("Manager signature")
      .locator("option", { hasText: "Named signature" }),
  ).toHaveCount(1);
  expect(state.pageErrors).toEqual([]);
});

test("PDF preview submits unsaved layout and opens a separate window, not an issuance", async ({
  page,
}) => {
  const state = await fixtures(page);
  await page.goto("/awards");
  await page.getByLabel("Name", { exact: true }).fill("Unsaved mock award");
  const popupPromise = page.waitForEvent("popup");
  await page
    .getByRole("button", { name: "Generate preview PDF", exact: true })
    .click();
  const popup = await popupPromise;
  await expect(page.getByRole("status")).toContainText("Mock PDF opened");
  expect(state.previews).toHaveLength(1);
  expect(state.previews[0].name).toBe("Unsaved mock award");
  expect(state.previews[0].template.elements).toHaveLength(6);
  expect(state.saved).toHaveLength(0);
  await popup.close();
  expect(state.pageErrors).toEqual([]);
});
