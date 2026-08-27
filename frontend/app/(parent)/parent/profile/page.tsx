"use client";

import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { Button } from "@/components/ds/button";
import { FormField, fieldDescribedBy } from "@/components/ds/form-field";
import { Skeleton } from "@/components/ds/skeleton";
import { useToast } from "@/components/ds/toast";
import { queryKeys } from "@/lib/query/keys";
import {
  confirmParentEmail,
  getParentProfile,
  updateParentChild,
  updateParentProfile,
  type ParentSelfChild,
  type ParentSelfProfile,
} from "@/lib/api/parent";

const NO_MEDICAL_SENTINEL = "__none_declared__";

const inputClass = "mt-1 w-full rounded-lg border border-rally-line px-3 py-2 text-sm";

function errorMessage(err: unknown, fallback: string): string {
  return err instanceof Error && err.message ? err.message : fallback;
}

export default function ParentProfilePage() {
  const { data, isLoading, isError } = useQuery({
    queryKey: queryKeys.parent.profile(),
    queryFn: getParentProfile,
  });

  return (
    <section data-testid="parent-profile">
      <div className="mb-4 animate-fade-in-up">
        <h1 className="font-display text-2xl font-bold tracking-tight text-rally-ink">My profile</h1>
        <p className="text-sm mt-0.5 text-rally-muted">Keep your details and your children&apos;s up to date</p>
      </div>

      {isError ? (
        <p className="text-sm text-status-red-600">Could not load your profile.</p>
      ) : isLoading || !data ? (
        <div className="space-y-4">
          <div className="rounded-2xl border border-rally-line bg-white p-4">
            <Skeleton variant="line" width="8rem" />
            <Skeleton variant="line" width="12rem" />
          </div>
        </div>
      ) : (
        <div className="space-y-4 stagger-children">
          <AboutYouCard profile={data} />
          {data.children.map((child) => (
            <ChildCard key={child.student_id} child={child} />
          ))}
        </div>
      )}
    </section>
  );
}

function GapBadge({ count }: { count: number }) {
  if (count === 0) return null;
  return (
    <span className="inline-block rounded-full px-2 py-0.5 text-xs font-semibold bg-amber-100 text-amber-800">
      {count} missing
    </span>
  );
}

function AboutYouCard({ profile }: { profile: ParentSelfProfile }) {
  const queryClient = useQueryClient();
  const { toast } = useToast();
  const [displayName, setDisplayName] = useState(profile.display_name);
  const [phone, setPhone] = useState(profile.phone ?? "");

  useEffect(() => {
    setDisplayName(profile.display_name);
    setPhone(profile.phone ?? "");
  }, [profile.display_name, profile.phone]);

  const saveMutation = useMutation({
    mutationFn: () => updateParentProfile({ display_name: displayName, phone }),
    onSuccess: (updated) => {
      queryClient.setQueryData(queryKeys.parent.profile(), updated);
      toast({ kind: "success", title: "Saved" });
    },
  });

  const confirmMutation = useMutation({
    mutationFn: confirmParentEmail,
    onSuccess: (updated) => {
      queryClient.setQueryData(queryKeys.parent.profile(), updated);
      toast({ kind: "success", title: "Email confirmed" });
    },
  });

  const saveError = saveMutation.isError
    ? errorMessage(saveMutation.error, "Could not save your details.")
    : null;

  return (
    <article className="rounded-2xl border border-rally-line bg-white p-4 animate-fade-in-up">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="font-bold text-rally-ink text-[15px]">About you</h2>
        <GapBadge count={profile.gaps.parent.length} />
      </div>

      <form
        className="space-y-3"
        onSubmit={(e) => {
          e.preventDefault();
          saveMutation.mutate();
        }}
      >
        <FormField label="Your name" htmlFor="profile-name" error={saveError}>
          <input
            id="profile-name"
            className={inputClass}
            aria-describedby={fieldDescribedBy("profile-name", { error: saveError })}
            value={displayName}
            onChange={(e) => setDisplayName(e.target.value)}
            required
          />
        </FormField>
        <FormField label="Phone" htmlFor="profile-phone">
          <input
            id="profile-phone"
            type="tel"
            className={inputClass}
            value={phone}
            onChange={(e) => setPhone(e.target.value)}
          />
        </FormField>

        <div className="rounded-lg border border-rally-line bg-rally-paper px-3 py-2">
          <p className="text-xs font-semibold text-rally-muted">Login email</p>
          <p className="text-sm text-rally-ink">{profile.email}</p>
          {profile.email_confirmed ? (
            <p className="mt-1 text-xs font-medium text-status-green-700">Confirmed</p>
          ) : (
            <div className="mt-2 flex flex-wrap items-center gap-2">
              <span className="text-xs text-rally-muted">Is this still your email?</span>
              <Button
                type="button"
                variant="secondary"
                size="sm"
                onClick={() => confirmMutation.mutate()}
                disabled={confirmMutation.isPending}
              >
                Yes, that&apos;s right
              </Button>
            </div>
          )}
        </div>

        <div className="flex justify-end">
          <Button type="submit" variant="primary" size="sm" disabled={saveMutation.isPending}>
            Save
          </Button>
        </div>
      </form>
    </article>
  );
}

