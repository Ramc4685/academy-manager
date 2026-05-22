/**
 * v2 payouts client (review shell).
 *
 * Wave 5 Agent A still owns the backend work for occurrence-based
 * payout persistence and a per-payout breakdown endpoint. Until those
 * land, this module exposes:
 *
 *   - `listAdminPayouts()` — real, calls the existing v2 BFF
 *     `/admin/finance/payouts`.
 *   - `getAdminPayoutReview()` — MOCK. Returns a deterministic
 *     breakdown derived from the payout summary so the review UX
 *     can render today. Replace this with a real fetch once
 *     `/admin/finance/payouts/{payout_id}` ships.
 *
 * No SaaS page should call `/api/*` legacy routes.
 */
import { listPayouts, type AdminPayoutView } from "../admin";

export type { AdminPayoutView } from "../admin";

export async function listAdminPayouts() {
  return listPayouts();
}

export interface PayoutOccurrenceLine {
  occurrence_label: string; // human-readable, never a raw id
  session_title: string;
  occurred_at: string; // ISO 8601
  students_attended: number;
  rate_cents: number;
  amount_cents: number;
}

export interface AdminPayoutReview {
  payout_id: string;
  coach_id: string;
  amount_cents: number;
  period_start: string;
  period_end: string;
  paid_at: string | null;
  total_occurrences: number;
  total_students_attended: number;
  lines: PayoutOccurrenceLine[];
  mock: true;
}

/**
 * MOCK breakdown.
 *
 * TODO(wave5-A): replace with `apiFetch<AdminPayoutReview>(
 *   `/admin/finance/payouts/${payoutId}`)` once Agent A's
 * occurrence-based payout endpoints ship. Today the BFF only returns
 * the rolled-up amount — we synthesise a stable line set so the review
 * page can be navigated, screenshotted, and styled.
 */
export async function getAdminPayoutReview(
  payoutId: string,
  summary: AdminPayoutView,
): Promise<AdminPayoutReview> {
  const occurrenceCount = synthesiseOccurrenceCount(summary);
  const lines = synthesiseLines(summary, occurrenceCount);
  const totalStudents = lines.reduce((acc, line) => acc + line.students_attended, 0);
  return {
    payout_id: payoutId,
    coach_id: summary.coach_id,
    amount_cents: summary.amount_cents,
    period_start: summary.period_start,
    period_end: summary.period_end,
    paid_at: summary.paid_at,
    total_occurrences: lines.length,
    total_students_attended: totalStudents,
    lines,
    mock: true,
  };
}

function synthesiseOccurrenceCount(summary: AdminPayoutView): number {
  // Aim for roughly $50/occurrence at common indie-academy rates, with
  // a floor of 1 and a ceiling of 32. Deterministic given the amount.
  const guess = Math.max(1, Math.round(summary.amount_cents / 5000));
  return Math.min(guess, 32);
}

function synthesiseLines(
  summary: AdminPayoutView,
  count: number,
): PayoutOccurrenceLine[] {
  if (count === 0) return [];
  const start = new Date(summary.period_start);
  const end = new Date(summary.period_end);
  const span = Math.max(end.getTime() - start.getTime(), 0);
  const stepMs = span / Math.max(count - 1, 1);
  const ratePerLine = Math.round(summary.amount_cents / count);
  return Array.from({ length: count }, (_, i) => {
    const t = new Date(start.getTime() + stepMs * i);
    return {
      occurrence_label: `Session #${i + 1}`,
      session_title: `Coaching block ${String(i + 1).padStart(2, "0")}`,
      occurred_at: t.toISOString(),
      students_attended: 4 + ((i * 3) % 5), // 4..8, deterministic
      rate_cents: ratePerLine,
      amount_cents: ratePerLine,
    };
  });
}
