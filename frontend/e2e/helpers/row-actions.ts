import { expect, type Locator, type Page } from "@playwright/test";

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

/**
 * #857: the same branch, keyed by test id instead of by the row's visible
 * name.
 *
 * Some queues render rows whose titles are not unique — the level-up fixtures
 * are two "Unnamed student" rows — so those specs scope by
 * `<list>-row-<id>` and cannot use `rowTitle`. `actionsTestId` is the phone
 * row's trigger, deliberately `<list>-actions-<id>` and NOT the row id with
 * `actions-` appended, so a prefix match for rows never picks it up.
 *
 * The menu is portalled to `document.body`, so the returned menu-item locator
 * is page-scoped, not row-scoped. Callers get the element and assert or click
 * it; repeat calls for the same row reuse the menu that is already open.
 *
 * `directTestId` (#861) is for rows whose desktop action is not a button at
 * all — the Collections tab's WhatsApp and Message actions are anchors, which
 * `getByRole("button")` can never match — and for rows that already stamp a
 * per-action test id worth keeping. The menu half is unchanged: menu items are
 * found by their label, exactly as the trigger-based branch does.
 */
export async function rowActionControl(
  page: Page,
  {
    rowTestId,
    actionsTestId,
    label,
    directTestId,
  }: { rowTestId: string; actionsTestId: string; label: string; directTestId?: string },
): Promise<Locator> {
  const row = page.getByTestId(rowTestId);
  const direct = directTestId
    ? page.getByTestId(directTestId)
    : row.getByRole("button", { name: label, exact: true });
  const trigger = page.getByTestId(actionsTestId);
  const surface = await Promise.race([
    direct.waitFor({ state: "visible", timeout: 15_000 }).then((): "direct" => "direct"),
    trigger.waitFor({ state: "visible", timeout: 15_000 }).then((): "menu" => "menu"),
  ]);
  if (surface === "direct") return direct;
  // The trigger toggles, so a second lookup in the same row must NOT click it
  // again — that would shut the menu the first lookup opened. `aria-expanded`
  // is the state the component itself publishes. Opening a different row's
  // trigger needs no cleanup: the menu closes itself on the outside mousedown
  // that precedes the click.
  if ((await trigger.getAttribute("aria-expanded")) !== "true") {
    await trigger.click();
    await expect(trigger).toHaveAttribute("aria-expanded", "true");
  }
  return page.getByRole("menuitem", { name: label, exact: true });
}
