"use client";

import Link from "next/link";
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { Button, Card, EmptyState, FormField, Modal, TableSkeleton, useToast } from "@/components/ds";
import {
  bootstrapPlatformAcademy,
  createPlatformTenant,
  listPlatformTenants,
  type PlatformTenant,
} from "@/lib/api/platform";
import { usePlatformAuth } from "@/lib/auth/use-persona-auth";
import { TIMEZONE_OPTIONS } from "@/lib/format/timezone-options";
import { queryKeys } from "@/lib/query/keys";

import { TenantStatusChip } from "./status-chip";

type DialogKind = "create" | "bootstrap" | null;

export default function PlatformTenantsPage() {
  const auth = usePlatformAuth();
  const [dialog, setDialog] = useState<DialogKind>(null);

  const query = useQuery({
    queryKey: queryKeys.platform.tenants(),
    queryFn: listPlatformTenants,
    retry: false,
  });

  return (
    <section data-testid="platform-tenants" className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="font-display text-2xl font-bold tracking-tight text-rally-ink">Tenants</h1>
          <p className="mt-0.5 text-sm text-rally-subtle">
            Every academy the platform provisions, with its serving status and plan
          </p>
        </div>
        {auth.isAdmin && (
          <div className="flex flex-wrap gap-2">
            <Button variant="secondary" size="sm" onClick={() => setDialog("bootstrap")}>
              Bootstrap academy
            </Button>
            <Button size="sm" onClick={() => setDialog("create")}>
              Create tenant
            </Button>
          </div>
        )}
      </div>

      {query.isPending && (
        <Card p={20}>
          <TableSkeleton rows={4} />
        </Card>
      )}

      {query.isError && (
        <Card p={20}>
          <EmptyState
            title="Platform tenants are unavailable"
            description="This surface is only reachable by platform operators, and the tenant lifecycle service must be configured on the API."
          />
        </Card>
      )}

      {query.data &&
        (query.data.length === 0 ? (
          <Card p={20}>
            <EmptyState
              title="No tenants yet"
              description={
                auth.isAdmin
                  ? "Create a tenant to start onboarding an academy."
                  : "Nothing has been provisioned on this platform yet."
              }
            />
          </Card>
        ) : (
          <Card p={0}>
            <div className="overflow-x-auto">
              <table className="w-full min-w-[720px] text-sm">
                <thead>
                  <tr className="border-b border-rally-line text-left">
                    <Th>Academy</Th>
                    <Th>Domain</Th>
                    <Th>Status</Th>
                    <Th>Plan</Th>
                    <Th>Limits</Th>
                  </tr>
                </thead>
                <tbody>
                  {query.data.map((tenant) => (
                    <TenantRow key={tenant.academy_id} tenant={tenant} />
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
        ))}

      {dialog === "create" && <CreateTenantDialog onClose={() => setDialog(null)} />}
      {dialog === "bootstrap" && <BootstrapAcademyDialog onClose={() => setDialog(null)} />}
    </section>
  );
}

function Th({ children }: { children: React.ReactNode }) {
  return (
    <th className="px-4 py-2.5 text-xs font-semibold uppercase tracking-wide text-rally-subtle">
      {children}
    </th>
  );
}

function TenantRow({ tenant }: { tenant: PlatformTenant }) {
  return (
    <tr className="border-b border-rally-line last:border-0">
      <td className="px-4 py-3">
        <Link
          href={
            `/platform/tenants/${encodeURIComponent(tenant.academy_id)}` as Parameters<
              typeof Link
            >[0]["href"]
          }
          className="font-semibold text-rally-cobalt hover:underline"
        >
          {tenant.display_name}
        </Link>
        <p className="text-xs text-rally-subtle">{tenant.slug}</p>
      </td>
      <td className="px-4 py-3 text-rally-ink">{tenant.primary_domain}</td>
      <td className="px-4 py-3">
        <TenantStatusChip status={tenant.status} />
      </td>
      <td className="px-4 py-3 text-rally-ink">{tenant.plan_code}</td>
      <td className="px-4 py-3 text-xs text-rally-subtle">{formatLimits(tenant)}</td>
    </tr>
  );
}

function formatLimits(tenant: PlatformTenant): string {
  const parts = [
    tenant.limits.max_students === null ? null : `${tenant.limits.max_students} students`,
    tenant.limits.max_coaches === null ? null : `${tenant.limits.max_coaches} coaches`,
    tenant.limits.max_locations === null ? null : `${tenant.limits.max_locations} locations`,
  ].filter((part): part is string => part !== null);
  return parts.length > 0 ? parts.join(" · ") : "Unlimited";
}

/** Empty string means "leave unset" — the API treats a null limit as unlimited. */
function optionalLimit(value: string): number | null {
  const trimmed = value.trim();
  if (!trimmed) return null;
  const parsed = Number(trimmed);
  return Number.isFinite(parsed) && parsed >= 0 ? parsed : null;
}

function CreateTenantDialog({ onClose }: { onClose: () => void }) {
  const queryClient = useQueryClient();
  const { toast } = useToast();
  const [displayName, setDisplayName] = useState("");
  const [slug, setSlug] = useState("");
  const [primaryDomain, setPrimaryDomain] = useState("");
  const [planCode, setPlanCode] = useState("starter");
  const [maxStudents, setMaxStudents] = useState("");
  const [maxCoaches, setMaxCoaches] = useState("");
  const [maxLocations, setMaxLocations] = useState("");

  const mutation = useMutation({
    mutationFn: () =>
      createPlatformTenant({
        display_name: displayName.trim(),
        slug: slug.trim(),
        primary_domain: primaryDomain.trim(),
        plan_code: planCode.trim(),
        limits: {
          max_students: optionalLimit(maxStudents),
          max_coaches: optionalLimit(maxCoaches),
          max_locations: optionalLimit(maxLocations),
        },
      }),
    onSuccess: (tenant) => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.platform.tenants() });
      toast({
        kind: "success",
        title: "Tenant created",
        description: `${tenant.display_name} is provisioning.`,
      });
      onClose();
    },
    onError: (err: Error) => {
      toast({ kind: "error", title: "Could not create tenant", description: err.message });
    },
  });

  const complete = Boolean(
    displayName.trim() && slug.trim() && primaryDomain.trim() && planCode.trim(),
  );

  return (
    <Modal
      open
      onClose={onClose}
      title="Create tenant"
      dismissable={!mutation.isPending}
      footer={
        <div className="flex justify-end gap-2">
          <Button variant="ghost" size="sm" onClick={onClose} disabled={mutation.isPending}>
            Cancel
          </Button>
          <Button
            size="sm"
            disabled={!complete || mutation.isPending}
            onClick={() => mutation.mutate()}
          >
            {mutation.isPending ? "Creating…" : "Create tenant"}
          </Button>
        </div>
      }
    >
      <div className="space-y-3">
        <FormField label="Display name" htmlFor="tenant-display-name" required>
          <input
            id="tenant-display-name"
            className={INPUT_CLASS}
            value={displayName}
            onChange={(e) => setDisplayName(e.target.value)}
          />
        </FormField>
        <FormField
          label="Slug"
          htmlFor="tenant-slug"
          required
          hint="Lowercased and hyphenated by the API."
        >
          <input
            id="tenant-slug"
            className={INPUT_CLASS}
            value={slug}
            onChange={(e) => setSlug(e.target.value)}
          />
        </FormField>
        <FormField label="Primary domain" htmlFor="tenant-domain" required>
          <input
            id="tenant-domain"
            className={INPUT_CLASS}
            value={primaryDomain}
            onChange={(e) => setPrimaryDomain(e.target.value)}
          />
        </FormField>
        <FormField label="Plan code" htmlFor="tenant-plan" required>
          <input
            id="tenant-plan"
            className={INPUT_CLASS}
            value={planCode}
            onChange={(e) => setPlanCode(e.target.value)}
          />
        </FormField>
        <div className="grid grid-cols-3 gap-2">
          <FormField label="Max students" htmlFor="tenant-max-students" hint="Blank = unlimited">
            <input
              id="tenant-max-students"
              type="number"
              min={0}
              className={INPUT_CLASS}
              value={maxStudents}
              onChange={(e) => setMaxStudents(e.target.value)}
            />
          </FormField>
          <FormField label="Max coaches" htmlFor="tenant-max-coaches" hint="Blank = unlimited">
            <input
              id="tenant-max-coaches"
              type="number"
              min={0}
              className={INPUT_CLASS}
              value={maxCoaches}
              onChange={(e) => setMaxCoaches(e.target.value)}
            />
          </FormField>
          <FormField label="Max locations" htmlFor="tenant-max-locations" hint="Blank = unlimited">
            <input
              id="tenant-max-locations"
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

function BootstrapAcademyDialog({ onClose }: { onClose: () => void }) {
  const queryClient = useQueryClient();
  const { toast } = useToast();
  const [displayName, setDisplayName] = useState("");
  const [slug, setSlug] = useState("");
  const [primaryDomain, setPrimaryDomain] = useState("");
  const [ownerEmail, setOwnerEmail] = useState("");
  const [ownerName, setOwnerName] = useState("");
  // Deliberately empty, not "UTC". Bootstrapping every academy as UTC is the
  // upstream half of the reported defect: sessions resolve their zone from the
  // academy record, so an academy stamped UTC at creation makes a real 6:00 PM
  // Chicago class read back to the parent as 1:00 PM. The operator must pick.
  const [timezone, setTimezone] = useState("");

  const mutation = useMutation({
    mutationFn: () =>
      bootstrapPlatformAcademy({
        display_name: displayName.trim(),
        slug: slug.trim(),
        primary_domain: primaryDomain.trim(),
        owner_email: ownerEmail.trim(),
        owner_display_name: ownerName.trim(),
        timezone: timezone.trim() || "UTC",
      }),
    onSuccess: (result) => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.platform.tenants() });
      toast({
        kind: "success",
        title: result.created ? "Academy bootstrapped" : "Academy already existed",
        description: `${result.slug} — owner ${result.owner_role}`,
      });
      onClose();
    },
    onError: (err: Error) => {
      toast({ kind: "error", title: "Could not bootstrap academy", description: err.message });
    },
  });

  const complete = Boolean(
    displayName.trim() &&
      slug.trim() &&
      primaryDomain.trim() &&
      ownerEmail.trim() &&
      ownerName.trim(),
  );

  return (
    <Modal
      open
      onClose={onClose}
      title="Bootstrap academy"
      dismissable={!mutation.isPending}
      footer={
        <div className="flex justify-end gap-2">
          <Button variant="ghost" size="sm" onClick={onClose} disabled={mutation.isPending}>
            Cancel
          </Button>
          <Button
            size="sm"
            disabled={!complete || mutation.isPending}
            onClick={() => mutation.mutate()}
          >
            {mutation.isPending ? "Bootstrapping…" : "Bootstrap academy"}
          </Button>
        </div>
      }
    >
      <div className="space-y-3">
        <p className="text-sm text-rally-subtle">
          Creates the academy, its owner membership, and the default records a new tenant needs.
        </p>
        <FormField label="Display name" htmlFor="bootstrap-display-name" required>
          <input
            id="bootstrap-display-name"
            className={INPUT_CLASS}
            value={displayName}
            onChange={(e) => setDisplayName(e.target.value)}
          />
        </FormField>
        <FormField label="Slug" htmlFor="bootstrap-slug" required>
          <input
            id="bootstrap-slug"
            className={INPUT_CLASS}
            value={slug}
            onChange={(e) => setSlug(e.target.value)}
          />
        </FormField>
        <FormField label="Primary domain" htmlFor="bootstrap-domain" required>
          <input
            id="bootstrap-domain"
            className={INPUT_CLASS}
            value={primaryDomain}
            onChange={(e) => setPrimaryDomain(e.target.value)}
          />
        </FormField>
        <FormField label="Owner email" htmlFor="bootstrap-owner-email" required>
          <input
            id="bootstrap-owner-email"
            type="email"
            className={INPUT_CLASS}
            value={ownerEmail}
            onChange={(e) => setOwnerEmail(e.target.value)}
          />
        </FormField>
        <FormField label="Owner name" htmlFor="bootstrap-owner-name" required>
          <input
            id="bootstrap-owner-name"
            className={INPUT_CLASS}
            value={ownerName}
            onChange={(e) => setOwnerName(e.target.value)}
          />
        </FormField>
        <FormField label="Timezone" htmlFor="bootstrap-timezone">
          <input
            id="bootstrap-timezone"
            className={INPUT_CLASS}
            value={timezone}
            onChange={(e) => setTimezone(e.target.value)}
          />
        </FormField>
      </div>
    </Modal>
  );
}

const INPUT_CLASS =
  "w-full rounded-lg border border-rally-line bg-white px-3 py-2 text-sm text-rally-ink outline-none focus:border-rally-cobalt";
