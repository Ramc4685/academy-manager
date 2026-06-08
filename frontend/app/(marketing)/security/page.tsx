import Link from "next/link";

import { brand, copyrightNotice } from "@/lib/brand";

import styles from "../legal.module.css";

export const metadata = {
  title: `Security | ${brand.productName}`,
  description: `Security overview for ${brand.productName}, owned by ${brand.companyName}.`,
};

export default function SecurityPage() {
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
          <h1 className={styles.title}>Security</h1>
          <p className={styles.intro}>
            {brand.productName} is built as a hosted SaaS product with role-aware access controls,
            tenant isolation, encrypted transport, and audited operational workflows.
          </p>
        </header>

        <div className={styles.content}>
          <section className={styles.section}>
            <h2>Controls</h2>
            <ul>
              <li>HTTPS-only production access.</li>
              <li>Firebase Authentication with server-side token verification.</li>
              <li>Role and membership checks for admin, coach, and parent workflows.</li>
              <li>Explicit CORS allow-listing.</li>
              <li>Audit logging for sensitive authentication, admin, and payment events.</li>
            </ul>
          </section>

          <section className={styles.section}>
            <h2>Responsible Disclosure</h2>
            <p>
              Send security reports to{" "}
              <a href={`mailto:${brand.securityEmail}?subject=SECURITY%20DISCLOSURE`}>
                {brand.securityEmail}
              </a>{" "}
              with the subject line SECURITY DISCLOSURE. Do not access, modify, or exfiltrate data
              that is not yours.
            </p>
          </section>
        </div>

        <footer className={styles.footer}>{copyrightNotice()}</footer>
      </div>
    </main>
  );
}
