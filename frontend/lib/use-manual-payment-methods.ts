"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { getAdminPaymentMethods } from "@/lib/api/admin";
import {
  manualMethodOptions,
  resolveManualMethod,
  type ManualMethodOption,
  type ManualPaymentMethod,
} from "@/lib/payment-methods";
import { queryKeys } from "@/lib/query/keys";

/**
 * The one source for every incoming-payment dialog's Method select (row 22).
 *
 * Reads the academy's offline methods and holds the dialog's pick. The pick
 * defaults to the first enabled method (cash for an academy that offers all
 * six, as every dialog did before) and snaps back to it if the list loads
 * without the picked method. While loading, or if the read fails, all six are
 * offered: recording a payment is never blocked by this setting.
 *
 * `enabled` (default true) gates the read itself. Some callers -- MarkPaidDialog
 * and InvoiceDialog -- are mounted unconditionally by their parent tab (only
 * their *visibility* is toggled by a `payment` prop), so without this the read
 * would fire on every page load of that tab instead of only when a dialog is
 * actually in play. Callers that are only ever mounted while open (the
 * Collections RecordPaymentDialog, the student billing dialog) can omit it.
 */
export function useManualPaymentMethods(enabled: boolean = true): {
  options: ManualMethodOption[];
  method: ManualPaymentMethod;
  setMethod: (method: string) => void;
} {
  const query = useQuery({
    queryKey: queryKeys.admin.paymentMethods(),
    queryFn: getAdminPaymentMethods,
    staleTime: 5 * 60_000,
    enabled,
  });
  const [picked, setPicked] = useState<string | null>(null);
  const options = manualMethodOptions(query.data?.manual_methods);
  return { options, method: resolveManualMethod(picked, options), setMethod: setPicked };
}
