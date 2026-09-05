import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const sentryMock = vi.hoisted(() => {
  const scope = { setTag: vi.fn(), setContext: vi.fn() };
  return {
    scope,
    init: vi.fn(),
    captureException: vi.fn(),
    withScope: vi.fn((cb: (s: typeof scope) => void) => cb(scope)),
    metrics: { distribution: vi.fn() },
  };
});

vi.mock("@sentry/browser", () => sentryMock);

import { captureError, initSentry, recordVital, resetSentryForTests } from "./sentry";

describe("lib/observability/sentry", () => {
  beforeEach(() => {
    resetSentryForTests();
    vi.stubGlobal("window", {});
  });

  afterEach(() => {
    vi.unstubAllEnvs();
    vi.unstubAllGlobals();
    vi.clearAllMocks();
  });

  it("is a no-op and never loads the SDK when the DSN is unset", async () => {
    vi.stubEnv("NEXT_PUBLIC_SENTRY_DSN", "");
    expect(await initSentry()).toBeNull();
    captureError(new Error("boom"), { digest: "d1" });
    recordVital("LCP", 1200, { route: "coach.today" });
    await Promise.resolve();
    expect(sentryMock.init).not.toHaveBeenCalled();
    expect(sentryMock.captureException).not.toHaveBeenCalled();
    expect(sentryMock.metrics.distribution).not.toHaveBeenCalled();
  });

  it("initialises once with errors-only, PII-off settings when the DSN is set", async () => {
    vi.stubEnv("NEXT_PUBLIC_SENTRY_DSN", "https://key@o1.ingest.us.sentry.io/1");
    vi.stubEnv("NEXT_PUBLIC_APP_ENV", "staging");
    vi.stubEnv("NEXT_PUBLIC_SENTRY_RELEASE", "abc123");

    await initSentry();
    await initSentry();

    expect(sentryMock.init).toHaveBeenCalledTimes(1);
    expect(sentryMock.init).toHaveBeenCalledWith({
      dsn: "https://key@o1.ingest.us.sentry.io/1",
      environment: "staging",
      release: "abc123",
      sampleRate: 1,
      tracesSampleRate: 0,
      sendDefaultPii: false,
    });
  });

  it("defaults the environment to production and omits an unset release", async () => {
    vi.stubEnv("NEXT_PUBLIC_SENTRY_DSN", "https://key@o1.ingest.us.sentry.io/1");
    vi.stubEnv("NEXT_PUBLIC_APP_ENV", "");
    vi.stubEnv("NEXT_PUBLIC_SENTRY_RELEASE", "");

    await initSentry();

    expect(sentryMock.init.mock.calls[0][0]).toMatchObject({
      environment: "production",
      release: undefined,
    });
  });

  it("captures errors with the Next digest as a tag", async () => {
    vi.stubEnv("NEXT_PUBLIC_SENTRY_DSN", "https://key@o1.ingest.us.sentry.io/1");
    const error = new Error("render failed");

    captureError(error, { digest: "digest-1", tags: { boundary: "route" }, extra: { a: 1 } });
    await initSentry();
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(sentryMock.captureException).toHaveBeenCalledWith(error);
    expect(sentryMock.scope.setTag).toHaveBeenCalledWith("next.digest", "digest-1");
    expect(sentryMock.scope.setTag).toHaveBeenCalledWith("boundary", "route");
    expect(sentryMock.scope.setContext).toHaveBeenCalledWith("extra", { a: 1 });
  });

  it("records Web Vitals as distribution metrics", async () => {
    vi.stubEnv("NEXT_PUBLIC_SENTRY_DSN", "https://key@o1.ingest.us.sentry.io/1");

    recordVital("LCP", 1234.5, { rating: "good", route: "coach.today", id: "v1" });
    recordVital("CLS", 0.02, { rating: "good", route: "coach.today", id: "v2" });
    await initSentry();
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(sentryMock.metrics.distribution).toHaveBeenCalledWith("web_vitals.lcp", 1234.5, {
      unit: "millisecond",
      attributes: { rating: "good", route: "coach.today", id: "v1" },
    });
    expect(sentryMock.metrics.distribution).toHaveBeenCalledWith("web_vitals.cls", 0.02, {
      unit: "none",
      attributes: { rating: "good", route: "coach.today", id: "v2" },
    });
  });
});
