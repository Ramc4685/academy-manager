import { expect, type Locator, type Page } from "@playwright/test";

/**
 * The admin shell renders two nav surfaces from the same ADMIN_NAV data:
 * a desktop sidebar (visible at lg:) and a mobile drawer behind the
 * `admin-open-drawer` hamburger (hidden at lg:). Both carry the same
 * `admin-nav-<slug>` testids, so helpers branch on what is actually
 * visible — not on viewport size — to stay correct for every Playwright
 * project (mobile and desktop alike).
 */

/**
 * Reveal the admin navigation and return a locator scoped to the visible
 * surface: the mobile drawer (opening it first) when the hamburger is
 * shown, otherwise the always-visible desktop sidebar.
 */
export async function openAdminNav(page: Page): Promise<Locator> {
  const drawerButton = page.getByTestId("admin-open-drawer");
  if (await drawerButton.isVisible()) {
    await drawerButton.scrollIntoViewIfNeeded();
    await drawerButton.click({ force: true });
    const drawer = page.getByTestId("admin-mobile-drawer");
    await expect(drawer).toBeVisible();
    return drawer;
  }
  const sidebar = page.locator('aside[aria-label="Admin navigation"]');
  await expect(sidebar).toBeVisible();
  return sidebar;
}

/**
 * Navigate via an `admin-nav-<slug>` link, opening the mobile drawer first
 * when the sidebar link is not visible. On mobile the drawer duplicates the
 * sidebar's testids, so the click is scoped to the surface openAdminNav
 * returned.
 */
export async function gotoAdminNav(page: Page, slug: string): Promise<void> {
  const nav = await openAdminNav(page);
  await nav.getByTestId(`admin-nav-${slug}`).click();
}
