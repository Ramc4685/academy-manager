import { describe, expect, it } from "vitest";

import { loginErrorMessage, loginPathForError, shouldSelfRegister } from "./login-error";

function apiError(
  status: number,
  code?: string,
  details?: Record<string, unknown>,
): Error {
  return Object.assign(new Error("Request failed"), { status, code, details });
}

describe("loginPathForError", () => {
  it("carries the backend reason code into the redirect", () => {
    const err = apiError(401, "Auth.NotAuthenticated", {
      reason: "Identity.MembershipNotFound",
    });
    expect(loginPathForError(err)).toBe(
      "/login?error=Identity.MembershipNotFound",
    );
  });

  it("falls back to the top-level code when no reason detail is present", () => {
    expect(loginPathForError(apiError(403, "Platform.TenantForbidden"))).toBe(
      "/login?error=Platform.TenantForbidden",
    );
  });

  it("returns a plain /login for a network failure with no status", () => {
    expect(loginPathForError(new Error("Failed to fetch"))).toBe("/login");
  });

  it("returns a plain /login for a 401 that carries no code at all", () => {
    expect(loginPathForError(apiError(401))).toBe("/login");
  });
});

describe("loginErrorMessage", () => {
  it("maps a known code to parent-friendly copy", () => {
    expect(loginErrorMessage("Identity.MembershipNotFound")).toBe(
      "Your account isn't set up for this academy yet. Contact your academy to get access.",
    );
  });

  it("falls back to generic copy for an unrecognised code", () => {
    expect(loginErrorMessage("Identity.SomethingNew")).toBe(
      "We couldn't finish signing you in. Please try again, or contact your academy if this keeps happening.",
    );
  });

  it("renders nothing when there is no error param", () => {
    expect(loginErrorMessage(null)).toBeNull();
  });
});

describe("shouldSelfRegister", () => {
  const notFound = apiError(401, "Auth.NotAuthenticated", { reason: "Identity.UserNotFound" });

  it("registers a verified parent whose sign-up began in another browser", () => {
    expect(shouldSelfRegister(notFound, true)).toBe(true);
  });

  it("never registers an unverified email", () => {
    expect(shouldSelfRegister(notFound, false)).toBe(false);
  });

  it("leaves other failures (e.g. no membership here) to the login page", () => {
    const noMembership = apiError(401, "Auth.NotAuthenticated", {
      reason: "Identity.MembershipNotFound",
    });
    expect(shouldSelfRegister(noMembership, true)).toBe(false);
    expect(shouldSelfRegister(new Error("Failed to fetch"), true)).toBe(false);
  });
});
