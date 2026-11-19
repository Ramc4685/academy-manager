import Link from "next/link";

import { brand, copyrightNotice } from "@/lib/brand";

import styles from "../legal.module.css";

export const metadata = {
  title: "CourtMastr Academy Support",
  description: "Get help with the CourtMastr Academy app.",
};

export default function SupportPage() {
  return (
    <main className={styles.page}>
      <div className={styles.shell}>
        <nav className={styles.nav} aria-label="Support">
          <Link href="/" className={styles.brand}>
            {brand.productName}
          </Link>
          <div className={styles.navLinks}>
            <Link href="/privacy">Privacy</Link>
            <Link href="/login">Sign in</Link>
          </div>
        </nav>

        <header className={styles.header}>
          <p className={styles.eyebrow}>{brand.companyName}</p>
          <h1 className={styles.title}>CourtMastr Academy Support</h1>
          <p className={styles.intro}>Get help signing in, report an app issue, or suggest a feature.</p>
        </header>

        <div className={styles.content}>
          <section className={styles.section}>
            <h2>Contact support</h2>
            <p>
              Email{" "}
              <a href={`mailto:${brand.supportEmail}`} className="underline">{brand.supportEmail}</a>.
              Include your device type and what happened. Keep passwords and payment details private.
            </p>
            <p>For class schedules, enrollment, or billing questions, contact your academy.</p>
            <p>
              To close your account, follow the{" "}
              <Link href="/account-deletion" className="underline">account deletion instructions</Link>.
            </p>
          </section>
        </div>

        <footer className={styles.footer}>{copyrightNotice()}</footer>
      </div>
    </main>
  );
}
