import assert from "node:assert/strict";
import { test } from "node:test";

import {
  buildParentHomeModel,
  formatMoney,
  progressPercent,
} from "./parent-home.ts";

test("builds selected child progress hero and latest note", () => {
  const model = buildParentHomeModel({
    children: [
      {
        student_id: "s1",
        full_name: "Rohan Rao",
        status: "active",
        active_session_count: 1,
        attended_count: 9,
        absent_count: 1,
      },
    ],
    enrollments: [
      {
        enrollment_id: "e1",
        student_id: "s1",
        student_name: "Rohan Rao",
        session_id: "session-1",
        session_title: "Intermediate Badminton",
        status: "active",
        payment_mode: "monthly",
        subscription_status: "active",
      },
    ],
    attendance: [
      {
        attendance_id: "a1",
        student_id: "s1",
        student_name: "Rohan Rao",
        session_id: "session-1",
        session_title: "Intermediate Badminton",
        status: "present",
        marked_at: "2026-06-07T18:00:00Z",
        coach_name: "Coach Mani",
      },
    ],
    notes: [
      {
        note_id: "n1",
        student_id: "s1",
        student_name: "Rohan Rao",
        session_id: "session-1",
        session_title: "Intermediate Badminton",
        coach_id: "c1",
        coach_name: "Coach Mani",
        body: "Footwork is getting sharper.",
        created_at: "2026-06-07T19:00:00Z",
      },
    ],
    payments: [
      {
        payment_id: "p1",
        amount_cents: 18000,
        currency: "usd",
        status: "succeeded",
        refunded_cents: 0,
        created_at: "2026-06-06T12:00:00Z",
        session_id: "session-1",
      },
    ],
    credits: { balance_cents: 0, credits: [] },
    waiver: {
      required: true,
      waiver_template_id: "w1",
      title: "Waiver",
      version: "v1",
      body: "Text",
      students: [
        {
          student_id: "s1",
          student_name: "Rohan Rao",
          status: "signed",
          signed_at: "2026-06-01T00:00:00Z",
          waiver_version: "v1",
        },
      ],
    },
    progressRows: [
      {
        student_id: "s1",
        student_name: "Rohan Rao",
        program_id: "prog",
        program_name: "Badminton",
        current_level_id: "l3",
        current_level_name: "L3 Serve and Lift",
        current_level_sequence: 3,
        required_skill_count: 10,
        required_skills_passed: 7,
        total_skill_count: 12,
        total_skills_passed: 8,
        in_progress_count: 3,
        not_started_count: 1,
        test_ready_count: 1,
        level_completion_status: "in_progress",
        level_up_status: null,
        certificate_count: 0,
        next_action: "continue_practice",
      },
    ],
  });

  assert.equal(model.selectedChild?.student_id, "s1");
  assert.equal(model.hero.percent, 67);
  assert.equal(model.latestNote?.body, "Footwork is getting sharper.");
  assert.equal(model.primaryAction.kind, "progress");
  assert.equal(model.recentActivity.length, 3);
});

test("prioritizes missing waiver as strongest action", () => {
  const model = buildParentHomeModel({
    children: [
      {
        student_id: "s1",
        full_name: "Rohan Rao",
        status: "active",
        active_session_count: 1,
        attended_count: 0,
        absent_count: 0,
      },
    ],
    enrollments: [],
    attendance: [],
    notes: [],
    payments: [],
    credits: { balance_cents: 0, credits: [] },
    waiver: {
      required: true,
      waiver_template_id: "w1",
      title: "Waiver",
      version: "v1",
      body: "Text",
      students: [
        {
          student_id: "s1",
          student_name: "Rohan Rao",
          status: "pending",
          signed_at: null,
          waiver_version: null,
        },
      ],
    },
    progressRows: [],
  });

  assert.equal(model.primaryAction.kind, "waiver");
});

test("handles no children with registration action", () => {
  const model = buildParentHomeModel({
    children: [],
    enrollments: [],
    attendance: [],
    notes: [],
    payments: [],
    credits: { balance_cents: 0, credits: [] },
    waiver: null,
    progressRows: [],
  });

  assert.equal(model.selectedChild, null);
  assert.equal(model.primaryAction.kind, "register");
});

test("does not treat paused enrollment as next class", () => {
  const model = buildParentHomeModel({
    children: [
      {
        student_id: "s1",
        full_name: "Rohan Rao",
        status: "active",
        active_session_count: 0,
        attended_count: 0,
        absent_count: 0,
      },
    ],
    enrollments: [
      {
        enrollment_id: "e1",
        student_id: "s1",
        student_name: "Rohan Rao",
        session_id: "session-1",
        session_title: "Paused Badminton",
        status: "paused",
        payment_mode: "monthly",
        subscription_status: "paused",
      },
    ],
    attendance: [],
    notes: [],
    payments: [],
    credits: { balance_cents: 0, credits: [] },
    waiver: null,
    progressRows: [],
  });

  assert.equal(model.nextEnrollment, null);
  assert.equal(model.primaryAction.kind, "register");
  assert.equal(model.hero.subtitle, "First skills will appear after coach assessment.");
});

test("formats money and progress percentages safely", () => {
  assert.equal(formatMoney(18000, "usd"), "$180.00");
  assert.equal(progressPercent(7, 10), 70);
  assert.equal(progressPercent(0, 0), null);
});
