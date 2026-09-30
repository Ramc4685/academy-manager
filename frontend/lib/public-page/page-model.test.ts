import { describe, expect, it } from "vitest";

import fixtures from "@/e2e/fixtures/public-academy-pages.json";

import {
  classGroups,
  classifyPublicAcademyResponse,
  coachCards,
  describePublishedPage,
  faqEntries,
  isIndexable,
} from "./page-model";
import type { PublicAcademyNotPublished, PublicAcademyPage } from "./types";

const published = fixtures.published as PublicAcademyPage;
const empty = fixtures.empty as PublicAcademyPage;
const closed = fixtures.trials_closed as PublicAcademyPage;
const allFull = fixtures.all_full as PublicAcademyPage;
const notPublished = fixtures.not_published as PublicAcademyNotPublished;

describe("classifyPublicAcademyResponse", () => {
  it("maps the backend's bare 404 to the unknown-host state", () => {
    expect(classifyPublicAcademyResponse(404, { detail: "Not found" })).toEqual({
      kind: "unknown_host",
    });
  });

  it("recognises both page shapes", () => {
    expect(classifyPublicAcademyResponse(200, published).kind).toBe("published");
    expect(classifyPublicAcademyResponse(200, notPublished).kind).toBe("not_published");
  });

  it("treats errors, rate limits and malformed bodies as unavailable", () => {
    expect(classifyPublicAcademyResponse(500, null)).toEqual({ kind: "unavailable" });
    expect(classifyPublicAcademyResponse(429, {})).toEqual({ kind: "unavailable" });
    expect(classifyPublicAcademyResponse(200, { state: "published" })).toEqual({
      kind: "unavailable",
    });
    expect(classifyPublicAcademyResponse(200, "<html>")).toEqual({ kind: "unavailable" });
  });
});

describe("describePublishedPage", () => {
  it("leads with the free trial when classes are open", () => {
    const view = describePublishedPage(published);
    expect(view.hasClasses).toBe(true);
    expect(view.allFull).toBe(false);
    expect(view.primary).toEqual({ label: "Book a free trial", href: "#trial" });
    expect(view.coaches).toEqual(["Coach Alex Rivera", "Coach Sam Okafor"]);
    expect(view.pricePeriodLabel).toBe("per month");
  });

  it("asks to be told when classes open when nothing is listed", () => {
    const view = describePublishedPage(empty);
    expect(view.hasClasses).toBe(false);
    expect(view.primary).toEqual({ label: "Tell me when classes open", href: "#trial" });
  });

  it("sends visitors to the classes when trials are closed", () => {
    expect(describePublishedPage(closed).primary).toEqual({
      label: "See open classes",
      href: "#classes",
    });
    expect(describePublishedPage({ ...empty, page: { ...empty.page, trials_open: false } }).primary)
      .toEqual({ label: "Parent login", href: "/login" });
  });

  it("offers the waitlist when every class is full", () => {
    const view = describePublishedPage(allFull);
    expect(view.allFull).toBe(true);
    expect(view.primary.label).toBe("Join the waitlist");
  });
});

describe("classGroups", () => {
  it("keeps program order and puts ungrouped classes last", () => {
    const groups = classGroups(published);
    expect(groups.map((g) => g.name)).toEqual(["Shuttle Starters", "Match Play", "More classes"]);
    expect(classGroups({ ...published, programs: [] }).map((g) => g.name)).toEqual(["Classes"]);
  });
});

describe("isIndexable", () => {
  it("indexes only a published page that lists classes", () => {
    expect(isIndexable({ kind: "published", page: published })).toBe(true);
    expect(isIndexable({ kind: "published", page: closed })).toBe(true);
    expect(isIndexable({ kind: "published", page: empty })).toBe(false);
    expect(isIndexable({ kind: "not_published", page: notPublished })).toBe(false);
    expect(isIndexable({ kind: "unavailable" })).toBe(false);
  });
});

describe("faqEntries", () => {
  it("drops the free-trial question while trials are closed", () => {
    expect(faqEntries(published)[0].question).toBe("What happens at a free trial?");
    expect(faqEntries(closed).some((e) => e.question.includes("free trial"))).toBe(false);
  });
});

describe("academy content (Settings Phase 6)", () => {
  it("uses the built-in FAQ when the academy wrote none", () => {
    expect(faqEntries({ ...published, faqs: [] }).map((f) => f.question)).toEqual(
      faqEntries(published).map((f) => f.question),
    );
    expect(faqEntries(published)[0].question).toBe("What happens at a free trial?");
  });

  it("uses the academy's own FAQs when present", () => {
    const own = [{ question: "Rackets?", answer: "Yes." }];
    expect(faqEntries({ ...published, faqs: own })).toEqual(own);
  });

  it("with no profiles the coaches are today's name-only list", () => {
    const view = describePublishedPage(published);
    expect(coachCards(published, view.coaches)).toEqual(
      view.coaches.map((name) => ({ name, photoUrl: null, bio: null })),
    );
  });

  it("profiles come first and a coach without one stays a name", () => {
    const page = {
      ...published,
      coaches: [
        { name: "Coach Sam Okafor", photo_url: "https://firebasestorage.googleapis.com/v0/b/x/o/s.jpg", bio: "Loves drills." },
        { name: "coach alex rivera", photo_url: "http://insecure.test/a.jpg", bio: "" },
      ],
    };
    const cards = coachCards(page, describePublishedPage(page).coaches);
    expect(cards).toEqual([
      { name: "Coach Sam Okafor", photoUrl: "https://firebasestorage.googleapis.com/v0/b/x/o/s.jpg", bio: "Loves drills." },
      { name: "coach alex rivera", photoUrl: null, bio: null },
    ]);
  });

  it("the seat threshold reaches the all-full check", () => {
    expect(describePublishedPage({ ...allFull, page: { ...allFull.page, seats_left_threshold: 0 } }).allFull).toBe(
      true,
    );
  });
});
