# Parent Progress Home Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Rebuild `/parent/dashboard` as a frontend-only, progress-first parent home using existing parent APIs, app theme tokens, tenant display/logo, and subtle reduced-motion-safe animation.

**Architecture:** Keep backend APIs unchanged. Extract display-only dashboard derivation into a small pure frontend helper so selection, progress fallback, action choice, and activity rows can be tested without rendering the page. Keep the page presentation-focused and mobile-first.

**Tech Stack:** Next.js 15 App Router, React 19, TanStack Query, TypeScript, Node test runner, existing Rally CSS tokens and parent portal animations.

---

### Task 1: Add Parent Home Derivation Helper

**Files:**
- Create: `frontend/lib/parent-home.ts`
- Test: `frontend/lib/parent-home.node-test.mjs`
- Modify: `docs/test-results/active/2026-06-07-parent-portal-attractive-home.md`

**Step 1: Write the failing test**

Create `frontend/lib/parent-home.node-test.mjs` with tests for selected child progress, waiver priority, no-child registration, money formatting, and progress percentage safety.

**Step 2: Run tests to verify they fail**

Run:

```bash
cd frontend
node --no-warnings --test lib/parent-home.node-test.mjs
```

Expected: FAIL because `frontend/lib/parent-home.ts` does not exist.

**Step 3: Implement minimal helper**

Create `frontend/lib/parent-home.ts` exporting:

- `ParentHomeInput`
- `ParentHomeModel`
- `buildParentHomeModel(input)`
- `formatMoney(cents, currency)`
- `progressPercent(done, total)`

Helper behavior:

- select the first child by default;
- match the selected child to progress row, enrollments, attendance, and notes by `student_id`;
- sort notes, attendance, and payments by date descending;
- compute hero percentage from `total_skills_passed / total_skill_count`;
- choose primary action in priority order: register, waiver, credit, payment issue, progress, next class;
- return up to three activity rows.

**Step 4: Run tests to verify they pass**

Run:

```bash
cd frontend
node --no-warnings --test lib/parent-home.node-test.mjs
```

Expected: PASS.

**Step 5: Commit**

```bash
git add frontend/lib/parent-home.ts frontend/lib/parent-home.node-test.mjs docs/test-results/active/2026-06-07-parent-portal-attractive-home.md docs/plans/2026-06-08-parent-progress-home.md
git commit -m "feat: add parent home model"
```

### Task 2: Recompose Parent Dashboard UI

**Files:**
- Modify: `frontend/app/(parent)/parent/dashboard/page.tsx`
- Modify: `docs/test-results/active/2026-06-07-parent-portal-attractive-home.md`

**Step 1: Import data and helper**

Update dashboard imports to include:

- `useMemo`, `useState`;
- parent API calls for academy, children, enrollments, attendance, progress, payments, credits, waiver;
- `getParentProgressSummary` from curriculum API;
- `buildParentHomeModel`.

**Step 2: Replace old page composition**

Implement the approved flow:

- branded progress hero using academy display/logo and selected child;
- child selector pills with `+ Add` link;
- compact progress metrics;
- latest coach note card;
- next class/enrollment context card;
- strongest action card;
- recent activity card;
- academy contact footer.

**Step 3: Preserve states**

Render partial data even when noncritical queries fail:

- skeleton hero while core children/academy data loads;
- registration hero when no children exist;
- neutral progress fallback when skill progress is disabled or missing;
- error chips for failed optional queries instead of blanking the page;
- no decorative motion when `prefers-reduced-motion` disables global animations.

**Step 4: Run checks**

Run:

```bash
cd frontend
node --no-warnings --test lib/parent-home.node-test.mjs
pnpm typecheck
pnpm lint
```

Expected: all pass.

**Step 5: Commit**

```bash
git add frontend/app/'(parent)'/parent/dashboard/page.tsx docs/test-results/active/2026-06-07-parent-portal-attractive-home.md
git commit -m "feat: redesign parent progress home"
```

### Task 3: Browser Smoke And Final Verification

**Files:**
- Modify: `docs/test-results/active/2026-06-07-parent-portal-attractive-home.md`

**Step 1: Start local stack**

Run:

```bash
scripts/local_test_stack.sh all
```

Expected: backend and frontend reachable; frontend on `http://localhost:3001`.

**Step 2: Open parent dashboard**

Use the in-app browser at:

```text
http://blno.localhost:3001/parent/dashboard
```

Verify mobile viewport and desktop-ish viewport:

- hero renders and does not overlap;
- child pills fit;
- progress fallback or progress data appears;
- action card appears;
- recent activity appears or empty state is calm;
- academy logo/name displays where available.

**Step 3: Run final focused checks**

Run:

```bash
cd frontend
node --no-warnings --test lib/parent-home.node-test.mjs
pnpm typecheck
pnpm lint
```

Expected: all pass.

**Step 4: Record verification**

Run:

```bash
scripts/dev/test_result.py verify parent-portal-attractive-home --message "Final verification details..."
```

**Step 5: Final commit if verification note changed**

```bash
git add docs/test-results/active/2026-06-07-parent-portal-attractive-home.md
git commit -m "docs: record parent home verification"
```
