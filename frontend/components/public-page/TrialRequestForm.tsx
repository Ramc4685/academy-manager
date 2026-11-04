"use client";

import { useEffect, useId, useRef, useState, type FormEvent, type ReactElement } from "react";

import { safeHttpsUrl } from "@/lib/public-page/format";
import {
  EMPTY_TRIAL_FORM,
  TRIAL_FIELD_LABEL,
  TRIAL_FIELD_ORDER,
  TRIAL_LIMITS,
  submitTrialRequest,
  validateTrialForm,
  type TrialClassOption,
  type TrialField,
  type TrialFieldErrors,
  type TrialFormValues,
  type TrialSubmitResult,
} from "@/lib/public-page/trial-request";

import { CheckIcon } from "./icons";
import styles from "./public-page.module.css";

type Phase =
  | { kind: "editing" }
  | { kind: "sending" }
  | { kind: "received" }
  | { kind: "closed"; message: string };

const FAILED_MESSAGE =
  "We could not send your request just now. Please try again in a minute, or contact the academy directly.";
const RATE_LIMITED_MESSAGE =
  "Too many requests from this connection. Please wait a few minutes and try again.";

/**
 * The anonymous trial request form (Lane B4, brief section 7 "Free trial
 * form"). Rendered only while trials are open: TrialSection shows the
 * trials-closed notice instead of this slot.
 *
 * Accessibility: every control has a real label; hints and errors are tied
 * to their control with aria-describedby; a failed submit shows an error
 * summary that takes focus and links to each field; success replaces the
 * form in place, takes focus and is announced through a polite live region.
 * The honeypot sits off-screen inside an aria-hidden wrapper, out of the tab
 * order, so neither people nor screen readers meet it.
 */
