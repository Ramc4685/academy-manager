import { describe, expect, it } from "vitest";

import { homeForRoles, postLoginDestination, type UserRole } from "@/lib/api/me";
import { decidePersonaRedirect } from "@/lib/auth/persona-route-guard";

describe("homeForRoles", () => {
  it("lands a parent on Home, not Payments", () => {
    expect(homeForRoles(["parent"])).toBe("/parent/dashboard");
    expect(homeForRoles(["parent", "student"])).toBe("/parent/dashboard");
  });

  it("agrees with the edge guard's landing table", () => {
    const cases: [UserRole, string][] = [
      ["admin", "admin"],
      ["coach", "coach"],
      ["parent", "parent"],
    ];
    for (const [role, hint] of cases) {
      const target = role === "parent" ? "/admin" : "/parent/dashboard";
      const denied = decidePersonaRedirect({ pathname: target, personaHint: hint, hasIdentity: true });
      expect(denied?.split("?")[0]).toBe(homeForRoles([role]));
    }
  });

  it("lets a pending pay link from an email win over Home", () => {
    // The function app/post-login calls to pick where to go.
    expect(postLoginDestination("/parent/payments?pay=inv_1", ["parent"])).toBe(
      "/parent/payments?pay=inv_1",
    );
    expect(postLoginDestination(null, ["parent"])).toBe("/parent/dashboard");
    expect(postLoginDestination("https://evil.example/x", ["parent"])).toBe("/parent/dashboard");
  });
});
