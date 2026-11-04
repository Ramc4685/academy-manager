import Link from "next/link";

import { brand, copyrightNotice } from "@/lib/brand";

import styles from "../legal.module.css";

export const metadata = {
  title: `Privacy | ${brand.productName}`,
  description: `Privacy policy for ${brand.productName}, owned by ${brand.companyName}.`,
};

// Must match the App Store privacy label and Play data-safety answers
// (docs/plans/2026-11-03-store-listing.md section 3); change both together.
export default function PrivacyPage() {
  const contact = <a href={`mailto:${brand.supportEmail}`}>{brand.supportEmail}</a>;

  return (
    <main className={styles.page}>
      <div className={styles.shell}>
        <nav className={styles.nav} aria-label="Legal">
          <Link href="/" className={styles.brand}>
            {brand.productName}
          </Link>
          <div className={styles.navLinks}>
            <Link href="/terms">Terms</Link>
            <Link href="/security">Security</Link>
            <Link href="/account-deletion">Delete account</Link>
            <Link href="/login">Sign in</Link>
          </div>
        </nav>

        <header className={styles.header}>
          <p className={styles.eyebrow}>{brand.companyName}</p>
          <h1 className={styles.title}>Privacy</h1>
          <p className={styles.intro}>
            {brand.productName} is software that sports academies use to run classes, attendance,
            payments and messages with families. This policy explains what we collect, why, who
            helps us process it, how long we keep it, and how to delete it.
          </p>
        </header>

        <div className={styles.content}>
          <p className={styles.notice}>
            Draft pending legal review. Questions: {contact}.
          </p>

          <section className={styles.section}>
            <h2>Who is responsible</h2>
            <p>
              Each academy decides what it records about its families and students, and is
              responsible for that information. {brand.companyName} runs {brand.productName} on the
              academy&apos;s behalf. {brand.companyName} is responsible for your sign-in account
              itself. Contact your academy first about records it keeps; contact us at {contact} about
              your account or this policy.
            </p>
          </section>

          <section className={styles.section}>
            <h2>What we collect</h2>
            <ul>
              <li>Account details: name, email address, phone number and a user ID.</li>
              <li>
                Children&apos;s details, entered by a parent or the academy, never by the child:
                name, date of birth and, if the parent chooses, medical notes for the coach.
              </li>
              <li>
                Payments: cards and bank accounts are entered with Stripe. We store only the card
                brand and last four digits, plus invoices and payment history.
              </li>
              <li>Messages and absence notes between families and academy staff.</li>
              <li>Signed waivers: the typed name, time, IP address and browser.</li>
              <li>Attendance and skill progress recorded by coaches.</li>
              <li>A push notification token, if you allow notifications in the app.</li>
              <li>
                Crash and performance reports, linked to your user ID only, to fix faults.
              </li>
              <li>Photos and logos that academy staff upload for the academy&apos;s page.</li>
            </ul>
            <p>
              We do not show ads, sell data, track you across other apps or websites, or collect
              your location, contacts or camera. Children do not sign in.
            </p>
          </section>

          <section className={styles.section}>
            <h2>How we use it</h2>
            <p>
              To run the service: sign you in, enroll students, take attendance, bill and collect
              payments, send class and billing messages, keep a record of signed waivers, prevent
              abuse and fix faults. We do not use it for advertising.
            </p>
          </section>

          <section className={styles.section}>
            <h2>Who helps us process it</h2>
            <p>These providers process data only to run {brand.productName} for us:</p>
            <ul>
              <li>Google Firebase: sign-in and push notifications.</li>
              <li>Stripe: card and bank payments.</li>
              <li>Resend: email delivery.</li>
              <li>Sentry: crash reports and diagnostics.</li>
              <li>Fly.io and Cloudflare: hosting.</li>
              <li>MongoDB Atlas: database.</li>
            </ul>
            <p>Your academy can see the records it keeps about your family.</p>
          </section>

          <section className={styles.section}>
            <h2>How long we keep it</h2>
            <ul>
              <li>Account and family details: while the account is open.</li>
              <li>
                Invoices, payment records and audit logs: 7 years, as tax and accounting law
                requires.
              </li>
              <li>Signed waivers: kept as the academy&apos;s legal record.</li>
              <li>Data exports: 7 days.</li>
            </ul>
          </section>

          <section className={styles.section}>
            <h2>Deleting your account</h2>
            <p>
              Delete your account in the app under Profile, or follow the steps on{" "}
              <Link href="/account-deletion">the account deletion page</Link>. You are signed out
              at once. Your personal details are removed 14 days later; until then the academy can
              restore the account if you ask. Invoices and payment records stay for 7 years, and
              attendance and skill records stay with names removed.
            </p>
          </section>

          <section className={styles.section}>
            <h2>Security</h2>
            <p>
              All traffic is encrypted with HTTPS. Access is limited by role and academy. See{" "}
              <Link href="/security">Security</Link>.
            </p>
          </section>

          <section className={styles.section}>
            <h2>Your choices and requests</h2>
            <p>
              You can update your details in your profile, turn off push notifications in your
              device settings, and ask for a copy or correction of your information at {contact}.
            </p>
          </section>
        </div>

        <footer className={styles.footer}>{copyrightNotice()}</footer>
      </div>
    </main>
  );
}
