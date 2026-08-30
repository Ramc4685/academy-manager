import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { existsSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { test } from "node:test";

import {
  WORKTREE_PORT_BASE,
  WORKTREE_PORT_RANGE,
  deriveWorktreePort,
  resolvePort,
} from "./worktree-port.ts";

const repoRoot = resolve(dirname(fileURLToPath(import.meta.url)), "../..");
const bashLib = resolve(repoRoot, "scripts/dev/lib/worktree-port.sh");

const SAMPLE_PATHS = [
  "/Users/dev/Documents/Code/academy-manager",
  "/Users/dev/Documents/Code/academy-manager/.claude/worktrees/p2-522",
  "/Users/dev/Documents/Code/academy-manager/.claude/worktrees/feat-x",
  "/home/runner/work/academy-manager/academy-manager",
  "/tmp/a",
];

test("derived ports stay inside the 3001-3999 worktree range", () => {
  for (const p of SAMPLE_PATHS) {
    const port = deriveWorktreePort(p);
    assert.ok(
      port >= WORKTREE_PORT_BASE &&
        port < WORKTREE_PORT_BASE + WORKTREE_PORT_RANGE,
      `${p} derived out-of-range port ${port}`,
    );
  }
});

test("derivation is deterministic for the same path", () => {
  for (const p of SAMPLE_PATHS) {
    assert.equal(deriveWorktreePort(p), deriveWorktreePort(p));
  }
});

test("distinct worktree paths derive distinct ports (the #522 collision)", () => {
  // The exact guarantee the bug needs: a worktree and its parent checkout —
  // and sibling worktrees — must not share a default port.
  const ports = new Set(SAMPLE_PATHS.map(deriveWorktreePort));
  assert.equal(ports.size, SAMPLE_PATHS.length);
});

test("explicit PLAYWRIGHT_PORT override wins over derivation", () => {
  assert.equal(resolvePort({ override: "4123", repoRoot: SAMPLE_PATHS[0] }), "4123");
});

test("without an override the per-worktree port is used (never a fixed 3001 for all)", () => {
  assert.equal(
    resolvePort({ repoRoot: SAMPLE_PATHS[0] }),
    String(deriveWorktreePort(SAMPLE_PATHS[0])),
  );
});

test("bash implementation (scripts/dev/lib/worktree-port.sh) agrees byte-for-byte", () => {
  assert.ok(existsSync(bashLib), `missing ${bashLib}`);
  for (const p of SAMPLE_PATHS) {
    const bashPort = execFileSync("bash", [
      "-c",
      `. "$1" && derive_worktree_port "$2"`,
      "worktree-port-test",
      bashLib,
      p,
    ])
      .toString()
      .trim();
    assert.equal(
      bashPort,
      String(deriveWorktreePort(p)),
      `bash and TS derivations diverge for ${p}`,
    );
  }
});
