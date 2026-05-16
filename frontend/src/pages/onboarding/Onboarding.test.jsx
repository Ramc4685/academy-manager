/**
 * Phase 5 Slice 5 — parent onboarding flow tests.
 *
 * Pattern: react-dom/client.createRoot + React 19 act, virtual-mocked
 * react-router-dom, mocked lib/api.  No @testing-library/react.
 * Follows CoachToday.test.jsx precedent.
 */
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

import React, { act } from "react";
import { createRoot } from "react-dom/client";

// ─── Virtual mock: react-router-dom ──────────────────────────────────────────
jest.mock(
  "react-router-dom",
  () => {
    const React2 = require("react");
    const navigateFn = jest.fn();
    let _params = {};

    return {
      __esModule: true,
      MemoryRouter: ({ children }) =>
        React2.createElement(React2.Fragment, null, children),
      Link: ({ to, children, ...rest }) =>
        React2.createElement(
          "a",
          { href: typeof to === "string" ? to : "#", ...rest },
          children
        ),
      useNavigate: () => navigateFn,
      useParams: () => _params,
      __setParams: (p) => { _params = p; },
      __navigateFn: navigateFn,
    };
  },
  { virtual: true }
);

// ─── Virtual mock: lib/api ────────────────────────────────────────────────────
jest.mock("../../lib/api", () => {
  const mockGet = jest.fn();
  const mockPost = jest.fn();
  const mockPatch = jest.fn();
  return {
    __esModule: true,
    api: { get: mockGet, post: mockPost, patch: mockPatch },
    __mockGet: mockGet,
    __mockPost: mockPost,
    __mockPatch: mockPatch,
  };
});

// ─── Virtual mock: AuthContext ────────────────────────────────────────────────
jest.mock("../../contexts/AuthContext", () => {
  let _user = { id: "u1", role: "parent", email: "parent@test.com" };
  return {
    __esModule: true,
    useAuth: () => ({ user: _user }),
    __setUser: (u) => { _user = u; },
  };
}, { virtual: true });

// ─── Virtual mock: sonner ─────────────────────────────────────────────────────
jest.mock("sonner", () => ({ toast: { error: jest.fn(), success: jest.fn() } }), {
  virtual: true,
});

// ─── Virtual mock: UI components ─────────────────────────────────────────────
jest.mock("../../components/ui/button", () => {
  const React2 = require("react");
  return {
    __esModule: true,
    Button: ({ children, onClick, disabled, ...rest }) =>
      React2.createElement("button", { onClick, disabled, ...rest }, children),
  };
}, { virtual: true });

jest.mock("../../components/ui/input", () => {
  const React2 = require("react");
  return {
    __esModule: true,
    Input: (props) => React2.createElement("input", props),
  };
}, { virtual: true });

jest.mock("../../components/ui/label", () => {
  const React2 = require("react");
  return {
    __esModule: true,
    Label: ({ children, ...rest }) =>
      React2.createElement("label", rest, children),
  };
}, { virtual: true });

jest.mock("../../components/ui/textarea", () => {
  const React2 = require("react");
  return {
    __esModule: true,
    Textarea: (props) => React2.createElement("textarea", props),
  };
}, { virtual: true });

// ─── Imports ─────────────────────────────────────────────────────────────────
// eslint-disable-next-line import/first
import { __mockGet, __mockPost, __mockPatch } from "../../lib/api";
// eslint-disable-next-line import/first
import { __navigateFn, __setParams } from "react-router-dom";
// eslint-disable-next-line import/first
import OnboardingStart from "./OnboardingStart";
// eslint-disable-next-line import/first
import OnboardingProfile from "./OnboardingProfile";
// eslint-disable-next-line import/first
import OnboardingWaiver from "./OnboardingWaiver";
// eslint-disable-next-line import/first
import OnboardingSession from "./OnboardingSession";
// eslint-disable-next-line import/first
import OnboardingReview from "./OnboardingReview";
// eslint-disable-next-line import/first
import OnboardingStatus from "./OnboardingStatus";

// ─── Helpers ─────────────────────────────────────────────────────────────────
function flushPromises() {
  return new Promise((resolve) => setTimeout(resolve, 0));
}

async function render(Component) {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  await act(async () => {
    root.render(React.createElement(Component));
  });
  await act(async () => {
    await flushPromises();
  });
  return { container, root };
}

beforeEach(() => {
  __mockGet.mockReset();
  __mockPost.mockReset();
  __mockPatch.mockReset();
  __mockPost.mockResolvedValue({ data: { _id: "app-123", status: "draft" } });
  __navigateFn.mockReset();
  __setParams({ id: "app-123" });
  // Default window.location.search to empty
  Object.defineProperty(window, "location", {
    writable: true,
    configurable: true,
    value: { search: "", href: "" },
  });
});

