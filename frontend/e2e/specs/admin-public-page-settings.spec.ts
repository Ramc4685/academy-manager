import { expect, test, type Page, type Route } from "@playwright/test";

/**
 * Settings → Public page (Lane B5), against a mocked admin BFF.
 *
 * Covers: Publish + Save sends only the changed key, the price period and
 * privacy link validation, the unsaved-changes guard on a tab switch, the
 * per-class switch saving on its own (no Save button), program create and
 * class-to-program assignment, and the "View page" link. The Photos & details
 * card (content lane) is covered at the end: the consent-gated gallery upload,
 * the text sections and FAQ reorder, and coach profiles.
 */

const ADMIN_ME = {
  user_id: "user-admin-public-page-e2e",
  email: "admin@riverside.example",
  academy_id: "academy-e2e",
  roles: ["admin"],
};

const SETTINGS = {
  published: false,
  show_price: true,
  show_availability: true,
  price_period_default: "month",
  trials_open: true,
  privacy_notice_url: null,
  public_url: "https://riverside.example/",
};

const CLASS_ROW = {
  program_id: null as string | null,
  published: false,
  price_period: null,
  coach_display: "full_name",
  public_description: null,
  level: null,
  age_band: null,
};

function classes() {
  return [
    { ...CLASS_ROW, session_id: "sess-juniors", title: "Junior Shuttlers", status: "scheduled" },
    { ...CLASS_ROW, session_id: "sess-adults", title: "Adult Beginners", status: "scheduled" },
    { ...CLASS_ROW, session_id: "sess-old", title: "Summer Camp", status: "completed" },
  ];
}

// A 1x1 PNG so preview images of stubbed uploads load without the network.
const PIXEL = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==",
  "base64",
);

const COACHES = {
  users: [
    {
      user_id: "coach-1",
      email: "alex@riverside.example",
      display_name: "Alex Morgan",
      role: "coach",
      status: "active",
    },
  ],
};

async function stubContent(page: Page) {
  await page.route("https://cdn.example/**", (route) =>
    route.fulfill({ status: 200, contentType: "image/png", body: PIXEL }),
  );
  await page.route(/\/api\/v2\/admin\/users\?.*/, (route) => fulfillJson(route, COACHES));
}

function fulfillJson(route: Route, body: unknown, status = 200) {
  return route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
}

interface Seen {
  settingsPatches: unknown[];
  fieldPatches: Array<{ url: string; body: unknown }>;
  programPuts: Array<{ url: string; body: unknown }>;
  programPosts: unknown[];
}

