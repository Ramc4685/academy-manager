"use client";

/**
 * S68: a first-login checklist on Today (docs/design/coach-home.md 3.3).
 *
 * Progress lives in localStorage under `coach-welcome:<user_id>`.
 * shortcut: per device, so a coach on a new phone sees it again; move to a
 * profile field if that annoys anyone. It holds no personal data.
 */

import Link from "next/link";
import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { getCoachAcademy, getCoachProfile } from "@/lib/api/coach";
import { queryKeys } from "@/lib/query/keys";

export interface WelcomeProgress {
  contact?: boolean;
  pathway?: boolean;
  hidden?: boolean;
}

const storageKey = (userId: string) => `coach-welcome:${userId}`;

export function readWelcome(userId: string): WelcomeProgress {
  try {
    return JSON.parse(window.localStorage.getItem(storageKey(userId)) ?? "{}") as WelcomeProgress;
  } catch {
    return {};
  }
}

export function markWelcome(userId: string | null | undefined, patch: WelcomeProgress): void {
  if (!userId) return;
  try {
    window.localStorage.setItem(storageKey(userId), JSON.stringify({ ...readWelcome(userId), ...patch }));
  } catch {
    // Storage blocked: the card simply shows every time.
  }
}

/**
 * "none" once hidden (or before progress is read), "set" for the one visit
 * that finishes all three, else "steps". Finishing also stores hidden, so the
 * next visit is "none".
 */
export function welcomeStage(
  progress: WelcomeProgress | null,
  phoneDone: boolean,
): "none" | "set" | "steps" {
  if (!progress || progress.hidden) return "none";
  return phoneDone && progress.contact && progress.pathway ? "set" : "steps";
}

export function WelcomeCard() {
  const profile = useQuery({ queryKey: queryKeys.coach.profile(), queryFn: getCoachProfile });
  const { data: academy } = useQuery({ queryKey: queryKeys.coach.academy(), queryFn: getCoachAcademy });
  const userId = profile.data?.user_id;
  // Read after mount: storage is browser-only, and an SSR pass must not flash the card.
  const [progress, setProgress] = useState<WelcomeProgress | null>(null);
  useEffect(() => {
    if (userId) setProgress(readWelcome(userId));
  }, [userId]);

  const phoneDone = !!profile.data?.phone?.trim();
  const stage = welcomeStage(progress, phoneDone);
  const allDone = stage === "set";
  useEffect(() => {
    // Storage is marked hidden now, but this visit's state is not, so
    // "You're set." shows once and the card never returns.
    if (allDone) markWelcome(userId, { hidden: true });
  }, [allDone, userId]);

  if (!profile.data || !progress || stage === "none") return null;

  const name = academy?.name ?? "the academy";
  const hasContact = !!(academy?.contact_phone?.trim() || academy?.contact_email?.trim());
  const steps = [
    {
      done: phoneDone,
      label: "Check your phone number",
      hint: "So the academy can reach you.",
      href: "/coach/profile",
    },
    {
      done: !!progress.contact,
      label: hasContact ? "Save the academy's number" : "Find out who to call",
      hint: "Who to call if you are late or ill.",
      href: "#who-to-call",
      onClick: () => {
        markWelcome(userId, { contact: true });
        setProgress((p) => ({ ...p, contact: true }));
      },
    },
    {
      done: !!progress.pathway,
      label: "Read what Level 1 teaches",
      hint: "The skills and lesson plans.",
      href: "/coach/pathway",
    },
  ];
  const doneCount = steps.filter((s) => s.done).length;

  function hide() {
    markWelcome(userId, { hidden: true });
    setProgress((p) => ({ ...p, hidden: true }));
    document.querySelector<HTMLElement>("h1")?.focus();
  }

  return (
    <section
      aria-labelledby="coach-welcome-title"
      data-testid="coach-welcome"
      className="mb-4 rounded-lg border border-rally-line bg-white p-4 dark:bg-neutral-900"
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <h2 id="coach-welcome-title" className="text-xs font-semibold uppercase tracking-wide text-neutral-500">
            Welcome to {name}
          </h2>
          <p className="mt-1 font-semibold">{allDone ? "You're set." : "Three things before your first class"}</p>
        </div>
        <div className="flex shrink-0 items-center gap-1">
          <span className="text-xs tabular-nums text-neutral-500">{doneCount} of 3</span>
          <button
            type="button"
            onClick={hide}
            aria-label="Hide this"
            className="min-h-touch min-w-touch rounded-md text-neutral-500 hover:bg-neutral-100 dark:hover:bg-neutral-800"
          >
            ✕
          </button>
        </div>
      </div>
      {!allDone && (
        <>
          <ul className="mt-2">
            {steps.map((step) => (
              <li key={step.label}>
                <Link
                  href={step.href as Parameters<typeof Link>[0]["href"]}
                  onClick={step.onClick}
                  data-testid={`welcome-step-${step.href.replace(/\W+/g, "-")}`}
                  className="flex min-h-touch items-start gap-2 rounded py-1 hover:bg-neutral-50 dark:hover:bg-neutral-800"
                >
                  <span aria-hidden="true">{step.done ? "☑" : "☐"}</span>
                  <span>
                    <span className="block text-sm font-medium">
                      <span className="sr-only">{step.done ? "Done: " : "To do: "}</span>
                      {step.label}
                    </span>
                    <span className="block text-sm text-neutral-500">{step.hint}</span>
                  </span>
                </Link>
              </li>
            ))}
          </ul>
          <p className="mt-2 text-[13px] text-neutral-500">
            How you hear about classes: the academy assigns you, and you get a message in the app.
          </p>
        </>
      )}
    </section>
  );
}
