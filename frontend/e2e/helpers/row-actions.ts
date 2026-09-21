import { expect, type Page } from "@playwright/test";

/**
 * #847: admin list rows below `md` render through `PhoneListRow`
 * (`components/ds/phone-row.tsx`), which moves Edit/Cancel-style row actions
 * behind a 44px "Actions for <name>" menu trigger instead of exposing them as
 * direct buttons. The desktop table keeps the direct button.
 *
 * Specs written against the direct button (`getByRole("button", { name:
 * "Cancel session Cancelable Session" })`) still pass on chromium-desktop,
 * but time out on chromium-mobile because that button never renders there.
 * This helper branches on what is actually visible — like
 * `e2e/helpers/nav.ts` does for the admin nav — so the same spec exercises
 * both layouts instead of being pinned to one viewport.
 *
 * `directLabel` is the desktop button's accessible name (e.g. "Cancel
 * session Cancelable Session"); `menuItemLabel` is the same action's label
 * inside the phone row's actions menu (e.g. "Cancel session" or "Edit"),
 * which the phone row renders without the row's title mixed in.
 *
 * Waits for whichever of the two layouts is mounted, rather than an
 * instant `isVisible()` check: the row's data is stubbed via a mocked
 * route, so on a slow run the desktop button (or the phone trigger) may
 * not have painted yet when this helper is called, and `isVisible()`
 * returns false immediately instead of waiting for it.
 */
async function findRowActionSurface(
  page: Page,
  { rowTitle, directLabel }: { rowTitle: string; directLabel: string },
): Promise<"direct" | "menu"> {
  const directButton = page.getByRole("button", { name: directLabel, exact: true });
  const trigger = page.getByRole("button", { name: `Actions for ${rowTitle}` });
  const result = await Promise.race([
    directButton
      .waitFor({ state: "visible", timeout: 15_000 })
      .then((): "direct" => "direct"),
    trigger.waitFor({ state: "visible", timeout: 15_000 }).then((): "menu" => "menu"),
  ]);
  return result;
}

export async function clickRowAction(
  page: Page,
  {
    rowTitle,
    directLabel,
    menuItemLabel,
  }: { rowTitle: string; directLabel: string; menuItemLabel: string },
): Promise<void> {
  const surface = await findRowActionSurface(page, { rowTitle, directLabel });
  if (surface === "direct") {
    await page.getByRole("button", { name: directLabel, exact: true }).click();
    return;
  }
  await page.getByRole("button", { name: `Actions for ${rowTitle}` }).click();
  await page.getByRole("menuitem", { name: menuItemLabel, exact: true }).click();
}

/**
 * Assert a row action is still available (visible and, implicitly, not
 * disabled) without clicking it — e.g. re-asserting a row survived a failed
 * mutation. On phone this has to open the row's menu to see the item, then
 * close it again so the caller's next step (re-clicking the same action)
 * starts from a known, closed state.
 */
export async function expectRowActionAvailable(
  page: Page,
  {
    rowTitle,
    directLabel,
    menuItemLabel,
  }: { rowTitle: string; directLabel: string; menuItemLabel: string },
): Promise<void> {
  const surface = await findRowActionSurface(page, { rowTitle, directLabel });
  if (surface === "direct") {
    await expect(page.getByRole("button", { name: directLabel, exact: true })).toBeVisible();
    return;
  }
  const trigger = page.getByRole("button", { name: `Actions for ${rowTitle}` });
  await trigger.click();
  await expect(page.getByRole("menuitem", { name: menuItemLabel, exact: true })).toBeVisible();
  await page.keyboard.press("Escape");
}
