import { Card, EmptyState, Overline, Th } from "@/components/ds";
import type { PricingSavedOverride } from "@/lib/api/v2/pricing";
import { formatCents } from "@/lib/money";

const SOURCE_LABEL: Record<PricingSavedOverride["source"], string> = {
  billing_plan: "Billing plan override",
  class_enrollment: "Class fee override",
};

/**
 * Saved price overrides (Settings overhaul PR 11b): amounts saved by the two
 * owner "override price" buttons on a student. No bill reads them. Listed
 * read-only for the owner to review; nothing here turns one into a price.
 */
export function SavedOverridesCard({ overrides }: { overrides: PricingSavedOverride[] }) {
  return (
    <Card p={0} data-testid="pricing-saved-overrides">
      <div className="p-5 pb-3">
        <Overline>Saved price overrides</Overline>
        <p className="mt-1 max-w-2xl text-sm text-rally-muted">
          Prices saved on a student that are never charged. The family pays the class fee.
          Listed for your review only.
        </p>
      </div>
      {overrides.length === 0 ? (
        <EmptyState
          compact
          data-testid="pricing-saved-overrides-empty"
          title="No saved overrides"
          description="Nothing to review."
        />
      ) : (
        <div className="overflow-x-auto border-t border-rally-line">
          <table className="w-full min-w-[640px] text-sm">
            <thead>
              <tr className="border-b border-rally-line">
                <Th>Student</Th>
                <Th>Class or plan</Th>
                <Th align="right">Saved override</Th>
                <Th align="right">Charged now</Th>
              </tr>
            </thead>
            <tbody>
              {overrides.map((row) => (
                <tr
                  key={`${row.source}-${row.enrollment_id}`}
                  data-testid="pricing-saved-override-row"
                  className="border-b border-rally-line last:border-0"
                >
                  <td className="px-4 py-3">
                    <span className="font-semibold text-rally-ink">
                      {row.student_name ?? "Unknown student"}
                    </span>
                    <p className="text-xs text-rally-subtle">
                      {SOURCE_LABEL[row.source]}
                      {row.status ? ` · ${row.status}` : ""}
                    </p>
                  </td>
                  <td className="px-4 py-3">{row.label ?? "—"}</td>
                  <td className="px-4 py-3 text-right font-mono tabular-nums text-rally-muted">
                    {formatCents(row.override_cents)}
                  </td>
                  <td className="px-4 py-3 text-right font-mono tabular-nums text-rally-ink">
                    {row.charged_cents == null ? "—" : formatCents(row.charged_cents)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}
