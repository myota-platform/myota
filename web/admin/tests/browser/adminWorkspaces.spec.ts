import { expect, test, type Page } from "@playwright/test";

// Isolated API responses qualify presentation and save payloads, not live mutations.
async function fixtures(page: Page, scopes = ["*"], failure = "") {
  const requests: string[] = [];
  const writes: Array<{ path: string; body: any }> = [];
  const errors: string[] = [];
  const programmes = [
    { slug: "sevilla", name: "Sevilla initiative" },
    { slug: "regional", name: "Regional initiative" },
  ];
  const user: any = {
    id: "user-1",
    displayName: "Existing user",
    email: "fixture@example.test",
    status: "ACTIVE",
    roles: [
      {
        role: "GEO_APPROVER",
        programmeSlug: "sevilla",
        jurisdiction: "ES-AN",
        entityType: "PARK",
      },
      {
        role: "GEO_APPROVER",
        programmeSlug: "regional",
        jurisdiction: "ES-MD",
        entityType: "TRAIL",
      },
    ],
  };
  const roles = [
    {
      code: "GEO_APPROVER",
      name: "Geodata reviewer",
      system: true,
      scopes: ["geodata.review"],
    },
    {
      code: "CUSTOM_READER",
      name: "Custom reader",
      system: false,
      scopes: ["activity.read"],
    },
    {
      code: "GLOBAL_OPERATOR",
      name: "Global operator",
      system: true,
      scopes: ["*"],
    },
  ];
  const category: any = {
    code: "PARK",
    label: "Existing park",
    geometryTypes: ["POINT", "POLYGON"],
    active: true,
  };
  const policy = {
    id: "p1",
    type: "RULES",
    name: "Published policy",
    status: "PUBLISHED",
    schema: { rules: { minimumQsos: 10 } },
    effectiveFrom: "2026-10-09T10:00:00Z",
  };
  const content = {
    id: "c1",
    key: "welcome",
    locale: "en",
    value: "Existing published text",
    status: "PUBLISHED",
  };
  page.on("pageerror", (error) => errors.push(error.message));
  await page.addInitScript(() =>
    localStorage.setItem("myota_admin_access", "isolated-token"),
  );
  await page.route("https://tile.openstreetmap.org/**", (route) =>
    route.abort(),
  );
  await page.route("**/v1/**", async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    requests.push(path);
    if (request.method() !== "GET")
      writes.push({ path, body: request.postDataJSON() });
    if (failure && path === failure)
      return route.fulfill({
        status: 503,
        json: { detail: "Temporarily unavailable; retry." },
      });
    let body: any = { items: [], total: 0 };
    if (path === "/v1/identity/me")
      body = {
        id: "admin",
        displayName: "Test administrator",
        email: "admin@example.test",
        scopes,
      };
    else if (path === "/v1/programmes") body = { items: programmes, total: 2 };
    else if (path === "/v1/identity/admin/accounts")
      body = { items: [user], total: 1 };
    else if (path === "/v1/identity/admin/roles")
      body = {
        items: roles,
        permissions: [{ code: "activity.read", label: "Read activity" }],
      };
    else if (path === "/v1/identity/accounts/user-1") {
      const payload = request.postDataJSON();
      Object.assign(user, {
        ...payload,
        roles: payload.roles
          ? payload.roles.map((role: any) => ({ ...role, role: role.code }))
          : user.roles,
      });
      delete user.password;
      body = user;
    } else if (path === "/v1/entity-types") {
      if (request.method() === "POST")
        Object.assign(category, request.postDataJSON());
      body = { items: [category] };
    } else if (path.endsWith("/policy-drafts")) body = { items: [policy] };
    else if (path.endsWith("/content")) body = { items: [content] };
    else if (path.endsWith("/content/coverage")) body = { locales: [] };
    await route.fulfill({ json: body });
  });
  return { requests, writes, errors };
}

