import { describe, expect, it, vi } from "vitest";

vi.mock("next/headers", () => ({ headers: vi.fn() }));

import {
  classifySharedCertificateResponse,
  formatIssuedOn,
} from "./shared-certificate";

const body = {
  academy: {
    name: "Riverside",
    logo_url: null,
    brand_color: null,
    brand_fill: "#1e3a8a",
    brand_on_color: "#fff",
  },
  recipient_name: "Maya",
  level_name: "Grip and Control",
  level_number: 1,
  level_color: "#22c55e",
  cert_number: "RIV-C-0001",
  issued_on: "2026-10-30",
};

describe("classifySharedCertificateResponse", () => {
  it("returns the certificate on a 200 with the public shape", () => {
    expect(classifySharedCertificateResponse(200, body)).toEqual({
      kind: "found",
      certificate: body,
    });
  });

  it("treats the backend 404 (revoked, unshared, unknown, other host) as not found", () => {
    expect(classifySharedCertificateResponse(404, null)).toEqual({
      kind: "not_found",
    });
  });

  it("is unavailable on errors or a malformed body", () => {
    expect(classifySharedCertificateResponse(500, null).kind).toBe(
      "unavailable",
    );
    expect(
      classifySharedCertificateResponse(200, { recipient_name: "Maya" }).kind,
    ).toBe("unavailable");
  });
});

describe("formatIssuedOn", () => {
  it("formats the academy-local date without shifting it by the server zone", () => {
    expect(formatIssuedOn("2026-10-30")).toBe("October 30, 2026");
  });
});
