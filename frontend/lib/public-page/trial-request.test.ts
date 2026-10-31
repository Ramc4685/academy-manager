import { describe, expect, it, vi } from "vitest";

import {
  EMPTY_TRIAL_FORM,
  TRIAL_REQUESTS_PATH,
  classifyTrialResponse,
  submitTrialRequest,
  trialClassOptions,
  trialRequestBody,
  validateTrialForm,
  type TrialFormValues,
} from "./trial-request";
import type { PublicClass } from "./types";

const VALID: TrialFormValues = {
  ...EMPTY_TRIAL_FORM,
  name: "Jamie Testparent",
  email: "jamie@example.test",
  player_age: "9",
  contact_about_request: true,
};

function cls(overrides: Partial<PublicClass> = {}): PublicClass {
  return {
    public_id: "c_open",
    title: "Starters Saturday",
    description: null,
    level: null,
    age_band: null,
    days_of_week: ["Sat"],
    start_time: "09:00",
    end_time: "10:00",
    timezone: null,
    starts_on: null,
    location: null,
    venue_address: null,
    coach_name: null,
    price: null,
    seats: { band: "open", seats_left: null },
    ...overrides,
  };
}

describe("validateTrialForm", () => {
  it("accepts a complete form", () => {
    expect(validateTrialForm(VALID)).toEqual({});
  });

  it("reports every missing required field at once, with the backend's wording", () => {
    expect(validateTrialForm(EMPTY_TRIAL_FORM)).toEqual({
      name: "Enter your name.",
      email: "Enter your email address.",
      player_age: "Enter the player's age.",
      contact_about_request: "Tick this box so the academy can contact you about your request.",
    });
  });

  it("checks email shape, phone digits and the message cap", () => {
    const errors = validateTrialForm({
      ...VALID,
      email: "not-an-email",
      phone: "12",
      message: "x".repeat(1001),
    });
    expect(Object.keys(errors).sort()).toEqual(["email", "message", "phone"]);
    expect(validateTrialForm({ ...VALID, phone: "(555) 010-2030" })).toEqual({});
  });
});

describe("trialRequestBody", () => {
  it("sends blanks as null, keeps the honeypot and never carries a child name or academy", () => {
    const body = trialRequestBody({ ...VALID, marketing_opt_in: true, website: "" });
    expect(body).toEqual({
      name: "Jamie Testparent",
      email: "jamie@example.test",
      phone: null,
      player_age: "9",
      class_id: null,
      message: null,
      contact_about_request: true,
      marketing_opt_in: true,
      website: "",
    });
    expect(Object.keys(body)).not.toContain("child_name");
    expect(Object.keys(body)).not.toContain("academy_id");
  });
});

describe("classifyTrialResponse", () => {
  it("treats only the acknowledgement as success", () => {
    expect(classifyTrialResponse(200, { state: "received" })).toEqual({ kind: "received" });
    expect(classifyTrialResponse(200, {})).toEqual({ kind: "failed" });
  });

  it("maps field errors and keeps a form-level message for unknown fields", () => {
    const result = classifyTrialResponse(422, {
      error: {
        code: "Public.InvalidTrialRequest",
        message: "Some details need another look.",
        details: {
          fields: { email: "Enter an email address like name@example.com.", form: "Bad" },
        },
      },
    });
    expect(result).toEqual({
      kind: "invalid",
      fields: { email: "Enter an email address like name@example.com." },
      message: "Bad",
    });
  });

  it("recognises trials closed, rate limits and everything else", () => {
    expect(
      classifyTrialResponse(409, {
        error: { code: "Public.TrialsClosed", message: "Free trials are paused right now." },
      }),
    ).toEqual({ kind: "closed", message: "Free trials are paused right now." });
    expect(classifyTrialResponse(429, {})).toEqual({ kind: "rate_limited" });
    expect(classifyTrialResponse(404, { detail: "Not found" })).toEqual({ kind: "failed" });
    expect(classifyTrialResponse(500, null)).toEqual({ kind: "failed" });
  });
});

describe("submitTrialRequest", () => {
  it("posts JSON to the same-origin proxy without credentials or an academy header", async () => {
    const fetchImpl = vi.fn(
      async () => new Response(JSON.stringify({ state: "received" }), { status: 200 }),
    );
    const result = await submitTrialRequest(VALID, fetchImpl as unknown as typeof fetch);
    expect(result).toEqual({ kind: "received" });
    const [url, init] = fetchImpl.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe(TRIAL_REQUESTS_PATH);
    expect(init.method).toBe("POST");
    expect(init.credentials).toBe("omit");
    const headers = init.headers as Record<string, string>;
    expect(Object.keys(headers).map((h) => h.toLowerCase())).not.toContain("x-academy-id");
    expect(Object.keys(headers).map((h) => h.toLowerCase())).not.toContain("authorization");
    expect(JSON.parse(String(init.body)).email).toBe("jamie@example.test");
  });

  it("a network failure or a non-JSON body is a plain failure", async () => {
    const offline = vi.fn(async () => {
      throw new TypeError("offline");
    });
    expect(await submitTrialRequest(VALID, offline as unknown as typeof fetch)).toEqual({
      kind: "failed",
    });
    const html = vi.fn(async () => new Response("<html>", { status: 502 }));
    expect(await submitTrialRequest(VALID, html as unknown as typeof fetch)).toEqual({
      kind: "failed",
    });
  });
});

describe("trialClassOptions", () => {
  it("labels each class with its schedule and flags a full class", () => {
    const options = trialClassOptions([
      cls(),
      cls({
        public_id: "c_full",
        title: "Match Play",
        seats: { band: "waitlist", seats_left: null },
      }),
    ]);
    expect(options.map((o) => o.value)).toEqual(["c_open", "c_full"]);
    expect(options[0].label).toContain("Starters Saturday");
    expect(options[1].label).toMatch(/\(full, join waitlist\)$/);
    expect(options[0].label).not.toMatch(/full/);
  });
});
