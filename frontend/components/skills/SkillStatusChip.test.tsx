import { readFileSync } from "node:fs";
import { join } from "node:path";

import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { AA_TEXT, contrastRatio } from "@/lib/design/contrast.mjs";
import type { SkillStatus } from "@/lib/api/curriculum";

import {
  SKILL_STATUS_LABELS,
  SKILL_STATUS_SPEC,
  SKILL_STATUS_TONE_CLASSES,
  SkillStatusChip,
  skillStatusSpec,
  skillStatusToneClasses,
  type SkillStatusTone,
} from "./SkillStatusChip";

// The backend literal (backend/v2/contexts/student_progress/domain/models.py).
const ALL_STATUSES: SkillStatus[] = [
  "NOT_STARTED",
  "INTRODUCED",
  "LEARNING",
  "PRACTICING",
  "TEST_READY",
  "PASSED",
  "NEEDS_REVIEW",
];

const EXPECTED_LABELS: Record<SkillStatus, string> = {
  NOT_STARTED: "Not started",
  INTRODUCED: "Introduced",
  LEARNING: "Learning",
  PRACTICING: "Practicing",
  TEST_READY: "Test ready",
  PASSED: "Passed",
  NEEDS_REVIEW: "Needs review",
};

// tailwind.config.ts `status` hexes behind each tone's fill/ink pair.
const TONE_HEX: Record<SkillStatusTone, { fill: string; ink: string }> = {
  neutral: { fill: "#f1f5f9", ink: "#334155" }, // slate-100 / slate-700
  progress: { fill: "#fffbeb", ink: "#92400e" }, // amber-50 / amber-800
  ready: { fill: "#eff6ff", ink: "#1e40af" }, // blue-50 / blue-800
  success: { fill: "#ecfdf5", ink: "#065f46" }, // green-50 / green-800
  attention: { fill: "#fef2f2", ink: "#991b1b" }, // red-50 / red-800
};

const render = (status: string, extra: Record<string, unknown> = {}) =>
  renderToStaticMarkup(createElement(SkillStatusChip, { status, ...extra }));

describe("SkillStatusChip", () => {
  it("covers exactly the backend's seven states", () => {
    expect(Object.keys(SKILL_STATUS_SPEC).sort()).toEqual([...ALL_STATUSES].sort());
  });

  it.each(ALL_STATUSES)("renders %s with its shared label and a hidden icon", (status) => {
    const html = render(status);
    expect(html).toContain(`>${EXPECTED_LABELS[status]}</span>`);
    expect(html).toContain(`data-status="${status}"`);
    expect(html).toContain('aria-hidden="true"');
    expect(html).not.toContain("undefined");
    expect(SKILL_STATUS_LABELS[status]).toBe(EXPECTED_LABELS[status]);
  });

  it.each(ALL_STATUSES)("keeps the label for %s when the icon is off", (status) => {
    const html = render(status, { showIcon: false });
    expect(html).toContain(EXPECTED_LABELS[status]);
    expect(html).not.toContain("<svg");
  });

  it("speaks one vocabulary: never the old parent/student words", () => {
    const labels = Object.values(SKILL_STATUS_LABELS);
    expect(labels).not.toContain("Mastered");
    expect(labels).not.toContain("Almost there");
  });

  it("renders an unknown status as a neutral, readable chip instead of crashing", () => {
    const html = render("ON_HOLD_SOMEDAY");
    expect(html).toContain("On hold someday");
    expect(html).toContain(SKILL_STATUS_TONE_CLASSES.neutral);
    expect(skillStatusSpec("").label).toBe("Unknown");
    expect(skillStatusToneClasses("nope")).toBe(SKILL_STATUS_TONE_CLASSES.neutral);
  });

  it("uses design tokens only", () => {
    for (const classes of Object.values(SKILL_STATUS_TONE_CLASSES)) {
      for (const cls of classes.split(" ")) {
        expect(cls).toMatch(/^(bg|text)-status-[a-z]+-\d+$/);
      }
    }
  });

  it.each(Object.keys(TONE_HEX) as SkillStatusTone[])(
    "tone %s clears WCAG AA for small text",
    (tone) => {
      const { fill, ink } = TONE_HEX[tone];
      const classes = SKILL_STATUS_TONE_CLASSES[tone];
      // Pin the hex table to the classes it describes.
      expect(classes).toMatch(/^bg-status-[a-z]+-\d+ text-status-[a-z]+-\d+$/);
      expect(contrastRatio(fill, ink)).toBeGreaterThanOrEqual(AA_TEXT);
    },
  );
});

describe("progress surfaces share the one chip", () => {
  const FRONTEND = join(__dirname, "..", "..");
  const CALL_SITES = [
    "app/(student)/student/progress/page.tsx",
    "app/(parent)/parent/progress/page.tsx",
    "app/(coach)/coach/students/[studentId]/passport/page.tsx",
    "components/teaching/student-focus-row.tsx",
  ];
  // Local maps and helpers each surface used to hand-roll.
  const RETIRED = [
    "SKILL_STATUS_FRIENDLY",
    "skillStatusClasses",
    "statusColor(",
    "STATUS_BADGE",
    "const STATUS_LABEL",
    "function SkillStatusChip",
    ': "Mastered"',
    ': "Almost there"',
  ];

  it.each(CALL_SITES)("%s renders <SkillStatusChip> and no inline chip", (file) => {
    const source = readFileSync(join(FRONTEND, file), "utf8");
    expect(source).toContain('from "@/components/skills/SkillStatusChip"');
    expect(source).toContain("<SkillStatusChip");
    for (const retired of RETIRED) {
      expect(source, `${file} still has ${retired}`).not.toContain(retired);
    }
  });

  // The admin row edits status through a <select>, which already shows the
  // current status, so it takes the shared labels but renders no chip.
  it("admin progress row uses the shared labels and no second status display", () => {
    const file = "app/(admin)/admin/students/[studentId]/progress/page.tsx";
    const source = readFileSync(join(FRONTEND, file), "utf8");
    expect(source).toContain("SKILL_STATUS_LABELS[");
    expect(source).not.toContain("<SkillStatusChip");
    expect(source).not.toContain("const STATUS_LABELS");
    for (const retired of RETIRED) {
      expect(source, `${file} still has ${retired}`).not.toContain(retired);
    }
  });
});
