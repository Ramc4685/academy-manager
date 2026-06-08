import Link from "next/link";

import { brand, copyrightNotice } from "@/lib/brand";

import styles from "./landing.module.css";

const arrowSvg = (
  <svg
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    strokeWidth="2.4"
    strokeLinecap="round"
    strokeLinejoin="round"
    aria-hidden
  >
    <path d="M5 12h14M13 5l7 7-7 7" />
  </svg>
);

export default function LandingPage() {
  return (
    <div className={styles.page}>
      <header className={styles.topbar}>
        <div className={styles.brand}>
          <div className={styles.logomark}>
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none" aria-hidden>
              <path
                d="M12 2 L8 8 L4 6 L8 12 L4 18 L8 16 L12 22 L16 16 L20 18 L16 12 L20 6 L16 8 Z"
                fill="#facc15"
              />
              <circle cx="12" cy="12" r="2.4" fill="#fff" />
            </svg>
          </div>
          <div className={styles.brandText}>
            <span className={styles.b1}>{brand.productName}</span>
            <span className={styles.b2}>Badminton - Operations</span>
          </div>
        </div>
        <div className={styles.topbarRight}>
          <span className={styles.verPill}>
            <span className={styles.dot} />
            Production - Online
          </span>
          <Link href="/login" className={styles.signinLink}>
            Sign in
            <svg
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2.4"
              strokeLinecap="round"
              strokeLinejoin="round"
              aria-hidden
            >
              <path d="M5 12h14M13 5l7 7-7 7" />
            </svg>
          </Link>
        </div>
      </header>

      {/* HERO */}
      <section className={styles.hero}>
        <div>
          <div className={styles.heroEyebrow}>
            <span className={styles.badge}>Live</span>
            Three roles - one operations platform
          </div>
          <h1 className={styles.heroTitle}>
            Run your
            <br />
            <em>badminton</em>
            <br />
            <span className={styles.muted}>academy.</span>
          </h1>
        </div>
        <aside className={styles.heroSide}>
          <p>
            {brand.productName} gives coaches, parents, and admins one production workspace. Mark
            attendance, take payments, manage waitlists, and run the academy from one app.
          </p>
          <div className={styles.ctaRow}>
            <Link href="/login" className={styles.btnPrimary}>
              Sign in
              <span className={styles.arrow}>
                <svg
                  width="12"
                  height="12"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2.6"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  aria-hidden
                >
                  <path d="M5 12h14M13 5l7 7-7 7" />
                </svg>
              </span>
            </Link>
            <a href="#roles" className={styles.btnSecondary}>
              See what&apos;s inside
            </a>
          </div>
          <div className={styles.heroMetaRow}>
            <div className={styles.item}>
              <div className={styles.v}>247</div>
              <div className={styles.l}>Active students</div>
            </div>
            <div className={styles.item}>
              <div className={styles.v}>4</div>
              <div className={styles.l}>Coaches</div>
            </div>
            <div className={styles.item}>
              <div className={styles.v}>
                12<span style={{ color: "#64748b" }}>/wk</span>
              </div>
              <div className={styles.l}>Sessions</div>
            </div>
          </div>
        </aside>
      </section>

      <div className={styles.lane} id="roles">
        <span className={styles.y} />
        <span className={styles.g} />
        <span className={styles.lbl}>01 - Choose your view</span>
        <span className={styles.g} />
        <span className={styles.y} />
      </div>

      <section className={styles.roles}>
        <Link href="/login" className={styles.role}>
          <div className={`${styles.preview} ${styles.pvAdmin}`}>
            <div className={styles.row}>
              <div className={styles.kpi}>
                <div className={styles.l}>Revenue</div>
                <div className={styles.v}>$56.8K</div>
              </div>
              <div className={styles.kpi}>
                <div className={styles.l}>Profit</div>
                <div className={styles.v}>$35.0K</div>
              </div>
            </div>
            <div className={styles.row} style={{ flex: 1, alignItems: "stretch" }}>
              <div className={styles.chart}>
                <div className={styles.chartLbl}>REV - 7 MO</div>
                <svg width="100%" height="36" viewBox="0 0 120 36" preserveAspectRatio="none">
                  <path
                    d="M0,28 L20,24 L40,26 L60,18 L80,14 L100,10 L120,6"
                    stroke="#facc15"
                    strokeWidth="2"
                    fill="none"
                  />
                  <path
                    d="M0,32 L20,30 L40,30 L60,28 L80,26 L100,26 L120,24"
                    stroke="#64748b"
                    strokeWidth="1.5"
                    fill="none"
                    strokeDasharray="2 2"
                  />
                </svg>
              </div>
              <div className={styles.table}>
                <div className={styles.trow}>
                  <span className={styles.nm}>A. Sharma</span>
                  <span className={styles.am}>$480</span>
                </div>
                <div className={styles.trow}>
                  <span className={styles.nm}>K. Rao</span>
                  <span className={styles.am}>$480</span>
                </div>
                <div className={styles.trow}>
                  <span className={styles.nm}>R. Kapoor</span>
                  <span className={styles.am}>$620</span>
                </div>
                <div className={styles.trow}>
                  <span className={styles.nm}>D. Patel</span>
                  <span className={styles.am}>$480</span>
                </div>
              </div>
            </div>
          </div>
          <div className={styles.body}>
            <div className={styles.roleTag}>For admins - Desktop</div>
            <h2>Operations</h2>
            <p className={styles.desc}>
              A data-terminal-grade dashboard. Track payments, expenses, attendance, and waitlists
              from one screen.
            </p>
            <ul className={styles.feats}>
              <li>Live KPI dashboard for revenue, profit, and dues</li>
              <li>Enrollment approvals &amp; waitlist management</li>
              <li>Coach payouts, expenses, P&amp;L reports</li>
            </ul>
            <div className={styles.roleCta}>
              <span className={styles.open}>Open admin</span>
              <span className={styles.arrowChip}>{arrowSvg}</span>
            </div>
          </div>
        </Link>

        <Link href="/register" className={styles.role}>
          <div className={`${styles.preview} ${styles.pvParent}`}>
            <div className={styles.hello}>Tuesday - Good morning</div>
            <div className={styles.name}>Hi, Rohan</div>
            <div className={styles.ringcard}>
              <div className={styles.ringrow}>
                <svg width="48" height="48" viewBox="0 0 64 64" aria-hidden>
                  <circle cx="32" cy="32" r="26" fill="none" stroke="#e2e8f0" strokeWidth="6" />
                  <circle
                    cx="32"
                    cy="32"
                    r="26"
                    fill="none"
                    stroke="#2563eb"
                    strokeWidth="6"
                    strokeDasharray="163.4"
                    strokeDashoffset="9.8"
                    strokeLinecap="round"
                    transform="rotate(-90 32 32)"
                  />
                  <text
                    x="32"
                    y="38"
                    textAnchor="middle"
                    fontFamily="var(--font-outfit), sans-serif"
                    fontWeight="700"
                    fontSize="16"
                    fill="#0f172a"
                  >
                    94%
                  </text>
                </svg>
                <div className={styles.meta}>
                  <div className={styles.l}>AARAV&apos;S MAY</div>
                  <div className={styles.v}>15 / 16</div>
                </div>
              </div>
              <div className={styles.duebar}>
                <div>
                  <div className={styles.lbl}>Next - May 28</div>
                  <div className={styles.amt}>$180.00</div>
                </div>
                <span className={styles.pay}>Autopay on</span>
              </div>
            </div>
          </div>
          <div className={styles.body}>
            <div className={styles.roleTag}>For parents - Mobile</div>
            <h2>Parent portal</h2>
            <p className={styles.desc}>
              Everything a parent needs in one place. Register, pay, track attendance, and message
              the academy.
            </p>
            <ul className={styles.feats}>
              <li>Register and enroll with sibling-friendly onboarding</li>
              <li>Autopay, receipts, and waivers</li>
              <li>Daily attendance &amp; coach notes</li>
            </ul>
            <div className={styles.roleCta}>
              <span className={styles.open}>Register parent</span>
              <span className={styles.arrowChip}>{arrowSvg}</span>
            </div>
          </div>
        </Link>

        <Link href="/login" className={styles.role}>
          <div className={`${styles.preview} ${styles.pvCoach}`}>
            <div className={styles.ch}>
              <span className={styles.ll}>ON COURT</span>
              <span className={styles.now}>4:30 PM - TUE</span>
            </div>
            <div className={styles.nowCard}>
              <div className={styles.meta}>NEXT IN 12 MIN</div>
              <h4>Junior Smash - U10</h4>
              <div className={styles.court}>Court A - 12 of 12</div>
            </div>
            <div className={styles.rows}>
              <div className={styles.pr}>
                <span className={styles.av} style={{ background: "#dbeafe", color: "#1d4ed8" }}>
                  AS
                </span>
                <span className={styles.nm}>Aarav S.</span>
                <span className={styles.statusDot} style={{ background: "#10b981" }} />
              </div>
              <div className={styles.pr}>
                <span className={styles.av} style={{ background: "#fef9c3", color: "#854d0e" }}>
                  DP
                </span>
                <span className={styles.nm}>Diya P.</span>
                <span className={styles.statusDot} style={{ background: "#10b981" }} />
              </div>
              <div className={styles.pr}>
                <span className={styles.av} style={{ background: "#fee2e2", color: "#991b1b" }}>
                  KR
                </span>
                <span className={styles.nm}>Kabir R.</span>
                <span className={styles.statusDot} style={{ background: "#f59e0b" }} />
              </div>
              <div className={`${styles.pr} ${styles.active}`}>
                <span className={styles.av} style={{ background: "#dcfce7", color: "#166534" }}>
                  IM
                </span>
                <span className={styles.nm}>Ishita M.</span>
                <span className={styles.swipe}>SWIPE</span>
              </div>
            </div>
          </div>
          <div className={styles.body}>
            <div className={styles.roleTag}>For coaches - Mobile</div>
            <h2>Field tool</h2>
            <p className={styles.desc}>
              Built for courtside. Mark attendance with a swipe, log notes, and see your payout in
              real-time.
            </p>
            <ul className={styles.feats}>
              <li>One-tap attendance with offline-ready sync</li>
              <li>Per-student notes &amp; progress history</li>
              <li>Live payout calculator &amp; schedule</li>
            </ul>
            <div className={styles.roleCta}>
              <span className={styles.open}>Open coach</span>
              <span className={styles.arrowChip}>{arrowSvg}</span>
            </div>
          </div>
        </Link>
      </section>

      <section className={styles.botStrip}>
        <div className={styles.cell}>
          <div className={styles.l}>Built for</div>
          <div className={styles.v}>USA</div>
          <div className={styles.s}>USD, Stripe, ACH-ready</div>
        </div>
        <div className={styles.cell}>
          <div className={styles.l}>Works offline</div>
          <div className={styles.v}>Courtside</div>
          <div className={styles.s}>Coach tool syncs when back online</div>
        </div>
        <div className={styles.cell}>
          <div className={styles.l}>Mobile-first</div>
          <div className={styles.v}>PWA</div>
          <div className={styles.s}>Install on home screen</div>
        </div>
        <div className={styles.cell}>
          <div className={styles.l}>Single app</div>
          <div className={styles.v}>Unified</div>
          <div className={styles.s}>One web app for every academy role</div>
        </div>
      </section>

      <div className={styles.foot}>
        <span>{copyrightNotice()}</span>
        <div className={styles.right}>
          <Link href="/register">Register</Link>
          <Link href={brand.legalLinks.terms}>Terms</Link>
          <Link href={brand.legalLinks.privacy}>Privacy</Link>
          <Link href={brand.legalLinks.security}>Security</Link>
          <a href={brand.statusUrl}>Status</a>
          <Link href="/login">Sign in</Link>
        </div>
      </div>
    </div>
  );
}