afterEach(() => {
  document.body.innerHTML = "";
});

// ─── Tests ────────────────────────────────────────────────────────────────────

// 1. Start route creates or resumes a draft and redirects
test("test_start_route_creates_or_resumes_draft_and_redirects", async () => {
  __mockPost.mockResolvedValue({ data: { _id: "app-abc", status: "draft" } });

  const { container } = await render(OnboardingStart);

  expect(__mockPost).toHaveBeenCalledWith("/onboarding/start", {});
  expect(__navigateFn).toHaveBeenCalledWith(
    "/onboarding/app-abc/profile",
    expect.objectContaining({ replace: true })
  );
  expect(container).toBeDefined();
});

// 2. Profile step blocks advance without required fields
test("test_profile_step_blocks_advance_without_required_fields", async () => {
  const { container } = await render(OnboardingProfile);

  const nextBtn = container.querySelector("[data-testid='profile-next']");
  expect(nextBtn).not.toBeNull();
  // Button is disabled because all required fields are empty
  expect(nextBtn.disabled).toBe(true);
  expect(__mockPatch).not.toHaveBeenCalled();
});

// 2b. Profile step hydrates saved draft values when resuming
test("test_profile_step_hydrates_existing_draft", async () => {
  __mockPost.mockResolvedValue({
    data: {
      _id: "app-123",
      status: "draft",
      parent_profile: {
        phone: "5551234567",
        address: "123 Main St",
        emergency_contact: "Alex Parent",
        emergency_phone: "5559876543",
      },
    },
  });

  const { container } = await render(OnboardingProfile);

  expect(container.querySelector("[data-testid='profile-phone']").value).toBe(
    "5551234567"
  );
  expect(container.querySelector("[data-testid='profile-next']").disabled).toBe(
    false
  );
});

// 3. Waiver step: GET succeeds — renders content, patches with API version on submit
test("test_waiver_step_patches_acceptance_on_submit", async () => {
  __mockGet.mockResolvedValue({
    data: {
      version: "2026.1",
      content: "Real waiver text from the server.",
      content_hash: "a".repeat(64),
      effective_from: "2026-01-01T00:00:00+00:00",
    },
  });
  __mockPatch.mockResolvedValue({ data: { status: "draft" } });

  const { container } = await render(OnboardingWaiver);

  // Real content must be visible
  const waiverTextEl = container.querySelector("[data-testid='waiver-text']");
  expect(waiverTextEl).not.toBeNull();
  expect(waiverTextEl.textContent).toContain("Real waiver text from the server.");

  const checkbox = container.querySelector("[data-testid='waiver-checkbox']");
  expect(checkbox).not.toBeNull();

  await act(async () => {
    checkbox.click();
  });

  const submitBtn = container.querySelector("[data-testid='waiver-submit']");
  expect(submitBtn).not.toBeNull();
  expect(submitBtn.disabled).toBe(false);

  await act(async () => {
    submitBtn.click();
    await flushPromises();
  });

  // Version comes from the API response, not a hardcoded constant
  expect(__mockPatch).toHaveBeenCalledWith(
    "/onboarding/app-123",
    expect.objectContaining({
      waiver_acceptance: expect.objectContaining({
        version: "2026.1",
        accepted: true,
      }),
    })
  );
});

// 3b. Waiver step: GET fails — shows error notice, submit disabled
test("test_waiver_step_fetch_failure_disables_submit_and_shows_error", async () => {
  __mockGet.mockRejectedValue({ response: { status: 503 } });

  const { container } = await render(OnboardingWaiver);

  // Error notice must be present
  const errorEl = container.querySelector("[data-testid='waiver-fetch-error']");
  expect(errorEl).not.toBeNull();
  expect(errorEl.textContent).toMatch(/could not load/i);

  // Submit must be disabled when text hasn't loaded
  const submitBtn = container.querySelector("[data-testid='waiver-submit']");
  expect(submitBtn).not.toBeNull();
  expect(submitBtn.disabled).toBe(true);

  // PATCH must not have been called
  expect(__mockPatch).not.toHaveBeenCalled();
});

// 3c. Waiver step: empty content from API still blocks acceptance
test("test_waiver_step_empty_content_disables_submit", async () => {
  __mockGet.mockResolvedValue({
    data: {
      version: "2026.1",
      content: "   ",
      content_hash: "a".repeat(64),
      effective_from: "2026-01-01T00:00:00+00:00",
    },
  });

  const { container } = await render(OnboardingWaiver);

  const checkbox = container.querySelector("[data-testid='waiver-checkbox']");
  const submitBtn = container.querySelector("[data-testid='waiver-submit']");

  expect(checkbox).not.toBeNull();
  expect(submitBtn).not.toBeNull();
  expect(checkbox.disabled).toBe(true);
  expect(submitBtn.disabled).toBe(true);
  expect(__mockPatch).not.toHaveBeenCalled();
});

