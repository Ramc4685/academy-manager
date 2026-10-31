import {
  Check,
  Circle,
  CircleDashed,
  CircleDot,
  Repeat,
  Target,
  TriangleAlert,
  type LucideIcon,
} from "lucide-react";

import type { SkillStatus } from "@/lib/api/curriculum";

/**
 * The one rendering of a skill-progress status, shared by every persona
 * (student, parent, coach, admin).
 *
 * The seven states mirror the backend `SkillStatus` literal in
 * backend/v2/contexts/student_progress/domain/models.py. `SKILL_STATUS_SPEC`
 * is typed `Record<SkillStatus, …>`, so adding an eighth state to the API type
 * fails `pnpm typecheck` until it gets a label, tone and icon here.
 *
 * Every chip carries its label as text (WCAG 1.4.1: never colour alone); the
 * icon is decorative and hidden from assistive tech. Tones use DS status
 * tokens only, and each fill/ink pair clears AA (4.5:1) for small text —
 * SkillStatusChip.test.tsx checks the maths.
 *
 * Persona wording: one vocabulary everywhere. Student and parent pages used
 * to say "Mastered" / "Almost there" where coach and admin said "Passed" /
 * "Test ready" (#895 found the same split inside one coach screen).
 * PRODUCT.md sets no persona-specific skill wording, so all four personas
 * now read the coach/admin labels.
 */

export type SkillStatusTone =
  | "neutral"
  | "progress"
  | "ready"
  | "success"
  | "attention";

export interface SkillStatusSpec {
  label: string;
  tone: SkillStatusTone;
  icon: LucideIcon;
}

export const SKILL_STATUS_SPEC: Record<SkillStatus, SkillStatusSpec> = {
  NOT_STARTED: { label: "Not started", tone: "neutral", icon: Circle },
  INTRODUCED: { label: "Introduced", tone: "neutral", icon: CircleDot },
  LEARNING: { label: "Learning", tone: "progress", icon: CircleDashed },
  PRACTICING: { label: "Practicing", tone: "progress", icon: Repeat },
  TEST_READY: { label: "Test ready", tone: "ready", icon: Target },
  PASSED: { label: "Passed", tone: "success", icon: Check },
  NEEDS_REVIEW: { label: "Needs review", tone: "attention", icon: TriangleAlert },
};

/** Fill + ink token pair per tone. Hex values are pinned in the test. */
export const SKILL_STATUS_TONE_CLASSES: Record<SkillStatusTone, string> = {
  neutral: "bg-status-slate-100 text-status-slate-700",
  progress: "bg-status-amber-50 text-status-amber-800",
  ready: "bg-status-blue-50 text-status-blue-800",
  success: "bg-status-green-50 text-status-green-800",
  attention: "bg-status-red-50 text-status-red-800",
};

/** Label per status, for selects and legends that list states as text. */
export const SKILL_STATUS_LABELS: Record<SkillStatus, string> = Object.fromEntries(
  Object.entries(SKILL_STATUS_SPEC).map(([status, spec]) => [status, spec.label]),
) as Record<SkillStatus, string>;

export function isSkillStatus(value: string): value is SkillStatus {
  return Object.prototype.hasOwnProperty.call(SKILL_STATUS_SPEC, value);
}

/**
 * Spec for any status string the API sends. An unknown value (a newer backend
 * ahead of this bundle) renders as a neutral chip with a readable label
 * instead of crashing the page or printing "undefined".
 */
export function skillStatusSpec(status: string): SkillStatusSpec {
  if (isSkillStatus(status)) return SKILL_STATUS_SPEC[status];
  const words = status.replace(/_/g, " ").trim().toLowerCase();
  const label = words ? words.charAt(0).toUpperCase() + words.slice(1) : "Unknown";
  return { label, tone: "neutral", icon: Circle };
}

/** Tone classes for a status, for companion marks (e.g. a sequence badge). */
export function skillStatusToneClasses(status: string): string {
  return SKILL_STATUS_TONE_CLASSES[skillStatusSpec(status).tone];
}

const SIZE_CLASSES = {
  sm: "gap-1 px-2 py-0.5 text-[10px]",
  md: "gap-1 px-2 py-0.5 text-[11px]",
  lg: "gap-1.5 px-2.5 py-1 text-xs",
} as const;

const ICON_CLASSES = {
  sm: "size-2.5",
  md: "size-3",
  lg: "size-3.5",
} as const;

export interface SkillStatusChipProps {
  /** A `SkillStatus`; plain strings from loosely typed payloads are accepted. */
  status: SkillStatus | (string & {});
  size?: keyof typeof SIZE_CLASSES;
  /** The icon is decorative (aria-hidden); the label is always rendered. */
  showIcon?: boolean;
  className?: string;
}

export function SkillStatusChip({
  status,
  size = "md",
  showIcon = true,
  className,
}: SkillStatusChipProps) {
  const spec = skillStatusSpec(status);
  const Icon = spec.icon;
  return (
    <span
      data-testid="skill-status-chip"
      data-status={status}
      className={`inline-flex shrink-0 items-center whitespace-nowrap rounded-full font-semibold ${
        SIZE_CLASSES[size]
      } ${SKILL_STATUS_TONE_CLASSES[spec.tone]}${className ? ` ${className}` : ""}`}
    >
      {showIcon && <Icon aria-hidden="true" className={`${ICON_CLASSES[size]} shrink-0`} />}
      {spec.label}
    </span>
  );
}