async function stub(
  page: Page,
  seed: { programs?: Array<Record<string, unknown>>; rows?: ReturnType<typeof classes> } = {},
): Promise<Seen> {
  const seen: Seen = { settingsPatches: [], fieldPatches: [], programPuts: [], programPosts: [] };
  let settings: Record<string, unknown> = { ...SETTINGS };
  let rows = seed.rows ?? classes();
  const programs: Array<Record<string, unknown>> = [...(seed.programs ?? [])];

  // Catch-all first: Playwright matches the most recently registered route
  // first, so the specific stubs below win and shell polls get an empty shape.
  await page.route("**/api/v2/admin/**", (route) =>
    route.request().method() === "GET" ? fulfillJson(route, {}) : route.fallback(),
  );
  await page.route("**/api/v2/me", (route) =>
    route.request().method() === "GET" ? fulfillJson(route, ADMIN_ME) : route.fallback(),
  );
  await page.route("**/api/v2/me/memberships", (route) =>
    fulfillJson(route, {
      memberships: [
        {
          academy_id: "academy-e2e",
          academy_name: "Riverside Shuttle Club",
          academy_slug: "academy-e2e",
          roles: ADMIN_ME.roles,
          status: "active",
          is_default: true,
        },
      ],
      active_academy_id: "academy-e2e",
    }),
  );
  await page.route("**/api/v2/admin/academy", (route) =>
    route.request().method() === "GET"
      ? fulfillJson(route, {
          academy_id: "academy-e2e",
          display_name: "Riverside Shuttle Club",
          timezone: "America/Chicago",
          contact_email: null,
          contact_phone: null,
          hours_text: null,
          address: null,
          logo_url: null,
          brand_color: null,
        })
      : route.fallback(),
  );
  await page.route("**/api/v2/admin/academy/public-page", (route) => {
    const request = route.request();
    if (request.method() === "GET") return fulfillJson(route, settings);
    if (request.method() === "PATCH") {
      const body = request.postDataJSON() as Record<string, unknown>;
      seen.settingsPatches.push(body);
      settings = { ...settings, ...body };
      return fulfillJson(route, settings);
    }
    return route.fallback();
  });
  await page.route("**/api/v2/admin/class-public-profiles", (route) =>
    fulfillJson(route, { classes: rows }),
  );
  // A regex, not a glob, so ?include_archived=true matches too. Like the real
  // endpoint, archived programs come back only when asked for.
  await page.route(/\/api\/v2\/admin\/programs(\?.*)?$/, (route) => {
    const request = route.request();
    if (request.method() === "GET") {
      const withArchived = new URL(request.url()).searchParams.get("include_archived") === "true";
      return fulfillJson(route, {
        programs: withArchived ? programs : programs.filter((p) => !p.archived),
      });
    }
    if (request.method() === "POST") {
      const body = request.postDataJSON() as { name: string };
      seen.programPosts.push(body);
      const program = {
        program_id: `prog-${programs.length + 1}`,
        name: body.name,
        public_description: null,
        level: null,
        age_band: null,
        sort_order: programs.length,
        archived: false,
        created_at: "2026-09-23T12:00:00Z",
        updated_at: "2026-09-23T12:00:00Z",
      };
      programs.push(program);
      return fulfillJson(route, program, 201);
    }
    return route.fallback();
  });
  await page.route("**/api/v2/admin/sessions/*/public-fields", (route) => {
    const request = route.request();
    const body = request.postDataJSON() as Record<string, unknown>;
    seen.fieldPatches.push({ url: request.url(), body });
    const id = decodeURIComponent(request.url().split("/sessions/")[1].split("/")[0]);
    rows = rows.map((row) => (row.session_id === id ? { ...row, ...body } : row));
    return fulfillJson(route, rows.find((row) => row.session_id === id));
  });
  await page.route("**/api/v2/admin/sessions/*/program", (route) => {
    const request = route.request();
    const body = request.postDataJSON() as { program_id: string | null };
    seen.programPuts.push({ url: request.url(), body });
    const id = decodeURIComponent(request.url().split("/sessions/")[1].split("/")[0]);
    rows = rows.map((row) =>
      row.session_id === id ? { ...row, program_id: body.program_id } : row,
    );
    return fulfillJson(route, rows.find((row) => row.session_id === id));
  });
  return seen;
}

