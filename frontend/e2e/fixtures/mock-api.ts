/**
 * Playwright fixture: mock the v2 BFF + Firebase auth.
 *
 * For Wave 1A E2E we don't spin a real backend — we stub network at the
 * Playwright route layer. Real backend tests live in
 * `backend/v2/tests/interface/` (with FastAPI TestClient) and the
 * production cutover canary (W1A-20) is the integration gate.
 */

import { test as base, type Page, type Route } from "@playwright/test";

export interface MockState {
  /**
   * What `GET /api/v2/me` answers. Mutate before the first navigation to run a
   * spec as another coach-surface persona — e.g. `mock.me.roles =
   * ["assistant_coach"]` for the scoped assistant shell.
   */
  me: {
    user_id: string;
    email: string;
    academy_id: string;
    roles: Array<"admin" | "coach" | "assistant_coach" | "parent" | "student" | "owner">;
  };
  today: {
    date: string;
    sessions: Array<{
      session_id: string;
      occurrence_id: string;
      title: string;
      location: string;
      start_at: string;
      end_at: string;
      roster: Array<{
        student_id: string;
        full_name: string;
        enrollment_status: "active" | "paused" | "cancelled";
        /** Seed a server-saved mark (hydrates the row as already marked). */
        attendance_status?: "present" | "absent" | "late" | null;
      }>;
    }>;
  };
  /** Every `POST /coach/attendance` body, including replays from the offline queue. */
  attendanceCalls: Array<Record<string, unknown>>;
  correctionCalls: Array<Record<string, unknown>>;
  bulkAttendanceCalls: Array<Record<string, unknown>>;
  bulkSkillCalls: Array<Record<string, unknown>>;
  skillStatusCalls: Array<Record<string, unknown>>;
  attendanceResponder?: (body: Record<string, unknown>) => {
    status: number;
    body: Record<string, unknown>;
  };
  // Phase 3: coach daily teaching plan.
  teachingPlan: TeachingPlanFixture;
  statusCalls: Array<{
    studentId: string;
    skillId: string;
    body: Record<string, unknown>;
  }>;
  testCalls: Array<{
    studentId: string;
    skillId: string;
    body: Record<string, unknown>;
  }>;
  // When true, GET /coach/today/plan returns 500 (the app retries 5xx 3×, so a
  // single failure would recover on its own). Specs set this true to exercise
  // the error state, then flip it false before clicking Retry.
  failTeachingPlan: boolean;
  /**
   * Coach progress notes for `s-today-1`, served by GET and appended to by
   * POST (`visibility` defaults to private, as the BFF does). Seed before
   * navigating to render an existing note in the roster's note box.
   */
  progressNotes: MockProgressNote[];
  progressNoteCalls: Array<Record<string, unknown>>;
  /** `{ note_id, visibility }` for every PATCH on a progress note. */
  noteVisibilityCalls: Array<{ note_id: string; visibility: string }>;
  /** Skill notes for the passport's Notes panel; same GET/POST/PATCH shape. */
  skillNotes: MockSkillNote[];
  skillNoteCalls: Array<Record<string, unknown>>;
  skillNoteVisibilityCalls: Array<{ note_id: string; visibility: string }>;
}

export interface MockProgressNote {
  note_id: string;
  session_id: string;
  student_id: string;
  coach_id: string;
  body: string;
  created_at: string;
  visibility: "private" | "shared";
}

export interface MockSkillNote {
  note_id: string;
  academy_id: string;
  student_id: string;
  skill_id: string;
  coach_id: string;
  session_id: string | null;
  body: string;
  created_at: string;
  visibility: "private" | "shared";
}