test("navigation groups workspaces, searches labels and retains stable routes", async ({
  page,
}, info) => {
  const state = await fixtures(page);
  await page.goto("/dashboard");
  await expect(
    page.getByRole("heading", { name: "Overview", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("navigation", { name: "Entities", exact: true }),
  ).toBeVisible();
  await page.getByLabel("Find a workspace").fill("categories");
  await expect(
    page.locator(".sidebar").getByRole("link", { name: "Entity categories" }),
  ).toBeVisible();
  await expect(
    page.locator(".sidebar").getByRole("link", { name: "Users & access" }),
  ).toHaveCount(0);
  await page.getByLabel("Find a workspace").fill("");
  await page.screenshot({
    path: info.outputPath("overview-desktop.png"),
    fullPage: true,
  });
  await page
    .locator(".sidebar")
    .getByRole("link", { name: "Entity categories" })
    .click();
  await expect(
    page
      .getByRole("heading", { name: "Entity categories", exact: true })
      .first(),
  ).toBeVisible();
  expect(state.errors).toEqual([]);
});

test("restricted dashboard never requests unauthorized identity or activity data and guards deep links", async ({
  page,
}) => {
  const state = await fixtures(page, ["geodata.review"]);
  await page.goto("/dashboard");
  await expect(
    page.getByRole("heading", { name: "Candidates needing review" }),
  ).toBeVisible();
  await expect(
    page.locator(".sidebar").getByRole("link", { name: "Users & access" }),
  ).toHaveCount(0);
  expect(
    state.requests.some(
      (path) => path.includes("/admin/") || path === "/v1/activations",
    ),
  ).toBe(false);
  await page.goto("/identity");
  await expect(page).toHaveURL(/access-denied/);
  await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();
  expect(state.requests.filter((path) => path.includes("/admin/"))).toEqual([]);
});

test("partial service failure shows an alert, not invented zero counts, and refresh recovers", async ({
  page,
}) => {
  const state = await fixtures(page, ["*"], "/v1/activations");
  await page.goto("/dashboard");
  await expect(page.getByRole("alert")).toContainText(
    "activity data is unavailable",
  );
  await expect(
    page
      .locator(".metric")
      .filter({ hasText: "Activations" })
      .locator("strong"),
  ).toHaveText("—");
  await page.route("**/v1/activations?*", (route) =>
    route.fulfill({ json: { items: [], total: 4 } }),
  );
  await page.getByRole("button", { name: "Refresh", exact: true }).click();
  await expect(page.getByRole("alert")).toHaveCount(0);
  await expect(
    page
      .locator(".metric")
      .filter({ hasText: "Activations" })
      .locator("strong"),
  ).toHaveText("4");
  expect(state.errors).toEqual([]);
});

test("user saves retain scoped assignments, clear password and keep roles in separate tabs", async ({
  page,
}, info) => {
  const state = await fixtures(page);
  await page.goto("/identity");
  await page.getByRole("button", { name: /Existing user/ }).click();
  await expect(page.getByLabel("Display name", { exact: true })).toHaveValue(
    "Existing user",
  );
  await page.getByLabel("Display name", { exact: true }).fill("Renamed user");
  await page.getByRole("button", { name: "Save user", exact: true }).click();
  await expect(page.getByRole("status")).toContainText("User saved");
  expect(state.writes[0].body.roles).toBeUndefined();
  await page.getByRole("checkbox", { name: /Custom reader/ }).check();
  await page.getByLabel("Reset password").fill("isolated-new-password");
  await page.getByRole("button", { name: "Save user", exact: true }).click();
  await expect(page.getByLabel("Reset password")).toHaveValue("");
  expect(state.writes[1].body.roles).toEqual([
    {
      code: "GEO_APPROVER",
      programmeSlug: "sevilla",
      jurisdiction: "ES-AN",
      entityType: "PARK",
    },
    {
      code: "GEO_APPROVER",
      programmeSlug: "regional",
      jurisdiction: "ES-MD",
      entityType: "TRAIL",
    },
    { code: "CUSTOM_READER" },
  ]);
  await page.screenshot({
    path: info.outputPath("users-editor.png"),
    fullPage: true,
  });
  await page
    .getByRole("button", { name: "Roles & permissions", exact: true })
    .click();
  await page.getByRole("button", { name: /Geodata reviewer/ }).click();
  await expect(page.getByLabel("Display name", { exact: true })).toBeDisabled();
  await expect(page.getByRole("button", { name: "Save role" })).toHaveCount(0);
  await page.getByRole("button", { name: /Custom reader/ }).click();
  await expect(page.getByLabel("Display name", { exact: true })).toBeEnabled();
  expect(state.errors).toEqual([]);
});

test("roles-only access loads no account/security lists and opens the roles tab", async ({
  page,
}) => {
  const state = await fixtures(page, ["identity.roles.manage"]);
  await page.goto("/identity?tab=roles");
  await expect(
    page.getByRole("button", { name: "New custom role" }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Users", exact: true }),
  ).toHaveCount(0);
  expect(
    state.requests.some(
      (path) => path.endsWith("/accounts") || path.endsWith("/security-events"),
    ),
  ).toBe(false);
});

test("published policies/content are read-only and programme scope appears once", async ({
  page,
}) => {
  const state = await fixtures(page);
  await page.goto("/policies");
  await page.getByRole("button", { name: /Published policy/ }).click();
  await expect(page.getByLabel("Name", { exact: true })).toHaveAttribute(
    "readonly",
    "",
  );
  await expect(page.getByRole("button", { name: "Save draft" })).toHaveCount(0);
  await expect(
    page
      .locator("select")
      .filter({ has: page.locator('option[value="sevilla"]') }),
  ).toHaveCount(1);
  await page.getByLabel("Programme", { exact: true }).selectOption("regional");
  await expect(page.locator(".scope-indicator")).toHaveText(
    "Regional initiative",
  );
  await expect(page.getByLabel("Name", { exact: true })).toHaveValue("");
  await page.goto("/content");
  await page.getByRole("button", { name: /welcome/ }).click();
  await expect(page.getByLabel("Text or content value")).toHaveValue(
    "Existing published text",
  );
  await expect(page.getByLabel("Text or content value")).toHaveAttribute(
    "readonly",
    "",
  );
  await expect(page.getByRole("button", { name: "Save draft" })).toHaveCount(0);
  expect(state.writes).toEqual([]);
});

test("shared category edit loads immutable code and saves editable fields with clear feedback", async ({
  page,
}) => {
  const state = await fixtures(page);
  await page.goto("/master-data");
  await page.getByRole("button", { name: /Existing park/ }).click();
  await expect(page.getByLabel("Category code")).toHaveValue("PARK");
  await expect(page.getByLabel("Category code")).toHaveAttribute(
    "readonly",
    "",
  );
  await page.getByLabel("Display name", { exact: true }).fill("Renamed park");
  await page.getByRole("button", { name: "Save category" }).click();
  await expect(page.getByRole("status")).toContainText("Category saved");
  await expect(page.getByLabel("Display name", { exact: true })).toHaveValue(
    "Renamed park",
  );
  expect(state.writes[0].body.geometryTypes).toEqual(["POINT", "POLYGON"]);
});

test("category catalogue is read-only for a geodata reviewer", async ({
  page,
}) => {
  await fixtures(page, ["geodata.review"]);
  await page.goto("/master-data");
  await expect(page.getByRole("button", { name: "New category" })).toHaveCount(
    0,
  );
  await page.getByRole("button", { name: /Existing park/ }).click();
  await expect(page.getByLabel("Display name", { exact: true })).toBeDisabled();
  await expect(page.getByRole("button", { name: "Save category" })).toHaveCount(
    0,
  );
});

test("narrow viewport navigation opens, closes on selection and avoids page overflow", async ({
  page,
}, info) => {
  await fixtures(page);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/dashboard");
  await page.getByRole("button", { name: "Toggle navigation" }).click();
  await expect(page.getByLabel("Find a workspace")).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(
    page.getByRole("button", { name: "Toggle navigation" }),
  ).toBeFocused();
  await page.getByRole("button", { name: "Toggle navigation" }).click();
  await expect(
    page.getByRole("button", { name: "Toggle navigation" }),
  ).toHaveAttribute("aria-expanded", "true");
  await page
    .locator(".sidebar")
    .getByRole("link", { name: "Users & access" })
    .click();
  await expect(
    page.getByRole("button", { name: "Toggle navigation" }),
  ).toHaveAttribute("aria-expanded", "false");
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({
    path: info.outputPath("users-mobile.png"),
    fullPage: true,
  });
});

test("award readers can inspect but cannot edit, upload or request an admin preview", async ({
  page,
}) => {
  const state = await fixtures(page, ["awards.read"]);
  await page.goto("/awards");
  await expect(
    page.getByRole("heading", { name: "Awards & certificates", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "New award draft" }),
  ).toHaveCount(0);
  await expect(page.getByLabel("Name", { exact: true })).toHaveAttribute(
    "readonly",
    "",
  );
  await expect(
    page.getByRole("button", { name: "Generate preview PDF" }),
  ).toBeDisabled();
  await expect(page.locator(".award-upload-fields")).toHaveAttribute(
    "disabled",
    "",
  );
  await expect(
    page.locator(".award-upload-fields input").first(),
  ).toBeDisabled();
  expect(state.writes).toEqual([]);
  expect(state.errors).toEqual([]);
});

test("programme choice outage keeps the authenticated session and supports retry", async ({
  page,
}) => {
  await fixtures(page, ["geodata.review"], "/v1/programmes");
  await page.goto("/dashboard");
  await expect(page.locator(".warning-banner")).toContainText(
    "Your session is still active",
  );
  await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();
  await page.route("**/v1/programmes", (route) =>
    route.fulfill({ json: { items: [] } }),
  );
  await page.locator(".warning-banner").getByRole("button").click();
  await expect(page.locator(".warning-banner")).toHaveCount(0);
  expect(
    await page.evaluate(() => localStorage.getItem("myota_admin_access")),
  ).toBe("isolated-token");
});

test("legacy SeaweedFS Admin bookmark redirects to the provisioned Grafana dashboard", async ({
  page,
}) => {
  await fixtures(page, ["observability.view"]);
  await page.route("**/observability/d/myota-object-storage", (route) =>
    route.fulfill({ status: 200, body: "Grafana dashboard" }),
  );
  await page.goto("/object-storage");
  await expect(page).toHaveURL(/\/observability\/d\/myota-object-storage$/);
});

test("Grafana stays inside the Admin UI and renews its expiring auth cookie", async ({
  page,
}) => {
  let refreshes = 0;
  await page.addInitScript(() => {
    const encode = (value: unknown) =>
      btoa(JSON.stringify(value))
        .replace(/=/g, "")
        .replace(/\+/g, "-")
        .replace(/\//g, "_");
    const token = `header.${encode({ exp: Math.floor(Date.now() / 1000) + 60 })}.signature`;
    localStorage.setItem("myota_admin_access", token);
    localStorage.setItem("myota_admin_refresh", "refresh-fixture");
  });
  await page.route("**/v1/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/v1/identity/auth/refresh") {
      refreshes += 1;
      const exp = Math.floor(Date.now() / 1000) + 600;
      const payload = btoa(JSON.stringify({ exp }))
        .replace(/=/g, "")
        .replace(/\+/g, "-")
        .replace(/\//g, "_");
      return route.fulfill({
        json: {
          accessToken: `header.${payload}.signature`,
          refreshToken: `refresh-fixture-${refreshes}`,
        },
      });
    }
    if (path === "/v1/identity/me")
      return route.fulfill({
        json: {
          id: "admin-1",
          displayName: "Admin",
          email: "admin@example.test",
          roles: [],
          scopes: ["observability.view"],
        },
      });
    if (path === "/v1/programmes")
      return route.fulfill({ json: { items: [] } });
    return route.fulfill({ json: {} });
  });
  await page.route("**/observability/**", (route) =>
    route.fulfill({ status: 200, contentType: "text/html", body: "Grafana" }),
  );

  await page.goto("/dashboard");
  await page.getByRole("link", { name: "Metrics & dashboards" }).click();
  await expect(page).toHaveURL(/\/grafana$/);
  await expect(page.getByTitle("MyOTA Grafana dashboards")).toHaveAttribute(
    "src",
    "/observability/",
  );
  await expect.poll(() => refreshes).toBe(1);

  const cookie = (await page.context().cookies()).find(
    (item) => item.name === "myota_admin_access",
  );
  expect(cookie?.path).toBe("/observability");
  expect(cookie?.value).toBe(
    await page.evaluate(() => localStorage.getItem("myota_admin_access")),
  );
});
