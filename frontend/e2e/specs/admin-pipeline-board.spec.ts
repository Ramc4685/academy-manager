import { test, expect, type Page, type Route } from "@playwright/test";

import { collectConsoleErrors, installTenantGuard } from "../fixtures/tenant-isolation";
import {
  ACADEMY_A,
  ADMIN_USER_A,
  fulfillJson,
  stubAcademy,
  stubMe,
  stubMemberships,
} from "../fixtures/saas-stubs";

/**
 * People CRM Pipeline board (engineering-spec §3.4, roadmap L3b) at
 * `/admin/families?view=pipeline`, over a stubbed board that behaves like the
 * backend for the calls used here (moves update the column; quick add
 * inserts an Inquiry card). Moves are keyboard operable with an explicit
 * confirm; after a card leaves its column focus goes to the card that took
 * its place. On a phone the board is a stage switcher. Every name is fake.
 * The backend rules are covered by backend/v2/tests (unit, interface and
 * real-mongod contract tests).
 */

type Card = {
  card_id: string;
  kind: "contact" | "family";
  column: string;
  name: string;
  contact_id: string | null;
  family_id: string | null;
  child: string | null;
  child_age: string | null;
  source: string | null;
  created_at: string | null;
  lead_age_days: number | null;
  override_column: string | null;
  override_set_by: string | null;
  override_set_at: string | null;
  move_targets: string[];
};

const ORDER = ["inquiry", "trial_booked", "trial_done", "registered", "enrolled"];

function targets(column: string): string[] {
  const at = ORDER.indexOf(column);
  return ORDER.filter((c, i) => c !== "enrolled" && c !== column && i <= at + 1);
}

function contact(id: string, name: string, column = "inquiry"): Card {
  return {
    card_id: `contact:${id}`,
    kind: "contact",
    column,
    name,
    contact_id: id,
    family_id: null,
    child: "Kid Sample",
    child_age: "8",
    source: "whatsapp_or_phone",
    created_at: "2026-09-20T10:00:00Z",
    lead_age_days: 4,
    override_column: null,
    override_set_by: null,
    override_set_at: null,
    move_targets: targets(column),
  };
}

const FAMILY: Card = {
  ...contact("x", "Test Family Trial", "trial_booked"),
  card_id: "family:fam-1",
  kind: "family",
  contact_id: null,
  family_id: "fam-1",
  source: null,
  lead_age_days: null,
  move_targets: [],
};

async function setup(page: Page) {
  const errors = collectConsoleErrors(page);
  installTenantGuard(page);
  await stubMe(page, ADMIN_USER_A);
  await stubMemberships(page, [
    { academy_id: ACADEMY_A, academy_name: "Aces Academy", role: "owner" },
  ]);
  await stubAcademy(page, ACADEMY_A);
  await page.route("**/api/v2/admin/messages/**", (route) => fulfillJson(route, { messages: [] }));
  await page.route("**/api/v2/admin/inbox/counts", (route) =>
    fulfillJson(route, { counts: {}, total: 0 }),
  );
  await page.route("**/api/v2/admin/people/duplicate-check", (route) =>
    fulfillJson(route, { matches: [] }),
  );

  const cards: Card[] = [
    contact("c-1", "Test Lead One"),
    contact("c-2", "Test Lead Two"),
    FAMILY,
  ];
  const moves: Array<{ id: string; body: unknown }> = [];
  const adds: unknown[] = [];

  await page.route("**/api/v2/admin/crm/pipeline", (route) =>
    fulfillJson(route, { generated_at: "2026-09-24T12:00:00Z", cards, warnings: [] }),
  );
  await page.route("**/api/v2/admin/crm/contacts/*/pipeline-move", (route: Route) => {
    const id = decodeURIComponent(route.request().url().split("/").at(-2) ?? "");
    const body = JSON.parse(route.request().postData() ?? "{}") as { to_column: string };
    moves.push({ id, body });
    const card = cards.find((c) => c.contact_id === id);
    if (!card) return fulfillJson(route, { error: { code: "Crm.ContactNotFound" } }, 404);
    if (ORDER.indexOf(body.to_column) - ORDER.indexOf(card.column) > 1) {
      return fulfillJson(
        route,
        { error: { code: "Crm.PipelineMoveNotAllowed", details: { reason: "stage_skip" } } },
        409,
      );
    }
    card.column = body.to_column;
    card.override_column = body.to_column;
    card.override_set_by = "admin-a";
    card.override_set_at = "2026-09-24T12:00:00Z";
    card.move_targets = targets(body.to_column);
    return fulfillJson(route, { contact_id: id, column: body.to_column });
  });
  await page.route("**/api/v2/admin/crm/contacts", (route: Route) => {
    if (route.request().method() !== "POST") return route.fallback();
    const body = JSON.parse(route.request().postData() ?? "{}") as { name: string };
    adds.push(body);
    const card = { ...contact("c-new", body.name), lead_age_days: 0 };
    cards.unshift(card);
    return fulfillJson(route, card, 201);
  });
  return { errors, moves, adds };
}

function isPhone(page: Page): boolean {
  return (page.viewportSize()?.width ?? 1280) < 768;
}

