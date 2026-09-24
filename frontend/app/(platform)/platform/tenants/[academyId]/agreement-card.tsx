"use client";

import { useState } from "react";
import { useMutation } from "@tanstack/react-query";

import { Button, Card, FormField, Modal, Overline, useToast } from "@/components/ds";
import { recordPlatformAgreementAcceptance, type PlatformTenant } from "@/lib/api/platform";
import {
  formatAcceptedAt,
  formatFeeModel,
  hasAcceptedAgreement,
  replacedAcceptanceWarning,
} from "@/lib/platform-agreement";

/**
 * Fee model and platform agreement acceptance for one academy (roadmap L9c).
 *
 * Read from the tenant record. A platform admin records the acceptance
 * (version + academy signatory); support sees it read-only. Activation is
 * refused by the API until an acceptance is on record. The agreement text is
 * an owner/legal input (docs/platform/platform-agreement.md, DRAFT).
 */
export function AgreementCard({
  tenant,
  canEdit,
  onDone,
}: {
  tenant: PlatformTenant;
  canEdit: boolean;
  onDone: (tenant: PlatformTenant) => void;
}) {
  const [recording, setRecording] = useState(false);
  const accepted = hasAcceptedAgreement(tenant);
  const canRecord = canEdit && tenant.status !== "cancelled";

  return (
    <Card p={20}>
      <div data-testid="platform-tenant-agreement">
        <Overline>Fee model and platform agreement</Overline>
        <dl className="mt-3 grid grid-cols-2 gap-4 sm:grid-cols-4">
          <AgreementStat label="Fee model" value={formatFeeModel(tenant.fee_model)} />
          <AgreementStat
            label="Agreement version"
            value={tenant.platform_agreement_version ?? "Not accepted"}
          />
          <AgreementStat
            label="Accepted on"
            value={formatAcceptedAt(tenant.platform_agreement_accepted_at)}
          />
          <AgreementStat label="Accepted by" value={tenant.platform_agreement_accepted_by ?? "—"} />
        </dl>
        {!accepted && tenant.status === "provisioning" && (
          <p className="mt-4 rounded-lg bg-status-amber-50 px-3 py-2 text-sm text-status-amber-800">
            Record the academy&apos;s platform agreement acceptance before activating.
          </p>
        )}
        {canRecord && (
          <div className="mt-4">
            <Button variant="secondary" size="sm" onClick={() => setRecording(true)}>
              {accepted ? "Record a new acceptance" : "Record acceptance"}
            </Button>
          </div>
        )}
      </div>
      {recording && (
        <RecordAcceptanceDialog
          tenant={tenant}
          onDone={onDone}
          onClose={() => setRecording(false)}
        />
      )}
    </Card>
  );
}

function AgreementStat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-xs font-semibold uppercase tracking-wide text-rally-subtle">{label}</dt>
      <dd className="mt-0.5 break-words text-sm font-medium text-rally-ink">{value}</dd>
    </div>
  );
}

function RecordAcceptanceDialog({
  tenant,
  onDone,
  onClose,
}: {
  tenant: PlatformTenant;
  onDone: (tenant: PlatformTenant) => void;
  onClose: () => void;
}) {
  const { toast } = useToast();
  const [version, setVersion] = useState(tenant.platform_agreement_version ?? "");
  const [acceptedBy, setAcceptedBy] = useState("");
  // Replacing a recorded acceptance overwrites the legal record on the tenant
  // (the old one survives only in the audit log), so it needs an explicit
  // confirmation on top of the form.
  const replacing = replacedAcceptanceWarning(tenant);
  const [confirmedReplace, setConfirmedReplace] = useState(false);
  const valid =
    version.trim().length > 0 &&
    acceptedBy.trim().length > 0 &&
    (replacing === null || confirmedReplace);

  const mutation = useMutation({
    mutationFn: () =>
      recordPlatformAgreementAcceptance(tenant.academy_id, {
        agreement_version: version.trim(),
        accepted_by: acceptedBy.trim(),
      }),
    onSuccess: (updated) => {
      onDone(updated);
      toast({ kind: "success", title: "Agreement acceptance recorded" });
      onClose();
    },
    onError: (err: Error) => {
      toast({ kind: "error", title: "Could not record acceptance", description: err.message });
    },
  });

  return (
    <Modal
      open
      onClose={onClose}
      title="Record agreement acceptance"
      dismissable={!mutation.isPending}
      footer={
        <div className="flex justify-end gap-2">
          <Button variant="ghost" size="sm" onClick={onClose} disabled={mutation.isPending}>
            Cancel
          </Button>
          <Button size="sm" disabled={!valid || mutation.isPending} onClick={() => mutation.mutate()}>
            {mutation.isPending ? "Saving…" : "Record acceptance"}
          </Button>
        </div>
      }
    >
      <p className="text-sm text-rally-subtle">
        Only record an acceptance the academy has actually given. The time is stamped now.
      </p>
      {replacing && (
        <div
          className="mt-3 rounded-lg bg-status-amber-50 px-3 py-2 text-sm text-status-amber-800"
          data-testid="agreement-replace-warning"
        >
          <p>{replacing}</p>
          <label className="mt-2 flex items-start gap-2 font-medium">
            <input
              type="checkbox"
              className="mt-0.5"
              checked={confirmedReplace}
              onChange={(e) => setConfirmedReplace(e.target.checked)}
            />
            <span>Replace the recorded acceptance</span>
          </label>
        </div>
      )}
      <div className="mt-3 space-y-3">
        <FormField label="Agreement version" htmlFor="agreement-version" required>
          <input
            id="agreement-version"
            maxLength={64}
            className={INPUT_CLASS}
            value={version}
            onChange={(e) => setVersion(e.target.value)}
          />
        </FormField>
        <FormField
          label="Accepted by"
          htmlFor="agreement-accepted-by"
          hint="The academy signatory: a name or email, free text. Check it before saving."
          required
        >
          <input
            id="agreement-accepted-by"
            maxLength={200}
            className={INPUT_CLASS}
            value={acceptedBy}
            onChange={(e) => setAcceptedBy(e.target.value)}
          />
        </FormField>
      </div>
    </Modal>
  );
}

const INPUT_CLASS =
  "w-full rounded-lg border border-rally-line bg-white px-3 py-2 text-sm text-rally-ink outline-none focus:border-rally-cobalt";
