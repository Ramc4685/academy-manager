import { afterEach, describe, expect, it, vi } from "vitest";

import { buildProxyHeaders, buildProxyResponseHeaders } from "./proxy-headers";

describe("buildProxyHeaders proxy auth", () => {
  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it("strips an inbound x-cm-proxy-auth header so clients cannot inject it", () => {
    vi.stubEnv("BFF_PROXY_SHARED_SECRET", "");
    const inbound = new Headers({ "x-cm-proxy-auth": "client-forged" });

    const headers = buildProxyHeaders(inbound, "https:");

    expect(headers.get("x-cm-proxy-auth")).toBeNull();
  });

  it("sets x-cm-proxy-auth from the server-held secret when configured", () => {
    vi.stubEnv("BFF_PROXY_SHARED_SECRET", "server-secret");
    const inbound = new Headers({ "x-cm-proxy-auth": "client-forged" });

    const headers = buildProxyHeaders(inbound, "https:");

    expect(headers.get("x-cm-proxy-auth")).toBe("server-secret");
  });

  it("forwards CF-Connecting-IP unchanged", () => {
    vi.stubEnv("BFF_PROXY_SHARED_SECRET", "server-secret");
    const inbound = new Headers({ "cf-connecting-ip": "203.0.113.10" });

    const headers = buildProxyHeaders(inbound, "https:");

    expect(headers.get("cf-connecting-ip")).toBe("203.0.113.10");
  });
});

describe("request id propagation", () => {
  it("mints a request id when none is inbound and forwards it on the response", () => {
    const outbound = buildProxyHeaders(new Headers(), "https:");
    const requestId = outbound.get("x-request-id");

    expect(requestId).toMatch(/^[A-Za-z0-9._-]{1,128}$/);

    const response = buildProxyResponseHeaders(new Headers(), requestId);
    expect(response.get("x-request-id")).toBe(requestId);
  });

  it("prefers the upstream echo over the minted id and drops an invalid echo", () => {
    expect(
      buildProxyResponseHeaders(new Headers({ "x-request-id": "from-backend" }), "minted").get(
        "x-request-id"
      )
    ).toBe("from-backend");
    expect(
      buildProxyResponseHeaders(new Headers({ "x-request-id": "bad value" }), "minted").get(
        "x-request-id"
      )
    ).toBe("minted");
  });

  it("mints distinct ids per request", () => {
    const a = buildProxyHeaders(new Headers(), "https:").get("x-request-id");
    const b = buildProxyHeaders(new Headers(), "https:").get("x-request-id");
    expect(a).not.toBe(b);
  });
});