function ChildCard({ child }: { child: ParentSelfChild }) {
  const queryClient = useQueryClient();
  const { toast } = useToast();
  const [dateOfBirth, setDateOfBirth] = useState(child.date_of_birth ?? "");
  const [emergencyContactName, setEmergencyContactName] = useState(child.emergency_contact_name ?? "");
  const [emergencyContactPhone, setEmergencyContactPhone] = useState(child.emergency_contact_phone ?? "");
  const [medicalNotes, setMedicalNotes] = useState(child.medical_notes ?? "");
  const [noMedicalConditions, setNoMedicalConditions] = useState(child.no_medical_conditions);

  const gapCount =
    (dateOfBirth ? 0 : 1) +
    (emergencyContactName ? 0 : 1) +
    (emergencyContactPhone ? 0 : 1) +
    (noMedicalConditions || medicalNotes ? 0 : 1);

  const saveMutation = useMutation({
    mutationFn: () =>
      updateParentChild(child.student_id, {
        date_of_birth: dateOfBirth || undefined,
        emergency_contact_name: emergencyContactName,
        emergency_contact_phone: emergencyContactPhone,
        medical_notes: noMedicalConditions ? NO_MEDICAL_SENTINEL : medicalNotes,
        no_medical_conditions: noMedicalConditions,
      }),
    onSuccess: (updated) => {
      queryClient.setQueryData(queryKeys.parent.profile(), updated);
      toast({ kind: "success", title: `Saved ${child.full_name}` });
    },
  });

  const saveError = saveMutation.isError
    ? errorMessage(saveMutation.error, "Could not save these details.")
    : null;

  return (
    <article className="rounded-2xl border border-rally-line bg-white p-4 animate-fade-in-up">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="font-bold text-rally-ink text-[15px]">{child.full_name}</h2>
        <GapBadge count={gapCount} />
      </div>

      <form
        className="space-y-3"
        onSubmit={(e) => {
          e.preventDefault();
          saveMutation.mutate();
        }}
      >
        <FormField label="Date of birth" htmlFor={`dob-${child.student_id}`} error={saveError}>
          <input
            id={`dob-${child.student_id}`}
            className={inputClass}
            aria-describedby={fieldDescribedBy(`dob-${child.student_id}`, { error: saveError })}
            placeholder="YYYY-MM-DD"
            pattern="\d{4}-\d{2}-\d{2}"
            maxLength={10}
            value={dateOfBirth}
            onChange={(e) => setDateOfBirth(e.target.value)}
          />
        </FormField>
        <FormField label="Emergency contact name" htmlFor={`ecn-${child.student_id}`}>
          <input
            id={`ecn-${child.student_id}`}
            className={inputClass}
            value={emergencyContactName}
            onChange={(e) => setEmergencyContactName(e.target.value)}
          />
        </FormField>
        <FormField label="Emergency contact phone" htmlFor={`ecp-${child.student_id}`}>
          <input
            id={`ecp-${child.student_id}`}
            type="tel"
            className={inputClass}
            value={emergencyContactPhone}
            onChange={(e) => setEmergencyContactPhone(e.target.value)}
          />
        </FormField>
        <FormField label="Medical notes" htmlFor={`med-${child.student_id}`}>
          <textarea
            id={`med-${child.student_id}`}
            className={inputClass}
            rows={2}
            placeholder="Allergies, conditions, or anything a coach should know"
            disabled={noMedicalConditions}
            value={noMedicalConditions ? "" : medicalNotes}
            onChange={(e) => setMedicalNotes(e.target.value)}
          />
        </FormField>
        <label className="flex items-center gap-2 text-sm text-rally-ink">
          <input
            type="checkbox"
            checked={noMedicalConditions}
            onChange={(e) => {
              setNoMedicalConditions(e.target.checked);
              if (e.target.checked) setMedicalNotes("");
            }}
          />
          No known conditions or allergies
        </label>

        <div className="flex justify-end">
          <Button type="submit" variant="primary" size="sm" disabled={saveMutation.isPending}>
            Save
          </Button>
        </div>
      </form>
    </article>
  );
}
