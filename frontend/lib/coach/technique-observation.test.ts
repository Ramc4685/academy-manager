import { describe, expect, it } from "vitest";

import {
  OBSERVATION_MAX,
  noteFromDraft,
  techniqueDraftErrorMessage,
} from "./technique-observation";

const DRAFT = {
  criterion_id: "c-1",
  skill_id: "sk-grip",
  skill_name: "Forehand grip",
  parent_sentence: " Maya is holding the racket with a flat thumb now. ",
  coach_summary: "Flat thumb on forehand grip.",
};

describe("noteFromDraft", () => {
  it("prefills the suggested skill, the parent sentence and the coach summary", () => {
    expect(noteFromDraft(DRAFT)).toEqual({
      skillId: "sk-grip",
      body: "Maya is holding the racket with a flat thumb now.\n\nCoach summary: Flat thumb on forehand grip.",
      hint: "AI suggested: Forehand grip, edit before saving",
    });
  });
});

describe("techniqueDraftErrorMessage", () => {
  it("maps each refusal to its sentence", () => {
    expect(techniqueDraftErrorMessage(503)).toBe("AI notes are not enabled for this academy yet");
    expect(techniqueDraftErrorMessage(403)).toBe("AI notes are part of the Growth plan");
    expect(techniqueDraftErrorMessage(429)).toBe("This academy has used its AI drafts for the month");
    expect(techniqueDraftErrorMessage(502)).toBe("The suggestion could not be read, try again");
  });

  it("falls back to a plain retry sentence", () => {
    expect(techniqueDraftErrorMessage(500)).toBe("Couldn't draft from that, try again");
    expect(techniqueDraftErrorMessage(undefined)).toBe("Couldn't draft from that, try again");
  });
});

it("matches the backend observation limit", () => {
  expect(OBSERVATION_MAX).toBe(500);
});