// 3d. Waiver step: version in PATCH comes from API response, not hardcoded string
test("test_waiver_step_version_comes_from_api_response", async () => {
  __mockGet.mockResolvedValue({
    data: {
      version: "2026.99",
      content: "Future waiver text.",
      content_hash: "b".repeat(64),
      effective_from: "2026-07-01T00:00:00+00:00",
    },
  });
  __mockPatch.mockResolvedValue({ data: { status: "draft" } });

  const { container } = await render(OnboardingWaiver);

  const checkbox = container.querySelector("[data-testid='waiver-checkbox']");
  await act(async () => { checkbox.click(); });

  const submitBtn = container.querySelector("[data-testid='waiver-submit']");
  await act(async () => {
    submitBtn.click();
    await flushPromises();
  });

  const patchCall = __mockPatch.mock.calls[0];
  expect(patchCall[1].waiver_acceptance.version).toBe("2026.99");
});

// 4. Session step disables full sessions
test("test_session_step_disables_full_sessions", async () => {
  __mockGet.mockResolvedValue({
    data: [
      {
        id: "sess-open",
        name: "Open Session",
        is_full: false,
        enrolled_count: 3,
        capacity: 10,
      },
      {
        id: "sess-full",
        name: "Full Session",
        is_full: true,
        enrolled_count: 10,
        capacity: 10,
      },
      {
        id: "sess-full-by-count",
        name: "Full by Count",
        is_full: false,
        enrolled_count: 10,
        capacity: 10,
      },
    ],
  });

  const { container } = await render(OnboardingSession);

  const openBtn = container.querySelector("[data-testid='session-option-sess-open']");
  const fullBtn = container.querySelector("[data-testid='session-option-sess-full']");
  const fullByCountBtn = container.querySelector(
    "[data-testid='session-option-sess-full-by-count']"
  );

  expect(openBtn).not.toBeNull();
  expect(fullBtn).not.toBeNull();
  expect(fullByCountBtn).not.toBeNull();

  expect(openBtn.disabled).toBe(false);
  expect(fullBtn.disabled).toBe(true);
  expect(fullByCountBtn.disabled).toBe(true);

  expect(fullBtn.getAttribute("data-full")).toBe("true");
  expect(fullByCountBtn.getAttribute("data-full")).toBe("true");
  expect(openBtn.getAttribute("data-full")).toBe("false");
});

// 5. Review: continue to payment redirects to checkout URL
test("test_review_continue_to_payment_redirects_to_checkout_url", async () => {
  __mockGet.mockResolvedValue({
    data: {
      id: "app-123",
      status: "draft",
      child_name: "Test Child",
      selected_session_id: "sess-1",
    },
  });
  __mockPost.mockResolvedValue({
    data: {
      checkout_url: "https://checkout.stripe.com/pay/abc",
      checkout_session_id: "cs_test_abc",
      status: "checkout_pending",
    },
  });

  let assignedHref = null;
  Object.defineProperty(window, "location", {
    writable: true,
    configurable: true,
    value: {
      search: "",
      get href() { return assignedHref || ""; },
      set href(v) { assignedHref = v; },
    },
  });

  const { container } = await render(OnboardingReview);

  const btn = container.querySelector("[data-testid='checkout-button']");
  expect(btn).not.toBeNull();

  await act(async () => {
    btn.click();
    await flushPromises();
  });

  expect(__mockPost).toHaveBeenCalledWith("/onboarding/app-123/checkout");
  expect(assignedHref).toBe("https://checkout.stripe.com/pay/abc");
});

// 6. Review: 409 session_full routes back to session step
test("test_review_handles_session_full_409", async () => {
  __mockGet.mockResolvedValue({
    data: { id: "app-123", status: "draft", child_name: "Test Child" },
  });
  __mockPost.mockRejectedValue({
    response: {
      status: 409,
      data: { error: "session_full" },
    },
  });

  const { container } = await render(OnboardingReview);

  const btn = container.querySelector("[data-testid='checkout-button']");
  expect(btn).not.toBeNull();

  await act(async () => {
    btn.click();
    await flushPromises();
  });

  expect(__navigateFn).toHaveBeenCalledWith(
    expect.stringContaining("session?reason=session_full")
  );
});