test.describe("admin Pipeline board (People CRM §3.4)", () => {
  test("columns, read-only family card and a keyboard move with focus return", async ({
    page,
  }) => {
    const { errors, moves } = await setup(page);
    await page.goto("/admin/families?view=pipeline");
    await expect(page.getByTestId("admin-pipeline")).toBeVisible();
    await expect(page.getByTestId("admin-people-view-pipeline")).toHaveAttribute(
      "aria-current",
      "page",
    );

    if (isPhone(page)) {
      await expect(page.getByTestId("admin-pipeline-stage-inquiry")).toHaveAttribute(
        "aria-pressed",
        "true",
      );
      await expect(page.getByTestId("admin-pipeline-stage-trial_booked")).toContainText("(1)");
    } else {
      for (const column of ORDER) {
        await expect(page.getByTestId(`admin-pipeline-column-${column}`)).toBeVisible();
      }
      // The family card opens its record and cannot be moved on the board.
      const family = page.getByTestId("admin-pipeline-card-family:fam-1");
      await expect(family.getByRole("link", { name: "Test Family Trial" })).toHaveAttribute(
        "href",
        "/admin/families/fam-1",
      );
      await expect(family.getByRole("button", { name: "Move to…" })).toHaveCount(0);
    }

    // Keyboard: open Move to…, pick with the arrow keys, confirm explicitly.
    const inquiry = page.getByTestId("admin-pipeline-column-inquiry");
    await inquiry.getByTestId("admin-pipeline-move-contact:c-1").focus();
    await page.keyboard.press("Enter");
    const panel = page.getByTestId("admin-pipeline-move-panel-contact:c-1");
    await expect(panel).toBeVisible();
    // Only the next column forward is offered from Inquiry.
    await expect(panel.getByRole("radio")).toHaveCount(1);
    await page.keyboard.press("Space");
    await expect(panel.getByTestId("admin-pipeline-move-option-trial_booked")).toBeChecked();
    // Choosing an option does not move anything (WCAG 3.2.2).
    expect(moves).toHaveLength(0);
    await panel.getByRole("button", { name: "Move" }).click();

    await expect.poll(() => moves.length).toBe(1);
    expect(moves[0]).toEqual({ id: "c-1", body: { to_column: "trial_booked" } });
    // The card left Inquiry; focus is on the card that took its place.
    await expect(inquiry.getByTestId("admin-pipeline-card-contact:c-1")).toHaveCount(0);
    await expect(page.getByTestId("admin-pipeline-card-contact:c-2")).toBeFocused();

    if (isPhone(page)) {
      await page.getByTestId("admin-pipeline-stage-trial_booked").click();
    }
    const moved = page.getByTestId("admin-pipeline-card-contact:c-1");
    await expect(moved).toBeVisible();
    await expect(moved.getByTestId("admin-pipeline-card-moved")).toBeVisible();
    expect(errors).toEqual([]);
  });

  test("Escape closes the move panel and returns focus to its button", async ({ page }) => {
    const { moves } = await setup(page);
    await page.goto("/admin/families?view=pipeline");
    const trigger = page.getByTestId("admin-pipeline-move-contact:c-2");
    await trigger.click();
    await expect(page.getByTestId("admin-pipeline-move-panel-contact:c-2")).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(page.getByTestId("admin-pipeline-move-panel-contact:c-2")).toHaveCount(0);
    await expect(trigger).toBeFocused();
    expect(moves).toHaveLength(0);
  });

  test("phone deep link opens the requested stage", async ({ page }) => {
    test.skip(!isPhone(page), "the stage switcher is the phone layout");
    await setup(page);
    await page.goto("/admin/families?view=pipeline&stage=trial_booked");
    await expect(page.getByTestId("admin-pipeline-stage-trial_booked")).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    await expect(page.getByTestId("admin-pipeline-card-family:fam-1")).toBeVisible();
    await expect(page.getByTestId("admin-pipeline-column-inquiry")).toHaveCount(0);
  });

  test("quick add lead posts a staff source and focuses the new card", async ({ page }) => {
    const { adds, errors } = await setup(page);
    await page.goto("/admin/families?view=pipeline");
    await page.getByTestId("admin-pipeline-add-lead").click();
    const form = page.getByTestId("admin-pipeline-add-lead-form");
    await expect(page.getByLabel("Name")).toBeFocused();
    // Neither phone nor email: refused before any request.
    await page.getByLabel("Name").fill("Test New Lead");
    await form.getByRole("button", { name: "Add lead" }).click();
    await expect(form.getByRole("alert")).toContainText("phone number or an email");
    expect(adds).toHaveLength(0);

    await page.getByLabel("Phone").fill("555-010-9999");
    await page.getByLabel("Child", { exact: true }).fill("Kid New");
    await page.getByLabel("Source").selectOption("referral");
    await form.getByRole("button", { name: "Add lead" }).click();

    await expect.poll(() => adds.length).toBe(1);
    expect(adds[0]).toEqual({
      name: "Test New Lead",
      phone: "555-010-9999",
      email: null,
      child_name: "Kid New",
      child_age: null,
      source: "referral",
    });
    await expect(page.getByTestId("admin-pipeline-card-contact:c-new")).toBeFocused();
    expect(errors).toEqual([]);
  });
});
