import { describe, expect, it } from "vitest";

import { isAuthRejection, withTransientRetry } from "./me-failure";

function apiError(status: number): Error {
  return Object.assign(new Error("Request failed"), { status });
}

const noSleep = () => Promise.resolve();

describe("isAuthRejection", () => {
  it("treats 401 and 403 as auth rejections", () => {
    expect(isAuthRejection(apiError(401))).toBe(true);
    expect(isAuthRejection(apiError(403))).toBe(true);
  });

  it("treats 5xx responses as transient, not auth failures", () => {
    expect(isAuthRejection(apiError(500))).toBe(false);
    expect(isAuthRejection(apiError(502))).toBe(false);
    expect(isAuthRejection(apiError(503))).toBe(false);
  });

  it("treats network failures and aborts (no status) as transient", () => {
    expect(isAuthRejection(new Error("Failed to fetch"))).toBe(false);
    expect(
      isAuthRejection(
        Object.assign(new Error("The operation was aborted"), {
          name: "AbortError",
        }),
      ),
    ).toBe(false);
    expect(isAuthRejection(null)).toBe(false);
    expect(isAuthRejection(undefined)).toBe(false);
    expect(isAuthRejection("boom")).toBe(false);
  });
});

describe("withTransientRetry", () => {
  it("returns the value when the first attempt succeeds", async () => {
    const result = await withTransientRetry(() => Promise.resolve("ok"), {
      sleep: noSleep,
    });
    expect(result).toBe("ok");
  });

  it("rethrows a 401 immediately without retrying", async () => {
    let calls = 0;
    const err = apiError(401);
    await expect(
      withTransientRetry(
        () => {
          calls += 1;
          return Promise.reject(err);
        },
        { sleep: noSleep },
      ),
    ).rejects.toBe(err);
    expect(calls).toBe(1);
  });

  it("rethrows a 403 immediately without retrying", async () => {
    let calls = 0;
    await expect(
      withTransientRetry(
        () => {
          calls += 1;
          return Promise.reject(apiError(403));
        },
        { sleep: noSleep },
      ),
    ).rejects.toMatchObject({ status: 403 });
    expect(calls).toBe(1);
  });

  it("retries a 500 and succeeds on a later attempt", async () => {
    let calls = 0;
    const result = await withTransientRetry(
      () => {
        calls += 1;
        return calls < 2 ? Promise.reject(apiError(500)) : Promise.resolve("ok");
      },
      { sleep: noSleep },
    );
    expect(result).toBe("ok");
    expect(calls).toBe(2);
  });

  it("retries a network failure and succeeds on a later attempt", async () => {
    let calls = 0;
    const result = await withTransientRetry(
      () => {
        calls += 1;
        return calls < 3
          ? Promise.reject(new Error("Failed to fetch"))
          : Promise.resolve("ok");
      },
      { sleep: noSleep },
    );
    expect(result).toBe("ok");
    expect(calls).toBe(3);
  });

  it("gives up after the configured attempts and rethrows the last error", async () => {
    let calls = 0;
    const err = apiError(503);
    await expect(
      withTransientRetry(
        () => {
          calls += 1;
          return Promise.reject(err);
        },
        { attempts: 3, sleep: noSleep },
      ),
    ).rejects.toBe(err);
    expect(calls).toBe(3);
  });

  it("stops retrying the moment a transient failure turns into a 401", async () => {
    let calls = 0;
    await expect(
      withTransientRetry(
        () => {
          calls += 1;
          return calls === 1
            ? Promise.reject(apiError(500))
            : Promise.reject(apiError(401));
        },
        { sleep: noSleep },
      ),
    ).rejects.toMatchObject({ status: 401 });
    expect(calls).toBe(2);
  });

  it("waits between attempts using the provided backoff", async () => {
    const delays: number[] = [];
    await expect(
      withTransientRetry(() => Promise.reject(apiError(500)), {
        sleep: (ms) => {
          delays.push(ms);
          return Promise.resolve();
        },
      }),
    ).rejects.toMatchObject({ status: 500 });
    expect(delays).toEqual([500, 1_500]);
  });
});
