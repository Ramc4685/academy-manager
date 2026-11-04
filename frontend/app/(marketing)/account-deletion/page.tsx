import Link from "next/link";

import { brand, copyrightNotice } from "@/lib/brand";

import styles from "../legal.module.css";

export const metadata = {
  title: `Delete your account | ${brand.productName}`,
  description: `How to delete your ${brand.productName} account and what happens to your data.`,
};

/** Public deletion instructions; the URL Google Play's data-deletion form points at. */
export default function AccountDeletionPage() {
  const requestHref = `mailto:${brand.supportEmail}?subject=${encodeURIComponent(
    "Account deletion request",
  )}`;

  return (
    <main className={styles.page}>
      <div className={styles.shell}>
        <nav className={styles.nav} aria-label="Legal">
          <Link href="/" className={styles.brand}>
            {brand.productName}
          </Link>
          <div className={styles.navLinks}>
            <Link href="/terms">Terms</Link>
            <Link href="/privacy">Privacy</Link>
            <Link href="/login">Sign in</Link>
          </div>
        </nav>

        <header className={styles.header}>
          <p className={styles.eyebrow}>{brand.companyName}</p>
          <h1 className={styles.title}>Delete your account</h1>
          <p className={styles.intro}>
            You can delete your {brand.productName} account yourself, in the app or on the web, at
            any time.
          </p>
        </header>

        <div className={styles.content}>
          <section className={styles.section}>
            <h2>Delete it in the app</h2>
            <ol>
              <li>Sign in to {brand.productName}.</li>
              <li>Open Profile and scroll to Delete account.</li>
              <li>Type DELETE, confirm your password or sign-in, and tap Delete my account.</li>
            </ol>
            <p>You are signed out at once and cannot sign in again, in any academy.</p>
          </section>

          <section className={styles.section}>
            <h2>Can&apos;t sign in?</h2>
            <p>
              Email <a href={requestHref}>{brand.supportEmail}</a> from the address on your account
              and ask us to delete it. We confirm it is you, then delete it the same way.
            </p>
          </section>

          <section className={styles.section}>
            <h2>What is deleted</h2>
            <ul>
              <li>Your name, email address, phone number and sign-in.</li>
              <li>Saved cards and bank accounts.</li>
              <li>Family contacts, notes and email preferences the academy kept for you.</li>
              <li>
                Your children&apos;s names, birth dates and medical notes, unless another parent on
                the family still uses the account.
              </li>
            </ul>
            <p>
              This happens 14 days after you ask. If you change your mind before then, contact
              support at <a href={`mailto:${brand.supportEmail}`}>{brand.supportEmail}</a> to
              restore your account. Your academy cannot restore it for you.
            </p>
          </section>

          <section className={styles.section}>
            <h2>What is kept</h2>
            <ul>
              <li>
                Invoices and payment records, for 7 years, because tax law requires it. Any balance
                you owe stays with the academy.
              </li>
              <li>
                Attendance and skill records, with names removed, so the academy&apos;s class
                history stays accurate.
              </li>
              <li>Messages you sent, shown as from &ldquo;Deleted user&rdquo;.</li>
            </ul>
          </section>
        </div>

        <footer className={styles.footer}>{copyrightNotice()}</footer>
      </div>
    </main>
  );
}
