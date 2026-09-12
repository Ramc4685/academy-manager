"use client";

import { useEffect, useState } from "react";
import { useMutation } from "@tanstack/react-query";

import { Button, DialogActions, DialogError, Field, RallyModal } from "@/components/ds";
import type { AddInvoiceLineRequest } from "@/lib/api/admin";
import type { FamilyStudent } from "@/lib/api/admin-families";
import { parseDollarsToCents } from "@/lib/money";

import {
  currentPeriod,
  defaultDueDate,
  enrollmentOptions,
  periodLabel,
  type EnrollmentOption,
} from "./family-view";

const inputClass =
  "w-full rounded-lg border border-rally-line bg-white px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-rally-cobalt-600/30";

const LINE_TYPES = ["tuition", "equipment", "fee", "adjustment"];

export interface CreateInvoiceResult {
  student_id: string;
  enrollment_id: string | null;
  period: string;
  due_date: string;
}

/**
 * A blank draft to hang charges on. The draft starts at $0 — the charges are
 * added next — so this dialog only settles who and when.
 */
export function CreateInvoiceDialog({
  students,
  open,
  dueDays,
  onClose,
  onSubmit,
}: {
  students: FamilyStudent[];
  open: boolean;
  /** The academy's "Days until due" Billing rule (#739). */
  dueDays: number;
  onClose: () => void;
  onSubmit: (result: CreateInvoiceResult) => Promise<unknown>;
}) {
  const onlyStudentId = students.length === 1 ? students[0].student_id : "";
  const [studentId, setStudentId] = useState(onlyStudentId);
  const [enrollmentId, setEnrollmentId] = useState("");
  const [period, setPeriod] = useState(() => currentPeriod());
  const [dueDate, setDueDate] = useState(() => defaultDueDate(new Date(), dueDays));

  useEffect(() => {
    if (open) {
      setStudentId(onlyStudentId);
      setEnrollmentId("");
      setPeriod(currentPeriod());
      setDueDate(defaultDueDate(new Date(), dueDays));
    }
  }, [open, onlyStudentId, dueDays]);

  const options = enrollmentOptions(students).filter(
    (option) => !studentId || option.student_id === studentId,
  );
  const mutation = useMutation({
    mutationFn: () =>
      onSubmit({
        student_id: studentId,
        enrollment_id: enrollmentId || null,
        period,
        due_date: dueDate,
      }),
  });
  const disabled = !studentId || !period || !dueDate || mutation.isPending;

  return (
    <RallyModal
      open={open}
      onOpenChange={(v) => !v && onClose()}
      title="Create invoice"
      description="Makes an empty draft. Add the charges next, then send it."
      overline="Invoice"
    >
      <form
        data-testid="create-invoice-dialog"
        className="space-y-4"
        onSubmit={(e) => {
          e.preventDefault();
          if (!disabled) mutation.mutate();
        }}
      >
        <Field label="Student" required>
          <select
            data-testid="create-invoice-student"
            className={inputClass}
            value={studentId}
            onChange={(e) => {
              setStudentId(e.target.value);
              setEnrollmentId("");
            }}
          >
            <option value="">Pick a student</option>
            {students.map((student) => (
              <option key={student.student_id} value={student.student_id}>
                {student.name}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Class (optional)">
          <select
            data-testid="create-invoice-enrollment"
            className={inputClass}
            value={enrollmentId}
            onChange={(e) => setEnrollmentId(e.target.value)}
          >
            <option value="">Not tied to a class</option>
            {options.map((option) => (
              <option key={option.enrollment_id} value={option.enrollment_id}>
                {option.label}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Month" required>
          <input
            data-testid="create-invoice-period"
            type="month"
            className={inputClass}
            value={period}
            onChange={(e) => setPeriod(e.target.value)}
          />
        </Field>
        <Field label="Due date" required>
          <input
            data-testid="create-invoice-due-date"
            type="date"
            className={inputClass}
            value={dueDate}
            onChange={(e) => setDueDate(e.target.value)}
          />
        </Field>
        {mutation.isError && <DialogError message={(mutation.error as Error).message} />}
        <DialogActions>
          <Button variant="secondary" size="sm" type="button" onClick={onClose}>
            Cancel
          </Button>
          <Button size="sm" type="submit" disabled={disabled} data-testid="create-invoice-submit">
            {mutation.isPending ? "Working…" : "Create draft"}
          </Button>
        </DialogActions>
      </form>
    </RallyModal>
  );
}

export interface AddChargePrefill {
  description: string;
  line_type: string;
  unit_amount_cents: number | null;
}

/** One line on a draft invoice: what it is, how many, and what each one costs. */
export function AddChargeDialog({
  open,
  subject,
  prefill,
  onClose,
  onSubmit,
}: {
  open: boolean;
  /** "Sep 2026 · Arjun" — names the invoice the charge lands on. */
  subject: string;
  prefill: AddChargePrefill;
  onClose: () => void;
  onSubmit: (payload: AddInvoiceLineRequest) => Promise<unknown>;
}) {
  const [description, setDescription] = useState(prefill.description);
  const [lineType, setLineType] = useState(prefill.line_type);
  const [quantity, setQuantity] = useState("1");
  const [amount, setAmount] = useState("");

  useEffect(() => {
    if (open) {
      setDescription(prefill.description);
      setLineType(prefill.line_type);
      setQuantity("1");
      setAmount(
        prefill.unit_amount_cents != null ? (prefill.unit_amount_cents / 100).toFixed(2) : "",
      );
    }
  }, [open, prefill.description, prefill.line_type, prefill.unit_amount_cents]);

  const amountCents = parseDollarsToCents(amount);
  const quantityNumber = Number.parseInt(quantity, 10);
  const mutation = useMutation({
    mutationFn: () =>
      onSubmit({
        description: description.trim(),
        line_type: lineType,
        quantity: quantityNumber,
        unit_amount_cents: amountCents,
      }),
  });
  const disabled =
    description.trim().length === 0 ||
    !Number.isFinite(quantityNumber) ||
    quantityNumber < 1 ||
    amountCents < 0 ||
    mutation.isPending;

  return (
    <RallyModal
      open={open}
      onOpenChange={(v) => !v && onClose()}
      title="Add charge"
      description="Adds a line to this draft. The total updates as you add lines."
      overline="Invoice"
    >
      <form
        data-testid="add-charge-dialog"
        className="space-y-4"
        onSubmit={(e) => {
          e.preventDefault();
          if (!disabled) mutation.mutate();
        }}
      >
        <p className="text-sm text-rally-ink" data-testid="add-charge-subject">
          {subject}
        </p>
        <Field label="What it is" required>
          <input
            data-testid="add-charge-description"
            className={inputClass}
            value={description}
            onChange={(e) => setDescription(e.target.value)}
          />
        </Field>
        <Field label="Kind" required>
          <select
            data-testid="add-charge-type"
            className={inputClass}
            value={lineType}
            onChange={(e) => setLineType(e.target.value)}
          >
            {LINE_TYPES.map((type) => (
              <option key={type} value={type}>
                {type}
              </option>
            ))}
          </select>
        </Field>
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="How many" required>
            <input
              data-testid="add-charge-quantity"
              type="number"
              min="1"
              step="1"
              className={inputClass}
              value={quantity}
              onChange={(e) => setQuantity(e.target.value)}
            />
          </Field>
          <Field label="Price each" required>
            <input
              data-testid="add-charge-amount"
              inputMode="decimal"
              className={inputClass}
              value={amount}
              onChange={(e) => setAmount(e.target.value)}
              placeholder="0.00"
            />
          </Field>
        </div>
        {mutation.isError && <DialogError message={(mutation.error as Error).message} />}
        <DialogActions>
          <Button variant="secondary" size="sm" type="button" onClick={onClose}>
            Cancel
          </Button>
          <Button size="sm" type="submit" disabled={disabled} data-testid="add-charge-submit">
            {mutation.isPending ? "Working…" : "Add charge"}
          </Button>
        </DialogActions>
      </form>
    </RallyModal>
  );
}

export interface BillPeriodResult {
  period: string;
  due_date: string;
}

/** One month of tuition for one class, priced by the backend. */
export function BillPeriodDialog({
  open,
  option,
  dueDays,
  onClose,
  onSubmit,
}: {
  open: boolean;
  option: EnrollmentOption;
  /** The academy's "Days until due" Billing rule (#739). */
  dueDays: number;
  onClose: () => void;
  onSubmit: (result: BillPeriodResult) => Promise<unknown>;
}) {
  const [period, setPeriod] = useState(() => currentPeriod());
  const [dueDate, setDueDate] = useState(() => defaultDueDate(new Date(), dueDays));

  useEffect(() => {
    if (open) {
      setPeriod(currentPeriod());
      setDueDate(defaultDueDate(new Date(), dueDays));
    }
  }, [open, option.enrollment_id, dueDays]);

  const mutation = useMutation({ mutationFn: () => onSubmit({ period, due_date: dueDate }) });
  const disabled = !period || !dueDate || mutation.isPending;

  return (
    <RallyModal
      open={open}
      onOpenChange={(v) => !v && onClose()}
      title="Bill this month"
      description="Creates a draft invoice with this class's monthly tuition on it. Nothing is emailed until you send it."
      overline="Invoice"
    >
      <form
        data-testid="bill-period-dialog"
        className="space-y-4"
        onSubmit={(e) => {
          e.preventDefault();
          if (!disabled) mutation.mutate();
        }}
      >
        <p className="text-sm text-rally-ink" data-testid="bill-period-subject">
          {option.label} · {periodLabel(period)}
        </p>
        <p className="text-xs text-rally-muted" data-testid="bill-period-draft-warning">
          The backend prices the month the way the monthly run would — a class that starts
          mid-month is prorated — so check the draft before sending it. The monthly billing run
          skips this class for this month while the draft sits unsent — send it or void it.
        </p>
        <Field label="Month" required>
          <input
            data-testid="bill-period-period"
            type="month"
            className={inputClass}
            value={period}
            onChange={(e) => setPeriod(e.target.value)}
          />
        </Field>
        <Field label="Due date" required>
          <input
            data-testid="bill-period-due-date"
            type="date"
            className={inputClass}
            value={dueDate}
            onChange={(e) => setDueDate(e.target.value)}
          />
        </Field>
        {mutation.isError && <DialogError message={(mutation.error as Error).message} />}
        <DialogActions>
          <Button variant="secondary" size="sm" type="button" onClick={onClose}>
            Cancel
          </Button>
          <Button size="sm" type="submit" disabled={disabled} data-testid="bill-period-submit">
            {mutation.isPending ? "Working…" : "Create draft"}
          </Button>
        </DialogActions>
      </form>
    </RallyModal>
  );
}
