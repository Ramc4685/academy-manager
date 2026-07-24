"use client";

import { useEffect, useMemo, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { RefreshCw } from "lucide-react";

import {
  changeAdminStudentParent,
  type AdminUserView,
  type ChangeAdminStudentParentRequest,
} from "@/lib/api/admin";
import {
  updateAdminStudent,
  type AdminStudentDetail,
  type UpdateAdminStudentRequest,
} from "@/lib/api/v2/students";
import { Button } from "@/components/ds/button";

import { DetailList } from "./DetailList";

type EditableStatus = "active" | "paused" | "inactive" | "cancelled";
type StudentEditMode = "overview" | "training" | "family";

function StudentEditForm({
  mode,
  student,
  onSaved,
}: {
  mode: StudentEditMode;
  student: AdminStudentDetail;
  onSaved: () => void;
}) {
  const [fullName, setFullName] = useState(student.full_name);
  const [dateOfBirth, setDateOfBirth] = useState(student.date_of_birth ?? "");
  const [status, setStatus] = useState<EditableStatus>(
    (student.status as EditableStatus) ?? "active",
  );
  const [notes, setNotes] = useState(student.notes ?? "");
  const [previousExperience, setPreviousExperience] = useState(
    student.previous_experience ?? "",
  );
  const [medicalNotes, setMedicalNotes] = useState(
    student.medical_notes ?? "",
  );
  const [emergencyContactName, setEmergencyContactName] = useState(
    student.emergency_contact_name ?? "",
  );
  const [emergencyContactPhone, setEmergencyContactPhone] = useState(
    student.emergency_contact_phone ?? "",
  );
  const [tShirtSize, setTShirtSize] = useState(student.t_shirt_size ?? "");
  const [reason, setReason] = useState("Admin profile update");
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [submitOk, setSubmitOk] = useState(false);

  // Keep local state in sync if the server-side data refreshes.
  useEffect(() => {
    setFullName(student.full_name);
    setDateOfBirth(student.date_of_birth ?? "");
    setStatus((student.status as EditableStatus) ?? "active");
    setNotes(student.notes ?? "");
    setPreviousExperience(student.previous_experience ?? "");
    setMedicalNotes(student.medical_notes ?? "");
    setEmergencyContactName(student.emergency_contact_name ?? "");
    setEmergencyContactPhone(student.emergency_contact_phone ?? "");
    setTShirtSize(student.t_shirt_size ?? "");
  }, [
    student.full_name,
    student.date_of_birth,
    student.status,
    student.notes,
    student.previous_experience,
    student.medical_notes,
    student.emergency_contact_name,
    student.emergency_contact_phone,
    student.t_shirt_size,
  ]);

  const mutation = useMutation({
    mutationFn: (payload: UpdateAdminStudentRequest) =>
      updateAdminStudent(student.student_id, payload),
    onSuccess: () => {
      setSubmitError(null);
      setSubmitOk(true);
      onSaved();
    },
    onError: (err: unknown) => {
      setSubmitOk(false);
      const message =
        err instanceof Error ? err.message : "Could not save changes.";
      setSubmitError(message);
    },
  });

  const dirtyFields = {
    fullName: fullName !== student.full_name,
    dateOfBirth: dateOfBirth !== (student.date_of_birth ?? ""),
    status: status !== student.status,
    notes: (notes ?? "") !== (student.notes ?? ""),
    previousExperience:
      previousExperience !== (student.previous_experience ?? ""),
    medicalNotes: medicalNotes !== (student.medical_notes ?? ""),
    emergencyContactName:
      emergencyContactName !== (student.emergency_contact_name ?? ""),
    emergencyContactPhone:
      emergencyContactPhone !== (student.emergency_contact_phone ?? ""),
    tShirtSize: tShirtSize !== (student.t_shirt_size ?? ""),
  };

  const dirty =
    mode === "overview"
      ? dirtyFields.fullName ||
        dirtyFields.dateOfBirth ||
        dirtyFields.status ||
        dirtyFields.notes
      : mode === "training"
        ? dirtyFields.previousExperience ||
          dirtyFields.medicalNotes ||
          dirtyFields.emergencyContactName ||
          dirtyFields.emergencyContactPhone
        : dirtyFields.tShirtSize;

  const reset = () => {
    setFullName(student.full_name);
    setDateOfBirth(student.date_of_birth ?? "");
    setStatus((student.status as EditableStatus) ?? "active");
    setNotes(student.notes ?? "");
    setPreviousExperience(student.previous_experience ?? "");
    setMedicalNotes(student.medical_notes ?? "");
    setEmergencyContactName(student.emergency_contact_name ?? "");
    setEmergencyContactPhone(student.emergency_contact_phone ?? "");
    setTShirtSize(student.t_shirt_size ?? "");
    setSubmitError(null);
    setSubmitOk(false);
  };

  return (
    <form
      className="mt-3 space-y-4"
      data-testid={`admin-student-${mode}-edit-form`}
      onSubmit={(e) => {
        e.preventDefault();
        setSubmitOk(false);
        setSubmitError(null);
        const payload: UpdateAdminStudentRequest = {};
        if (mode === "overview") {
          if (dirtyFields.fullName) payload.full_name = fullName;
          if (dirtyFields.dateOfBirth)
            payload.date_of_birth = dateOfBirth || null;
          if (dirtyFields.status) payload.status = status;
          if (dirtyFields.notes) payload.notes = notes || null;
        }
        if (mode === "training") {
          if (dirtyFields.previousExperience)
            payload.previous_experience = previousExperience;
          if (dirtyFields.medicalNotes)
            payload.medical_notes = medicalNotes;
          if (dirtyFields.emergencyContactName)
            payload.emergency_contact_name = emergencyContactName;
          if (dirtyFields.emergencyContactPhone)
            payload.emergency_contact_phone = emergencyContactPhone;
        }
        if (mode === "family" && dirtyFields.tShirtSize) {
          payload.t_shirt_size = tShirtSize;
        }
        payload.reason = reason;
        mutation.mutate(payload);
      }}
    >
      {mode === "overview" && (
        <>
          <Field label="Full name" htmlFor="student-full-name">
            <input
              id="student-full-name"
              value={fullName}
              onChange={(e) => setFullName(e.target.value)}
              className="h-10 w-full rounded-md border border-neutral-200 bg-white px-3 text-sm text-rally-base outline-none focus:border-rally-cobalt-600 focus:ring-2 focus:ring-rally-cobalt-600/15"
              required
              minLength={1}
              maxLength={120}
            />
          </Field>

          <Field label="Date of birth" htmlFor="student-dob">
            <input
              id="student-dob"
              type="date"
              value={dateOfBirth}
              onChange={(e) => setDateOfBirth(e.target.value)}
              className="h-10 w-full rounded-md border border-neutral-200 bg-white px-3 text-sm text-rally-base outline-none focus:border-rally-cobalt-600 focus:ring-2 focus:ring-rally-cobalt-600/15"
            />
          </Field>

          <Field label="Status" htmlFor="student-status">
            <select
              id="student-status"
              value={status}
              onChange={(e) => setStatus(e.target.value as EditableStatus)}
              className="h-10 w-full rounded-md border border-neutral-200 bg-white px-3 text-sm text-rally-base outline-none focus:border-rally-cobalt-600 focus:ring-2 focus:ring-rally-cobalt-600/15"
            >
              <option value="active">Active</option>
              <option value="paused">Paused</option>
              <option value="inactive">Inactive</option>
              <option value="cancelled">Cancelled</option>
            </select>
          </Field>

          <Field label="Internal notes" htmlFor="student-notes">
            <textarea
              id="student-notes"
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              rows={4}
              maxLength={2000}
              className="w-full rounded-md border border-neutral-200 bg-white px-3 py-2 text-sm text-rally-base outline-none focus:border-rally-cobalt-600 focus:ring-2 focus:ring-rally-cobalt-600/15"
              placeholder="Allergies, behavioural notes, comms preferences..."
            />
          </Field>
        </>
      )}

      {mode === "training" && (
        <>
          <Field label="Previous experience" htmlFor="student-previous-experience">
            <textarea
              id="student-previous-experience"
              value={previousExperience}
              onChange={(e) => setPreviousExperience(e.target.value)}
              rows={3}
              maxLength={1000}
              className="w-full rounded-md border border-neutral-200 bg-white px-3 py-2 text-sm text-rally-base outline-none focus:border-rally-cobalt-600 focus:ring-2 focus:ring-rally-cobalt-600/15"
              placeholder="Prior coaching, club play, school teams"
            />
          </Field>

          <Field label="Medical notes" htmlFor="student-medical-notes">
            <textarea
              id="student-medical-notes"
              value={medicalNotes}
              onChange={(e) => setMedicalNotes(e.target.value)}
              rows={3}
              maxLength={1000}
              className="w-full rounded-md border border-neutral-200 bg-white px-3 py-2 text-sm text-rally-base outline-none focus:border-rally-cobalt-600 focus:ring-2 focus:ring-rally-cobalt-600/15"
              placeholder="Allergies, injuries, health notes"
            />
          </Field>

          <div className="grid gap-4 sm:grid-cols-2">
            <Field
              label="Emergency contact name"
              htmlFor="student-emergency-contact-name"
            >
              <input
                id="student-emergency-contact-name"
                value={emergencyContactName}
                onChange={(e) => setEmergencyContactName(e.target.value)}
                className="h-10 w-full rounded-md border border-neutral-200 bg-white px-3 text-sm text-rally-base outline-none focus:border-rally-cobalt-600 focus:ring-2 focus:ring-rally-cobalt-600/15"
                maxLength={120}
              />
            </Field>

            <Field
              label="Emergency contact phone"
              htmlFor="student-emergency-contact-phone"
            >
              <input
                id="student-emergency-contact-phone"
                value={emergencyContactPhone}
                onChange={(e) => setEmergencyContactPhone(e.target.value)}
                className="h-10 w-full rounded-md border border-neutral-200 bg-white px-3 text-sm text-rally-base outline-none focus:border-rally-cobalt-600 focus:ring-2 focus:ring-rally-cobalt-600/15"
                maxLength={40}
              />
            </Field>
          </div>
        </>
      )}

      {mode === "family" && (
        <Field label="T-shirt size" htmlFor="student-t-shirt-size">
          <input
            id="student-t-shirt-size"
            value={tShirtSize}
            onChange={(e) => setTShirtSize(e.target.value)}
            className="h-10 w-full rounded-md border border-neutral-200 bg-white px-3 text-sm text-rally-base outline-none focus:border-rally-cobalt-600 focus:ring-2 focus:ring-rally-cobalt-600/15"
            maxLength={20}
          />
        </Field>
      )}

      <Field label="Reason" htmlFor="student-edit-reason">
        <input
          id="student-edit-reason"
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          className="h-10 w-full rounded-md border border-neutral-200 bg-white px-3 text-sm text-rally-base outline-none focus:border-rally-cobalt-600 focus:ring-2 focus:ring-rally-cobalt-600/15"
          required
          maxLength={500}
        />
      </Field>

      {submitError && (
        <p
          role="alert"
          data-testid="admin-student-edit-error"
          className="rounded-md border border-red-200 bg-red-50 p-2 text-sm text-red-700"
        >
          {submitError}
        </p>
      )}
      {submitOk && (
        <p
          role="status"
          data-testid="admin-student-edit-ok"
          className="rounded-md border border-emerald-200 bg-emerald-50 p-2 text-sm text-emerald-800"
        >
          Saved.
        </p>
      )}

      <div className="flex items-center gap-2">
        <Button
          type="submit"
          variant="primary"
          size="sm"
          disabled={!dirty || mutation.isPending}
          icon={
            mutation.isPending ? (
              <RefreshCw className="size-3.5 animate-spin" />
            ) : undefined
          }
        >
          {mutation.isPending ? "Saving…" : "Save changes"}
        </Button>
        {dirty && (
          <Button
            type="button"
            variant="secondary"
            size="sm"
            onClick={reset}
          >
            Reset
          </Button>
        )}
      </div>
    </form>
  );
}

function ChangeParentPanel({
  student,
  parents,
  parentsLoading,
  parentsError,
  onSaved,
}: {
  student: AdminStudentDetail;
  parents: AdminUserView[];
  parentsLoading: boolean;
  parentsError: boolean;
  onSaved: () => void;
}) {
  const activeParents = useMemo(
    () => parents.filter((parent) => parent.status === "active"),
    [parents],
  );
  const [search, setSearch] = useState("");
  const [parentId, setParentId] = useState("");
  const [reason, setReason] = useState("Admin parent account correction");
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [submitOk, setSubmitOk] = useState(false);
  const [warnings, setWarnings] = useState<string[]>([]);

  const filteredParents = useMemo(() => {
    const normalized = search.trim().toLowerCase();
    if (!normalized) return activeParents;
    return activeParents.filter((parent) => {
      const haystack =
        `${parent.display_name} ${parent.email} ${parent.phone ?? ""}`.toLowerCase();
      return haystack.includes(normalized);
    });
  }, [activeParents, search]);

  useEffect(() => {
    if (
      !parentId ||
      filteredParents.some((parent) => parent.user_id === parentId)
    )
      return;
    setParentId("");
  }, [filteredParents, parentId]);

  useEffect(() => {
    setParentId("");
    setSubmitError(null);
    setSubmitOk(false);
    setWarnings([]);
  }, [student.student_id, student.parent_id]);

  const selectedParent = activeParents.find(
    (parent) => parent.user_id === parentId,
  );
  const canSubmit = Boolean(
    parentId && parentId !== student.parent_id && reason.trim(),
  );

  const mutation = useMutation({
    mutationFn: (payload: ChangeAdminStudentParentRequest) =>
      changeAdminStudentParent(student.student_id, payload),
    onSuccess: (result) => {
      setSubmitError(null);
      setSubmitOk(true);
      setWarnings(result.warnings);
      setParentId("");
      setSearch("");
      onSaved();
    },
    onError: (err: unknown) => {
      setSubmitOk(false);
      setWarnings([]);
      setSubmitError(
        err instanceof Error ? err.message : "Could not change parent account.",
      );
    },
  });

  return (
    <form
      className="mt-3 space-y-4"
      data-testid="admin-student-change-parent-form"
      onSubmit={(event) => {
        event.preventDefault();
        if (!canSubmit) return;
        setSubmitError(null);
        setSubmitOk(false);
        setWarnings([]);
        mutation.mutate({ parent_id: parentId, reason: reason.trim() });
      }}
    >
      <DetailList
        rows={[
          {
            label: "Current parent",
            value:
              student.parent_name ?? student.parent_email ?? "Parent on file",
          },
          {
            label: "Available parents",
            value: parentsLoading ? "Loading" : String(activeParents.length),
          },
        ]}
      />

      {parentsError && (
        <p
          role="alert"
          className="rounded-md border border-red-200 bg-red-50 p-2 text-sm text-red-700"
        >
          Could not load parent accounts.
        </p>
      )}

      <Field label="Search parents" htmlFor="student-parent-search">
        <input
          id="student-parent-search"
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          className="h-10 w-full rounded-md border border-neutral-200 bg-white px-3 text-sm text-rally-base outline-none focus:border-rally-cobalt-600 focus:ring-2 focus:ring-rally-cobalt-600/15"
          placeholder="Name, email, or phone"
          disabled={parentsLoading || parentsError}
        />
      </Field>

      <Field label="New parent" htmlFor="student-parent-id">
        <select
          id="student-parent-id"
          value={parentId}
          onChange={(event) => {
            setParentId(event.target.value);
            setSubmitOk(false);
            setSubmitError(null);
          }}
          className="h-10 w-full rounded-md border border-neutral-200 bg-white px-3 text-sm text-rally-base outline-none focus:border-rally-cobalt-600 focus:ring-2 focus:ring-rally-cobalt-600/15"
          disabled={
            parentsLoading || parentsError || filteredParents.length === 0
          }
          required
        >
          <option value="">
            {parentsLoading
              ? "Loading parents..."
              : filteredParents.length === 0
                ? "No active parents found"
                : "Select a parent"}
          </option>
          {filteredParents.map((parent) => (
            <option key={parent.user_id} value={parent.user_id}>
              {parent.display_name} ({parent.email})
            </option>
          ))}
        </select>
      </Field>

      {selectedParent && (
        <div className="rounded-md border border-neutral-200 bg-neutral-50 p-3 text-sm">
          <div className="font-medium text-rally-ink">
            {selectedParent.display_name}
          </div>
          <div className="text-rally-muted">{selectedParent.email}</div>
          {selectedParent.phone && (
            <div className="text-rally-muted">{selectedParent.phone}</div>
          )}
        </div>
      )}

      <Field label="Reason" htmlFor="student-parent-reason">
        <input
          id="student-parent-reason"
          value={reason}
          onChange={(event) => setReason(event.target.value)}
          className="h-10 w-full rounded-md border border-neutral-200 bg-white px-3 text-sm text-rally-base outline-none focus:border-rally-cobalt-600 focus:ring-2 focus:ring-rally-cobalt-600/15"
          required
          maxLength={500}
        />
      </Field>

      {submitError && (
        <p
          role="alert"
          data-testid="admin-student-change-parent-error"
          className="rounded-md border border-red-200 bg-red-50 p-2 text-sm text-red-700"
        >
          {submitError}
        </p>
      )}
      {submitOk && (
        <p
          role="status"
          data-testid="admin-student-change-parent-ok"
          className="rounded-md border border-emerald-200 bg-emerald-50 p-2 text-sm text-emerald-800"
        >
          Parent account changed.
        </p>
      )}
      {warnings.length > 0 && (
        <div className="rounded-md border border-amber-200 bg-amber-50 p-2 text-sm text-amber-900">
          {warnings.map((warning) => (
            <div key={warning}>{warning}</div>
          ))}
        </div>
      )}

      <Button
        type="submit"
        variant="primary"
        size="sm"
        disabled={
          !canSubmit || mutation.isPending || parentsLoading || parentsError
        }
        icon={
          mutation.isPending ? (
            <RefreshCw className="size-3.5 animate-spin" />
          ) : undefined
        }
      >
        {mutation.isPending ? "Changing..." : "Change parent"}
      </Button>
    </form>
  );
}

function Field({
  label,
  htmlFor,
  children,
}: {
  label: string;
  htmlFor: string;
  children: React.ReactNode;
}) {
  return (
    <div className="space-y-1.5">
      <label
        htmlFor={htmlFor}
        className="font-mono text-[10px] font-bold uppercase tracking-overline text-rally-muted"
      >
        {label}
      </label>
      {children}
    </div>
  );
}

export { StudentEditForm, ChangeParentPanel, Field };
