"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";

import { Button, Card, EmptyState, Overline, Th } from "@/components/ds";
import {
  formatBillingMonth,
  linkMatchingClasses,
  setClassPlan,
  type PricingClass,
  type PricingPlan,
} from "@/lib/api/v2/pricing";
import { formatCents } from "@/lib/money";
import { queryKeys } from "@/lib/query/keys";

const CUSTOM = "";

const STALE_MESSAGE: Record<NonNullable<PricingClass["stale_reason"]>, string> = {
  archived: "Its plan was archived, so it shows as Custom.",
  price_changed: "Its plan's price changed, so it shows as Custom.",
  plan_removed: "Its plan was removed, so it shows as Custom.",
};

/**
 * "Where each class's price comes from" (Settings overhaul PR 11b).
 *
 * "Charged / month" is the class's own monthly fee, the number every bill
 * uses. Picking a plan is a label: the list only offers plans at exactly
 * that fee (the API refuses any other), so a link can never disagree with
 * what a family pays, and nothing here changes an amount.
 */
export function ClassPricesCard({
  classes,
  plans,
  autoLinkable,
}: {
  classes: PricingClass[];
  plans: PricingPlan[];
  autoLinkable: number;
}) {
  const queryClient = useQueryClient();
  const planById = new Map(plans.map((plan) => [plan.plan_id, plan]));
  const refresh = () => queryClient.invalidateQueries({ queryKey: queryKeys.admin.pricing() });

  const linkMutation = useMutation({
    mutationFn: ({ sessionId, planId }: { sessionId: string; planId: string | null }) =>
      setClassPlan(sessionId, planId),
    onSuccess: () => void refresh(),
  });

  const matchMutation = useMutation({
    mutationFn: linkMatchingClasses,
    onSuccess: () => void refresh(),
  });

  const pendingId = linkMutation.isPending ? linkMutation.variables?.sessionId : null;
  const failedId = linkMutation.isError ? linkMutation.variables?.sessionId : null;

  return (
    <Card p={0} data-testid="pricing-classes">
      <div className="flex flex-wrap items-start justify-between gap-3 p-5 pb-3">
        <div>
          <Overline>Where each class&apos;s price comes from</Overline>
          <p className="mt-1 max-w-2xl text-sm text-rally-muted">
            Every bill uses the class&apos;s own monthly fee. Linking a class to a plan at
            the same price never changes what anyone pays.
          </p>
        </div>
        <Button
          variant="secondary"
          size="sm"
          disabled={autoLinkable === 0 || matchMutation.isPending}
          onClick={() => matchMutation.mutate()}
          data-testid="pricing-link-matching"
        >
          {matchMutation.isPending ? "Linking..." : "Link matching classes"}
        </Button>
      </div>
      <p className="px-5 pb-3 text-xs text-rally-subtle" data-testid="pricing-link-matching-help">
        {matchMutation.isSuccess
          ? `Linked ${matchMutation.data.linked} ${
              matchMutation.data.linked === 1 ? "class" : "classes"
            }. Classes with no plan, or more than one plan, at their fee stay Custom.`
          : autoLinkable > 0
            ? `${autoLinkable} ${
                autoLinkable === 1 ? "class has" : "classes have"
              } exactly one plan at the same price and can be linked.`
            : "Links a class only when exactly one plan has its price. Others stay Custom."}
      </p>
      {matchMutation.isError && (
        <p role="alert" className="px-5 pb-3 text-sm text-status-red-800">
          Could not link classes. Try again.
        </p>
      )}

      {classes.length === 0 ? (
        <EmptyState
          data-testid="pricing-classes-empty"
          title="No classes yet"
          description="Classes you add on Sessions show here with the fee they are charged."
        />
      ) : (
        <div className="overflow-x-auto border-t border-rally-line">
          <table className="w-full min-w-[640px] text-sm">
            <thead>
              <tr className="border-b border-rally-line">
                <Th>Class</Th>
                <Th>Plan</Th>
                <Th align="right">Charged / month</Th>
                <Th align="right">Students</Th>
              </tr>
            </thead>
            <tbody>
              {classes.map((cls) => {
                const options = cls.matching_plan_ids
                  .map((id) => planById.get(id))
                  .filter((plan): plan is PricingPlan => Boolean(plan));
                const selectId = `pricing-plan-${cls.session_id}`;
                return (
                  <tr
                    key={cls.session_id}
                    data-testid="pricing-class-row"
                    className="border-b border-rally-line last:border-0"
                  >
                    <td className="px-4 py-3 font-semibold text-rally-ink">{cls.title}</td>
                    <td className="px-4 py-3">
                      <label htmlFor={selectId} className="sr-only">
                        Plan for {cls.title}
                      </label>
                      <select
                        id={selectId}
                        data-testid="pricing-class-plan"
                        value={cls.plan_id ?? CUSTOM}
                        disabled={pendingId === cls.session_id}
                        onChange={(event) =>
                          linkMutation.mutate({
                            sessionId: cls.session_id,
                            planId: event.target.value || null,
                          })
                        }
                        className="h-9 w-full max-w-[16rem] rounded-md border border-rally-line bg-white px-2 text-sm outline-none focus:border-blue-500"
                      >
                        <option value={CUSTOM}>Custom</option>
                        {options.map((plan) => (
                          <option key={plan.plan_id} value={plan.plan_id}>
                            {plan.name}
                          </option>
                        ))}
                      </select>
                      {options.length === 0 && (
                        <p className="mt-1 text-xs text-rally-subtle">No plan has this price.</p>
                      )}
                      {cls.stale_link && (
                        <p className="mt-1 text-xs text-status-amber-800">
                          {STALE_MESSAGE[cls.stale_reason ?? "price_changed"]}
                        </p>
                      )}
                      {failedId === cls.session_id && (
                        <p role="alert" className="mt-1 text-xs text-status-red-800">
                          Could not save. Try again.
                        </p>
                      )}
                    </td>
                    <td
                      className="px-4 py-3 text-right font-mono tabular-nums text-rally-ink"
                      data-testid="pricing-class-charged"
                    >
                      {cls.fee_set ? formatCents(cls.charged_cents) : "No fee set"}
                      {cls.scheduled_cents != null && cls.scheduled_from && (
                        <p
                          className="font-sans text-xs text-status-amber-800"
                          data-testid="pricing-class-scheduled"
                        >
                          Scheduled: {formatCents(cls.scheduled_cents)} from{" "}
                          {formatBillingMonth(cls.scheduled_from, { year: true })}
                        </p>
                      )}
                    </td>
                    <td className="px-4 py-3 text-right font-mono tabular-nums">
                      {cls.students}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}
