import { describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api/client", () => ({ apiFetch: vi.fn(async () => ({ status: "scheduled" })) }));

import { apiFetch } from "@/lib/api/client";
import { requestAccountDeletion } from "@/lib/api/me";

import { deletionErrorMessage } from "./delete-account-section";

function apiError(code: string, message: string): Error {
  return Object.assign(new Error(message), { code });
}

describe("account deletion (mobile M5, D2)", () => {
  it("posts the typed confirmation the backend requires", async () => {
    await requestAccountDeletion();
    expect(apiFetch).toHaveBeenCalledWith("/me/account-deletion", {
      method: "POST",
      body: JSON.stringify({ confirm: "DELETE" }),
    });
  });

  it("tells a stale session to sign in again", () => {
    expect(deletionErrorMessage(apiError("Identity.RecentSignInRequired", "x"))).toMatch(
      /sign back in/,
    );
  });

  it("shows the backend's reason for the last owner and an assigned coach", () => {
    for (const code of ["Identity.CannotRemoveLastOwner", "Identity.CoachHasFutureSessions"]) {
      expect(deletionErrorMessage(apiError(code, "ask the academy to reassign"))).toBe(
        "ask the academy to reassign",
      );
    }
  });

  it("maps a wrong password to the sign-in message", () => {
    const wrong = Object.assign(new Error("Firebase: x"), { code: "auth/wrong-password" });
    expect(deletionErrorMessage(wrong)).not.toContain("Firebase");
  });
});
