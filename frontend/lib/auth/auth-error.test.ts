import { describe, expect, it } from "vitest";
import { toAuthErrorMessage } from "./auth-error";

const FALLBACK = "Sign-in failed. Please try again.";

describe("toAuthErrorMessage", () => {
  it("maps a known Firebase code to friendly copy", () => {
    const err = Object.assign(new Error("Firebase: Error (auth/wrong-password)."), {
      code: "auth/wrong-password",
    });
    expect(toAuthErrorMessage(err, FALLBACK)).toBe(
      "Email or password is incorrect. Check your details and try again."
    );
  });

  it("merges user-not-found and wrong-password so the wrong field is not revealed", () => {
    const notFound = Object.assign(new Error("x"), { code: "auth/user-not-found" });
    const wrongPw = Object.assign(new Error("x"), { code: "auth/wrong-password" });
    expect(toAuthErrorMessage(notFound, FALLBACK)).toBe(toAuthErrorMessage(wrongPw, FALLBACK));
  });

  it("never returns raw provider text for an unknown auth code", () => {
    const err = Object.assign(new Error("Firebase: Error (auth/something-new)."), {
      code: "auth/something-new",
    });
    const out = toAuthErrorMessage(err, FALLBACK);
    expect(out).toBe(FALLBACK);
    expect(out).not.toMatch(/firebase/i);
    expect(out).not.toMatch(/\(auth\//);
  });

  it("falls back when the error has no code and the message is raw Firebase text", () => {
    const err = new Error("Firebase: Error (auth/internal-error).");
    expect(toAuthErrorMessage(err, FALLBACK)).toBe(FALLBACK);
  });

  it("passes through our own curated (non-Firebase) error message", () => {
    const err = new Error(
      "Google sign-in could not complete on this browser. Please try again, or sign in with your email and password."
    );
    expect(toAuthErrorMessage(err, FALLBACK)).toBe(err.message);
  });

  it("uses the fallback for non-error values", () => {
    expect(toAuthErrorMessage("boom", FALLBACK)).toBe(FALLBACK);
    expect(toAuthErrorMessage(null, FALLBACK)).toBe(FALLBACK);
  });
});
