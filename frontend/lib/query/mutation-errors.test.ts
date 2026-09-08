import { afterEach, describe, expect, it, vi } from "vitest";
import { MutationCache, MutationObserver, QueryClient } from "@tanstack/react-query";

import {
  describeMutationError,
  handleGlobalMutationError,
  registerMutationErrorSink,
  shouldNotifyGlobally,
  type MutationErrorNotice,
} from "./mutation-errors";

function makeApiError(status: number, message: string): Error & { status: number } {
  const err = new Error(message) as Error & { status: number };
  err.status = status;
  return err;
}

/** A QueryClient wired exactly like lib/providers.tsx wires the real one. */
function makeClient(): QueryClient {
  return new QueryClient({
    mutationCache: new MutationCache({
      onError: (error, _variables, _context, mutation) => {
        handleGlobalMutationError(error, mutation);
      },
    }),
    defaultOptions: { mutations: { retry: false } },
  });
}

async function runFailingMutation(
  client: QueryClient,
  options: {
    onError?: (error: unknown) => void;
    meta?: Record<string, unknown>;
  } = {},
): Promise<void> {
  const observer = new MutationObserver(client, {
    mutationFn: async () => {
      throw makeApiError(409, "Session already has active enrollments");
    },
    ...options,
  });
  await observer.mutate().catch(() => {
    /* the caller-side rejection is expected */
  });
}

describe("describeMutationError", () => {
  it("maps a 4xx ApiError to its server message", () => {
    const notice = describeMutationError(makeApiError(409, "Seat already taken"));
    expect(notice.title).toBe("Action failed");
    expect(notice.description).toBe("Seat already taken");
  });

  it("maps a 5xx ApiError to a server-error title", () => {
    const notice = describeMutationError(makeApiError(500, "boom"));
    expect(notice.title).toBe("Something went wrong");
    expect(notice.description).toBe("boom");
  });

  it("maps the 20s client abort to a timeout message", () => {
    const abort = new Error("The operation was aborted");
    abort.name = "AbortError";
    const notice = describeMutationError(abort);
    expect(notice.title).toBe("Request timed out");
  });

  it("appends the first 8 chars of the request id as a support reference", () => {
    const err = makeApiError(500, "boom") as Error & { status: number; requestId?: string };
    err.requestId = "0f3a9c2e-7b1d-4e55-9a10-abcdef012345";
    const notice = describeMutationError(err);
    expect(notice.title).toBe("Something went wrong");
    expect(notice.description).toBe("boom Reference: 0f3a9c2e");
  });

  it("shows the reference even when there is no server message", () => {
    const err = makeApiError(502, "Request failed") as Error & { status: number; requestId?: string };
    err.requestId = "abcdefghijk";
    const notice = describeMutationError(err);
    expect(notice.description).toBe(
      "The server hit an unexpected error. Please try again. Reference: abcdefgh"
    );
  });

  it("omits the reference when no request id reached the client", () => {
    const notice = describeMutationError(makeApiError(409, "Seat already taken"));
    expect(notice.description).not.toMatch(/Reference:/);
  });

  it("falls back to a generic description for opaque errors", () => {
    const notice = describeMutationError(new Error("Request failed"));
    expect(notice.title).toBe("Action failed");
    expect(notice.description).toMatch(/could not be completed/i);
  });
});

describe("shouldNotifyGlobally", () => {
  it("skips mutations that define their own onError", () => {
    expect(shouldNotifyGlobally({ options: { onError: () => undefined } })).toBe(false);
  });

  it("skips mutations that opt out via meta.suppressGlobalError", () => {
    expect(
      shouldNotifyGlobally({ options: {}, meta: { suppressGlobalError: true } }),
    ).toBe(false);
  });

  it("notifies for mutations with no error handling of their own", () => {
    expect(shouldNotifyGlobally({ options: {} })).toBe(true);
  });
});

describe("MutationCache onError default (providers wiring)", () => {
  let unregister: (() => void) | null = null;

  afterEach(() => {
    unregister?.();
    unregister = null;
  });

  it("pushes an error notice to the registered sink when a mutation fails", async () => {
    const notices: MutationErrorNotice[] = [];
    unregister = registerMutationErrorSink((n) => notices.push(n));

    await runFailingMutation(makeClient());

    expect(notices).toHaveLength(1);
    expect(notices[0].title).toBe("Action failed");
    expect(notices[0].description).toBe("Session already has active enrollments");
  });

  it("does not double-notify when the mutation has a contextual onError", async () => {
    const notices: MutationErrorNotice[] = [];
    unregister = registerMutationErrorSink((n) => notices.push(n));
    const contextual = vi.fn();

    await runFailingMutation(makeClient(), { onError: contextual });

    expect(contextual).toHaveBeenCalledTimes(1);
    expect(notices).toHaveLength(0);
  });

  it("respects meta.suppressGlobalError", async () => {
    const notices: MutationErrorNotice[] = [];
    unregister = registerMutationErrorSink((n) => notices.push(n));

    await runFailingMutation(makeClient(), { meta: { suppressGlobalError: true } });

    expect(notices).toHaveLength(0);
  });

  it("falls back to console.error when no sink is registered", async () => {
    const spy = vi.spyOn(console, "error").mockImplementation(() => undefined);
    try {
      await runFailingMutation(makeClient());
      expect(spy).toHaveBeenCalledTimes(1);
      expect(spy.mock.calls[0][0]).toBe("[mutation]");
    } finally {
      spy.mockRestore();
    }
  });

  it("unregistering restores the console fallback", async () => {
    const notices: MutationErrorNotice[] = [];
    const un = registerMutationErrorSink((n) => notices.push(n));
    un();
    const spy = vi.spyOn(console, "error").mockImplementation(() => undefined);
    try {
      await runFailingMutation(makeClient());
      expect(notices).toHaveLength(0);
      expect(spy).toHaveBeenCalledTimes(1);
    } finally {
      spy.mockRestore();
    }
  });
});
