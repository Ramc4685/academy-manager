import Link from "next/link";
import type { ReactNode } from "react";

import { CLASSES_ANCHOR } from "@/lib/public-page/page-model";

import { CheckIcon } from "./icons";
import styles from "./public-page.module.css";

/**
 * The `#trial` section. PublicTenantPage puts the anonymous trial request
 * form (Lane B4, TrialRequestForm) in the `form` slot while trials are open;
 * with no form supplied the slot points the visitor at Register so the
 * primary action is never a dead end. Trials closed: the notice, no form.
 */
export function TrialSection({
  academyName,
  trialsOpen,
  hasClasses,
  allFull,
  form,
}: {
  academyName: string;
  trialsOpen: boolean;
  hasClasses: boolean;
  allFull: boolean;
  form?: ReactNode;
}) {
  if (!trialsOpen) {
    return (
      <section className={styles.trial} id="trial" aria-labelledby="trial-heading" data-testid="trial-closed">
        <div className={styles.wrap}>
          <div className={styles.notice} style={{ marginTop: 0 }}>
            <h2 id="trial-heading">Free trials are paused right now</h2>
            <p>
              {academyName} is not running trial sessions at the moment. You can still register for
              any class with open places.
            </p>
            <div className={styles.noticeCta}>
              {hasClasses ? (
                <a className={`${styles.btn} ${styles.btnBrand}`} href={CLASSES_ANCHOR}>
                  See open classes
                </a>
              ) : null}
              <Link className={`${styles.btn} ${styles.btnLine}`} href="/login">
                Parent login
              </Link>
            </div>
          </div>
        </div>
      </section>
    );
  }

  const heading = !hasClasses
    ? "Hear first when classes open"
    : allFull
      ? "Join the waitlist"
      : "Book a free trial class";
  const lead = !hasClasses
    ? "Leave your details and the academy will let you know when the timetable is published."
    : allFull
      ? "Tell the academy which class you want. Places are offered in the order families asked."
      : "Pick a class and tell the academy who is coming. They will confirm a date with you.";

  return (
    <section className={styles.trial} id="trial" aria-labelledby="trial-heading" data-testid="trial-section">
      <div className={`${styles.wrap} ${styles.trialGrid}`}>
        <div>
          <h2 id="trial-heading">{heading}</h2>
          <p className={styles.trialLead}>{lead}</p>
          {hasClasses ? (
            <ul className={styles.ticks}>
              <li>
                <CheckIcon />
                No payment details needed
              </li>
              <li>
                <CheckIcon />
                Nothing is booked until the academy confirms
              </li>
            </ul>
          ) : null}
        </div>
        <div className={styles.trialSlot} data-slot="trial-request-form">
          {form ?? (
            <>
              <p>Create a parent account to choose a class and ask about a first session.</p>
              <Link className={`${styles.btn} ${styles.btnBrand}`} href="/register">
                Register
              </Link>
            </>
          )}
        </div>
      </div>
    </section>
  );
}
