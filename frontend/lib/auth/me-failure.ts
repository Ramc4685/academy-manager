/**
 * Transient-failure handling for the /me identity check (issue #515).
 *
 * `getCurrentUser()` is a raw promise (dedup:false, not react-query), so no
 * retry policy applies to it. Before this module, every rejection — a single
 * backend 500 during a deploy, a network blip, or the client's own 20-second
 * abort — was treated as an auth failure: identity cookie cleared, hard
 * redirect to /login, even though the Firebase session was still valid.
 *
 * Only 401/403 mean "this session is not (or no longer) authenticated".
 * Everything else is treated as transient: retried with a short backoff, and
 * surfaced to the caller as a recoverable outage rather than a logout.
 */

interface StatusCarrier {
  status?: unknown;
}

/**
 * True only for rejections that genuinely mean the caller is not
 * authenticated/authorized (HTTP 401 or 403 from the backend). Network
 * failures, aborts, and 5xx responses carry either no `status` or a
 * non-auth status and must NOT log the user out.
 */
export function isAuthRejection(err: unknown): boolean {
  if (typeof err !== "object" || err === null) return false;
  const status = (err as StatusCarrier).status;
  return status === 401 || status === 403;
}

export interface TransientRetryOptions {
  /** Total attempts including the first one. Default 3. */
  attempts?: number;
  /** Delay before retry N (1-based). Default 500ms, then 1500ms. */
  delayMs?: (retry: number) => number;
  /** Injectable for tests. */
  sleep?: (ms: number) => Promise<void>;
}

const DEFAULT_ATTEMPTS = 3;

function defaultDelayMs(retry: number): number {
  return retry === 1 ? 500 : 1_500;
}

function defaultSleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/**
 * Run `fn`, retrying transient failures with backoff. Auth rejections
 * (401/403) are rethrown immediately — retrying cannot fix a dead session,
 * and the caller must redirect to /login. Any other rejection is retried
 * up to `attempts` total tries; the last rejection is rethrown so the
 * caller can show a "can't reach the server" state.
 */
export async function withTransientRetry<T>(
  fn: () => Promise<T>,
  options: TransientRetryOptions = {},
): Promise<T> {
  const attempts = options.attempts ?? DEFAULT_ATTEMPTS;
  const delayMs = options.delayMs ?? defaultDelayMs;
  const sleep = options.sleep ?? defaultSleep;

  let lastError: unknown;
  for (let attempt = 1; attempt <= attempts; attempt += 1) {
    try {
      return await fn();
    } catch (err) {
      if (isAuthRejection(err)) throw err;
      lastError = err;
      if (attempt < attempts) {
        await sleep(delayMs(attempt));
      }
    }
  }
  throw lastError;
}
