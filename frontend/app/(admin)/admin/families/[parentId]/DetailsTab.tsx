"use client";

import { useEffect, useId, useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { ConfirmActionDialog } from "@/components/admin/confirm-action-dialog";
import { useReportUnsavedChanges } from "@/components/admin/unsaved-changes-guard";
import { Button, Card, Chip, Overline, Skeleton, useToast } from "@/components/ds";
import { ErrorNotice } from "@/components/ds/error-notice";
import { FormField, fieldDescribedBy } from "@/components/ds/form-field";
import type { FamilyIndexRow, FamilyParent } from "@/lib/api/admin-families";
import {
  addFamilyContact,
  deleteFamilyContact,
  familyContactKeys,
  fetchFamilyContacts,
  fetchFamilyDetails,
  updateFamilyContact,
  updateFamilyDetails,
  type FamilyContact,
} from "@/lib/api/admin-family-contacts";
import { lifecycleLabel, lifecycleVariant } from "@/lib/format/lifecycle-copy";

import {
  CHANNEL_OPTIONS,
  CONTACT_SWITCHES,
  MAX_ADDRESS_LEN,
  MAX_CONTACT_NAME_LEN,
  MAX_HEARD_ABOUT_US_LEN,
  RELATIONSHIP_OPTIONS,
  apiFieldError,
  contactDraftErrors,
  contactPatch,
  contactPayload,
  detailsDraftErrors,
  detailsDraftFrom,
  detailsPatch,
  draftFromContact,
  emptyContactDraft,
  isContactDraftDirty,
  isDetailsDirty,
  relationshipLabel,
  type ContactDraft,
  type ContactErrors,
  type ContactField,
  type ContactSwitchId,
  type DetailsDraft,
  type DetailsErrors,
  type DetailsField,
} from "./family-contacts";
import { primaryContactRows, type OverviewChild } from "./family-record";

const inputClass =
  "w-full rounded-lg border border-rally-line bg-white px-3 py-2 text-sm text-rally-ink focus:outline-none focus:ring-2 focus:ring-rally-cobalt-600/30";

/**
 * Details (People CRM spec §4, Phase 4b): the primary parent (from the login
 * account, read-only here), the family's other contacts with their opt-in
 * switches, the editable family details, and the children.
 *
 * A contact receives nothing unless staff turn a switch on. "Gets notices"
 * adds their email to this family's class notices; "Gets invoices" is saved
 * but invoice emails do not use it yet, and its description says so.
 */
export function DetailsTab({
  parentId,
  family,
  parent,
  kids,
}: {
  parentId: string;
  family: FamilyIndexRow | null;
  parent: FamilyParent | null;
  kids: OverviewChild[];
}) {
  return (
    <div className="space-y-4" data-testid="family-details">
      <Card p={20}>
        <Overline>Primary parent</Overline>
        <dl className="mt-2 grid gap-2 sm:grid-cols-[8rem_1fr]">
          {primaryContactRows(family, parent).map((row) => (
            <div key={row.label} className="contents">
              <dt className="text-sm text-rally-muted">{row.label}</dt>
              <dd className="text-sm text-rally-ink" data-testid={row.testId}>
                {row.value}
              </dd>
            </div>
          ))}
        </dl>
        <p className="mt-3 text-xs text-rally-muted">
          Name, email and phone come from the parent&apos;s login account.
        </p>
      </Card>

      <ContactsCard parentId={parentId} />
      <FamilyDetailsCard parentId={parentId} />

      <Card p={20}>
        <Overline>Children</Overline>
        {kids.length === 0 ? (
          <p className="mt-2 text-sm text-rally-muted">No children on this family yet.</p>
        ) : (
          <ul className="mt-2 space-y-2" data-testid="family-details-children">
            {kids.map((kid) => (
              <li key={kid.studentId} className="flex flex-wrap items-center gap-2 text-sm">
                <span className="text-rally-ink">{kid.name}</span>
                {kid.lifecycle && (
                  <Chip
                    variant={lifecycleVariant(kid.lifecycle)}
                    label={lifecycleLabel(kid.lifecycle, kid.lifecycleAsOf)}
                  />
                )}
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Switch: a labelled checkbox with role="switch" and a description.
// ---------------------------------------------------------------------------

function ContactSwitch({
  id,
  label,
  description,
  checked,
  disabled,
  error,
  testId,
  onChange,
}: {
  id: string;
  label: string;
  description: string;
  checked: boolean;
  disabled?: boolean;
  error?: string | null;
  testId: string;
  onChange: (checked: boolean) => void;
}) {
  const descId = `${id}-desc`;
  const errId = `${id}-error`;
  return (
    <div className="flex min-h-11 items-start gap-3">
      <input
        id={id}
        type="checkbox"
        role="switch"
        aria-checked={checked}
        checked={checked}
        disabled={disabled}
        aria-describedby={error ? `${descId} ${errId}` : descId}
        aria-invalid={error ? true : undefined}
        data-testid={testId}
        onChange={(e) => onChange(e.target.checked)}
        className="mt-0.5 size-5 shrink-0 accent-rally-cobalt-600"
      />
      <div className="min-w-0">
        <label htmlFor={id} className="text-sm font-medium text-rally-ink">
          {label}
        </label>
        <p id={descId} className="text-xs text-rally-muted">
          {description}
        </p>
        {error && (
          <p id={errId} role="alert" className="text-xs font-medium text-status-red-800">
            {error}
          </p>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Contacts
// ---------------------------------------------------------------------------

function ContactsCard({ parentId }: { parentId: string }) {
  const key = familyContactKeys.contacts(parentId);
  const contacts = useQuery({
    queryKey: key,
    queryFn: () => fetchFamilyContacts(parentId),
  });
  const [adding, setAdding] = useState(false);
  const list = contacts.data?.contacts ?? [];

  return (
    <Card p={20} data-testid="family-contacts">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <Overline>Other contacts</Overline>
        {!adding && (
          <Button
            size="sm"
            variant="secondary"
            onClick={() => setAdding(true)}
            data-testid="family-contact-add-open"
          >
            Add contact
          </Button>
        )}
      </div>
      <p className="mt-1 text-xs text-rally-muted">
        A second parent, guardian or other adult. Contacts never get a login, and they receive
        nothing unless you turn a switch on.
      </p>

      {adding && (
        <ContactForm
          parentId={parentId}
          formKey="new"
          initial={emptyContactDraft()}
          onDone={() => setAdding(false)}
        />
      )}

      {contacts.isLoading ? (
        <div className="mt-3">
          <Skeleton lines={2} />
        </div>
      ) : contacts.isError ? (
        <ErrorNotice
          className="mt-3"
          testId="family-contacts-error"
          message="Could not load the contacts."
          onRetry={() => void contacts.refetch()}
          retrying={contacts.isFetching}
        />
      ) : list.length === 0 ? (
        <p className="mt-3 text-sm text-rally-muted" data-testid="family-contacts-empty">
          No other contacts yet.
        </p>
      ) : (
        <ul className="mt-3 divide-y divide-rally-line" data-testid="family-contacts-list">
          {list.map((contact) => (
            <ContactRow key={contact.contact_id} parentId={parentId} contact={contact} />
          ))}
        </ul>
      )}
    </Card>
  );
}

function ContactRow({ parentId, contact }: { parentId: string; contact: FamilyContact }) {
  const qc = useQueryClient();
  const key = familyContactKeys.contacts(parentId);
  const { toast } = useToast();
  const [editing, setEditing] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [switchError, setSwitchError] = useState<{
    id: ContactSwitchId;
    text: string;
  } | null>(null);
  // The switch flips as it is clicked; a failed save puts it back.
  const [optimistic, setOptimistic] = useState<Partial<Record<ContactSwitchId, boolean>>>({});
  const baseId = useId();

  const toggle = useMutation({
    mutationFn: ({ id, on }: { id: ContactSwitchId; on: boolean }) =>
      updateFamilyContact(parentId, contact.contact_id, { [id]: on }),
    onMutate: () => setSwitchError(null),
    onSuccess: (row, { id, on }) => {
      qc.setQueryData(key, (old: { family_id: string; contacts: FamilyContact[] } | undefined) =>
        old
          ? {
              ...old,
              contacts: old.contacts.map((c) => (c.contact_id === row.contact_id ? row : c)),
            }
          : old,
      );
      void qc.invalidateQueries({ queryKey: key });
      const label = CONTACT_SWITCHES.find((s) => s.id === id)?.label ?? "Setting";
      toast({
        kind: "success",
        title: `${label} ${on ? "on" : "off"} for ${row.name}`,
      });
    },
    onError: (error, { id }) => setSwitchError({ id, text: apiFieldError(error).message }),
  });
  const settle = (id: ContactSwitchId) =>
    setOptimistic((o) => {
      const next = { ...o };
      delete next[id];
      return next;
    });
  const remove = useMutation({
    mutationFn: () => deleteFamilyContact(parentId, contact.contact_id),
    onSuccess: () => {
      setConfirming(false);
      void qc.invalidateQueries({ queryKey: key });
      toast({ kind: "success", title: `${contact.name} removed` });
    },
  });

  if (editing) {
    return (
      <li className="py-3" data-testid={`family-contact-${contact.contact_id}`}>
        <ContactForm
          parentId={parentId}
          formKey={contact.contact_id}
          initial={draftFromContact(contact)}
          original={contact}
          onDone={() => setEditing(false)}
        />
      </li>
    );
  }

  return (
    <li className="space-y-2 py-3" data-testid={`family-contact-${contact.contact_id}`}>
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0 text-sm">
          <p className="font-medium text-rally-ink" data-testid="family-contact-name">
            {contact.name}{" "}
            <span className="font-normal text-rally-muted">
              ({relationshipLabel(contact.relationship)})
            </span>
          </p>
          <p className="break-all text-rally-muted">
            {[contact.email, contact.phone].filter(Boolean).join(" · ")}
          </p>
        </div>
        <div className="flex gap-2">
          <Button
            size="sm"
            variant="ghost"
            onClick={() => setEditing(true)}
            data-testid="family-contact-edit"
            aria-label={`Edit ${contact.name}`}
          >
            Edit
          </Button>
          <Button
            size="sm"
            variant="ghost"
            onClick={() => setConfirming(true)}
            data-testid="family-contact-remove"
            aria-label={`Remove ${contact.name}`}
          >
            Remove
          </Button>
        </div>
      </div>
      <div className="space-y-1">
        {CONTACT_SWITCHES.map((sw) => (
          <ContactSwitch
            key={sw.id}
            id={`${baseId}-${sw.id}`}
            label={sw.label}
            description={sw.description}
            checked={optimistic[sw.id] ?? contact[sw.id]}
            disabled={toggle.isPending}
            error={switchError?.id === sw.id ? switchError.text : null}
            testId={`family-contact-${sw.id}`}
            onChange={(on) => {
              setOptimistic((o) => ({ ...o, [sw.id]: on }));
              toggle.mutate({ id: sw.id, on }, { onSettled: () => settle(sw.id) });
            }}
          />
        ))}
      </div>
      <ConfirmActionDialog
        open={confirming}
        onOpenChange={(open) => {
          if (!open) setConfirming(false);
        }}
        overline="Remove contact"
        title={`Remove ${contact.name}?`}
        consequence={
          <p>
            They stop receiving this family&apos;s notices. The family and its children are not
            changed.
          </p>
        }
        confirmLabel="Remove contact"
        pending={remove.isPending}
        error={remove.isError ? apiFieldError(remove.error).message : undefined}
        onConfirm={() => remove.mutate()}
      />
    </li>
  );
}

function ContactForm({
  parentId,
  formKey,
  initial,
  original,
  onDone,
}: {
  parentId: string;
  formKey: string;
  initial: ContactDraft;
  original?: FamilyContact;
  onDone: () => void;
}) {
  const qc = useQueryClient();
  const key = familyContactKeys.contacts(parentId);
  const { toast } = useToast();
  const baseId = useId();
  const [draft, setDraft] = useState<ContactDraft>(initial);
  const [errors, setErrors] = useState<ContactErrors>({});
  const [formError, setFormError] = useState<string | null>(null);
  const dirty = isContactDraftDirty(draft, initial);
  useReportUnsavedChanges(`family-contact-${formKey}`, dirty);

  const save = useMutation({
    mutationFn: () =>
      original
        ? updateFamilyContact(parentId, original.contact_id, contactPatch(original, draft))
        : addFamilyContact(parentId, contactPayload(draft)),
    onSuccess: (row) => {
      void qc.invalidateQueries({ queryKey: key });
      toast({
        kind: "success",
        title: original ? `${row.name} saved` : `${row.name} added`,
      });
      onDone();
    },
    onError: (error) => {
      const { field, message } = apiFieldError(error);
      if (field && field in draft) setErrors({ [field]: message } as ContactErrors);
      else setFormError(message);
    },
  });

  const set = <K extends ContactField>(field: K, value: ContactDraft[K]) => {
    setDraft((d) => ({ ...d, [field]: value }));
    setErrors((e) => ({ ...e, [field]: undefined }));
    setFormError(null);
  };

  const submit = (event: FormEvent) => {
    event.preventDefault();
    const problems = contactDraftErrors(draft);
    setErrors(problems);
    setFormError(null);
    if (Object.keys(problems).length === 0 && !save.isPending) save.mutate();
  };

  const fid = (name: string) => `${baseId}-${name}`;

  return (
    <form
      className="mt-3 space-y-3 rounded-lg border border-rally-line p-3"
      onSubmit={submit}
      noValidate
      aria-label={original ? `Edit ${original.name}` : "Add a contact"}
      data-testid="family-contact-form"
    >
      <div className="grid gap-3 sm:grid-cols-2">
        <FormField label="Name" htmlFor={fid("name")} error={errors.name} required>
          <input
            id={fid("name")}
            className={inputClass}
            value={draft.name}
            maxLength={MAX_CONTACT_NAME_LEN}
            autoComplete="off"
            aria-invalid={errors.name ? true : undefined}
            aria-describedby={fieldDescribedBy(fid("name"), {
              error: errors.name,
            })}
            onChange={(e) => set("name", e.target.value)}
            data-testid="family-contact-name-input"
          />
        </FormField>
        <FormField label="Relationship" htmlFor={fid("relationship")} error={errors.relationship}>
          <select
            id={fid("relationship")}
            className={inputClass}
            value={draft.relationship}
            onChange={(e) => set("relationship", e.target.value as ContactDraft["relationship"])}
            data-testid="family-contact-relationship"
          >
            {RELATIONSHIP_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
        </FormField>
        <FormField label="Email" htmlFor={fid("email")} error={errors.email}>
          <input
            id={fid("email")}
            type="email"
            className={inputClass}
            value={draft.email}
            autoComplete="off"
            aria-invalid={errors.email ? true : undefined}
            aria-describedby={fieldDescribedBy(fid("email"), {
              error: errors.email,
            })}
            onChange={(e) => set("email", e.target.value)}
            data-testid="family-contact-email"
          />
        </FormField>
        <FormField label="Phone" htmlFor={fid("phone")} error={errors.phone}>
          <input
            id={fid("phone")}
            type="tel"
            className={inputClass}
            value={draft.phone}
            autoComplete="off"
            aria-invalid={errors.phone ? true : undefined}
            aria-describedby={fieldDescribedBy(fid("phone"), {
              error: errors.phone,
            })}
            onChange={(e) => set("phone", e.target.value)}
            data-testid="family-contact-phone"
          />
        </FormField>
      </div>
      <div className="space-y-1">
        {CONTACT_SWITCHES.map((sw) => (
          <ContactSwitch
            key={sw.id}
            id={fid(sw.id)}
            label={sw.label}
            description={sw.description}
            checked={draft[sw.id]}
            error={errors[sw.id]}
            testId={`family-contact-form-${sw.id}`}
            onChange={(on) => set(sw.id, on)}
          />
        ))}
      </div>
      {formError && (
        <p role="alert" className="text-xs font-medium text-status-red-800">
          {formError}
        </p>
      )}
      <div className="flex justify-end gap-2">
        <Button type="button" size="sm" variant="ghost" onClick={onDone}>
          Cancel
        </Button>
        <Button type="submit" size="sm" disabled={save.isPending} data-testid="family-contact-save">
          {save.isPending ? "Saving…" : original ? "Save contact" : "Add contact"}
        </Button>
      </div>
    </form>
  );
}

// ---------------------------------------------------------------------------
// Family details
// ---------------------------------------------------------------------------

function FamilyDetailsCard({ parentId }: { parentId: string }) {
  const key = familyContactKeys.details(parentId);
  const details = useQuery({
    queryKey: key,
    queryFn: () => fetchFamilyDetails(parentId),
  });

  return (
    <Card p={20} data-testid="family-details-form-card">
      <Overline>Family details</Overline>
      {details.isLoading ? (
        <div className="mt-3">
          <Skeleton lines={3} />
        </div>
      ) : details.isError ? (
        <ErrorNotice
          className="mt-3"
          testId="family-details-error"
          message="Could not load the family details."
          onRetry={() => void details.refetch()}
          retrying={details.isFetching}
        />
      ) : (
        <DetailsForm parentId={parentId} initial={detailsDraftFrom(details.data)} />
      )}
    </Card>
  );
}

function DetailsForm({ parentId, initial }: { parentId: string; initial: DetailsDraft }) {
  const qc = useQueryClient();
  const key = familyContactKeys.details(parentId);
  const { toast } = useToast();
  const baseId = useId();
  const [saved, setSaved] = useState<DetailsDraft>(initial);
  const [draft, setDraft] = useState<DetailsDraft>(initial);
  const [errors, setErrors] = useState<DetailsErrors>({});
  const [formError, setFormError] = useState<string | null>(null);
  const dirty = isDetailsDirty(draft, saved);
  useReportUnsavedChanges("family-details", dirty);

  // A background refetch must not throw away what the admin is typing.
  useEffect(() => {
    if (!dirty) {
      setSaved(initial);
      setDraft(initial);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initial.address, initial.preferred_channel, initial.heard_about_us, initial.tags]);

  const save = useMutation({
    mutationFn: () => updateFamilyDetails(parentId, detailsPatch(saved, draft)),
    onSuccess: (row) => {
      const next = detailsDraftFrom(row);
      setSaved(next);
      setDraft(next);
      qc.setQueryData(key, row);
      toast({ kind: "success", title: "Family details saved" });
    },
    onError: (error) => {
      const { field, message } = apiFieldError(error);
      if (field && field in draft) setErrors({ [field]: message } as DetailsErrors);
      else setFormError(message);
    },
  });

  const set = <K extends DetailsField>(field: K, value: DetailsDraft[K]) => {
    setDraft((d) => ({ ...d, [field]: value }));
    setErrors((e) => ({ ...e, [field]: undefined }));
    setFormError(null);
  };

  const submit = (event: FormEvent) => {
    event.preventDefault();
    const problems = detailsDraftErrors(draft);
    setErrors(problems);
    if (Object.keys(problems).length === 0 && dirty && !save.isPending) save.mutate();
  };

  const fid = (name: string) => `${baseId}-${name}`;

  return (
    <form className="mt-2 space-y-3" onSubmit={submit} noValidate data-testid="family-details-form">
      <div className="grid gap-3 sm:grid-cols-2">
        <FormField
          label="Home address"
          htmlFor={fid("address")}
          error={errors.address}
          className="sm:col-span-2"
        >
          <input
            id={fid("address")}
            className={inputClass}
            value={draft.address}
            maxLength={MAX_ADDRESS_LEN}
            autoComplete="off"
            aria-invalid={errors.address ? true : undefined}
            aria-describedby={fieldDescribedBy(fid("address"), {
              error: errors.address,
            })}
            onChange={(e) => set("address", e.target.value)}
            data-testid="family-details-address"
          />
        </FormField>
        <FormField
          label="Preferred channel"
          htmlFor={fid("channel")}
          error={errors.preferred_channel}
        >
          <select
            id={fid("channel")}
            className={inputClass}
            value={draft.preferred_channel}
            onChange={(e) =>
              set("preferred_channel", e.target.value as DetailsDraft["preferred_channel"])
            }
            data-testid="family-details-channel"
          >
            <option value="">Not set</option>
            {CHANNEL_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
        </FormField>
        <FormField
          label="How they heard about us"
          htmlFor={fid("heard")}
          error={errors.heard_about_us}
        >
          <input
            id={fid("heard")}
            className={inputClass}
            value={draft.heard_about_us}
            maxLength={MAX_HEARD_ABOUT_US_LEN}
            autoComplete="off"
            aria-invalid={errors.heard_about_us ? true : undefined}
            aria-describedby={fieldDescribedBy(fid("heard"), {
              error: errors.heard_about_us,
            })}
            onChange={(e) => set("heard_about_us", e.target.value)}
            data-testid="family-details-heard"
          />
        </FormField>
        <FormField
          label="Tags"
          htmlFor={fid("tags")}
          hint="Separate tags with commas."
          error={errors.tags}
          className="sm:col-span-2"
        >
          <input
            id={fid("tags")}
            className={inputClass}
            value={draft.tags}
            autoComplete="off"
            aria-invalid={errors.tags ? true : undefined}
            aria-describedby={fieldDescribedBy(fid("tags"), {
              hint: true,
              error: errors.tags,
            })}
            onChange={(e) => set("tags", e.target.value)}
            data-testid="family-details-tags"
          />
        </FormField>
      </div>
      {formError && (
        <p role="alert" className="text-xs font-medium text-status-red-800">
          {formError}
        </p>
      )}
      <div className="flex items-center justify-end gap-2">
        {dirty && (
          <span className="text-xs text-rally-muted" data-testid="family-details-dirty">
            Unsaved changes
          </span>
        )}
        <Button
          type="button"
          size="sm"
          variant="ghost"
          disabled={!dirty || save.isPending}
          onClick={() => {
            setDraft(saved);
            setErrors({});
            setFormError(null);
          }}
        >
          Discard
        </Button>
        <Button
          type="submit"
          size="sm"
          disabled={!dirty || save.isPending}
          data-testid="family-details-save"
        >
          {save.isPending ? "Saving…" : "Save details"}
        </Button>
      </div>
    </form>
  );
}
