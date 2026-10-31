import { describe, expect, it } from "vitest";

import type { FamilyIndexRow, FamilyViewPreset } from "@/lib/api/admin-families";
import {
  familiesCountLabel,
  EMPTY_FAMILY_INDEX_STATE,
  FALLBACK_PRESETS,
  ariaSort,
  classOptions,
  clearFilterChips,
  familyDisplayName,
  familyHref,
  familyResultRows,
  hasFilterChips,
  isPresetActive,
  nextSort,
  parseFamilyIndexState,
  toFamilyIndexParams,
  togglePreset,
  writeFamilyIndexState,
  type FamilyIndexState,
} from "./family-index-view";

/**
 * People CRM Families view (engineering-spec §3.2): the view model over
 * `GET /admin/families`. Fixture names are obviously fake.
 */

function family(overrides: Partial<FamilyIndexRow> = {}): FamilyIndexRow {
  return {
    family_id: "fam-1",
    parent_name: "Test Parent One",
    email: "parent.one@example.test",
    phone: null,
    has_account: true,
    stage: "active",
    children: [],
    card_on_file: true,
    registration: "registered",
    money: null,
    matched_parent: false,
    ...overrides,
  };
}

const OVERDUE: FamilyViewPreset = {
  id: "overdue",
  label: "Overdue",
  params: { overdue: "true" },
  money: true,
};
const ACTIVE = FALLBACK_PRESETS.find((p) => p.id === "active")!;
const LEAVING = FALLBACK_PRESETS.find((p) => p.id === "leaving")!;
const NO_CARD = FALLBACK_PRESETS.find((p) => p.id === "no_card")!;

const state = (overrides: Partial<FamilyIndexState> = {}): FamilyIndexState => ({
  ...EMPTY_FAMILY_INDEX_STATE,
  ...overrides,
});

describe("URL state round trip", () => {
  it("parses every owned key", () => {
    const parsed = parseFamilyIndexState(
      new URLSearchParams(
        "q=ada&scope=leaving&stage=paused&stage=on_hold&class_id=s-1&card_on_file=false&overdue=true&sort=balance&order=asc",
      ),
    );
    expect(parsed).toEqual({
      q: "ada",
      scope: "leaving",
      stage: ["paused", "on_hold"],
      classId: "s-1",
      cardOnFile: false,
      overdue: true,
      sort: "balance",
      order: "asc",
    });
  });

  it("drops values the API would reject with a 422", () => {
    const parsed = parseFamilyIndexState(
      new URLSearchParams("scope=everyone&stage=bogus,active&sort=age&order=up&overdue=yes"),
    );
    expect(parsed.scope).toBeNull();
    expect(parsed.stage).toEqual(["active"]);
    expect(parsed.sort).toBeNull();
    expect(parsed.order).toBeNull();
    expect(parsed.overdue).toBeNull();
  });

  it("keeps keys it does not own, such as view=families from the /admin/parents redirect", () => {
    const next = writeFamilyIndexState(
      new URLSearchParams("view=families&scope=left"),
      state({ q: "  ada ", scope: "active", cardOnFile: false }),
    );
    expect(next.get("view")).toBe("families");
    expect(next.get("q")).toBe("ada");
    expect(next.get("scope")).toBe("active");
    expect(next.get("card_on_file")).toBe("false");
    expect(next.has("overdue")).toBe(false);
  });

  it("an empty state writes nothing, so an untouched page keeps its URL", () => {
    const base = new URLSearchParams("view=families");
    expect(writeFamilyIndexState(base, EMPTY_FAMILY_INDEX_STATE).toString()).toBe(
      base.toString(),
    );
  });

  it("maps state onto API params without inventing filters", () => {
    expect(toFamilyIndexParams(state({ q: " ada " }), 2, 50)).toEqual({
      search: "ada",
      scope: undefined,
      stage: undefined,
      class_id: undefined,
      card_on_file: undefined,
      overdue: undefined,
      sort: undefined,
      order: undefined,
      page: 2,
      page_size: 50,
    });
  });
});