// 7. Status: polls until terminal state, then stops — assert exactly 2 fetch calls
test("test_status_polls_until_terminal_state", async () => {
  jest.useFakeTimers();

  __mockGet
    .mockResolvedValueOnce({ data: { id: "app-123", status: "checkout_pending" } })
    .mockResolvedValueOnce({ data: { id: "app-123", status: "pending_approval" } });

  Object.defineProperty(window, "location", {
    writable: true,
    configurable: true,
    value: { search: "?checkout=success", href: "" },
  });

  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);

  await act(async () => {
    root.render(React.createElement(OnboardingStatus));
  });

  // First poll fires immediately in useEffect
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
    await Promise.resolve();
  });

  // Advance timer to trigger second poll
  await act(async () => {
    jest.advanceTimersByTime(3000);
    await Promise.resolve();
    await Promise.resolve();
    await Promise.resolve();
  });

  jest.useRealTimers();

  expect(__mockGet).toHaveBeenCalledTimes(2);
  expect(__mockGet).toHaveBeenCalledWith("/onboarding/app-123/status");
  expect(container.querySelector("[data-testid='status-pending-approval']")).not.toBeNull();
}, 15000);

// 8. Status: stops at 2-minute cap (40 polls)
test("test_status_stops_at_2_minute_cap", async () => {
  jest.useFakeTimers();

  __mockGet.mockResolvedValue({ data: { id: "app-123", status: "checkout_pending" } });

  Object.defineProperty(window, "location", {
    writable: true,
    configurable: true,
    value: { search: "?checkout=success", href: "" },
  });

  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);

  await act(async () => {
    root.render(React.createElement(OnboardingStatus));
  });

  // Run all 40 poll cycles
  for (let i = 0; i < 41; i++) {
    await act(async () => {
      jest.advanceTimersByTime(3000);
      await Promise.resolve();
      await Promise.resolve();
      await Promise.resolve();
    });
  }

  const countAfter40 = __mockGet.mock.calls.length;
  expect(countAfter40).toBeLessThanOrEqual(41);
  expect(countAfter40).toBeGreaterThanOrEqual(40);

  // Advance further — no more calls
  const countBefore = __mockGet.mock.calls.length;
  await act(async () => {
    jest.advanceTimersByTime(60000);
    await Promise.resolve();
    await Promise.resolve();
  });

  jest.useRealTimers();

  expect(__mockGet.mock.calls.length).toBe(countBefore);
  expect(container.querySelector("[data-testid='status-manual-refresh']")).not.toBeNull();
}, 30000);

// 9. Status: refunded shows waitlist messaging
test("test_status_refunded_shows_waitlist_messaging", async () => {
  __mockGet.mockResolvedValue({ data: { id: "app-123", status: "refunded" } });

  Object.defineProperty(window, "location", {
    writable: true,
    configurable: true,
    value: { search: "?checkout=success", href: "" },
  });

  const { container } = await render(OnboardingStatus);

  const el = container.querySelector("[data-testid='status-refunded']");
  expect(el).not.toBeNull();
  expect(el.textContent.toLowerCase()).toMatch(/waitlist/);
});

// 10. Status: capacity_failed_refund_failed shows contact team messaging
test("test_status_capacity_failed_refund_failed_shows_contact_team", async () => {
  __mockGet.mockResolvedValue({
    data: { id: "app-123", status: "capacity_failed_refund_failed" },
  });

  Object.defineProperty(window, "location", {
    writable: true,
    configurable: true,
    value: { search: "?checkout=success", href: "" },
  });

  const { container } = await render(OnboardingStatus);

  const el = container.querySelector(
    "[data-testid='status-capacity-failed-refund-failed']"
  );
  expect(el).not.toBeNull();
  expect(el.textContent).toMatch(/1 business day/i);

  const contactLink = container.querySelector("[data-testid='status-contact-team']");
  expect(contactLink).not.toBeNull();
});

// 11. No calls to legacy auth routes
test("test_no_calls_to_legacy_auth_routes", async () => {
  const legacyRoutes = [
    "/auth/login",
    "/auth/refresh",
    "/auth/forgot-password",
    "/auth/reset-password",
  ];

  __mockGet.mockResolvedValue({ data: {} });
  __mockPost.mockResolvedValue({ data: { _id: "app-123", status: "draft" } });
  __mockPatch.mockResolvedValue({ data: {} });

  await render(OnboardingStart);
  await act(async () => { await flushPromises(); });
  document.body.innerHTML = "";

  await render(OnboardingProfile);
  await act(async () => { await flushPromises(); });
  document.body.innerHTML = "";

  const allCalls = [
    ...__mockGet.mock.calls.map((c) => c[0]),
    ...__mockPost.mock.calls.map((c) => c[0]),
    ...__mockPatch.mock.calls.map((c) => c[0]),
  ];

  for (const route of legacyRoutes) {
    const found = allCalls.some(
      (url) => typeof url === "string" && url.includes(route)
    );
    expect(found).toBe(false);
  }
});
