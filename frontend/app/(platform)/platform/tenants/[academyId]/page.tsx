"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  Button,
  Card,
  EmptyState,
  FormField,
  Modal,
  Overline,
  Skeleton,
  useToast,
} from "@/components/ds";
import {
  activatePlatformTenant,
  cancelPlatformTenant,
  getPlatformTenantHealth,
  getPlatformTenantStatus,
  reactivatePlatformTenant,
  suspendPlatformTenant,
  updatePlatformTenantPlan,
  type PlatformTenant,
} from "@/lib/api/platform";
import { usePlatformAuth } from "@/lib/auth/use-persona-auth";
import { queryKeys } from "@/lib/query/keys";

import { TenantStatusChip } from "../status-chip";

/** Which lifecycle transitions the API accepts from each status. */
function allowedActions(status: PlatformTenant["status"]) {
  return {
    activate: status === "provisioning",
    suspend: status === "active",
    cancel: status === "active" || status === "suspended",
    reactivate: status === "suspended" || status === "cancelled",
    editPlan: status !== "cancelled",
  };
}

export default function PlatformTenantDetailPage() {
  const params = useParams<{ academyId: string }>();
  const academyId = decodeURIComponent(params.academyId);
  const auth = usePlatformAuth();
  const queryClient = useQueryClient();
  const { toast } = useToast();
  const [reasonDialog, setReasonDialog] = useState<"suspend" | "cancel" | null>(null);
  const [planDialogOpen, setPlanDialogOpen] = useState(false);

  const statusQuery = useQuery({
    queryKey: queryKeys.platform.tenantStatus(academyId),
    queryFn: () => getPlatformTenantStatus(academyId),
    retry: false,
  });

  const healthQuery = useQuery({
    queryKey: queryKeys.platform.tenantHealth(academyId),
    queryFn: () => getPlatformTenantHealth(academyId),
    retry: false,
  });

  const refresh = (tenant: PlatformTenant) => {
    queryClient.setQueryData(queryKeys.platform.tenantStatus(academyId), tenant);
    void queryClient.invalidateQueries({ queryKey: queryKeys.platform.tenantHealth(academyId) });
    void queryClient.invalidateQueries({ queryKey: queryKeys.platform.tenants() });
  };

  const onLifecycleError = (err: Error) => {
    toast({ kind: "error", title: "Lifecycle action failed", description: err.message });
  };

  const activateMutation = useMutation({
    mutationFn: () => activatePlatformTenant(academyId),
    onSuccess: (tenant) => {
      refresh(tenant);
      toast({ kind: "success", title: "Tenant activated" });
    },
    onError: onLifecycleError,
  });

  const reactivateMutation = useMutation({
    mutationFn: () => reactivatePlatformTenant(academyId),
    onSuccess: (tenant) => {
      refresh(tenant);
      toast({ kind: "success", title: "Tenant reactivated" });
    },
    onError: onLifecycleError,
  });

  const tenant = statusQuery.data;
  const actions = tenant ? allowedActions(tenant.status) : null;
  const mutating = activateMutation.isPending || reactivateMutation.isPending;

  return (
    <section data-testid="platform-tenant-detail" className="space-y-6">
      <Link
        href="/platform/tenants"
        className="text-sm font-semibold text-rally-cobalt hover:underline"
      >
        Back to tenants
      </Link>

      {statusQuery.isPending && (
        <Card p={20}>
          <Skeleton variant="line" lines={3} />
        </Card>
      )}

      {statusQuery.isError && (
        <Card p={20}>
          <EmptyState
            title="Tenant unavailable"
            description="This tenant does not exist, or the tenant lifecycle service is not configured on the API."
          />
        </Card>
      )}

      {tenant && actions && (
        <>
          <Card p={20}>
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <h1 className="font-display text-2xl font-bold tracking-tight text-rally-ink">
                  {tenant.display_name}
                </h1>
                <p className="mt-0.5 text-sm text-rally-subtle">
                  {tenant.slug} · {tenant.primary_domain}
                </p>
                <p className="mt-1 font-mono text-xs text-rally-subtle">{tenant.academy_id}</p>
              </div>
              <TenantStatusChip status={tenant.status} />
            </div>

            <dl className="mt-5 grid grid-cols-2 gap-4 sm:grid-cols-4">
              <Stat label="Servable" value={tenant.servable ? "Yes" : "No"} />
              <Stat label="Plan" value={tenant.plan_code} />
              <Stat label="Last updated by" value={tenant.updated_by} />
              <Stat label="Health reason" value={healthQuery.data?.reason ?? tenant.reason ?? "—"} />
            </dl>

            {tenant.status_reason && (
              <p className="mt-4 rounded-lg bg-status-amber-50 px-3 py-2 text-sm text-status-amber-800">
                Status reason: {tenant.status_reason}
              </p>
            )}
          </Card>

          <Card p={20}>
            <Overline>Plan limits</Overline>
            <dl className="mt-3 grid grid-cols-3 gap-4">
              <Stat label="Max students" value={formatLimit(tenant.limits.max_students)} />
              <Stat label="Max coaches" value={formatLimit(tenant.limits.max_coaches)} />
              <Stat label="Max locations" value={formatLimit(tenant.limits.max_locations)} />
            </dl>
            {auth.isAdmin && actions.editPlan && (
              <div className="mt-4">
                <Button variant="secondary" size="sm" onClick={() => setPlanDialogOpen(true)}>
                  Edit plan and limits
                </Button>
              </div>
            )}
          </Card>

          <Card p={20}>
            <Overline>Lifecycle</Overline>
            {auth.isAdmin ? (
              <div className="mt-3 flex flex-wrap gap-2">
                <Button
                  size="sm"
                  disabled={!actions.activate || mutating}
                  onClick={() => activateMutation.mutate()}
                >
                  Activate
                </Button>
                <Button
                  variant="secondary"
                  size="sm"
                  disabled={!actions.reactivate || mutating}
                  onClick={() => reactivateMutation.mutate()}
                >
                  Reactivate
                </Button>
                <Button
                  variant="danger"
                  size="sm"
                  disabled={!actions.suspend || mutating}
                  onClick={() => setReasonDialog("suspend")}
                >
                  Suspend
                </Button>
                <Button
                  variant="danger"
                  size="sm"
                  disabled={!actions.cancel || mutating}
                  onClick={() => setReasonDialog("cancel")}
                >
                  Cancel
                </Button>
              </div>
            ) : (
              <p className="mt-3 text-sm text-rally-subtle">
                Lifecycle changes require a platform admin. Support access is read-only.
              </p>
            )}
          </Card>

          {reasonDialog && (
            <LifecycleReasonDialog
              kind={reasonDialog}
              academyId={academyId}
              onDone={refresh}
              onClose={() => setReasonDialog(null)}
            />
          )}
          {planDialogOpen && (
            <EditPlanDialog
              tenant={tenant}
              onDone={refresh}
              onClose={() => setPlanDialogOpen(false)}
            />
          )}
        </>
      )}
    </section>
  );
}

