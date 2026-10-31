"use client";

import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  getAdminPaymentMethods,
  getSelfServicePolicy,
  updateAdminPaymentMethods,
  updateSelfServicePolicy,
} from "@/lib/api/admin";
import {
  MANUAL_PAYMENT_METHODS,
  manualMethodOptions,
  type ManualPaymentMethod,
} from "@/lib/payment-methods";
import { queryKeys } from "@/lib/query/keys";
import { Button } from "@/components/ds/button";
import { Card } from "@/components/ds/card";
import { Overline } from "@/components/ds/typography";
import { useIsOwner } from "@/components/admin/owner-context";
import { useReportSettingsDirty } from "@/components/admin/settings/settings-dirty-context";

/** The picked methods in canonical order; the save payload and the dirty check. */
export function orderedSelection(selected: ReadonlySet<string>): ManualPaymentMethod[] {
  return MANUAL_PAYMENT_METHODS.filter((method) => selected.has(method));
}

/**
 * Settings → Billing rules → Offline payments (row 22). Owner only, like the
 * panel it sits in; the save is audited server side.
 *
 * Chooses which offline methods the Record payment dialogs list. The first
 * ticked method is the dialogs' default. Recording is never blocked by it.
 */
const PAYMENT_INSTRUCTIONS_MAX_LENGTH = 1000;