export function TrialRequestForm({
  academyName,
  classOptions,
  privacyNoticeUrl,
  variant,
  submit = submitTrialRequest,
}: {
  academyName: string;
  classOptions: TrialClassOption[];
  privacyNoticeUrl: string | null;
  /** "trial" (open classes), "waitlist" (all full) or "notify" (none listed). */
  variant: "trial" | "waitlist" | "notify";
  submit?: (values: TrialFormValues) => Promise<TrialSubmitResult>;
}) {
  const uid = useId();
  const id = (field: string) => `trial-${field}-${uid.replace(/[^a-zA-Z0-9_-]/g, "")}`;
  const [values, setValues] = useState<TrialFormValues>(EMPTY_TRIAL_FORM);
  const [errors, setErrors] = useState<TrialFieldErrors>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [phase, setPhase] = useState<Phase>({ kind: "editing" });
  const [summaryTick, setSummaryTick] = useState(0);
  const summaryRef = useRef<HTMLDivElement>(null);
  const doneRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (summaryTick > 0) summaryRef.current?.focus();
  }, [summaryTick]);

  useEffect(() => {
    if (phase.kind === "received" || phase.kind === "closed") doneRef.current?.focus();
  }, [phase.kind]);

  const privacyHref = safeHttpsUrl(privacyNoticeUrl) ?? "/privacy";
  const submitLabel =
    variant === "notify"
      ? "Tell me when classes open"
      : variant === "waitlist"
        ? "Join the waitlist"
        : "Request a free trial";

  function set<K extends keyof TrialFormValues>(key: K, value: TrialFormValues[K]) {
    setValues((current) => ({ ...current, [key]: value }));
  }

  function showErrors(next: TrialFieldErrors, message: string | null) {
    setErrors(next);
    setFormError(message);
    setSummaryTick((tick) => tick + 1);
  }

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (phase.kind === "sending") return;
    const local = validateTrialForm(values);
    if (Object.keys(local).length > 0) {
      showErrors(local, null);
      return;
    }
    setPhase({ kind: "sending" });
    const result = await submit(values);
    switch (result.kind) {
      case "received":
        setErrors({});
        setFormError(null);
        setPhase({ kind: "received" });
        return;
      case "closed":
        setPhase({ kind: "closed", message: result.message });
        return;
      case "invalid":
        setPhase({ kind: "editing" });
        showErrors(result.fields, result.message);
        return;
      case "rate_limited":
        setPhase({ kind: "editing" });
        showErrors({}, RATE_LIMITED_MESSAGE);
        return;
      default:
        setPhase({ kind: "editing" });
        showErrors({}, FAILED_MESSAGE);
    }
  }

  const live = (
    <p className={styles.srOnly} aria-live="polite" data-testid="trial-live-region">
      {phase.kind === "received" ? `Request sent to ${academyName}.` : ""}
    </p>
  );

  let content: ReactElement;
  if (phase.kind === "received") {
    content = (
      <div
        className={styles.trialDone}
        ref={doneRef}
        tabIndex={-1}
        data-testid="trial-request-received"
      >
        <CheckIcon />
        <h3>Thanks, your request is with {academyName}</h3>
        <p>
          {variant === "notify"
            ? "They will email you when the timetable is published."
            : "They will reply by email within one working day to arrange a date."}{" "}
          Nothing is booked or charged yet.
        </p>
        <a className={`${styles.btn} ${styles.btnLine}`} href="#classes">
          Back to classes
        </a>
      </div>
    );
  } else if (phase.kind === "closed") {
    content = (
      <div
        className={styles.trialDone}
        ref={doneRef}
        tabIndex={-1}
        role="status"
        data-testid="trial-request-closed"
      >
        <h3>Free trials are paused</h3>
        <p>{phase.message}</p>
        <a className={`${styles.btn} ${styles.btnLine}`} href="#classes">
          See open classes
        </a>
      </div>
    );
  } else {
    content = renderForm();
  }

  return (
    <div data-testid="trial-request">
      {live}
      {content}
    </div>
  );

  function renderForm(): ReactElement {
    const listed = TRIAL_FIELD_ORDER.filter((field) => errors[field]);
    const hasSummary = listed.length > 0 || formError !== null;
    const sending = phase.kind === "sending";

    function describedBy(field: TrialField, hint?: boolean): string | undefined {
      const ids = [hint ? id(`${field}-hint`) : null, errors[field] ? id(`${field}-error`) : null];
      const joined = ids.filter(Boolean).join(" ");
      return joined || undefined;
    }

    function errorText(field: TrialField) {
      return errors[field] ? (
        <p className={styles.fieldError} id={id(`${field}-error`)}>
          <span className={styles.srOnly}>Error: </span>
          {errors[field]}
        </p>
      ) : null;
    }

    return (
      <form
        className={styles.trialForm}
        noValidate
        onSubmit={onSubmit}
        aria-labelledby="trial-heading"
        data-testid="trial-request-form"
      >
        {hasSummary ? (
          <div
            className={styles.errorSummary}
            ref={summaryRef}
            tabIndex={-1}
            role="alert"
            aria-labelledby={id("summary-title")}
            data-testid="trial-error-summary"
          >
            <h3 id={id("summary-title")}>
              {listed.length > 0 ? "Check these details" : "Your request was not sent"}
            </h3>
            {formError ? <p>{formError}</p> : null}
            {listed.length > 0 ? (
              <ul>
                {listed.map((field) => (
                  <li key={field}>
                    <a href={`#${id(field)}`}>
                      {TRIAL_FIELD_LABEL[field]}: {errors[field]}
                    </a>
                  </li>
                ))}
              </ul>
            ) : null}
          </div>
        ) : null}

        <div className={styles.fieldPair}>
          <div className={styles.field}>
            <label htmlFor={id("name")}>Your name</label>
            <input
              id={id("name")}
              name="name"
              autoComplete="name"
              maxLength={TRIAL_LIMITS.name}
              required
              aria-required="true"
              aria-invalid={errors.name ? true : undefined}
              aria-describedby={describedBy("name")}
              value={values.name}
              onChange={(e) => set("name", e.target.value)}
            />
            {errorText("name")}
          </div>
          <div className={styles.field}>
            <label htmlFor={id("email")}>Email</label>
            <input
              id={id("email")}
              name="email"
              type="email"
              inputMode="email"
              autoComplete="email"
              maxLength={TRIAL_LIMITS.email}
              required
              aria-required="true"
              aria-invalid={errors.email ? true : undefined}
              aria-describedby={describedBy("email")}
              value={values.email}
              onChange={(e) => set("email", e.target.value)}
            />
            {errorText("email")}
          </div>
        </div>

        <div className={styles.fieldPair}>
          <div className={styles.field}>
            <label htmlFor={id("phone")}>
              Phone <span className={styles.optional}>(optional)</span>
            </label>
            <input
              id={id("phone")}
              name="phone"
              type="tel"
              inputMode="tel"
              autoComplete="tel"
              maxLength={TRIAL_LIMITS.phone}
              aria-invalid={errors.phone ? true : undefined}
              aria-describedby={describedBy("phone")}
              value={values.phone}
              onChange={(e) => set("phone", e.target.value)}
            />
            {errorText("phone")}
          </div>
          <div className={styles.field}>
            <label htmlFor={id("player_age")}>Player&apos;s age</label>
            <input
              id={id("player_age")}
              name="player_age"
              inputMode="numeric"
              autoComplete="off"
              maxLength={TRIAL_LIMITS.age}
              required
              aria-required="true"
              aria-invalid={errors.player_age ? true : undefined}
              aria-describedby={describedBy("player_age", true)}
              value={values.player_age}
              onChange={(e) => set("player_age", e.target.value)}
            />
            <p className={styles.fieldHint} id={id("player_age-hint")}>
              We do not ask for the player&apos;s name here.
            </p>
            {errorText("player_age")}
          </div>
        </div>

        {classOptions.length > 0 ? (
          <div className={styles.field}>
            <label htmlFor={id("class_id")}>
              Class <span className={styles.optional}>(optional)</span>
            </label>
            <select
              id={id("class_id")}
              name="class_id"
              aria-invalid={errors.class_id ? true : undefined}
              aria-describedby={describedBy("class_id")}
              value={values.class_id}
              onChange={(e) => set("class_id", e.target.value)}
            >
              <option value="">Not sure, please suggest one</option>
              {classOptions.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
            {errorText("class_id")}
          </div>
        ) : null}

        <div className={styles.field}>
          <label htmlFor={id("message")}>
            Anything the coach should know <span className={styles.optional}>(optional)</span>
          </label>
          <textarea
            id={id("message")}
            name="message"
            maxLength={TRIAL_LIMITS.message}
            aria-invalid={errors.message ? true : undefined}
            aria-describedby={describedBy("message")}
            value={values.message}
            onChange={(e) => set("message", e.target.value)}
          />
          {errorText("message")}
        </div>

        <div className={styles.honeypot} aria-hidden="true">
          <label htmlFor={id("website")}>Leave this field empty</label>
          <input
            id={id("website")}
            name="website"
            type="text"
            tabIndex={-1}
            autoComplete="off"
            value={values.website}
            onChange={(e) => set("website", e.target.value)}
          />
        </div>

        <div className={styles.check}>
          <input
            id={id("contact_about_request")}
            name="contact_about_request"
            type="checkbox"
            required
            aria-required="true"
            aria-invalid={errors.contact_about_request ? true : undefined}
            aria-describedby={describedBy("contact_about_request")}
            checked={values.contact_about_request}
            onChange={(e) => set("contact_about_request", e.target.checked)}
          />
          <label htmlFor={id("contact_about_request")}>
            {academyName} may contact me about this request.
          </label>
          {errorText("contact_about_request")}
        </div>

        <div className={styles.check}>
          <input
            id={id("marketing_opt_in")}
            name="marketing_opt_in"
            type="checkbox"
            checked={values.marketing_opt_in}
            onChange={(e) => set("marketing_opt_in", e.target.checked)}
          />
          <label htmlFor={id("marketing_opt_in")}>
            Also send me news and offers from {academyName}{" "}
            <span className={styles.optional}>(optional)</span>
          </label>
        </div>

        <button
          type="submit"
          className={`${styles.btn} ${styles.btnBrand} ${styles.trialSubmit}`}
          aria-disabled={sending ? true : undefined}
          data-testid="trial-request-submit"
        >
          {sending ? "Sending..." : submitLabel}
        </button>

        <p className={styles.fine}>
          We only use these details to reply to this request.{" "}
          <a href={privacyHref} data-testid="trial-privacy-link">
            Privacy notice
          </a>
        </p>
      </form>
    );
  }
}
