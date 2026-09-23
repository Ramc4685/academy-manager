import Link from "next/link";
import type { CSSProperties, ReactNode } from "react";

import { monogram, safeHexColor, safeHttpsUrl } from "@/lib/public-page/format";
import type { PrimaryAction } from "@/lib/public-page/page-model";
import type { PublicBrand } from "@/lib/public-page/types";

import { ShuttleIcon } from "./icons";
import styles from "./public-page.module.css";

/**
 * The two backend-computed colours, validated as hex and set as CSS custom
 * properties. No colour is derived here (brief section 3; the one derivation
 * function is backend/v2/shared/comms/colour.py readable_button_colors).
 */
export function brandStyle(brand: Pick<PublicBrand, "brand_fill" | "brand_on_color">): CSSProperties {
  return {
    ["--brand-fill" as string]: safeHexColor(brand.brand_fill, "#0f172a"),
    ["--brand-on" as string]: safeHexColor(brand.brand_on_color, "#ffffff"),
  } as CSSProperties;
}

export function PageFrame({
  brand,
  children,
  testId,
}: {
  brand: Pick<PublicBrand, "brand_fill" | "brand_on_color">;
  children: ReactNode;
  testId: string;
}) {
  return (
    <div className={styles.page} style={brandStyle(brand)} data-testid={testId}>
      <a className={styles.skip} href="#main">
        Skip to content
      </a>
      {children}
    </div>
  );
}

export interface NavItem {
  href: string;
  label: string;
}

export function SiteHeader({
  brand,
  nav = [],
  action,
}: {
  brand: Pick<PublicBrand, "name" | "logo_url">;
  nav?: NavItem[];
  action?: PrimaryAction | null;
}) {
  const logo = safeHttpsUrl(brand.logo_url);
  return (
    <header className={`${styles.top} ${styles.night}`}>
      <div className={`${styles.wrap} ${styles.topRow}`}>
        <Link className={styles.brandmark} href="/">
          {logo ? (
            <img className={styles.logoImage} src={logo} alt="" width={36} height={36} />
          ) : (
            <span className={styles.logo} aria-hidden="true">
              {monogram(brand.name)}
            </span>
          )}
          <span className={styles.brandName}>{brand.name}</span>
        </Link>
        {nav.length > 0 ? (
          <nav className={styles.topNav} aria-label="Page sections">
            {nav.map((item) => (
              <a key={item.href} href={item.href}>
                {item.label}
              </a>
            ))}
          </nav>
        ) : null}
        <Link className={styles.login} href="/login">
          Parent login
        </Link>
        {action ? (
          <a className={`${styles.btn} ${styles.btnSm} ${styles.btnBrand} ${styles.topCta}`} href={action.href}>
            {action.label}
          </a>
        ) : null}
      </div>
    </header>
  );
}

/** Fixed footer with the non-removable CourtMastr credit (brief section 9). */
export function SiteFooter({ privacyUrl }: { privacyUrl?: string | null }) {
  const privacy = safeHttpsUrl(privacyUrl) ?? "/privacy";
  return (
    <footer className={`${styles.footer} ${styles.night}`}>
      <div className={`${styles.wrap} ${styles.footerInner}`}>
        <ul aria-label="Footer">
          <li>
            <Link href="/login">Parent login</Link>
          </li>
          <li>
            <Link href="/register">Register</Link>
          </li>
          <li>
            <a href={privacy}>Privacy</a>
          </li>
          <li>
            <Link href="/terms">Terms</Link>
          </li>
        </ul>
        <p className={styles.credit} data-testid="courtmastr-credit">
          <ShuttleIcon />
          Bookings and payments by CourtMastr
        </p>
      </div>
    </footer>
  );
}
