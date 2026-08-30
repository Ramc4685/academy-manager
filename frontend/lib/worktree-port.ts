// Per-worktree port derivation for the local e2e stack (#522).
//
// Every git worktree used to default to port 3001, which made the local e2e
// gate a one-worktree-at-a-time resource: with CI=true the webServer could not
// bind while another worktree's `next dev` held 3001 (mass fake regressions),
// and without CI, reuseExistingServer silently attached to the OTHER
// worktree's server and green-lighted code that never ran.
//
// The fix: hash the repo root path into a deterministic port in 3001-3999, so
// each worktree gets its own stable default. Explicit PLAYWRIGHT_PORT /
// FRONTEND_PORT overrides still win; only scripts/local_test_stack.sh keeps
// the historical 3001 under CI (the real-auth workflow pins
// LOCAL_AUTH_BASE_URL to http://localhost:3001).
//
// The djb2 hash below is duplicated in scripts/dev/lib/worktree-port.sh; the
// node test cross-checks both implementations byte-for-byte. Paths are hashed
// as ASCII/UTF-16 code units (TS) vs bytes (bash) — identical for ASCII
// paths, which repo checkouts are expected to use.

export const WORKTREE_PORT_BASE = 3001;
export const WORKTREE_PORT_RANGE = 999; // ports 3001-3999

/** djb2 (h*33 + c) over the path, mod 2^32. Mirrors worktree-port.sh. */
export function hashPath(path: string): number {
  let h = 5381;
  for (let i = 0; i < path.length; i++) {
    h = (Math.imul(h, 33) + path.charCodeAt(i)) >>> 0;
  }
  return h;
}

/** Deterministic per-worktree port in [3001, 3999] derived from the repo root path. */
export function deriveWorktreePort(repoRoot: string): number {
  return WORKTREE_PORT_BASE + (hashPath(repoRoot) % WORKTREE_PORT_RANGE);
}

/**
 * Resolve the frontend port for this run: an explicit override
 * (PLAYWRIGHT_PORT) wins, otherwise a stable per-worktree port derived from
 * the repo root. Deliberately NOT pinned to 3001 under CI=true — the local
 * pre-push e2e gate runs with CI=true from every worktree, which is exactly
 * the collision this exists to prevent. GitHub Actions derives a port too;
 * baseURL and webServer share it, so the absolute value does not matter
 * there. Only scripts/local_test_stack.sh keeps a CI pin (the real-auth
 * workflow hardcodes LOCAL_AUTH_BASE_URL=http://localhost:3001).
 */
export function resolvePort(env: { override?: string; repoRoot: string }): string {
  if (env.override) return env.override;
  return String(deriveWorktreePort(env.repoRoot));
}
