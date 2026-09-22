import { expect, type Page } from "@playwright/test";

/**
 * Month close groups its cards into collapsible sections (issue #862), and the
 * default follows the viewport: collapsed on a phone, open on a desktop.
 *
 * Any spec that asserts on a card inside a group therefore has to say which
 * group it wants open, rather than assume. This helper is idempotent and
 * viewport-agnostic — the same line works under chromium-mobile and
 * chromium-desktop.
 *
 * It re-clicks rather than clicking once: `useIsDesktop` reports `false` for a
 * paint while the client store resolves, so a click that lands before React
 * hydrates is simply dropped. Polling the disclosure's own state converges
 * whichever way that race falls, and clicking an already-open group is never
 * what happens because the state is read first.
 */
export async function openMonthCloseSection(page: Page, id: string): Promise<void> {
  const toggle = page.getByTestId(`month-close-section-${id}-toggle`);
  await expect(toggle).toBeVisible({ timeout: 45_000 });
  await expect
    .poll(
      async () => {
        if ((await toggle.getAttribute("aria-expanded")) === "false") {
          await toggle.click();
        }
        return toggle.getAttribute("aria-expanded");
      },
      { timeout: 15_000 },
    )
    .toBe("true");
  await expect(page.getByTestId(`month-close-section-${id}-body`)).toBeVisible();
}