export function OfflinePaymentsCard() {
  const queryClient = useQueryClient();
  const isOwner = useIsOwner();
  const query = useQuery({
    queryKey: queryKeys.admin.paymentMethods(),
    queryFn: getAdminPaymentMethods,
  });
  // Settings overhaul Phase 1 Lane C item 5: owner-edited plain text for
  // manual payers, saved next to the offline payment methods it lives beside
  // on the self-service policy record.
  const instructionsQuery = useQuery({
    queryKey: queryKeys.admin.selfServicePolicy(),
    queryFn: getSelfServicePolicy,
  });
  const [instructions, setInstructions] = useState("");
  const [instructionsSaved, setInstructionsSaved] = useState(false);
  useEffect(() => {
    if (instructionsQuery.data) setInstructions(instructionsQuery.data.payment_instructions ?? "");
  }, [instructionsQuery.data]);
  const instructionsDirty =
    Boolean(instructionsQuery.data) &&
    instructions !== (instructionsQuery.data?.payment_instructions ?? "");
  const instructionsTooLong = instructions.length > PAYMENT_INSTRUCTIONS_MAX_LENGTH;
  useReportSettingsDirty("payment-instructions", instructionsDirty);
  const instructionsMutation = useMutation({
    mutationFn: () => updateSelfServicePolicy({ payment_instructions: instructions }),
    onSuccess: (data) => {
      queryClient.setQueryData(queryKeys.admin.selfServicePolicy(), data);
      setInstructionsSaved(true);
    },
  });
  const loaded = useMemo(
    () => manualMethodOptions(query.data?.manual_methods).map((option) => option.value),
    [query.data],
  );
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    if (query.data) setSelected(new Set(loaded));
  }, [query.data, loaded]);

  const picked = orderedSelection(selected);
  const dirty = Boolean(query.data) && picked.join(",") !== loaded.join(",");
  const empty = picked.length === 0;
  useReportSettingsDirty("offline-payments", dirty);

  const mutation = useMutation({
    mutationFn: () => updateAdminPaymentMethods({ manual_methods: picked }),
    onSuccess: (data) => {
      queryClient.setQueryData(queryKeys.admin.paymentMethods(), data);
      // The Payments tab lists the same methods off the gateway read.
      void queryClient.invalidateQueries({ queryKey: queryKeys.admin.gateway() });
      setSaved(true);
    },
  });

  return (
    <Card p={24} className="max-w-3xl" data-testid="offline-payments-card">
      <Overline>Offline payments</Overline>
      <p className="mt-2 text-sm text-rally-muted">
        The methods staff can pick when they record a payment made outside Stripe. The first
        ticked method is selected by default.
      </p>
      {query.isError && (
        <p className="mt-3 text-sm text-red-700" role="alert">
          Could not load the offline payment methods.
        </p>
      )}
      {query.data && (
        <>
          <fieldset className="mt-4 grid gap-2 sm:grid-cols-3">
            <legend className="sr-only">Offline payment methods</legend>
            {manualMethodOptions(MANUAL_PAYMENT_METHODS).map((option) => (
              <label
                key={option.value}
                className="flex items-center gap-2 text-sm font-medium text-rally-ink"
              >
                <input
                  type="checkbox"
                  checked={selected.has(option.value)}
                  onChange={(event) => {
                    setSaved(false);
                    setSelected((prev) => {
                      const next = new Set(prev);
                      if (event.target.checked) next.add(option.value);
                      else next.delete(option.value);
                      return next;
                    });
                  }}
                  data-testid={`offline-payments-method-${option.value}`}
                />
                {option.label}
              </label>
            ))}
          </fieldset>
          {empty && (
            <p className="mt-2 text-xs text-red-700" role="alert" data-testid="offline-payments-empty">
              Keep at least one method.
            </p>
          )}
          <div className="mt-4 flex flex-wrap items-center gap-3">
            <Button
              variant={dirty && !empty ? "volt" : "secondary"}
              size="sm"
              disabled={!dirty || empty || mutation.isPending}
              onClick={() => mutation.mutate()}
              data-testid="offline-payments-save"
            >
              {mutation.isPending ? "Saving…" : "Save offline payments"}
            </Button>
            {saved && !mutation.isPending && !dirty && (
              <span className="text-sm text-rally-muted" data-testid="offline-payments-saved">
                Saved.
              </span>
            )}
            {mutation.isError && (
              <span className="text-sm text-red-700" role="alert">
                {mutation.error instanceof Error
                  ? mutation.error.message
                  : "Could not save the offline payment methods."}
              </span>
            )}
          </div>

          <div className="mt-8">
            <Overline>Payment instructions</Overline>
          </div>
          <p className="mt-2 text-sm text-rally-muted">
            Shown to parents on their invoice/pay screen and in the invoice email, for families
            paying outside Stripe. Leave blank to show nothing.
          </p>
          <p className="mt-2 text-xs text-rally-muted" data-testid="payment-instructions-owner-note">
            {isOwner
              ? "Changes are recorded in the billing audit log."
              : "Only the academy owner can change payment instructions."}
          </p>
          <label className="mt-3 block">
            <span className="sr-only">Payment instructions</span>
            <textarea
              className="min-h-[96px] w-full rounded-md border border-rally-line bg-white p-3 text-sm outline-none focus:border-blue-500 disabled:cursor-not-allowed disabled:bg-rally-line/40 disabled:text-rally-muted"
              value={instructions}
              maxLength={PAYMENT_INSTRUCTIONS_MAX_LENGTH}
              disabled={!isOwner}
              onChange={(e) => {
                setInstructionsSaved(false);
                setInstructions(e.target.value);
              }}
              placeholder="e.g. Pay by Venmo @academy-name, then email a screenshot to office@academy.com."
              data-testid="payment-instructions-textarea"
            />
          </label>
          <p
            className={`mt-1 text-xs ${instructionsTooLong ? "text-red-700" : "text-rally-muted"}`}
            role={instructionsTooLong ? "alert" : undefined}
          >
            {instructions.length}/{PAYMENT_INSTRUCTIONS_MAX_LENGTH}
            {instructionsTooLong ? " — too long." : ""}
          </p>
          <div className="mt-3 flex flex-wrap items-center gap-3">
            <Button
              variant={instructionsDirty && !instructionsTooLong ? "volt" : "secondary"}
              size="sm"
              disabled={
                !isOwner || !instructionsDirty || instructionsTooLong || instructionsMutation.isPending
              }
              onClick={() => instructionsMutation.mutate()}
              data-testid="payment-instructions-save"
            >
              {instructionsMutation.isPending ? "Saving…" : "Save payment instructions"}
            </Button>
            {instructionsSaved && !instructionsMutation.isPending && !instructionsDirty && (
              <span className="text-sm text-rally-muted">Saved.</span>
            )}
            {instructionsMutation.isError && (
              <span className="text-sm text-red-700" role="alert">
                {instructionsMutation.error instanceof Error
                  ? instructionsMutation.error.message
                  : "Could not save the payment instructions."}
              </span>
            )}
          </div>
        </>
      )}
    </Card>
  );
}
