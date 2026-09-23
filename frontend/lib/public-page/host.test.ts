import { describe, expect, it } from "vitest";

import { isPlatformProductHost, normalizeHost, platformProductHosts, siteOrigin } from "./host";

describe("normalizeHost", () => {
  it("lower-cases and drops the port and trailing dot", () => {
    expect(normalizeHost("Academy.CourtMastr.com:443")).toBe("academy.courtmastr.com");
    expect(normalizeHost("riverside-academy.courtmastr.com.")).toBe(
      "riverside-academy.courtmastr.com",
    );
    expect(normalizeHost("[::1]:3001")).toBe("[::1]");
    expect(normalizeHost(null)).toBe("");
  });
});

describe("isPlatformProductHost", () => {
  it("keeps the product's own hosts on the landing page by default", () => {
    expect(isPlatformProductHost("academy.courtmastr.com", {})).toBe(true);
    expect(isPlatformProductHost("www.courtmastr.com", {})).toBe(true);
  });

  it("treats a tenant host as a tenant host", () => {
    expect(isPlatformProductHost("riverside-academy.courtmastr.com", {})).toBe(false);
    expect(isPlatformProductHost("classes.riverside.example", {})).toBe(false);
    expect(isPlatformProductHost("localhost:3001", {})).toBe(false);
    expect(isPlatformProductHost("", {})).toBe(false);
  });

  it("lets the environment replace the list", () => {
    const env = { PUBLIC_PAGE_PLATFORM_HOSTS: "product.example, Localhost:3001" };
    expect(platformProductHosts(env)).toEqual(["product.example", "localhost"]);
    expect(isPlatformProductHost("localhost:3001", env)).toBe(true);
    expect(isPlatformProductHost("academy.courtmastr.com", env)).toBe(false);
    expect(platformProductHosts({ PUBLIC_PAGE_PLATFORM_HOSTS: "" })).toEqual([]);
  });
});

describe("siteOrigin", () => {
  it("uses https in production and http in development", () => {
    expect(siteOrigin("riverside-academy.courtmastr.com", "production")).toBe(
      "https://riverside-academy.courtmastr.com",
    );
    expect(siteOrigin("localhost:3001", "development")).toBe("http://localhost:3001");
  });
});