interface TeachingPlanFixture {
  date: string;
  program_id: string;
  program_name: string;
  pathway_configured: boolean;
  sessions: Array<{
    session_id: string;
    occurrence_id: string | null;
    title: string;
    location: string;
    start_at: string | null;
    end_at: string | null;
    groups: Array<{
      level_id: string;
      level_name: string;
      level_sequence: number;
      youtube_links: Array<{ title: string; url: string }>;
      lesson_card: {
        card_id: string;
        lesson_number: number;
        title: string;
        goal_summary: string;
        teaching_points: string[];
        equipment: string[];
        activity_summary: string;
        safety_notes: string[];
        source: string;
        module_name: string;
        lesson_range: string;
        page_hint: string | null;
        resource_links: Array<{
          kind: "YOUTUBE" | "PDF_REFERENCE";
          title: string;
          url: string | null;
        }>;
      } | null;
      students: Array<{
        student_id: string;
        student_name: string;
        focus: "practice" | "review" | "ready_for_level_up";
        next_skill: {
          skill_id: string;
          name: string;
          sequence: number;
          level_id: string;
          status: string;
          is_review: boolean;
          criteria: string[];
          youtube_links: Array<{ title: string; url: string }>;
        } | null;
      }>;
    }>;
    unplaced: Array<{ student_id: string; student_name: string }>;
  }>;
}

