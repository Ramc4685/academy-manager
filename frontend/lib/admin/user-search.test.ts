import { describe, expect, it } from "vitest";

import type { AdminUserView } from "@/lib/api/admin";

import { filterUsersBySearch, matchesUserSearch } from "./user-search";

function user(overrides: Partial<AdminUserView>): AdminUserView {
  return {
    user_id: "usr_1",
    email: "a@example.com",
    display_name: "A",
    role: "parent",
    status: "active",
    ...overrides,
  };
}

const USERS: AdminUserView[] = [
  user({ user_id: "usr_1", display_name: "Priya Raman", email: "priya@example.com" }),
  user({ user_id: "usr_2", display_name: "Manoj Kumar", email: "manoj.k@example.com" }),
  user({
    user_id: "usr_3",
    display_name: "Sharanda Ellis",
    email: "sharanda@other.test",
    phone: "+15551234567",
  }),
];

describe("matchesUserSearch (#839)", () => {
  it("matches on a name substring, ignoring case", () => {
    expect(matchesUserSearch(USERS[0], "pri")).toBe(true);
    expect(matchesUserSearch(USERS[0], "RAMAN")).toBe(true);
  });

  it("matches on an email substring", () => {
    expect(matchesUserSearch(USERS[1], "manoj.k@")).toBe(true);
    expect(matchesUserSearch(USERS[2], "other.test")).toBe(true);
  });

  it("matches on a phone substring, so a number on a note finds the person", () => {
    expect(matchesUserSearch(USERS[2], "5551234")).toBe(true);
    expect(matchesUserSearch(USERS[0], "5551234")).toBe(false);
  });

  it("does not match an unrelated term", () => {
    expect(matchesUserSearch(USERS[0], "manoj")).toBe(false);
  });

  it("treats a blank query as a match, so whitespace never empties the directory", () => {
    expect(matchesUserSearch(USERS[0], "   ")).toBe(true);
    expect(matchesUserSearch(USERS[0], "")).toBe(true);
  });
});

describe("filterUsersBySearch (#839)", () => {
  it("returns every user for a blank query", () => {
    expect(filterUsersBySearch(USERS, "")).toHaveLength(3);
    expect(filterUsersBySearch(USERS, "  ")).toHaveLength(3);
  });

  it("narrows to the matching rows", () => {
    expect(filterUsersBySearch(USERS, "sharanda").map((u) => u.user_id)).toEqual(["usr_3"]);
    expect(filterUsersBySearch(USERS, "example.com").map((u) => u.user_id)).toEqual([
      "usr_1",
      "usr_2",
    ]);
  });

  it("trims the query before matching", () => {
    expect(filterUsersBySearch(USERS, "  Manoj  ").map((u) => u.user_id)).toEqual(["usr_2"]);
  });

  it("returns nothing when no row matches", () => {
    expect(filterUsersBySearch(USERS, "zzz")).toEqual([]);
  });
});
