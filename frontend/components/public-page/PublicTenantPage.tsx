import Link from "next/link";
import type { ReactNode } from "react";

import {
  ageSpan,
  formatAgeBand,
  mapsSearchUrl,
  monogram,
  weeklyClassCount,
} from "@/lib/public-page/format";
import {
  CLASSES_ANCHOR,
  allClasses,
  classGroups,
  describePublishedPage,
  faqEntries,
} from "@/lib/public-page/page-model";
import { serializeJsonLd } from "@/lib/public-page/structured-data";
import type { PublicAcademyPage } from "@/lib/public-page/types";

import { ClassRow } from "./ClassRow";
import { PageFrame, SiteFooter, SiteHeader, type NavItem } from "./chrome";
import { ArrowIcon, CheckIcon, CourtDrawing, PinIcon, PlusIcon } from "./icons";
import styles from "./public-page.module.css";
import { TrialSection } from "./TrialSection";

function lowerFirst(value: string): string {
  return value.charAt(0).toLowerCase() + value.slice(1);
}

/**
 * The published public academy page (brief sections 2 and 7): hero, classes
 * grouped by program, the trial section, how joining works, coaches, FAQ,
 * find us, and the fixed footer credit. Server-rendered; no client fetch.
 */
export function PublicTenantPage({
  page,
  jsonLd,
  trialForm,
}: {
  page: PublicAcademyPage;
  jsonLd: unknown;
  trialForm?: ReactNode;
}) {
  const { academy } = page;
  const view = describePublishedPage(page);
  const classes = allClasses(page);
  const groups = classGroups(page);
  const faq = faqEntries(page);
  const span = formatAgeBand(
    ageSpan([...page.programs.map((p) => p.age_band), ...classes.map((c) => c.age_band)]),
  );
  const perWeek = weeklyClassCount(classes);
  const address = academy.venue.address;
  const hours = academy.venue.hours_text;
  const hasVisit = Boolean(address || hours);

  const nav: NavItem[] = [{ href: CLASSES_ANCHOR, label: "Classes" }];
  if (view.coaches.length > 0) nav.push({ href: "#coaches", label: "Coaches" });
  nav.push({ href: "#faq", label: "FAQ" });
  if (hasVisit) nav.push({ href: "#visit", label: "Find us" });

  const headline = span
    ? `Coaching for ${lowerFirst(span)} at ${academy.name}.`
    : `Coaching at ${academy.name}.`;
  const lede = !view.hasClasses
    ? "The new timetable is on its way."
    : page.page.show_price
      ? "See every class, what it costs and when it runs."
      : "See every class and when it runs.";

  const facts: string[] = [];
  if (span) facts.push(span);
  if (perWeek > 0) facts.push(perWeek === 1 ? "1 class a week" : `${perWeek} classes a week`);
  if (view.trialsOpen && view.hasClasses) facts.push("First class free");

  return (
    <PageFrame brand={academy} testId="public-academy-page">
      <script
        type="application/ld+json"
        // JSON-LD is data, not script; serializeJsonLd escapes <, > and &.
        dangerouslySetInnerHTML={{ __html: serializeJsonLd(jsonLd) }}
      />
      <SiteHeader brand={academy} nav={nav} action={view.primary} />
      <div className={`${styles.hero} ${styles.night}`}>
        <div className={`${styles.wrap} ${styles.heroInner}`}>
          <h1 className={styles.heroTitle}>{headline}</h1>
          <p className={styles.lede}>{lede}</p>
          <div className={styles.heroCta}>
            <a className={`${styles.btn} ${styles.btnBrand}`} href={view.primary.href} data-testid="hero-primary-action">
              {view.primary.label}
              <ArrowIcon />
            </a>
            {view.hasClasses && view.primary.href !== CLASSES_ANCHOR ? (
              <a className={`${styles.btn} ${styles.btnGhostNight}`} href={CLASSES_ANCHOR}>
                {page.page.show_price ? "See classes and prices" : "See classes"}
              </a>
            ) : null}
          </div>
          {facts.length > 0 || address ? (
            <ul className={styles.facts} aria-label="At a glance">
              {facts.map((fact) => (
                <li key={fact}>
                  <CheckIcon />
                  {fact}
                </li>
              ))}
              {address ? (
                <li>
                  <PinIcon />
                  {address}
                </li>
              ) : null}
            </ul>
          ) : null}
        </div>
        <CourtDrawing />
      </div>
      <div className={styles.lane} />

      <main id="main" tabIndex={-1}>
        <section className={styles.section} id="classes" aria-labelledby="classes-heading">
          <div className={styles.wrap}>
            <div className={styles.secHead}>
              <h2 id="classes-heading">{page.page.show_price ? "Classes and prices" : "Classes"}</h2>
            </div>
            {!view.hasClasses ? (
              <div className={styles.notice} data-testid="no-classes-published">
                <h3>The new timetable is on its way</h3>
                <p>
                  {academy.name} has not published classes yet.
                  {view.trialsOpen ? " Leave your details below and hear first when they open." : null}
                </p>
              </div>
            ) : (
              <>
                {page.page.show_price ? (
                  <p className={styles.secLead}>Each price shows what it covers.</p>
                ) : null}
                {view.allFull ? (
                  <div className={styles.notice} data-testid="all-classes-full">
                    <h3>Every class is full right now</h3>
                    <p>Places open up as families move on. Joining a waitlist costs nothing.</p>
                  </div>
                ) : null}
                {groups.map((group) => {
                  const groupAge = group.program ? formatAgeBand(group.program.age_band) : null;
                  const sub = [group.level, groupAge].filter(Boolean).join(" · ");
                  return (
                    <div className={styles.program} key={group.key}>
                      <div className={styles.programHead}>
                        <h3>{group.name}</h3>
                        {sub ? <p>{sub}</p> : null}
                      </div>
                      {group.description ? (
                        <p className={styles.programDescription}>{group.description}</p>
                      ) : null}
                      <ul>
                        {group.classes.map((cls) => (
                          <ClassRow
                            key={cls.public_id}
                            cls={cls}
                            currency={academy.currency}
                            trialsOpen={view.trialsOpen}
                          />
                        ))}
                      </ul>
                    </div>
                  );
                })}
              </>
            )}
          </div>
        </section>

        <TrialSection
          academyName={academy.name}
          trialsOpen={view.trialsOpen}
          hasClasses={view.hasClasses}
          allFull={view.allFull}
          form={trialForm}
        />

        <section className={styles.section} aria-labelledby="joining-heading">
          <div className={styles.wrap}>
            <div className={styles.secHead}>
              <h2 id="joining-heading">How joining works</h2>
            </div>
            <ol className={styles.steps}>
              {view.trialsOpen ? (
                <li>
                  <span className={styles.stepNumber} aria-hidden="true">1</span>
                  <b>Try a class</b>
                  <span>One free session in a real class, so you can see if the level fits.</span>
                </li>
              ) : null}
              <li>
                <span className={styles.stepNumber} aria-hidden="true">{view.trialsOpen ? 2 : 1}</span>
                <b>Register online</b>
                <span>Create a parent account, add the player and choose the class.</span>
              </li>
              <li>
                <span className={styles.stepNumber} aria-hidden="true">{view.trialsOpen ? 3 : 2}</span>
                <b>Pay online</b>
                <span>
                  Prices are {view.pricePeriodLabel} unless a class says otherwise, paid through the parent
                  account.
                </span>
              </li>
            </ol>
          </div>
        </section>

        {view.coaches.length > 0 ? (
          <section className={styles.section} id="coaches" aria-labelledby="coaches-heading">
            <div className={styles.wrap}>
              <div className={styles.secHead}>
                <h2 id="coaches-heading">Coaches</h2>
              </div>
              <ul className={styles.coaches} data-testid="public-coaches">
                {view.coaches.map((name) => (
                  <li key={name}>
                    <span className={styles.avatar} aria-hidden="true">
                      {monogram(name.replace(/^coach\s+/i, ""))}
                    </span>
                    {name}
                  </li>
                ))}
              </ul>
            </div>
          </section>
        ) : null}

        <section className={`${styles.section} ${styles.faq}`} id="faq" aria-labelledby="faq-heading">
          <div className={styles.wrap}>
            <div className={styles.secHead}>
              <h2 id="faq-heading">Questions parents ask</h2>
            </div>
            {faq.map((entry) => (
              <details key={entry.question}>
                <summary>
                  {entry.question}
                  <PlusIcon />
                </summary>
                <p>{entry.answer}</p>
              </details>
            ))}
          </div>
        </section>

        {hasVisit ? (
          <section className={styles.section} id="visit" aria-labelledby="visit-heading">
            <div className={styles.wrap}>
              <div className={styles.secHead}>
                <h2 id="visit-heading">Find us</h2>
              </div>
              <dl className={styles.visit}>
                {address ? (
                  <div>
                    <dt>Where</dt>
                    <dd>
                      {address}
                      <br />
                      <a href={mapsSearchUrl(address)} rel="noopener noreferrer" target="_blank">
                        Open in maps<span className={styles.srOnly}> (opens in a new tab)</span>
                      </a>
                    </dd>
                  </div>
                ) : null}
                {hours ? (
                  <div>
                    <dt>Coaching hours</dt>
                    <dd>{hours}</dd>
                  </div>
                ) : null}
                <div>
                  <dt>Already a member</dt>
                  <dd>
                    <Link href="/login">Parent login</Link>
                  </dd>
                </div>
              </dl>
            </div>
          </section>
        ) : null}
      </main>

      <SiteFooter privacyUrl={page.page.privacy_notice_url} />
      <div className={styles.stick}>
        <a className={`${styles.btn} ${styles.btnBrand}`} href={view.primary.href}>
          {view.primary.label}
        </a>
      </div>
    </PageFrame>
  );
}