function formatLimit(value: number | null): string {
  return value === null ? "Unlimited" : String(value);
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-xs font-semibold uppercase tracking-wide text-rally-subtle">{label}</dt>
      <dd className="mt-0.5 text-sm font-medium text-rally-ink">{value}</dd>
    </div>
  );
}

function LifecycleReasonDialog({
  kind,
  academyId,
  onDone,
  onClose,
}: {
  kind: "suspend" | "cancel";
  academyId: string;
  onDone: (tenant: PlatformTenant) => void;
  onClose: () => void;
}) {
  const { toast } = useToast();
  const [reason, setReason] = useState("");

  const mutation = useMutation({
    mutationFn: () =>
      kind === "suspend"
        ? suspendPlatformTenant(academyId, { reason: reason.trim() })
        : cancelPlatformTenant(academyId, { reason: reason.trim() }),
    onSuccess: (tenant) => {
      onDone(tenant);
      toast({
        kind: "success",
        title: kind === "suspend" ? "Tenant suspended" : "Tenant cancelled",
      });
      onClose();
    },
    onError: (err: Error) => {
      toast({ kind: "error", title: "Lifecycle action failed", description: err.message });
    },
  });

  const title = kind === "suspend" ? "Suspend tenant" : "Cancel tenant";

  return (
    <Modal
      open
      onClose={onClose}
      title={title}
      dismissable={!mutation.isPending}
      footer={
        <div className="flex justify-end gap-2">
          <Button variant="ghost" size="sm" onClick={onClose} disabled={mutation.isPending}>
            Back
          </Button>
          <Button
            variant="danger"
            size="sm"
            disabled={!reason.trim() || mutation.isPending}
            onClick={() => mutation.mutate()}
          >
            {mutation.isPending ? "Working…" : title}
          </Button>
        </div>
      }
    >
      <p className="text-sm text-rally-subtle">
        {kind === "suspend"
          ? "A suspended tenant stops being servable immediately. It can be reactivated later."
          : "Cancelling stops the tenant from being servable. It can still be reactivated."}
      </p>
      <div className="mt-3">
        <FormField label="Reason" htmlFor="lifecycle-reason" required>
          <textarea
            id="lifecycle-reason"
            rows={3}
            className={INPUT_CLASS}
            value={reason}
            onChange={(e) => setReason(e.target.value)}
          />
        </FormField>
      </div>
    </Modal>
  );
}

