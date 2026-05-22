/**
 * v2 reporting client (snapshot placeholders).
 *
 * Wave 5 Agent A is building the reporting read models — pre-computed
 * snapshots for retention, attendance trends, dues funnel, etc. Until
 * those endpoints land, this module exposes typed shapes + a clearly
 * labelled mock so the dashboard cards can render today.
 *
 * Swap the implementations below for real `apiFetch` calls once Agent
 * A's routes ship (`/admin/reports/snapshots/*`).
 */

export interface ReportSnapshotCard {
  key: string;
  label: string; // human-readable card title
  value: string; // formatted metric (e.g. "92%", "$4,500")
  delta?: string | null; // formatted change vs prior period
  trend?: "up" | "down" | "flat";
  description: string;
  mock: true;
}

/**
 * MOCK snapshot cards.
 *
 * TODO(wave5-A): replace with
 *   `apiFetch<ReportSnapshotsResponse>('/admin/reports/snapshots')`.
 * Card keys here are stable so the dashboard layout doesn't shift when
 * the real data lands.
 */
export async function listReportSnapshots(): Promise<ReportSnapshotCard[]> {
  return [
    {
      key: "active_students",
      label: "Active students",
      value: "—",
      delta: null,
      trend: "flat",
      description:
        "Students with at least one active enrollment this period. Backed by the directory read model.",
      mock: true,
    },
    {
      key: "attendance_rate",
      label: "Attendance rate (30d)",
      value: "—",
      delta: null,
      trend: "flat",
      description:
        "Share of expected attendance marks recorded as present. Backed by the occurrence-based attendance read model.",
      mock: true,
    },
    {
      key: "dues_collected",
      label: "Dues collected (MTD)",
      value: "—",
      delta: null,
      trend: "flat",
      description:
        "Dollars collected this month relative to invoiced. Backed by the billing ledger read model.",
      mock: true,
    },
    {
      key: "pending_waivers",
      label: "Pending waivers",
      value: "—",
      delta: null,
      trend: "flat",
      description:
        "Students whose latest waiver is unsigned or expired. Backed by the onboarding read model.",
      mock: true,
    },
  ];
}