describe("preset chips are click-to-apply toggles", () => {
  it("pressing a preset applies its params; pressing it again clears only those", () => {
    const on = togglePreset(state({ q: "ada", classId: "s-1" }), NO_CARD);
    expect(on.cardOnFile).toBe(false);
    expect(isPresetActive(NO_CARD, on)).toBe(true);
    const off = togglePreset(on, NO_CARD);
    expect(off.cardOnFile).toBeNull();
    // search and class survive both clicks
    expect(off.q).toBe("ada");
    expect(off.classId).toBe("s-1");
  });

  it("scope presets replace each other; other chips combine", () => {
    let s = togglePreset(state(), ACTIVE);
    s = togglePreset(s, NO_CARD);
    s = togglePreset(s, LEAVING);
    expect(s.scope).toBe("leaving");
    expect(isPresetActive(ACTIVE, s)).toBe(false);
    expect(isPresetActive(LEAVING, s)).toBe(true);
    expect(isPresetActive(NO_CARD, s)).toBe(true);
  });

  it("a money preset maps onto the overdue filter", () => {
    expect(togglePreset(state(), OVERDUE).overdue).toBe(true);
  });

  it("an unknown preset key is ignored, never guessed", () => {
    const odd: FamilyViewPreset = { id: "x", label: "X", params: { tag: "vip" }, money: false };
    expect(togglePreset(state(), odd)).toEqual(state());
    expect(isPresetActive(odd, state())).toBe(false);
  });

  it("All clears the chips but keeps search, class and sort", () => {
    const s = clearFilterChips(
      state({ q: "ada", classId: "s-1", sort: "stage", scope: "left", overdue: true }),
    );
    expect(hasFilterChips(s)).toBe(false);
    expect(s).toMatchObject({ q: "ada", classId: "s-1", sort: "stage" });
  });

  it("the fallback presets never carry a money filter", () => {
    expect(FALLBACK_PRESETS.every((p) => !p.money && !("overdue" in p.params))).toBe(true);
  });
});

describe("column sorting", () => {
  it("name is the default, ascending", () => {
    expect(ariaSort(state(), "name", true)).toBe("ascending");
    expect(ariaSort(state(), "stage", true)).toBe("none");
  });

  it("clicking the sorted column flips it; a new column starts on its default", () => {
    const flipped = nextSort(state(), "name", true);
    expect(ariaSort(flipped, "name", true)).toBe("descending");
    const balance = nextSort(flipped, "balance", true);
    expect(balance).toMatchObject({ sort: "balance", order: null });
    // the backend runs balance high-to-low by default
    expect(ariaSort(balance, "balance", true)).toBe("descending");
    expect(ariaSort(nextSort(balance, "balance", true), "balance", true)).toBe("ascending");
  });

  it("balance without money visible falls back to ascending, like the backend", () => {
    expect(ariaSort(state({ sort: "balance" }), "balance", false)).toBe("ascending");
  });
});

describe("result rows", () => {
  const kids = [
    { student_id: "stu-a", name: "Kid A", lifecycle: "active" as const, lifecycle_as_of: null, classes: [], matched: true },
    { student_id: "stu-b", name: "Kid B", lifecycle: "paused" as const, lifecycle_as_of: null, classes: [], matched: false },
  ];

  it("a child match makes the child the result row", () => {
    const rows = familyResultRows([family({ children: kids })], true);
    expect(rows).toHaveLength(1);
    expect(rows[0]).toMatchObject({ kind: "child", child: { student_id: "stu-a" } });
  });

  it("a parent match keeps the family row", () => {
    const rows = familyResultRows([family({ children: kids, matched_parent: true })], true);
    expect(rows.map((r) => r.kind)).toEqual(["family"]);
  });

  it("without a search the family row is shown even if a stale matched flag arrives", () => {
    expect(familyResultRows([family({ children: kids })], false)[0].kind).toBe("family");
  });
});

describe("links and labels", () => {
  it("a family with no account never links to the Billing page", () => {
    expect(familyHref(family({ has_account: false }))).toBeNull();
    expect(familyHref(family({ family_id: "a b" }))).toBe("/admin/families/a%20b");
  });

  it("falls back from name to email to a neutral label", () => {
    expect(familyDisplayName(family({ parent_name: " " }))).toBe("parent.one@example.test");
    expect(familyDisplayName(family({ parent_name: null, email: null }))).toBe("Unnamed family");
  });
});

describe("class filter options", () => {
  it("merges sessions and loaded classes, de-duplicated and sorted", () => {
    const fam = family({
      children: [
        {
          student_id: "stu-a",
          name: "Kid A",
          lifecycle: "active",
          lifecycle_as_of: null,
          matched: false,
          classes: [
            { session_id: "s-2", title: "Beta class" },
            { session_id: "s-9", title: "Zeta class" },
          ],
        },
      ],
    });
    expect(
      classOptions(
        [
          { session_id: "s-2", title: "Beta class" },
          { session_id: "s-1", title: "Alpha class" },
        ],
        [fam],
        null,
      ),
    ).toEqual([
      { value: "s-1", label: "Alpha class" },
      { value: "s-2", label: "Beta class" },
      { value: "s-9", label: "Zeta class" },
    ]);
  });

  it("keeps an unknown class id from the URL selectable", () => {
    expect(classOptions([], [], "s-404")).toEqual([{ value: "s-404", label: "Selected class" }]);
  });
});

describe("results heading copy", () => {
  it("agrees in number with the count", () => {
    expect(familiesCountLabel(1, false)).toBe("1 family");
    expect(familiesCountLabel(0, false)).toBe("0 families");
    expect(familiesCountLabel(3, false)).toBe("3 families");
    expect(familiesCountLabel(1, true)).toBe("1 family matches this search");
    expect(familiesCountLabel(0, true)).toBe("0 families match this search");
    expect(familiesCountLabel(2, true)).toBe("2 families match this search");
  });
});