test.describe("admin settings → public page", () => {
  test("publish + save sends only the changed keys and the page reads live", async ({ page }) => {
    const seen = await stub(page);
    await page.goto("/admin/settings?panel=public-page");
    const panel = page.getByTestId("admin-settings-public-page");
    await expect(panel).toBeVisible();

    await expect(page.getByTestId("public-page-live-note")).toContainText("not live");
    const view = page.getByTestId("public-page-view-link");
    await expect(view).toHaveAttribute("href", "https://riverside.example/");
    await expect(view).toHaveAttribute("target", "_blank");

    const save = page.getByTestId("public-page-save");
    await expect(save).toBeDisabled();
    await page.getByTestId("public-page-published").check();
    await page.getByTestId("public-page-price-period").selectOption("term");
    await expect(save).toBeEnabled();
    await save.click();

    await expect(page.getByText(/Saved at/)).toBeVisible();
    expect(seen.settingsPatches).toEqual([{ published: true, price_period_default: "term" }]);
    await expect(page.getByTestId("public-page-live-note")).toContainText("Your page is live");
    await expect(save).toBeDisabled();
  });

  test("the privacy link is not edited here; a pointer sends you to Academy profile", async ({
    page,
  }) => {
    await stub(page);
    await page.goto("/admin/settings?panel=public-page");
    await expect(page.getByTestId("public-page-view-link")).toBeVisible();
    await expect(page.getByTestId("public-page-privacy-url")).toHaveCount(0);
    const pointer = page.getByTestId("public-page-privacy-moved");
    await expect(pointer).toContainText("The privacy notice now lives with the terms and refund links.");
    await expect(pointer.getByRole("link", { name: "Open Academy profile", exact: true })).toHaveAttribute(
      "href",
      "/admin/settings?panel=academy",
    );
  });

  test("an unsaved switch is guarded on a tab switch", async ({ page }) => {
    await stub(page);
    await page.goto("/admin/settings?panel=public-page");
    await page.getByTestId("public-page-show-price").uncheck();

    const guard = page.getByTestId("confirm-action-dialog");
    const notifyTab = page.getByRole("link", { name: "Notifications", exact: true });
    await notifyTab.click();
    await expect(guard).toBeVisible();
    await guard.getByRole("button", { name: "Stay on this page" }).click();
    await expect(guard).toHaveCount(0);
    await expect(page).toHaveURL(/panel=public-page/);
    await expect(page.getByTestId("public-page-show-price")).not.toBeChecked();

    await notifyTab.click();
    await expect(guard).toBeVisible();
    await Promise.all([
      page.waitForURL(/panel=notifications/),
      guard.getByTestId("confirm-action-submit").click(),
    ]);
    await expect(page.getByTestId("admin-settings-notify")).toBeVisible();
  });

  test("per-class switches save on their own and never dirty the page form", async ({ page }) => {
    const seen = await stub(page);
    await page.goto("/admin/settings?panel=public-page");

    const rows = page.getByTestId("public-page-class-row");
    // Ended classes that are not switched on are left out; sorted by title.
    await expect(rows).toHaveCount(2);
    await expect(rows.nth(0)).toContainText("Adult Beginners");
    await expect(rows.nth(1)).toContainText("Junior Shuttlers");

    const juniors = page.locator('[data-session-id="sess-juniors"]');
    // click, not check(): the row re-renders from the query cache a tick
    // after the click (TanStack batches cache notifications).
    await juniors.getByTestId("public-page-class-published").click();
    await expect(juniors.getByTestId("public-page-class-published")).toBeChecked();
    await expect(juniors).toContainText("Shown");
    await juniors.getByTestId("public-page-class-price-period").selectOption("class");
    await juniors.getByTestId("public-page-class-coach-display").selectOption("first_name");
    await expect(juniors.getByTestId("public-page-class-coach-display")).toHaveValue(
      "first_name",
    );

    await expect.poll(() => seen.fieldPatches.length).toBe(3);
    expect(seen.fieldPatches.map((p) => p.body)).toEqual([
      { published: true },
      { price_period: "class" },
      { coach_display: "first_name" },
    ]);
    expect(seen.fieldPatches.every((p) => p.url.includes("/sessions/sess-juniors/"))).toBe(true);
    expect(seen.settingsPatches).toEqual([]);
    await expect(page.getByTestId("public-page-save")).toBeDisabled();

    // No draft left behind: switching tabs does not ask.
    await Promise.all([
      page.waitForURL(/panel=notifications/),
      page.getByRole("link", { name: "Notifications", exact: true }).click(),
    ]);
    await expect(page.getByTestId("confirm-action-dialog")).toHaveCount(0);
  });

  test("create a program and put a class in it", async ({ page }) => {
    const seen = await stub(page);
    await page.goto("/admin/settings?panel=public-page");
    await expect(page.getByTestId("public-page-programs-empty")).toBeVisible();

    await page.getByTestId("public-page-new-program").fill("Juniors");
    await page.getByTestId("public-page-add-program").click();
    await expect(page.getByTestId("public-page-program-row")).toContainText("Juniors");
    expect(seen.programPosts).toEqual([{ name: "Juniors" }]);

    const juniors = page.locator('[data-session-id="sess-juniors"]');
    await juniors.getByTestId("public-page-class-program").selectOption({ label: "Juniors" });
    await expect(juniors.getByTestId("public-page-class-program")).toHaveValue("prog-1");
    expect(seen.programPuts).toEqual([
      {
        url: expect.stringContaining("/admin/sessions/sess-juniors/program"),
        body: { program_id: "prog-1" },
      },
    ]);
  });

  test("a class in an archived program says so instead of reading as unassigned", async ({
    page,
  }) => {
    const archived = {
      program_id: "prog-old",
      name: "Winter Squad",
      public_description: null,
      level: null,
      age_band: null,
      sort_order: 0,
      archived: true,
      created_at: "2026-09-23T12:00:00Z",
      updated_at: "2026-09-23T12:00:00Z",
    };
    const rows = classes().map((row) =>
      row.session_id === "sess-juniors" ? { ...row, program_id: "prog-old" } : row,
    );
    await stub(page, { programs: [archived], rows });
    await page.goto("/admin/settings?panel=public-page");

    // The Programs card lists only active programs.
    await expect(page.getByTestId("public-page-programs-empty")).toBeVisible();
    const juniors = page.locator('[data-session-id="sess-juniors"]');
    const select = juniors.getByTestId("public-page-class-program");
    await expect(select).toHaveValue("prog-old");
    await expect(select.locator("option:checked")).toHaveText("Winter Squad (archived)");
    // Other classes are not offered the archived program.
    const adults = page.locator('[data-session-id="sess-adults"]');
    await expect(adults.getByTestId("public-page-class-program")).toHaveValue("");
    await expect(adults.locator("option", { hasText: "Winter Squad" })).toHaveCount(0);
  });

  test("gallery upload needs the parents-agreed box, then saves the photo with consent", async ({
    page,
  }) => {
    const seen = await stub(page);
    await stubContent(page);
    const uploads: string[] = [];
    await page.route("**/api/v2/admin/academy/media", (route) => {
      uploads.push(route.request().postData() ?? "");
      return fulfillJson(route, {
        logo_url: null,
        url: "https://cdn.example/g1.jpg",
        purpose: "gallery",
      });
    });
    await page.goto("/admin/settings?panel=public-page");

    const button = page.getByTestId("public-page-gallery-upload-button");
    const file = page.getByTestId("public-page-gallery-upload-file");
    await expect(button).toBeDisabled();
    await expect(file).toBeDisabled();
    expect(uploads).toEqual([]);

    await page.getByTestId("public-page-gallery-consent").check();
    await expect(button).toBeEnabled();
    await file.setInputFiles({
      name: "juniors.jpg",
      mimeType: "image/jpeg",
      buffer: Buffer.from("jpeg-bytes"),
    });

    await expect(page.getByTestId("public-page-gallery-item")).toHaveCount(1);
    expect(uploads).toHaveLength(1);
    expect(uploads[0]).toContain('name="purpose"');
    expect(uploads[0]).toContain("gallery");
    expect(uploads[0]).toContain('name="consent"');
    // Each photo needs its own confirmation.
    await expect(page.getByTestId("public-page-gallery-consent")).not.toBeChecked();
    await expect(button).toBeDisabled();

    await page.getByTestId("public-page-gallery-caption").fill("Saturday juniors");
    await page.getByTestId("public-page-content-save").click();
    await expect(page.getByText(/Saved at/)).toBeVisible();
    expect(seen.settingsPatches).toEqual([
      {
        gallery: [
          {
            url: "https://cdn.example/g1.jpg",
            caption: "Saturday juniors",
            consent_confirmed: true,
          },
        ],
      },
    ]);
  });

  test("about text, highlights and FAQs save as one patch; FAQ rows reorder", async ({ page }) => {
    const seen = await stub(page);
    await stubContent(page);
    await page.goto("/admin/settings?panel=public-page");

    await expect(page.getByTestId("public-page-faq-helper")).toContainText(
      "Leave empty to use the standard questions.",
    );
    await page.getByTestId("public-page-about").fill("Est. 2019.");
    await page.getByTestId("public-page-highlight-input").fill("Small groups");
    await page.getByTestId("public-page-highlight-add").click();

    await page.getByTestId("public-page-faq-add").click();
    await page.getByTestId("public-page-faq-add").click();
    const rows = page.getByTestId("public-page-faq-row");
    await rows.nth(0).getByTestId("public-page-faq-question").fill("Do I need a racket?");
    await rows.nth(0).getByTestId("public-page-faq-answer").fill("We lend one.");
    await rows.nth(1).getByTestId("public-page-faq-question").fill("Where do we park?");
    await rows.nth(1).getByTestId("public-page-faq-answer").fill("Behind the hall.");
    await rows.nth(1).getByTestId("public-page-faq-up").click();

    await page.getByTestId("public-page-content-save").click();
    await expect(page.getByText(/Saved at/)).toBeVisible();
    expect(seen.settingsPatches).toEqual([
      {
        about_text: "Est. 2019.",
        highlights: ["Small groups"],
        faqs: [
          { question: "Where do we park?", answer: "Behind the hall." },
          { question: "Do I need a racket?", answer: "We lend one." },
        ],
      },
    ]);
  });

  test("a coach gets a profile when shown, with a bio counter", async ({ page }) => {
    const seen = await stub(page);
    await stubContent(page);
    await page.goto("/admin/settings?panel=public-page");

    const row = page.getByTestId("public-page-coach-row");
    await expect(row).toContainText("Alex Morgan");
    await row.getByTestId("public-page-coach-shown").check();
    await row.getByTestId("public-page-coach-bio").fill("Level 2 BWF");
    await expect(row.getByTestId("public-page-coach-bio-count")).toHaveText("11 / 280");
    await page.getByTestId("public-page-content-save").click();
    await expect(page.getByText(/Saved at/)).toBeVisible();
    expect(seen.settingsPatches).toEqual([
      {
        coach_profiles: [
          { coach_id: "coach-1", photo_url: null, bio: "Level 2 BWF", shown: true },
        ],
      },
    ]);
  });
});