export const test = base.extend<{
  mock: MockState;
  signIn: () => Promise<void>;
}>({
  mock: async ({ page }, use) => {
    const state: MockState = {
      me: {
        user_id: "user-coach-e2e",
        email: "coach@example.com",
        academy_id: "academy-e2e",
        roles: ["coach"],
      },
      today: {
        date: new Date().toISOString().slice(0, 10),
        sessions: [
          {
            session_id: "s-today-1",
            occurrence_id: "occ-today-1",
            title: "Junior A",
            location: "Court 1",
            start_at: `${new Date().toISOString().slice(0, 10)}T09:00:00Z`,
            end_at: `${new Date().toISOString().slice(0, 10)}T10:30:00Z`,
            roster: [
              {
                student_id: "st1",
                full_name: "Alice",
                enrollment_status: "active",
              },
              {
                student_id: "st2",
                full_name: "Bob",
                enrollment_status: "active",
              },
            ],
          },
        ],
      },
      attendanceCalls: [],
      correctionCalls: [],
      bulkAttendanceCalls: [],
      bulkSkillCalls: [],
      skillStatusCalls: [],
      statusCalls: [],
      testCalls: [],
      failTeachingPlan: false,
      progressNotes: [],
      progressNoteCalls: [],
      noteVisibilityCalls: [],
      skillNotes: [],
      skillNoteCalls: [],
      skillNoteVisibilityCalls: [],
      teachingPlan: {
        date: new Date().toISOString().slice(0, 10),
        program_id: "prog-badminton",
        program_name: "Badminton",
        pathway_configured: true,
        sessions: [
          {
            session_id: "s-today-1",
            occurrence_id: "occ-today-1",
            title: "Junior A",
            location: "Court 1",
            start_at: `${new Date().toISOString().slice(0, 10)}T09:00:00Z`,
            end_at: `${new Date().toISOString().slice(0, 10)}T10:30:00Z`,
            groups: [
              {
                level_id: "lvl-1",
                level_name: "Starter",
                level_sequence: 1,
                youtube_links: [
                  { title: "Level 1 intro", url: "https://youtu.be/level1" },
                ],
                lesson_card: {
                  card_id: "card-3",
                  lesson_number: 3,
                  title: "Overhead Clear",
                  goal_summary: "Hit a clear to the back of the court.",
                  teaching_points: ["Side-on stance", "Throwing action"],
                  equipment: ["Rackets", "Shuttles"],
                  activity_summary: "Feed shuttles for repeated clears.",
                  safety_notes: ["Keep spacing between players"],
                  source: "BWF_SHUTTLE_TIME",
                  module_name: "Starter Lessons",
                  lesson_range: "3-6",
                  page_hint: "p.16-30",
                  resource_links: [
                    {
                      kind: "YOUTUBE",
                      title: "Overhead clear demo",
                      url: "https://youtu.be/clear-demo",
                    },
                    {
                      kind: "PDF_REFERENCE",
                      title: "Shuttle Time · Starter Lessons · L3–6 · p.16–30",
                      url: null,
                    },
                  ],
                },
                students: [
                  {
                    student_id: "st1",
                    student_name: "Alice",
                    focus: "practice",
                    next_skill: {
                      skill_id: "sk-1",
                      name: "Forehand Clear",
                      sequence: 2,
                      level_id: "lvl-1",
                      status: "PRACTICING",
                      is_review: false,
                      criteria: ["Reaches the back line"],
                      youtube_links: [
                        { title: "Forehand clear", url: "https://youtu.be/fh-clear" },
                      ],
                    },
                  },
                  {
                    student_id: "st2",
                    student_name: "Bob",
                    focus: "review",
                    next_skill: {
                      skill_id: "sk-2",
                      name: "Backhand Serve",
                      sequence: 1,
                      level_id: "lvl-1",
                      status: "NEEDS_REVIEW",
                      is_review: true,
                      criteria: ["Lands in the service box"],
                      youtube_links: [],
                    },
                  },
                ],
              },
            ],
            unplaced: [],
          },
        ],
      },
    };

    const skillGroups = [
      {
        skill_id: "skill-backhand",
        skill_name: "Backhand clear",
        student_ids: ["st1", "st2"],
        student_names: ["Alice", "Bob"],
        status: "LEARNING",
      },
    ];
    const skillStudents = [
      {
        student_id: "st1",
        full_name: "Alice",
        enrollment_status: "active",
        top_gaps: [
          {
            skill_id: "skill-backhand",
            skill_name: "Backhand clear",
            status: "LEARNING",
            program_id: "prog-001",
            level_id: "level-001",
          },
        ],
        skills: [
          {
            skill_id: "skill-backhand",
            skill_name: "Backhand clear",
            status: "LEARNING",
            program_id: "prog-001",
            level_id: "level-001",
          },
        ],
      },
      {
        student_id: "st2",
        full_name: "Bob",
        enrollment_status: "active",
        top_gaps: [
          {
            skill_id: "skill-backhand",
            skill_name: "Backhand clear",
            status: "LEARNING",
            program_id: "prog-001",
            level_id: "level-001",
          },
        ],
        skills: [
          {
            skill_id: "skill-backhand",
            skill_name: "Backhand clear",
            status: "LEARNING",
            program_id: "prog-001",
            level_id: "level-001",
          },
        ],
      },
    ];

    const dayHub = {
      date: state.today.date,
      summary: {
        session_count: 1,
        student_count: 2,
        attendance_state: "not_started",
        skill_focus_count: 1,
        parent_message_count: 0,
        absence_notice_count: 0,
      },
      sessions: state.today.sessions.map((session) => ({
        ...session,
        skill_groups: skillGroups,
        students: skillStudents,
      })),
    };

    await page.route("**/api/v2/me", async (route: Route) => {
      if (route.request().method() !== "GET") return route.fallback();
      // Read at request time so a spec can swap persona before navigating.
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(state.me),
      });
    });

    await page.route("**/api/v2/coach/today*", async (route: Route) => {
      if (route.request().method() !== "GET") return route.fallback();
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(state.today),
      });
    });

    await page.route("**/api/v2/coach/day-hub*", async (route: Route) => {
      if (route.request().method() !== "GET") return route.fallback();
      const url = new URL(route.request().url());
      const date = url.searchParams.get("date") ?? state.today.date;
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ ...dayHub, date }),
      });
    });

    await page.route("**/api/v2/coach/sessions/*/skills/bulk-status", async (route: Route) => {
      if (route.request().method() !== "POST") return route.fallback();
      const body = JSON.parse(route.request().postData() ?? "{}");
      state.bulkSkillCalls.push(body);
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ updated: body.student_ids?.length ?? 0, student_ids: body.student_ids ?? [] }),
      });
    });

    await page.route("**/api/v2/coach/sessions/*/skills**", async (route: Route) => {
      if (route.request().method() !== "GET") return route.fallback();
      const url = new URL(route.request().url());
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          ...dayHub.sessions[0],
          date: url.searchParams.get("date") ?? state.today.date,
          roster: state.today.sessions[0].roster,
        }),
      });
    });

    await page.route("**/api/v2/coach/students/*/passport*", async (route: Route) => {
      if (route.request().method() !== "GET") return route.fallback();
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          passport: [
            {
              skill_id: "skill-backhand",
              level_id: "level-001",
              program_id: "prog-001",
              skill_name: "Backhand clear",
              skill_description: "Clear from the back court",
              sequence: 1,
              is_required: true,
              status: "LEARNING",
              last_test_passed: null,
              last_tested_at: null,
              test_attempt_count: 0,
            },
          ],
        }),
      });
    });

    await page.route("**/api/v2/coach/attendance", async (route: Route) => {
      if (route.request().method() !== "POST") return route.fallback();
      const body = JSON.parse(route.request().postData() ?? "{}");
      state.attendanceCalls.push(body);
      const responder = state.attendanceResponder?.(body);
      if (responder) {
        return route.fulfill({
          status: responder.status,
          contentType: "application/json",
          body: JSON.stringify(responder.body),
        });
      }
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          attendance_id: body.mutation_id,
          occurrence_id: body.occurrence_id,
          session_id: body.session_id,
          student_id: body.student_id,
          status: body.status,
          marked_at: new Date().toISOString(),
        }),
      });
    });

    // Correction of an existing mark (#517/#646): PATCH keyed by occurrence +
    // student. Echoes the requested status back as the corrected mark.
    await page.route(
      "**/api/v2/coach/occurrences/*/attendance/*",
      async (route: Route) => {
        if (route.request().method() !== "PATCH") return route.fallback();
        const url = new URL(route.request().url());
        const parts = url.pathname.split("/");
        const studentId = decodeURIComponent(parts[parts.length - 1] ?? "");
        const occurrenceId = decodeURIComponent(parts[parts.length - 3] ?? "");
        const body = JSON.parse(route.request().postData() ?? "{}");
        state.correctionCalls.push({ occurrence_id: occurrenceId, student_id: studentId, ...body });
        return route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            attendance_id: `corr-${studentId}`,
            occurrence_id: occurrenceId,
            session_id: "s-today-1",
            student_id: studentId,
            status: body.status,
            previous_status: "present",
            corrected_by: "coach-1",
            corrected_at: new Date().toISOString(),
          }),
        });
      },
    );

    await page.route(
      "**/api/v2/coach/occurrences/*/attendance/bulk",
      async (route: Route) => {
        if (route.request().method() !== "POST") return route.fallback();
        const body = JSON.parse(route.request().postData() ?? "{}");
        state.bulkAttendanceCalls.push(body);
        const entries = (body.entries ?? []) as Array<{
          student_id: string;
          status: string;
        }>;
        return route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            results: entries.map((entry, index) => ({
              student_id: entry.student_id,
              status: entry.status,
              attendance_id: `${body.mutation_id}-${index}`,
            })),
          }),
        });
      },
    );

    await page.route(
      "**/api/v2/coach/sessions/*/lesson-plans",
      async (route: Route) => {
        if (route.request().method() !== "GET") return route.fallback();
        return route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({ plans: [] }),
        });
      },
    );

    // Progress notes (slice 3): GET lists, POST appends (private unless the
    // body says shared), PATCH /{note_id} flips `visibility`.
    let noteSeq = 0;
    await page.route(
      "**/api/v2/coach/sessions/*/progress-notes",
      async (route: Route) => {
        const method = route.request().method();
        const url = new URL(route.request().url());
        const parts = url.pathname.split("/");
        const sessionId = decodeURIComponent(parts[parts.length - 2] ?? "");
        if (method === "GET") {
          return route.fulfill({
            status: 200,
            contentType: "application/json",
            body: JSON.stringify({
              notes: state.progressNotes.filter((n) => n.session_id === sessionId),
            }),
          });
        }
        if (method === "POST") {
          const body = JSON.parse(route.request().postData() ?? "{}");
          state.progressNoteCalls.push(body);
          noteSeq += 1;
          const note: MockProgressNote = {
            note_id: `note-${noteSeq}`,
            session_id: sessionId,
            student_id: body.student_id,
            coach_id: state.me.user_id,
            body: body.body,
            created_at: new Date(Date.now() + noteSeq).toISOString(),
            visibility: body.visibility === "shared" ? "shared" : "private",
          };
          state.progressNotes.push(note);
          return route.fulfill({
            status: 201,
            contentType: "application/json",
            body: JSON.stringify(note),
          });
        }
        return route.fallback();
      },
    );

    await page.route(
      "**/api/v2/coach/sessions/*/progress-notes/*",
      async (route: Route) => {
        if (route.request().method() !== "PATCH") return route.fallback();
        const url = new URL(route.request().url());
        const parts = url.pathname.split("/");
        const noteId = decodeURIComponent(parts[parts.length - 1] ?? "");
        const body = JSON.parse(route.request().postData() ?? "{}");
        state.noteVisibilityCalls.push({ note_id: noteId, visibility: body.visibility });
        const note = state.progressNotes.find((n) => n.note_id === noteId);
        if (!note) {
          return route.fulfill({
            status: 404,
            contentType: "application/json",
            body: JSON.stringify({
              error: { code: "Coaching.NoteNotFound", message: "note not found", details: {} },
            }),
          });
        }
        note.visibility = body.visibility;
        return route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify(note),
        });
      },
    );

    // Skill notes (passport Notes panel): same three verbs, keyed by student.
    let skillNoteSeq = 0;
    await page.route(
      "**/api/v2/coach/students/*/skill-notes*",
      async (route: Route) => {
        const method = route.request().method();
        const url = new URL(route.request().url());
        const parts = url.pathname.split("/");
        const studentId = decodeURIComponent(parts[parts.length - 2] ?? "");
        if (method === "GET") {
          const skillId = url.searchParams.get("skill_id");
          return route.fulfill({
            status: 200,
            contentType: "application/json",
            body: JSON.stringify({
              notes: state.skillNotes.filter(
                (n) => n.student_id === studentId && (!skillId || n.skill_id === skillId),
              ),
            }),
          });
        }
        if (method === "POST") {
          const body = JSON.parse(route.request().postData() ?? "{}");
          state.skillNoteCalls.push(body);
          skillNoteSeq += 1;
          const note: MockSkillNote = {
            note_id: `skill-note-${skillNoteSeq}`,
            academy_id: state.me.academy_id,
            student_id: studentId,
            skill_id: body.skill_id,
            coach_id: state.me.user_id,
            session_id: null,
            body: body.body,
            created_at: new Date(Date.now() + skillNoteSeq).toISOString(),
            visibility: body.visibility === "shared" ? "shared" : "private",
          };
          state.skillNotes.push(note);
          return route.fulfill({
            status: 201,
            contentType: "application/json",
            body: JSON.stringify(note),
          });
        }
        return route.fallback();
      },
    );

    await page.route(
      "**/api/v2/coach/students/*/skill-notes/*",
      async (route: Route) => {
        if (route.request().method() !== "PATCH") return route.fallback();
        const url = new URL(route.request().url());
        const parts = url.pathname.split("/");
        const noteId = decodeURIComponent(parts[parts.length - 1] ?? "");
        const body = JSON.parse(route.request().postData() ?? "{}");
        state.skillNoteVisibilityCalls.push({ note_id: noteId, visibility: body.visibility });
        const note = state.skillNotes.find((n) => n.note_id === noteId);
        if (!note) {
          return route.fulfill({
            status: 404,
            contentType: "application/json",
            body: JSON.stringify({
              error: { code: "Coaching.NoteNotFound", message: "note not found", details: {} },
            }),
          });
        }
        note.visibility = body.visibility;
        return route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify(note),
        });
      },
    );

    // Session skill board (/coach/sessions/<id>/progress): one level, one
    // skill, both roster students placed.
    await page.route("**/api/v2/coach/sessions/*/skill-board*", async (route: Route) => {
      if (route.request().method() !== "GET") return route.fallback();
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          program_id: "prog-001",
          program_name: "Badminton",
          groups: [
            {
              level_id: "level-001",
              level_name: "Starter",
              sequence: 1,
              skills: [
                { skill_id: "skill-backhand", name: "Backhand clear", sequence: 1, is_required: true },
                { skill_id: "skill-serve", name: "Low serve", sequence: 2, is_required: false },
              ],
              students: state.today.sessions[0].roster.map((student) => ({
                student_id: student.student_id,
                student_name: student.full_name,
                statuses: {
                  "skill-backhand": { status: "LEARNING", last_updated_at: null },
                },
                required_passed: 0,
                required_total: 1,
                total_passed: 0,
                total_count: 2,
                level_up_status: null,
              })),
            },
          ],
          unplaced: [],
        }),
      });
    });

    // Phase 3: daily teaching plan. Registered after `coach/today*` so it
    // wins for `/coach/today/plan` (Playwright matches most-recent route first).
    await page.route(
      "**/api/v2/coach/today/plan*",
      async (route: Route) => {
        if (route.request().method() !== "GET") return route.fallback();
        if (state.failTeachingPlan) {
          return route.fulfill({
            status: 500,
            contentType: "application/json",
            body: JSON.stringify({
              error: { code: "Internal", message: "boom", details: {} },
            }),
          });
        }
        return route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify(state.teachingPlan),
        });
      },
    );

    await page.route(
      "**/api/v2/coach/students/*/skills/*/status",
      async (route: Route) => {
        if (route.request().method() !== "POST") return route.fallback();
        const m = route
          .request()
          .url()
          .match(/students\/([^/]+)\/skills\/([^/?]+)\/status/);
        const body = JSON.parse(route.request().postData() ?? "{}");
        state.skillStatusCalls.push(body);
        state.statusCalls.push({
          studentId: m?.[1] ?? "",
          skillId: m?.[2] ?? "",
          body,
        });
        return route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({ updated: true }),
        });
      },
    );

    await page.route(
      "**/api/v2/coach/students/*/skills/*/test",
      async (route: Route) => {
        if (route.request().method() !== "POST") return route.fallback();
        const m = route
          .request()
          .url()
          .match(/students\/([^/]+)\/skills\/([^/?]+)\/test/);
        const body = JSON.parse(route.request().postData() ?? "{}");
        state.testCalls.push({
          studentId: m?.[1] ?? "",
          skillId: m?.[2] ?? "",
          body,
        });
        return route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({ recorded: true }),
        });
      },
    );

    await use(state);
  },

  signIn: async ({ page }, use) => {
    await use(async () => {
      await page.addInitScript(() => {
        // Mock Firebase user before the page boots.
        (window as unknown as { __FAKE_AUTH__: boolean }).__FAKE_AUTH__ = true;
      });
    });
  },
});

export { expect } from "@playwright/test";

export async function bypassAuth(page: Page): Promise<void> {
  // For pages that gate on Firebase, we navigate directly to coach surfaces
  // with the auth state pre-seeded. The coach layout reads onAuthChange
  // synchronously — in tests we override the module via init script.
  await page.addInitScript(() => {
    const FAKE_USER = {
      uid: "coach-1",
      email: "coach@example.com",
      getIdToken: async () => "fake-id-token",
    };
    // Patch the Firebase auth module's named exports for client bundles
    // that imported them. The Wave-1A login flow uses `onAuthChange` which
    // we stub to immediately fire the callback.
    Object.defineProperty(window, "__fakeFirebaseUser", { value: FAKE_USER });
  });
}
