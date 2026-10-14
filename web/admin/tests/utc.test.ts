import assert from "node:assert/strict";
import { test } from "node:test";
import { utcDisplay, utcInput, utcInputValue, utcIso } from "../src/lib/utc.ts";

test("UTC inputs are independent of local offsets and preserve untouched seconds", () => {
  assert.equal(utcInput("2026-10-09T14:45:30+02:00"), "2026-10-09T12:45");
  assert.equal(
    utcInputValue("2026-10-09T12:45", "2026-10-09T12:45:30Z"),
    "2026-10-09T12:45:30.000Z",
  );
  assert.equal(utcInputValue("2026-10-09T13:15"), "2026-10-09T13:15:00.000Z");
  assert.equal(utcInputValue(""), null);
  assert.equal(utcIso("2026-10-25T01:30"), "2026-10-25T01:30:00.000Z");
});
test("UTC displays explicitly identify the zone; invalid values do not become local times", () => {
  assert.equal(
    utcDisplay("2026-10-09T14:45:30+02:00"),
    "2026-10-09 12:45:30 UTC",
  );
  assert.equal(utcDisplay(), "Not sampled yet");
  assert.equal(utcDisplay("bad"), "Invalid timestamp");
  assert.throws(() => utcIso("bad"), /valid UTC/);
});
