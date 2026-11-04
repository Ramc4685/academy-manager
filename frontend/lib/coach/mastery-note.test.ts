import { describe, expect, it } from "vitest";

import { NOTE_MAX, composeMasteryNote, pickedCriteria, toggleCriterion } from "./mastery-note";

const GRIP = ["Thumb is flat on back of handle", "Back of hand leads on contact", "Elbow in front of body"];

describe("composeMasteryNote", () => {
  it("writes one templated sentence, lower-casing each cue", () => {
    expect(composeMasteryNote([GRIP[0]])).toBe("Nailed it today: thumb is flat on back of handle.");
    expect(composeMasteryNote([GRIP[0], GRIP[2]])).toBe(
      "Nailed it today: thumb is flat on back of handle and elbow in front of body.",
    );
    expect(composeMasteryNote(GRIP)).toBe(
      "Nailed it today: thumb is flat on back of handle, back of hand leads on contact and elbow in front of body.",
    );
  });

  it("keeps a leading capital that is not a sentence start and drops a trailing full stop", () => {
    expect(composeMasteryNote(["V shape between thumb and forefinger."])).toBe(
      "Nailed it today: V shape between thumb and forefinger.",
    );
  });

  it("is empty with nothing picked", () => {
    expect(composeMasteryNote([])).toBe("");
    expect(composeMasteryNote(["  "])).toBe("");
  });

  it("leaves out criteria that would push the note past the 140-character cap", () => {
    const long = ["a".repeat(50), "b".repeat(50), "c".repeat(50)];
    const note = composeMasteryNote(long);
    expect(note.length).toBeLessThanOrEqual(NOTE_MAX);
    expect(note).toBe(`Nailed it today: ${long[0]} and ${long[1]}.`);
  });
});

describe("toggleCriterion", () => {
  it("adds, keeps curriculum order, and removes on a second tap", () => {
    const one = toggleCriterion("", GRIP, GRIP[2]);
    expect(one).toBe("Nailed it today: elbow in front of body.");
    const two = toggleCriterion(one, GRIP, GRIP[0]);
    expect(two).toBe("Nailed it today: thumb is flat on back of handle and elbow in front of body.");
    expect(pickedCriteria(two, GRIP)).toEqual([GRIP[0], GRIP[2]]);
    expect(toggleCriterion(two, GRIP, GRIP[2])).toBe("Nailed it today: thumb is flat on back of handle.");
    expect(toggleCriterion("Nailed it today: thumb is flat on back of handle.", GRIP, GRIP[0])).toBe("");
  });

  it("replaces a hand-typed draft with the sentence, and reads chips off the coach's own edits", () => {
    expect(toggleCriterion("Quick feet", GRIP, GRIP[1])).toBe(
      "Nailed it today: back of hand leads on contact.",
    );
    expect(pickedCriteria("Great: elbow in front of body all class", GRIP)).toEqual([GRIP[2]]);
    expect(pickedCriteria("Quick feet", GRIP)).toEqual([]);
  });
});
