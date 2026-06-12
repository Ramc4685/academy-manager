/**
 * TanStack Query keys (stable, typed).
 *
 * Persisting only coach.* keys to IndexedDB is what scopes offline cache
 * to the coach persona — see lib/query/persistence.ts.
 */

export const queryKeys = {
  coach: {
    all: ["coach"] as const,
    dashboard: () => ["coach", "dashboard"] as const,
    today: (date: string) => ["coach", "today", date] as const,
    todayPlan: (date: string) => ["coach", "today-plan", date] as const,
    skillBoard: (sessionId: string, programId?: string) =>
      ["coach", "skill-board", sessionId, programId ?? "default"] as const,
    schedule: () => ["coach", "schedule"] as const,
    profile: () => ["coach", "profile"] as const,
    session: (sessionId: string) => ["coach", "session", sessionId] as const,
  },
  admin: {
    all: ["admin"] as const,
    sessions: (date?: string) => ["admin", "sessions", date ?? "all"] as const,
    coachSessions: (coachId: string) =>
      ["admin", "sessions", "coach", coachId] as const,
    users: (role?: string) => ["admin", "users", role ?? "all"] as const,
    userDetail: (userId: string) => ["admin", "user", userId] as const,
    students: (params?: { search?: string; status?: string; limit?: number }) =>
      [
        "admin",
        "students",
        params?.search ?? "",
        params?.status ?? "all",
        params?.limit ?? "default",
      ] as const,
    studentDetail: (studentId: string) =>
      ["admin", "student", studentId] as const,
    sessionDetail: (sessionId: string) =>
      ["admin", "session", sessionId] as const,
    sessionOccurrences: (sessionId: string) =>
      ["admin", "session", sessionId, "occurrences"] as const,
    enrollments: (sessionId: string) =>
      ["admin", "enrollments", sessionId] as const,
    waitlist: (sessionId: string) => ["admin", "waitlist", sessionId] as const,
    globalWaitlist: () => ["admin", "waitlist", "global"] as const,
    registrations: () => ["admin", "registrations"] as const,
    registrationDetail: (applicationId: string) =>
      ["admin", "registrations", applicationId] as const,
    payments: () => ["admin", "payments"] as const,
    payouts: () => ["admin", "finance", "payouts"] as const,
    expenses: () => ["admin", "finance", "expenses"] as const,
    revenue: () => ["admin", "finance", "revenue"] as const,
    messages: () => ["admin", "messages"] as const,
    waivers: () => ["admin", "waivers"] as const,
    waiverTemplates: () => ["admin", "waivers", "templates"] as const,
    attention: () => ["admin", "dashboard", "attention"] as const,
    academy: () => ["admin", "academy"] as const,
    fees: () => ["admin", "academy", "fees"] as const,
    notifications: () => ["admin", "academy", "notifications"] as const,
    gateway: () => ["admin", "academy", "gateway"] as const,
  },
} as const;

type QueryKeyFactory = (...args: never[]) => readonly unknown[];
type QueryKeyFrom<T> = T extends QueryKeyFactory ? ReturnType<T> : never;

export type QueryKey =
  | QueryKeyFrom<(typeof queryKeys.coach)[keyof typeof queryKeys.coach]>
  | QueryKeyFrom<(typeof queryKeys.admin)[keyof typeof queryKeys.admin]>;
