import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const observability = vi.hoisted(() => ({ captureError: vi.fn() }));

vi.mock("@/lib/auth/firebase", () => ({ getIdToken: vi.fn(async () => null) }));
vi.mock("@/lib/api/auth-token", () => ({ resolveApiAuthToken: vi.fn(async () => null) }));
vi.mock("@/lib/api/auth-bridge-cookie", () => ({ setBffIdentityCookie: vi.fn() }));
vi.mock("@/lib/observability/sentry", async () => {
  const actual = await vi.importActual<typeof import("@/lib/observability/sentry")>(
    "@/lib/observability/sentry",
  );
  return { ...actual, captureError: observability.captureError };
});

import { apiFetch, apiRouteTemplate, type ApiError } from "./client";

function jsonResponse(status: number, body: unknown, requestId?: string): Response {
  const headers = new Headers({ "content-type": "application/json" });
  if (requestId) headers.set("X-Request-ID", requestId);
  return new Response(JSON.stringify(body), { status, headers });
}

describe("apiRouteTemplate", () => {
  it("collapses id-looking segments and drops the query string", () => {
    expect(apiRouteTemplate("/admin/students/stu_01J8ZK/notes?q=ada@example.com")).toBe(
      "/admin/students/{id}/notes",
    );
    expect(apiRouteTemplate("/parent/session-occurrences/42/absence")).toBe(
      "/parent/session-occurrences/{id}/absence",
    );
    expect(apiRouteTemplate("/parent/requests")).toBe("/parent/requests");
  });
});

describe("apiFetch Sentry capture (#707)", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.clearAllMocks();
  });

  it("captures a 5xx with request id, method, route and a per-route fingerprint", async () => {
    vi.mocked(fetch).mockResolvedValue(
      jsonResponse(500, { error: { code: "Internal", message: "boom" } }, "rid-500"),
    );

    const error = await apiFetch("/parent/session-occurrences/occ_1/absence", {
      method: "POST",
      body: "{}",
    }).catch((e: ApiError) => e);

    expect(error.status).toBe(500);
    expect(error.requestId).toBe("rid-500");
    expect(observability.captureError).toHaveBeenCalledTimes(1);
    const [reported, context] = observability.captureError.mock.calls[0];
    expect(reported).toBeInstanceOf(Error);
    expect(reported.name).toBe("ApiRequestFailed");
    expect(reported.message).toBe("POST /parent/session-occurrences/{id}/absence -> 500");
    expect(context.tags).toEqual({
      "api.method": "POST",
      "api.path": "/parent/session-occurrences/{id}/absence",
      "api.status": 500,
      "api.failure": "server",
      requestId: "rid-500",
    });
    expect(context.extra).toEqual({ code: "Internal", message: "boom" });
    expect(context.fingerprint).toEqual([
      "api-failure",
      "POST",
      "/parent/session-occurrences/{id}/absence",
      "500",
    ]);
  });

  it("never captures a 4xx", async () => {
    vi.mocked(fetch).mockResolvedValue(
      jsonResponse(409, { error: { code: "Conflict", message: "already noticed" } }, "rid-409"),
    );

    const error = await apiFetch("/parent/requests", { method: "POST" }).catch((e: ApiError) => e);

    expect(error.status).toBe(409);
    expect(error.code).toBe("Conflict");
    expect(observability.captureError).not.toHaveBeenCalled();
  });

  it("captures a network failure as api.failure=network and re-throws it", async () => {
    vi.mocked(fetch).mockRejectedValue(new TypeError("Failed to fetch"));

    await expect(apiFetch("/parent/home")).rejects.toBeInstanceOf(TypeError);

    expect(observability.captureError).toHaveBeenCalledTimes(1);
    const [reported, context] = observability.captureError.mock.calls[0];
    expect(reported.message).toBe("GET /parent/home -> network");
    expect(context.tags).toMatchObject({
      "api.method": "GET",
      "api.path": "/parent/home",
      "api.failure": "network",
    });
    expect(context.tags["api.status"]).toBeUndefined();
    expect(context.fingerprint).toEqual(["api-failure", "GET", "/parent/home", "network"]);
  });

  it("captures the 20 s abort as api.failure=timeout", async () => {
    const abort = new Error("aborted");
    abort.name = "AbortError";
    vi.mocked(fetch).mockRejectedValue(abort);

    await expect(apiFetch("/coach/today")).rejects.toBe(abort);

    const [, context] = observability.captureError.mock.calls[0];
    expect(context.tags["api.failure"]).toBe("timeout");
  });

  it("caps an HTML gateway body so it never becomes the event payload", async () => {
    const page = `<html>${"x".repeat(5000)}</html>`;
    vi.mocked(fetch).mockResolvedValue(
      new Response(page, { status: 502, headers: { "content-type": "text/html" } }),
    );

    await apiFetch("/parent/home").catch(() => undefined);

    const [, context] = observability.captureError.mock.calls[0];
    expect(String(context.extra.message).length).toBeLessThanOrEqual(200);
    expect(context.tags["api.status"]).toBe(502);
  });
});
