import { expect, test } from "@playwright/test";

// Regression guard for the mobile Google sign-in mode (PR #127 follow-up).
//
// On phones (iOS WebKit and Android Chrome) "Continue with Google" must use
// the full-page signInWithRedirect flow: signInWithPopup is unreliable there
// (popup blockers + third-party storage partitioning). The UA heuristic is
// unit-tested in lib/auth/google-sign-in-mode.node-test.mjs; this spec runs
// the real login page under both mobile device descriptors (Pixel 7 and
// iPhone 14, see playwright.config.ts projects) and asserts the page itself
// chooses redirect: in E2E auth bypass mode the click must navigate THIS tab
// to the Firebase auth handler path (/__/auth/handler) instead of opening a
// popup window.
//
// Note this can only prove the redirect leaves correctly. Whether the
// redirect *returns* correctly depends on the authDomain being same-site
// with the app (third-party storage partitioning), which emulation cannot
// reproduce — that part needs a real device against production.

test.describe("google sign-in mode on mobile devices", () => {
  test("continue-with-google does a full-page redirect, not a popup", async ({
    page,
  }) => {
    const popups: string[] = [];
    page.on("popup", (popup) => popups.push(popup.url()));

    // Serve a stub for the Firebase auth handler so the redirect stays
    // on-box after the E2E auth bypass navigates to the handler path.
    await page.route("**/__/auth/**", (route) =>
      route.fulfill({
        status: 200,
        contentType: "text/html",
        body: "<html><body>e2e stub: firebase auth handler</body></html>",
      })
    );

    await page.goto("/login");
    await page.getByTestId("login-google").click();

    await page.waitForURL("**/__/auth/handler**");
    const url = new URL(page.url());
    expect(url.pathname).toBe("/__/auth/handler");
    expect(url.searchParams.get("authType")).toBe("signInViaRedirect");
    expect(url.searchParams.get("providerId")).toBe("google.com");
    expect(popups).toHaveLength(0);
  });
});
