import assert from "node:assert/strict";
import { test } from "node:test";
import {
  canAdministerLocation,
  canBrowseEntities,
  hasAnyScope,
  isGlobalAdministrator,
  roleAssignmentPayload,
} from "../src/lib/adminAccess.ts";

test("permissions resolve canonical scopes without granting another service domain", () => {
  const account = {
    id: "reviewer",
    email: "",
    displayName: "",
    scopes: ["geodata.review"],
    roles: [],
  };
  assert.equal(canBrowseEntities(account), true);
  assert.equal(hasAnyScope(account, "identity.admin"), false);
  assert.equal(hasAnyScope(account, "awards.admin"), false);
  assert.equal(canAdministerLocation(account), false);
  assert.equal(hasAnyScope(null, "geodata.review"), false);
});

test("global compatibility roles and wildcard have the same navigation access", () => {
  for (const account of [
    { roles: [{ role: "GLOBAL_ADMIN" }] },
    { roles: [{ role: "GLOBAL_OPERATOR" }] },
    { scopes: ["*"] },
  ]) {
    const resolved = { id: "global", email: "", displayName: "", ...account };
    assert.equal(isGlobalAdministrator(resolved), true);
    assert.equal(hasAnyScope(resolved, "identity.roles.manage"), true);
  }
});

test("GIS location access mirrors the service GIS_ADMIN compatibility rule", () => {
  assert.equal(
    canAdministerLocation({
      id: "gis",
      email: "",
      displayName: "",
      roles: [{ role: "GIS_ADMIN" }],
    }),
    true,
  );
});

test("retained roles preserve every programme, jurisdiction and category restriction", () => {
  const original = [
    {
      role: "GEO_APPROVER",
      programmeSlug: "one",
      jurisdiction: "ES-AN",
      entityType: "PARK",
    },
    {
      role: "GEO_APPROVER",
      programmeSlug: "two",
      jurisdiction: "ES-MD",
      entityType: "TRAIL",
    },
    { role: "OLD_ROLE", programmeSlug: "one" },
  ];
  assert.deepEqual(
    roleAssignmentPayload(
      ["GEO_APPROVER", "GEO_APPROVER", "ACTIVITY_ADMIN"],
      original,
    ),
    [
      {
        code: "GEO_APPROVER",
        programmeSlug: "one",
        jurisdiction: "ES-AN",
        entityType: "PARK",
      },
      {
        code: "GEO_APPROVER",
        programmeSlug: "two",
        jurisdiction: "ES-MD",
        entityType: "TRAIL",
      },
      { code: "ACTIVITY_ADMIN" },
    ],
  );
  assert.deepEqual(roleAssignmentPayload([], original), []);
});
