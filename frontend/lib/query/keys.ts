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
    session: (sessionId: string) => ["coach", "session", sessionId] as const,
  },
  admin: {
    all: ["admin"] as const,
    sessions: (date?: string) => ["admin", "sessions", date ?? "all"] as const,
    users: (role?: string) => ["admin", "users", role ?? "all"] as const,
    students: (params?: { search?: string; status?: string; limit?: number }) =>
      ["admin", "students", params?.search ?? "", params?.status ?? "all", params?.limit ?? "default"] as const,
    sessionDetail: (sessionId: string) => ["admin", "session", sessionId] as const,
    enrollments: (sessionId: string) => ["admin", "enrollments", sessionId] as const,
    waitlist: (sessionId: string) => ["admin", "waitlist", sessionId] as const,
    payments: () => ["admin", "payments"] as const,
    payouts: () => ["admin", "finance", "payouts"] as const,
    expenses: () => ["admin", "finance", "expenses"] as const,
    revenue: () => ["admin", "finance", "revenue"] as const,
    messages: () => ["admin", "messages"] as const,
    waivers: () => ["admin", "waivers"] as const,
    academy: () => ["admin", "academy"] as const,
    fees: () => ["admin", "academy", "fees"] as const,
    notifications: () => ["admin", "academy", "notifications"] as const,
    gateway: () => ["admin", "academy", "gateway"] as const,
  },
} as const;

export type QueryKey = ReturnType<
  (typeof queryKeys.coach)["today"] | (typeof queryKeys.coach)["session"]
>;
