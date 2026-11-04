"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { Button, Card, FormField, Modal, Overline, Skeleton, useToast } from "@/components/ds";
import {
  getPlatformBillingIdentity,
  setPlatformBillingIdentity,
  type BillingIdentity,
} from "@/lib/api/platform";
import { queryKeys } from "@/lib/query/keys";

/**
 * Platform view of an academy's billing identity (Settings overhaul Phase 1
 * PR 3 / PR #987): invoice-number prefix and currency.
 *
 * Currency is always USD — there is nothing to fetch or change there. The
 * invoice prefix can be changed here by a platform admin until the academy's
 * first numbered invoice, after which the endpoint reports it locked and
 * this card goes read-only with the reason.
 */
export function BillingIdentityCard({
  academyId,
  canEdit,
}: {
  academyId: string;
  canEdit: boolean;
}) {
  const [editing, setEditing] = useState(false);
  const identityQuery = useQuery({
    queryKey: queryKeys.platform.tenantBillingIdentity(academyId),
    queryFn: () => getPlatformBillingIdentity(academyId),
    retry: false,
    // Platform-admin only on the API: support gets a 404, so don't ask.
    enabled: canEdit,
  });

  if (!canEdit) return null;

  return (
    <Card p={20}>
      <div data-testid="platform-billing-identity">
        <Overline>Billing identity</Overline>
        {identityQuery.isPending && (
          <div className="mt-3">
            <Skeleton variant="line" lines={2} />
          </div>
        )}
        {identityQuery.isError && (
          <p className="mt-3 text-sm text-rally-subtle">
            The billing identity could not be loaded.
          </p>
        )}
        {identityQuery.data && (
          <>
            <dl className="mt-3 grid grid-cols-2 gap-4">
              <div>
                <dt className="text-xs font-semibold uppercase tracking-wide text-rally-subtle">
                  Invoice prefix
                </dt>
                <dd
                  className="mt-0.5 font-mono text-sm font-medium text-rally-ink"
                  data-testid="billing-identity-prefix"
                >
                  {identityQuery.data.invoice_prefix ?? "Not set"}
                </dd>
              </div>
              <div>
                <dt className="text-xs font-semibold uppercase tracking-wide text-rally-subtle">
                  Currency
                </dt>
                <dd className="mt-0.5 text-sm font-medium text-rally-ink">USD</dd>
              </div>
            </dl>
            {identityQuery.data.locked ? (
              <p className="mt-3 text-sm text-rally-subtle" data-testid="billing-identity-locked">
                Locked: this academy has a numbered invoice, so its prefix can no longer change.
              </p>
            ) : (
              <div className="mt-4">
                <Button variant="secondary" size="sm" onClick={() => setEditing(true)}>
                  Change prefix
                </Button>
              </div>
            )}
          </>
        )}
      </div>
      {editing && identityQuery.data && (
        <EditBillingIdentityDialog identity={identityQuery.data} onClose={() => setEditing(false)} />
      )}
    </Card>
  );
}

function EditBillingIdentityDialog({
  identity,
  onClose,
}: {
  identity: BillingIdentity;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const { toast } = useToast();
  const [prefix, setPrefix] = useState(identity.invoice_prefix ?? "");
  const [reason, setReason] = useState("");
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const mutation = useMutation({
    mutationFn: () =>
      setPlatformBillingIdentity(identity.academy_id, {
        invoice_prefix: prefix.trim(),
        reason: reason.trim() || undefined,
      }),
    onSuccess: (updated) => {
      queryClient.setQueryData(
        queryKeys.platform.tenantBillingIdentity(identity.academy_id),
        updated,
      );
      toast({ kind: "success", title: "Invoice prefix updated" });
      onClose();
    },
    onError: (err: Error) => {
      // Surface the endpoint's own message (format, uniqueness, locked).
      setErrorMessage(err.message);
    },
  });

  return (
    <Modal
      open
      onClose={onClose}
      title="Change invoice prefix"
      dismissable={!mutation.isPending}
      footer={
        <div className="flex justify-end gap-2">
          <Button variant="ghost" size="sm" onClick={onClose} disabled={mutation.isPending}>
            Cancel
          </Button>
          <Button
            size="sm"
            disabled={!prefix.trim() || mutation.isPending}
            onClick={() => mutation.mutate()}
          >
            {mutation.isPending ? "Saving…" : "Save prefix"}
          </Button>
        </div>
      }
    >
      <div className="space-y-3">
        <FormField
          label="Invoice prefix"
          htmlFor="billing-identity-prefix-input"
          hint="2-6 letters and digits, starting with a letter. Unique across academies."
          required
        >
          <input
            id="billing-identity-prefix-input"
            className={INPUT_CLASS}
            value={prefix}
            onChange={(e) => setPrefix(e.target.value)}
          />
        </FormField>
        <FormField label="Reason" htmlFor="billing-identity-reason" hint="Kept in the audit trail">
          <input
            id="billing-identity-reason"
            className={INPUT_CLASS}
            value={reason}
            onChange={(e) => setReason(e.target.value)}
          />
        </FormField>
        {errorMessage && (
          <p className="text-sm font-medium text-red-700" data-testid="billing-identity-error">
            {errorMessage}
          </p>
        )}
      </div>
    </Modal>
  );
}

const INPUT_CLASS =
  "w-full rounded-lg border border-rally-line bg-white px-3 py-2 text-sm text-rally-ink outline-none focus:border-rally-cobalt";
