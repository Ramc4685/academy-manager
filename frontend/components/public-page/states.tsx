import Link from "next/link";

import type { PublicAcademyNotPublished } from "@/lib/public-page/types";

import { PageFrame, SiteFooter, SiteHeader } from "./chrome";
import styles from "./public-page.module.css";

const NEUTRAL_BRAND = { brand_fill: "#0f172a", brand_on_color: "#ffffff" };

/**
 * The page exists but the owner has not switched it on. Branding only: no
 * venue, classes, prices or form (the API sends nothing else), and noindex.
 */
export function NotPublishedPage({ page }: { page: PublicAcademyNotPublished }) {
  return (
    <PageFrame brand={page.academy} testId="public-page-not-published">
      <SiteHeader brand={page.academy} />
      <main id="main" tabIndex={-1} className={`${styles.wrap} ${styles.stateMain}`}>
        <h1>{page.academy.name}</h1>
        <p>
          The class page is not published yet. Current families can sign in to see schedules and
          pay.
        </p>
        <div className={styles.noticeCta} style={{ marginTop: 24 }}>
          <Link className={`${styles.btn} ${styles.btnBrand}`} href="/login">
            Parent login
          </Link>
        </div>
      </main>
      <SiteFooter />
    </PageFrame>
  );
}

/** The API could not be reached or answered something unexpected. */
export function PublicPageUnavailable() {
  return (
    <PageFrame brand={NEUTRAL_BRAND} testId="public-page-unavailable">
      <main id="main" tabIndex={-1} className={`${styles.wrap} ${styles.stateMain}`}>
        <h1>This page is having trouble</h1>
        <p>Try again in a minute. Current families can still sign in.</p>
        <div className={styles.noticeCta} style={{ marginTop: 24 }}>
          <Link className={`${styles.btn} ${styles.btnBrand}`} href="/" prefetch={false}>
            Try again
          </Link>
          <Link className={`${styles.btn} ${styles.btnLine}`} href="/login">
            Parent login
          </Link>
        </div>
      </main>
      <SiteFooter />
    </PageFrame>
  );
}

/** Streaming fallback while the server reads the page data. */
export function PublicPageLoading() {
  return (
    <PageFrame brand={NEUTRAL_BRAND} testId="public-page-loading">
      <main id="main" tabIndex={-1} className={styles.wrap} aria-busy="true">
        <p className={styles.srOnly} role="status">
          Loading classes
        </p>
        <div className={styles.skeleton} aria-hidden="true">
          <div className={styles.skeletonBar} style={{ width: "60%", height: 36 }} />
          <div className={styles.skeletonBar} style={{ width: "80%" }} />
          <div className={styles.skeletonBar} style={{ width: "70%" }} />
          <div className={styles.skeletonBar} style={{ width: "50%" }} />
        </div>
      </main>
    </PageFrame>
  );
}
