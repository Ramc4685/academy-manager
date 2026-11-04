import { describe, expect, it } from "vitest";

import {
  childProfileFromExistingChild,
  initialChildSelection,
  NEW_CHILD_SELECTION,
  RE_ENROLL_CHILD_PARAM,
  reEnrollChildId,
  reEnrollHref,
} from "./re-enroll";

describe("reEnrollHref (#827)", () => {
  it("sends the family into onboarding with the departed child pre-bound", () => {
    expect(reEnrollHref("st-1")).toBe("/parent/onboarding?child=st-1");
  });

  it("escapes an id that would otherwise break out of the query string", () => {
    expect(reEnrollHref("st/1&role=admin")).toBe(
      "/parent/onboarding?child=st%2F1%26role%3Dadmin",
    );
  });

  it("names the parameter the onboarding stepper reads back", () => {
    expect(RE_ENROLL_CHILD_PARAM).toBe("child");
  });
});

describe("reEnrollChildId (#827)", () => {
  it("reads the pre-bound child back out of the onboarding url", () => {
    const href = reEnrollHref("st-1");
    expect(reEnrollChildId(href.slice(href.indexOf("?")))).toBe("st-1");
  });

  it("round-trips an id that needed escaping", () => {
    const href = reEnrollHref("st/1&role=admin");
    expect(reEnrollChildId(href.slice(href.indexOf("?")))).toBe("st/1&role=admin");
  });

  it("is null for a plain onboarding visit, so first-time signup is untouched", () => {
    expect(reEnrollChildId("")).toBeNull();
    expect(reEnrollChildId("?step=child")).toBeNull();
    expect(reEnrollChildId("?child=")).toBeNull();
  });
});

const AVA = {
  student_id: "st-1",
  full_name: "Ava Kim",
  date_of_birth: "2015-04-02",
  emergency_contact_name: "Jo Kim",
  emergency_contact_phone: "+1 555 0100",
  medical_notes: "Peanut allergy",
  no_medical_conditions: false,
};

const BLANK_DRAFT = {
  first_name: "",
  last_name: "",
  date_of_birth: "",
  skill_level: "" as const,
  emergency_contact_name: "",
  emergency_contact_phone: "",
  medical_notes: "",
};

describe("initialChildSelection (#827)", () => {
  it("pre-selects the child the departed row pinned to the url", () => {
    expect(initialChildSelection([AVA], "st-1")).toBe("st-1");
  });

  it("falls back to the new-child form when the pinned id is not this parent's", () => {
    expect(initialChildSelection([AVA], "st-someone-else")).toBe(NEW_CHILD_SELECTION);
  });

  it("is the new-child form for a first-time family, so signup is untouched", () => {
    expect(initialChildSelection([], "st-1")).toBe(NEW_CHILD_SELECTION);
    expect(initialChildSelection([AVA], null)).toBe(NEW_CHILD_SELECTION);
  });
});

describe("childProfileFromExistingChild (#827)", () => {
  it("copies the record forward so name and date of birth match the student exactly", () => {
    const profile = childProfileFromExistingChild(AVA, BLANK_DRAFT);
    expect(profile.first_name).toBe("Ava");
    expect(profile.last_name).toBe("Kim");
    expect(profile.date_of_birth).toBe("2015-04-02");
    expect(profile.emergency_contact_name).toBe("Jo Kim");
    expect(profile.emergency_contact_phone).toBe("+1 555 0100");
    expect(profile.medical_notes).toBe("Peanut allergy");
  });

  it("keeps everything after the first word as the last name", () => {
    const profile = childProfileFromExistingChild(
      { ...AVA, full_name: "  Ava  Marie Kim " },
      BLANK_DRAFT,
    );
    expect(profile.first_name).toBe("Ava");
    expect(profile.last_name).toBe("Marie Kim");
  });

  it("leaves a one-word name's last name empty rather than duplicating it", () => {
    const profile = childProfileFromExistingChild({ ...AVA, full_name: "Ava" }, BLANK_DRAFT);
    expect(profile.first_name).toBe("Ava");
    expect(profile.last_name).toBe("");
  });

  it("carries a declared 'no conditions' across as the sentinel the wizard uses", () => {
    const profile = childProfileFromExistingChild(
      { ...AVA, medical_notes: null, no_medical_conditions: true },
      BLANK_DRAFT,
    );
    expect(profile.medical_notes).toBe("__none_declared__");
  });

  it("keeps the skill level the family already picked — the record carries none", () => {
    const profile = childProfileFromExistingChild(AVA, {
      ...BLANK_DRAFT,
      skill_level: "intermediate" as const,
    });
    expect(profile.skill_level).toBe("intermediate");
  });

  it("blanks missing optional fields instead of leaving the previous child's answers", () => {
    const profile = childProfileFromExistingChild(
      {
        ...AVA,
        date_of_birth: null,
        emergency_contact_name: null,
        emergency_contact_phone: null,
        medical_notes: null,
      },
      {
        ...BLANK_DRAFT,
        date_of_birth: "2010-01-01",
        emergency_contact_name: "Someone Else",
        emergency_contact_phone: "+1 555 9999",
        medical_notes: "Asthma",
      },
    );
    expect(profile.date_of_birth).toBe("");
    expect(profile.emergency_contact_name).toBe("");
    expect(profile.emergency_contact_phone).toBe("");
    expect(profile.medical_notes).toBe("");
  });
});