function EditPlanDialog({
  tenant,
  onDone,
  onClose,
}: {
  tenant: PlatformTenant;
  onDone: (tenant: PlatformTenant) => void;
  onClose: () => void;
}) {
  const { toast } = useToast();
  const [planCode, setPlanCode] = useState(tenant.plan_code);
  const [maxStudents, setMaxStudents] = useState(limitToInput(tenant.limits.max_students));
  const [maxCoaches, setMaxCoaches] = useState(limitToInput(tenant.limits.max_coaches));
  const [maxLocations, setMaxLocations] = useState(limitToInput(tenant.limits.max_locations));

  const mutation = useMutation({
    mutationFn: () =>
      updatePlatformTenantPlan(tenant.academy_id, {
        plan_code: planCode.trim(),
        limits: {
          max_students: inputToLimit(maxStudents),
          max_coaches: inputToLimit(maxCoaches),
          max_locations: inputToLimit(maxLocations),
        },
      }),
    onSuccess: (updated) => {
      onDone(updated);
      toast({ kind: "success", title: "Plan updated" });
      onClose();
    },
    onError: (err: Error) => {
      toast({ kind: "error", title: "Could not update plan", description: err.message });
    },
  });

  return (
    <Modal
      open
      onClose={onClose}
      title="Edit plan and limits"
      dismissable={!mutation.isPending}
      footer={
        <div className="flex justify-end gap-2">
          <Button variant="ghost" size="sm" onClick={onClose} disabled={mutation.isPending}>
            Cancel
          </Button>
          <Button
            size="sm"
            disabled={!planCode.trim() || mutation.isPending}
            onClick={() => mutation.mutate()}
          >
            {mutation.isPending ? "Saving…" : "Save plan"}
          </Button>
        </div>
      }
    >
      <div className="space-y-3">
        <FormField label="Plan code" htmlFor="edit-plan-code" required>
          <input
            id="edit-plan-code"
            className={INPUT_CLASS}
            value={planCode}
            onChange={(e) => setPlanCode(e.target.value)}
          />
        </FormField>
        <div className="grid grid-cols-3 gap-2">
          <FormField label="Max students" htmlFor="edit-max-students" hint="Blank = unlimited">
            <input
              id="edit-max-students"
              type="number"
              min={0}
              className={INPUT_CLASS}
              value={maxStudents}
              onChange={(e) => setMaxStudents(e.target.value)}
            />
          </FormField>
          <FormField label="Max coaches" htmlFor="edit-max-coaches" hint="Blank = unlimited">
            <input
              id="edit-max-coaches"
              type="number"
              min={0}
              className={INPUT_CLASS}
              value={maxCoaches}
              onChange={(e) => setMaxCoaches(e.target.value)}
            />
          </FormField>
          <FormField label="Max locations" htmlFor="edit-max-locations" hint="Blank = unlimited">
            <input
              id="edit-max-locations"
              type="number"
              min={0}
              className={INPUT_CLASS}
              value={maxLocations}
              onChange={(e) => setMaxLocations(e.target.value)}
            />
          </FormField>
        </div>
      </div>
    </Modal>
  );
}

function limitToInput(value: number | null): string {
  return value === null ? "" : String(value);
}

function inputToLimit(value: string): number | null {
  const trimmed = value.trim();
  if (!trimmed) return null;
  const parsed = Number(trimmed);
  return Number.isFinite(parsed) && parsed >= 0 ? parsed : null;
}

const INPUT_CLASS =
  "w-full rounded-lg border border-rally-line bg-white px-3 py-2 text-sm text-rally-ink outline-none focus:border-rally-cobalt";
