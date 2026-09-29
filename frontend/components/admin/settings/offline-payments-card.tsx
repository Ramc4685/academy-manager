"use client";

import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { getAdminPaymentMethods, updateAdminPaymentMethods } from "@/lib/api/admin";
import {
  MANUAL_PAYMENT_METHODS,
  manualMethodOptions,
  type ManualPaymentMethod,
} from "@/lib/payment-methods";
import { queryKeys } from "@/lib/query/keys";
import { Button } from "@/components/ds/button";
import { Card } from "@/components/ds/card";
import { Overline } from "@/components/ds/typography";
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
export function OfflinePaymentsCard() {
  const queryClient = useQueryClient();
  const query = useQuery({
    queryKey: queryKeys.admin.paymentMethods(),
    queryFn: getAdminPaymentMethods,
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
        </>
      )}
    </Card>
  );
}
