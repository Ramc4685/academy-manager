import { describe, expect, it } from "vitest";

import {
  clearRegisterDraft,
  loadRegisterDraft,
  PASSWORD_RULE,
  passwordRuleError,
  saveRegisterDraft,
} from "@/lib/auth/register-form";

function memoryStorage() {
  const data = new Map<string, string>();
  return {
    data,
    getItem: (k: string) => data.get(k) ?? null,
    setItem: (k: string, v: string) => void data.set(k, v),
    removeItem: (k: string) => void data.delete(k),
  };
}

describe("register form (S23)", () => {
  it("states the rule and explains a short password inline", () => {
    expect(PASSWORD_RULE).toBe("At least 8 characters.");
    expect(passwordRuleError("abc")).toBe("Your password needs at least 8 characters (it has 3).");
    expect(passwordRuleError("correct-horse-1")).toBeNull();
  });

  it("keeps the email across a reload and never stores the password", () => {
    const storage = memoryStorage();
    saveRegisterDraft(storage, "rosa.alvarez@example.com");
    expect(loadRegisterDraft(storage)).toBe("rosa.alvarez@example.com");
    expect([...storage.data.values()].join("")).not.toMatch(/password|correct-horse/);
    expect(Object.keys(JSON.parse([...storage.data.values()][0]))).toEqual(["email"]);
    clearRegisterDraft(storage);
    expect(loadRegisterDraft(storage)).toBe("");
  });

  it("survives blocked storage", () => {
    const blocked = {
      getItem: () => {
        throw new Error("blocked");
      },
      setItem: () => {
        throw new Error("blocked");
      },
      removeItem: () => {},
    };
    expect(() => saveRegisterDraft(blocked, "a@example.com")).not.toThrow();
    expect(loadRegisterDraft(blocked)).toBe("");
  });
});
