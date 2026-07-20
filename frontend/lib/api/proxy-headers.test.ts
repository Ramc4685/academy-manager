import { afterEach, describe, expect, it, vi } from "vitest";

import { buildProxyHeaders } from "./proxy-headers";

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
