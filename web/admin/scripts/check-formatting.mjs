import { execFileSync, spawnSync } from "node:child_process";

const suppliedBase = process.env.BASE_SHA ?? "";
const zeroSha = /^0+$/;
let baseSha = suppliedBase;

if (!baseSha || zeroSha.test(baseSha)) {
  baseSha = execFileSync("git", ["merge-base", "origin/testing", "HEAD"], {
    encoding: "utf8",
  }).trim();
}

const changedFiles = execFileSync(
  "git",
  ["diff", "--name-only", "--diff-filter=ACMR", `${baseSha}...HEAD`],
  { encoding: "utf8" },
)
  .split("\n")
  .filter(
    (file) =>
      file && /^(src|scripts)\/.*\.(css|js|json|ts|vue|mjs)$/.test(file),
  );

if (changedFiles.length === 0) {
  console.log("No changed frontend source files require formatting checks.");
  process.exit(0);
}

const result = spawnSync("npx", ["prettier", "--check", ...changedFiles], {
  stdio: "inherit",
});
process.exit(result.status ?? 1);
