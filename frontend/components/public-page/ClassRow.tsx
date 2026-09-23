import Link from "next/link";

import {
  formatAgeBand,
  formatPrice,
  formatSeatBand,
  formatTimeRange,
  formatWhen,
  truncate,
} from "@/lib/public-page/format";
import { TRIAL_ANCHOR } from "@/lib/public-page/page-model";
import type { PublicClass } from "@/lib/public-page/types";

import { PinIcon, UserIcon } from "./icons";
import styles from "./public-page.module.css";

const TONE_CLASS = { ok: styles.chipOk, few: styles.chipFew, queue: styles.chipQueue } as const;

/**
 * One class, one row (brief section 8: rows, not cards). The coach name
 * arrives already shaped by the class's coach display setting; the row
 * renders it as given and never re-derives it.
 */
export function ClassRow({
  cls,
  currency,
  trialsOpen,
}: {
  cls: PublicClass;
  currency: string;
  trialsOpen: boolean;
}) {
  const when = formatWhen(cls);
  const time = formatTimeRange(cls.start_time, cls.end_time);
  const price = formatPrice(cls.price, currency);
  const seats = formatSeatBand(cls.seats);
  const full = seats?.full === true;
  const title = truncate(cls.title, 60);
  const label = [title, when, time].filter(Boolean).join(", ");
  const age = formatAgeBand(cls.age_band);
  const where = cls.location ?? cls.venue_address;

  return (
    <li className={styles.classRow} data-testid="public-class-row" data-public-class-id={cls.public_id}>
      <div>
        <h4 className={styles.classTitle}>{title}</h4>
        <p className={styles.when}>
          {when}
          {time ? <small>{time}</small> : null}
        </p>
      </div>
      <div className={styles.meta}>
        {cls.coach_name ? (
          <span>
            <UserIcon />
            {cls.coach_name}
          </span>
        ) : null}
        {where ? (
          <span>
            <PinIcon />
            {where}
          </span>
        ) : null}
        {age ? <span>{age}</span> : null}
        {cls.level ? <span>{cls.level}</span> : null}
      </div>
      <div className={styles.priceRow}>
        {price ? (
          <span className={styles.price} data-testid="public-class-price">
            {price.amount} {price.period ? <small>{price.period}</small> : null}
          </span>
        ) : null}
        {seats ? (
          <span className={`${styles.chip} ${TONE_CLASS[seats.tone]}`} data-testid="public-class-seats">
            {seats.text}
          </span>
        ) : null}
      </div>
      <div className={styles.actions}>
        {full ? (
          trialsOpen ? (
            <a
              className={`${styles.btn} ${styles.btnSm} ${styles.btnBrand}`}
              href={TRIAL_ANCHOR}
              data-public-class-id={cls.public_id}
              aria-label={`Join waitlist: ${label}`}
            >
              Join waitlist
            </a>
          ) : (
            <Link
              className={`${styles.btn} ${styles.btnSm} ${styles.btnBrand}`}
              href="/register"
              aria-label={`Join waitlist: ${label}`}
            >
              Join waitlist
            </Link>
          )
        ) : (
          <>
            {trialsOpen ? (
              <a
                className={`${styles.btn} ${styles.btnSm} ${styles.btnBrand}`}
                href={TRIAL_ANCHOR}
                data-public-class-id={cls.public_id}
                aria-label={`Try a class free: ${label}`}
              >
                Try a class free
              </a>
            ) : null}
            <Link
              className={`${styles.btn} ${styles.btnSm} ${styles.btnLine}`}
              href="/register"
              aria-label={`Register for ${label}`}
            >
              Register
            </Link>
          </>
        )}
      </div>
    </li>
  );
}
