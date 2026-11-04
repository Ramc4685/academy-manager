import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("next/headers", () => ({ headers: vi.fn() }));

import { PUBLIC_FORWARDED_HEADERS, buildPublicAcademyRequestHeaders } from "./server-fetch";

describe("buildPublicAcademyRequestHeaders", () => {
  afterEach(() => {
    vi.unstubAllEnvs();
  });

  const inbound = () =>
    new Headers({
      host: "riverside-academy.courtmastr.com",
      "cf-connecting-ip": "203.0.113.9",
      "user-agent": "Mozilla/5.0",
      cookie: "__cm_identity=secret-token; theme=dark",
      authorization: "Bearer leaked",
      "x-cm-proxy-auth": "forged",
      "x-forwarded-proto": "http",
    });

  it("forwards the host for tenant resolution and the visitor IP for rate limiting", () => {
    vi.stubEnv("BFF_PROXY_SHARED_SECRET", "server-secret");
    const out = buildPublicAcademyRequestHeaders(inbound(), "https:");
    expect(out.get("x-forwarded-host")).toBe("riverside-academy.courtmastr.com");
    expect(out.get("cf-connecting-ip")).toBe("203.0.113.9");
    expect(out.get("x-cm-proxy-auth")).toBe("server-secret");
    expect(out.get("x-forwarded-proto")).toBe("https");
    expect(out.get("x-request-id")).toBeTruthy();
  });

  it("never forwards credentials or a client-supplied proxy secret", () => {
    const out = buildPublicAcademyRequestHeaders(inbound(), "https:");
    expect(out.get("cookie")).toBeNull();
    expect(out.get("authorization")).toBeNull();
    expect(out.get("x-courtmastr-auth")).toBeNull();
    expect(out.get("x-cm-proxy-auth")).toBeNull();
  });

  it("forwards only the allow-listed inbound headers", () => {
    expect([...PUBLIC_FORWARDED_HEADERS]).toEqual([
      "host",
      "cf-connecting-ip",
      "user-agent",
      "accept-language",
      "x-request-id",
    ]);
  });
});
