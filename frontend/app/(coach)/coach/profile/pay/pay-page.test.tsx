import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

import type { CoachPay } from "@/lib/api/coach";
import { queryKeys } from "@/lib/query/keys";

vi.mock("next/link", () => ({
  default: ({ href, children, ...rest }: { href: string; children: React.ReactNode }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));

import CoachPayPage from "./page";
import { formatTaught } from "./format-taught";

const BASE: CoachPay = {
  month: "2026-11",
  month_label: "November 2026",
  classes_taught: 2,
  minutes_taught: 120,
  classes: [
    {
      occurrence_id: "o2",
      start_at: "2026-11-24T23:30:00Z",
      class_name: "Tuesday Intermediate",
      minutes: 60,
      role: "cover",
    },
    {
      occurrence_id: "o1",
      start_at: "2026-11-21T15:00:00Z",
      class_name: "Junior Beginners",
      minutes: 60,
      role: "assistant",
    },
  ],
  payslip: null,
  academy_contact: { name: "Demo Academy", phone: "(309) 555-0142", email: "hello@example.com" },
};

function render(pay: Partial<CoachPay>) {
  const client = new QueryClient();
  client.setQueryData(queryKeys.coach.academy(), {
    name: "Demo Academy",
    logo_url: null,
    brand_color: null,
    timezone: "America/Chicago",
  });
  client.setQueryData(queryKeys.coach.pay("current"), { ...BASE, ...pay });
  return renderToStaticMarkup(
    <QueryClientProvider client={client}>
      <CoachPayPage />
    </QueryClientProvider>,
  );
}

describe("coach Pay page", () => {
  it("lists classes taught with role words and says no payslip without hinting at a draft", () => {
    const html = render({});
    expect(html).toContain("Tuesday Intermediate · 60 min");
    expect(html).toContain("Cover");
    expect(html).toContain("Assistant");
    expect(html).toContain("2 h");
    expect(html).toContain("No payslip for November yet. It appears here once the academy approves it.");
    expect(html).not.toMatch(/draft|rate|session|occurrence/i);
    expect(html).toContain('aria-label="Next month"');
    expect(html).toContain("Questions about your pay?");
    expect(html).toContain('href="tel:');
  });

  it("shows an approved payslip with its approval date", () => {
    const html = render({
      payslip: {
        period_start: "2026-11-01",
        period_end: "2026-11-30",
        status: "approved",
        total_cents: 38000,
        currency: "usd",
        approved_on: "2026-12-02",
        paid_on: null,
        paid_method_label: null,
        paid_amount_cents: null,
      },
    });
    expect(html).toContain("APPROVED");
    expect(html).toContain("$380.00");
    expect(html).toContain("Approved Dec 2. Not paid yet.");
    expect(html).toContain("Nov 1 – Nov 30");
  });

  it("shows a paid payslip and flags a paid amount that differs from the total", () => {
    const html = render({
      payslip: {
        period_start: "2026-10-01",
        period_end: "2026-10-31",
        status: "paid",
        total_cents: 42000,
        currency: "usd",
        approved_on: "2026-11-02",
        paid_on: "2026-11-03",
        paid_method_label: "bank transfer",
        paid_amount_cents: 40000,
      },
    });
    expect(html).toContain("PAID");
    expect(html).toContain("Paid Nov 3 by bank transfer.");
    expect(html).toContain("Payslip total $420.00, paid $400.00. Ask the academy about the difference.");
  });

  it("an empty month says what happens next; no contact falls back to the owner", () => {
    const html = render({
      classes: [],
      classes_taught: 0,
      minutes_taught: 0,
      academy_contact: { name: "Demo Academy", phone: null, email: null },
    });
    expect(html).toContain("No classes taught in November");
    expect(html).toContain("0 min");
    expect(html).toContain("Questions about your pay? Ask the academy owner.");
  });

  it("formats time taught", () => {
    expect(formatTaught(570)).toBe("9 h 30 min");
    expect(formatTaught(45)).toBe("45 min");
    expect(formatTaught(120)).toBe("2 h");
  });
});
