/**
 * Phase 5 Slice 7 — coach today screen.
 *
 * No @testing-library/react in this repo, so we drive the component via
 * react-dom/client into a JSDOM container and assert on rendered HTML.
 */
// React 19's `act` requires this flag to be set before rendering.
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

import React, { act } from "react";
import { createRoot } from "react-dom/client";

// CRA 5's jest does not resolve react-router-dom v7 package "exports". Stub the
// pieces we use to keep the test framework-agnostic.
jest.mock(
  "react-router-dom",
  () => {
    const React2 = require("react");
    return {
      __esModule: true,
      MemoryRouter: ({ children }) => React2.createElement(React2.Fragment, null, children),
      Link: ({ to, children, ...rest }) =>
        React2.createElement("a", { href: typeof to === "string" ? to : "#", ...rest }, children),
    };
  },
  { virtual: true }
);

// Mock the API client. CRA jest sets jsdom as the default environment.
jest.mock("../../lib/api", () => {
  const mockGet = jest.fn();
  return {
    __esModule: true,
    api: { get: mockGet },
    __mockGet: mockGet,
  };
});

// eslint-disable-next-line import/first
import { __mockGet } from "../../lib/api";
// eslint-disable-next-line import/first
import { MemoryRouter } from "react-router-dom";
// eslint-disable-next-line import/first
import CoachToday from "./CoachToday";

function flushPromises() {
  return new Promise((resolve) => setTimeout(resolve, 0));
}

async function renderWithData(data) {
  __mockGet.mockReset();
  __mockGet.mockResolvedValue({ data });
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  await act(async () => {
    root.render(
      <MemoryRouter>
        <CoachToday />
      </MemoryRouter>
    );
  });
  // Allow the queued .then in the effect to settle and re-render.
  await act(async () => {
    await flushPromises();
  });
  return { container, root };
}

const baseSession = {
  id: "sess-1",
  name: "Beginner Badminton",
  start_time: "16:00",
  end_time: "17:30",
  roster: [],
  shortcuts: {
    attendance_path: "/coach/sessions/sess-1/attendance",
    lesson_plan_path: "/coach/sessions/sess-1/plan",
    progress_note_path: "/coach/sessions/sess-1/progress",
  },
};

test("renders session cards from fetched data", async () => {
  const { container } = await renderWithData({
    date: "2026-05-15",
    timezone: "America/Chicago",
    sessions: [baseSession],
  });
  expect(container.querySelector('[data-testid="session-card-sess-1"]')).not.toBeNull();
  expect(container.textContent).toContain("Beginner Badminton");
  expect(container.textContent).toContain("16:00");
});

test("empty state when API returns sessions: []", async () => {
  const { container } = await renderWithData({
    date: "2026-05-15",
    timezone: "America/Chicago",
    sessions: [],
  });
  expect(container.querySelector('[data-testid="coach-today-empty"]')).not.toBeNull();
  expect(container.textContent).toContain("No sessions today");
});

test("roster row shows medical indicator when flag is true", async () => {
  const { container } = await renderWithData({
    date: "2026-05-15",
    timezone: "America/Chicago",
    sessions: [
      {
        ...baseSession,
        roster: [
          {
            student_id: "stu-1",
            name: "Alice One",
            has_medical_notes: true,
            is_paused: false,
            attendance_status: null,
          },
        ],
      },
    ],
  });
  expect(container.querySelector('[data-testid="roster-stu-1-medical"]')).not.toBeNull();
});

test("does not render any payment-related text", async () => {
  const { container } = await renderWithData({
    date: "2026-05-15",
    timezone: "America/Chicago",
    sessions: [
      {
        ...baseSession,
        roster: [
          {
            student_id: "stu-1",
            name: "Alice One",
            has_medical_notes: false,
            is_paused: false,
            attendance_status: "present",
          },
        ],
      },
    ],
  });
  const text = container.textContent.toLowerCase();
  expect(text).not.toMatch(/unpaid/);
  expect(text).not.toMatch(/\bpaid\b/);
  expect(text).not.toContain("$");
  expect(text).not.toContain("overdue");
});

test("does not auto-poll: fetch called exactly once on mount", async () => {
  __mockGet.mockReset();
  __mockGet.mockResolvedValue({
    data: { date: "2026-05-15", timezone: "America/Chicago", sessions: [] },
  });
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  await act(async () => {
    root.render(
      <MemoryRouter>
        <CoachToday />
      </MemoryRouter>
    );
  });
  await act(async () => {
    await flushPromises();
  });
  // Wait a short while to ensure no interval re-fires.
  await act(async () => {
    await new Promise((r) => setTimeout(r, 60));
  });
  expect(__mockGet).toHaveBeenCalledTimes(1);
  expect(__mockGet).toHaveBeenCalledWith("/coach/today");
});
