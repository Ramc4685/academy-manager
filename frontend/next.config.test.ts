import { describe, expect, it } from "vitest";

import config from "./next.config";

type RedirectEntry = {
  source: string;
  destination: string;
  permanent?: boolean;
  has?: unknown;
};

async function resolveRedirects(): Promise<RedirectEntry[]> {
  const redirects = config.redirects;
  if (!redirects) throw new Error("next.config declares no redirects()");
  return (await redirects()) as RedirectEntry[];
}

describe("next.config redirects", () => {
  // #689: the retired Dues paths used to be RSC pages that threw
  // `redirect()` from inside the `(admin)` layout. On Cloudflare Workers the
  // authenticated layout render for a route that only forwards blew the
  // per-request resource ceiling and served `Error 1102` instead of the
  // redirect. A static config redirect is matched before route resolution, so
  // the admin layout never renders for these two paths.
  it.each([
    ["/admin/dues"],
    ["/admin/reports/dues"],
  ])("forwards the retired %s bookmark to Payments without a host condition", async (source) => {
    const entry = (await resolveRedirects()).find((redirect) => redirect.source === source);

    expect(entry, `no redirect declared for ${source}`).toBeDefined();
    expect(entry?.destination).toBe("/admin/payments");
    expect(entry?.permanent).toBe(true);
    expect(entry?.has).toBeUndefined();
  });

  // #827: /admin/parents and /admin/coaches have been pure forwards into the
  // Users directory for some time, but they forwarded by RENDERING the
  // `(admin)` layout and throwing `redirect()` from it — the exact shape that
  // served Cloudflare's Error 1102 instead of a redirect on the Dues paths.
  // A static config redirect is matched before route resolution, so the
  // authenticated layout never runs for a URL that only forwards.
  // Sidebar regroup PR 3: parents left the Staff list, so /admin/parents lands
  // on the Families view (`?view=families`, People CRM Phase 1). It is a 307
  // on purpose — the old 308 to `?role=parent` is already pinned in some
  // browsers, and this move must stay reversible.
  it.each([
    ["/admin/parents", "/admin/families?view=families", false],
    ["/admin/coaches", "/admin/users?role=coach", true],
  ])("forwards the retired %s bookmark to %s", async (source, destination, permanent) => {
    const entry = (await resolveRedirects()).find((redirect) => redirect.source === source);

    expect(entry, `no redirect declared for ${source}`).toBeDefined();
    expect(entry?.destination).toBe(destination);
    expect(entry?.permanent).toBe(permanent);
    expect(entry?.has).toBeUndefined();
  });

  // #839: /admin/users/new was a second, differently-shaped add-user form
  // sitting beside the directory's own Add user dialog. One form now, and the
  // old URL forwards to it with the dialog open.
  it("forwards the retired add-user page to the directory's dialog", async () => {
    const entry = (await resolveRedirects()).find(
      (redirect) => redirect.source === "/admin/users/new",
    );

    expect(entry, "no redirect declared for /admin/users/new").toBeDefined();
    expect(entry?.destination).toBe("/admin/users?add=1");
    expect(entry?.permanent).toBe(true);
    expect(entry?.has).toBeUndefined();
  });

  // The Users directory itself is live and sets `?role=` as its own filter —
  // redirecting it would break the page the two entries above point at.
  it("leaves the live Users directory alone", async () => {
    const sources = (await resolveRedirects()).map((entry) => entry.source);
    expect(sources).not.toContain("/admin/users");
  });

  it("keeps the canonical-host redirect", async () => {
    const hostRedirects = (await resolveRedirects()).filter((entry) => entry.has !== undefined);

    expect(hostRedirects.length).toBeGreaterThan(0);
    expect(hostRedirects.every((entry) => entry.source === "/:path*")).toBe(true);
  });
});
