# Admin Student Profile Redesign Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build the approved tabbed admin student record with editable profile/training fields, guarded session and parent actions, billing visibility, compliance fields, and focused verification.

**Architecture:** Extend the v2 admin student BFF DTO/use-case models to expose normalized student profile fields, waiver state, and recent attendance. Keep business truth in the backend; the frontend only formats and edits allowed fields. Split the current large admin student detail page into focused components under the existing route while preserving current move-session and change-parent behavior.

**Tech Stack:** FastAPI/Pydantic/MongoDB backend under `backend/v2`, Next.js 15 App Router + React 19 frontend under `frontend/`, TanStack Query, Tailwind, existing `components/ds/*`, Playwright E2E, pytest.

---

### Task 1: Add Backend Tests For Expanded Student Detail Fields

**Files:**
- Modify: `backend/v2/tests/application/test_admin_student_edit.py`
- Modify: `backend/v2/tests/contract/test_admin_directory_mongo_student_repo.py`

**Step 1: Write failing application test assertions**

In `FakeStudentEditor.__init__`, add expected detail fields:

```python
self.student = AdminStudentDetail(
    ...
    level="beginner",
    previous_experience="Played recreationally",
    medical_notes="Uses inhaler before intense sessions",
    emergency_contact_name="Anita Chen",
    emergency_contact_phone="555-0199",
    t_shirt_size="M",
    waiver_status="signed",
    waiver_signed_at=None,
    waiver_version="2026-v1",
    recent_attendance=[],
)
```

Extend `test_get_admin_student_returns_parent_contact_details`:

```python
assert result.previous_experience == "Played recreationally"
assert result.medical_notes == "Uses inhaler before intense sessions"
assert result.emergency_contact_name == "Anita Chen"
assert result.emergency_contact_phone == "555-0199"
assert result.t_shirt_size == "M"
assert result.waiver_status == "signed"
assert result.waiver_version == "2026-v1"
```

Extend `test_update_admin_student_forwards_safe_fields_with_audit_context` command with:

```python
previous_experience="Tournament prep",
medical_notes="No restrictions",
emergency_contact_name="Rina Rao",
emergency_contact_phone="555-0303",
t_shirt_size="L",
```

Assert the command is forwarded and the fake result updates those fields.

**Step 2: Write failing Mongo repository test data/assertions**

In `test_get_admin_student_enriches_sessions_payments_and_current_invoice`, add to the `st-alice` student doc:

```python
"skill_level": "intermediate",
"previous_experience": "Two years of club play",
"medical_notes": "Peanut allergy",
"emergency_contact_name": "Anita Chen",
"emergency_contact_phone": "555-0199",
"t_shirt_size": "M",
```

Insert waiver acceptance and attendance rows for `st-alice`:

```python
await db["waiver_acceptances"].insert_one({
    "academy_id": acad,
    "student_id": "st-alice",
    "waiver_version_id": "waiver-2026",
    "accepted_at": now - timedelta(days=20),
})
await db["waiver_versions"].insert_one({
    "academy_id": acad,
    "waiver_version_id": "waiver-2026",
    "version": "2026-v1",
})
await db["attendance"].insert_many([
    {
        "academy_id": acad,
        "student_id": "st-alice",
        "session_id": "sess-active",
        "date": "2026-05-18",
        "status": "present",
        "marked_at": now - timedelta(days=3),
    },
    {
        "academy_id": acad,
        "student_id": "st-alice",
        "session_id": "sess-active",
        "date": "2026-05-11",
        "status": "absent",
        "marked_at": now - timedelta(days=10),
    },
])
```

Add assertions:

```python
assert detail.level == "intermediate"
assert detail.previous_experience == "Two years of club play"
assert detail.medical_notes == "Peanut allergy"
assert detail.emergency_contact_name == "Anita Chen"
assert detail.emergency_contact_phone == "555-0199"
assert detail.t_shirt_size == "M"
assert detail.waiver_status == "signed"
assert detail.waiver_version == "2026-v1"
assert detail.waiver_signed_at is not None
assert [row.status for row in detail.recent_attendance] == ["present", "absent"]
```

Add a second focused test for missing waiver:

```python
@pytest.mark.asyncio
async def test_get_admin_student_marks_missing_waiver(db, acad) -> None:
    await db["students"].insert_one({
        "academy_id": acad,
        "student_id": "st-missing",
        "full_name": "Mira Patel",
        "parent_id": "parent-1",
        "status": "active",
    })
    detail = await MongoStudentRepository(db).get_admin_student("st-missing")
    assert detail is not None
    assert detail.waiver_status == "missing"
    assert detail.recent_attendance == []
```

**Step 3: Run failing backend tests**

Run:

```bash
cd backend
source .venv/bin/activate
pytest v2/tests/application/test_admin_student_edit.py v2/tests/contract/test_admin_directory_mongo_student_repo.py -q
```

Expected: FAIL because new fields do not exist on Pydantic models/repository yet.

### Task 2: Implement Backend Student Detail Field Additions

**Files:**
- Modify: `backend/v2/contexts/enrollment/application/use_cases/admin_directory.py`
- Modify: `backend/v2/interfaces/admin/views.py`
- Modify: `backend/v2/interfaces/admin/directory_routes.py`
- Modify: `backend/v2/contexts/enrollment/infrastructure/mongo_student_repo.py`

**Step 1: Add Pydantic models**

In `admin_directory.py`, add:

```python
class AdminStudentRecentAttendance(BaseModel):
    model_config = {"frozen": True}

    session_id: str | None = None
    date: str | None = None
    status: str
    marked_at: datetime | None = None
```

Add fields to `AdminStudentDetail`:

```python
previous_experience: str | None = None
medical_notes: str | None = None
emergency_contact_name: str | None = None
emergency_contact_phone: str | None = None
t_shirt_size: str | None = None
waiver_status: Literal["signed", "missing", "unknown"] = "unknown"
waiver_signed_at: datetime | None = None
waiver_version: str | None = None
recent_attendance: list[AdminStudentRecentAttendance] = Field(default_factory=list)
```

Add fields to `UpdateAdminStudentCommand`:

```python
previous_experience: str | None = Field(default=None, max_length=1000)
medical_notes: str | None = Field(default=None, max_length=1000)
emergency_contact_name: str | None = Field(default=None, max_length=120)
emergency_contact_phone: str | None = Field(default=None, max_length=40)
t_shirt_size: str | None = Field(default=None, max_length=20)
```

**Step 2: Add interface DTOs**

In `views.py`, add a matching `AdminStudentRecentAttendanceView` and the same new fields to `AdminStudentDetailView`.

Add the new safe edit fields to `UpdateAdminStudentRequest` with the same max lengths.

**Step 3: Forward new update fields in the route**

In `directory_routes.py`, pass the new payload fields into `UpdateAdminStudentCommand`.

**Step 4: Implement repository mapping**

In `_to_admin_detail`, normalize level:

```python
raw_level = doc.get("level") if doc.get("level") is not None else doc.get("skill_level")
```

Map profile fields:

```python
previous_experience=cls._optional_str(doc.get("previous_experience")),
medical_notes=cls._optional_str(doc.get("medical_notes")),
emergency_contact_name=cls._optional_str(doc.get("emergency_contact_name")),
emergency_contact_phone=cls._optional_str(doc.get("emergency_contact_phone")),
t_shirt_size=cls._optional_str(doc.get("t_shirt_size")),
```

Add helpers:

```python
async def _waiver_summary(self, academy_id: str, student_id: str) -> tuple[str, datetime | None, str | None]:
    ...

async def _recent_attendance(self, academy_id: str, student_id: str) -> list[AdminStudentRecentAttendance]:
    ...
```

Use `waiver_acceptances`, `waiver_signatures`, and `waiver_versions` where available. Return `("missing", None, None)` when no acceptance/signature exists for an existing student. Limit attendance to 10 rows ordered newest first.

In `update_admin_student`, add the new set fields. For `level`, write both `level` and `skill_level` to keep local seed/legacy data coherent.

**Step 5: Run backend tests**

Run:

```bash
cd backend
source .venv/bin/activate
pytest v2/tests/application/test_admin_student_edit.py v2/tests/contract/test_admin_directory_mongo_student_repo.py -q
```

Expected: PASS.

**Step 6: Commit backend data work**

Run:

```bash
git add backend/v2/contexts/enrollment/application/use_cases/admin_directory.py backend/v2/interfaces/admin/views.py backend/v2/interfaces/admin/directory_routes.py backend/v2/contexts/enrollment/infrastructure/mongo_student_repo.py backend/v2/tests/application/test_admin_student_edit.py backend/v2/tests/contract/test_admin_directory_mongo_student_repo.py
git commit -m "feat(admin): expand student profile detail data"
```

### Task 3: Add Frontend Test Coverage For Tabbed Student Record

**Files:**
- Modify: `frontend/e2e/specs/admin-students.spec.ts`

**Step 1: Extend student detail fixture**

In the `renders the student profile with enrolled sessions and payment history` route fixture, add:

```ts
previous_experience: "Two years of club play",
medical_notes: "Peanut allergy",
emergency_contact_name: "Anita Chen",
emergency_contact_phone: "555-0199",
t_shirt_size: "M",
waiver_status: "signed",
waiver_signed_at: "2026-05-10T15:00:00Z",
waiver_version: "2026-v1",
recent_attendance: [
  {
    session_id: "sess-1",
    date: "2026-05-18",
    status: "present",
    marked_at: "2026-05-18T15:00:00Z",
  },
  {
    session_id: "sess-1",
    date: "2026-05-11",
    status: "absent",
    marked_at: "2026-05-11T15:00:00Z",
  },
],
```

**Step 2: Add tab assertions**

After visiting `/admin/students/student-1`, assert:

```ts
await expect(page.getByTestId("admin-student-summary-strip")).toContainText("$110");
await expect(page.getByTestId("admin-student-summary-strip")).toContainText("91%");
await expect(page.getByRole("tab", { name: "Training" })).toBeVisible();

await page.getByRole("tab", { name: "Training" }).click();
await expect(page.getByTestId("admin-student-training-tab")).toContainText("Two years of club play");
await expect(page.getByLabel("Medical notes")).toHaveValue("Peanut allergy");
await expect(page.getByLabel("Emergency contact name")).toHaveValue("Anita Chen");
await expect(page.getByLabel("Emergency contact phone")).toHaveValue("555-0199");
await expect(page.getByTestId("admin-student-recent-attendance")).toContainText("PRESENT");

await page.getByRole("tab", { name: "Sessions" }).click();
await expect(page.getByTestId("admin-student-enrolled-sessions")).toContainText("Advanced Footwork");

await page.getByRole("tab", { name: "Billing" }).click();
await expect(page.getByTestId("admin-student-payment-history")).toContainText("$110");

await page.getByRole("tab", { name: "Family & Compliance" }).click();
await expect(page.getByTestId("admin-student-compliance-tab")).toContainText("2026-v1");
await expect(page.getByLabel("T-shirt size")).toHaveValue("M");
```

**Step 3: Add edit request assertion**

Capture `PATCH /api/v2/admin/students/student-1` and assert that editing a Training field sends only the safe changed field plus reason:

```ts
let patchBody: unknown = null;
await page.route("**/api/v2/admin/students/student-1", async (route) => {
  if (route.request().method() === "PATCH") {
    patchBody = route.request().postDataJSON();
    return fulfillJson(route, { ...studentFixture, medical_notes: "Carries inhaler" });
  }
  ...
});
...
await page.getByRole("tab", { name: "Training" }).click();
await page.getByLabel("Medical notes").fill("Carries inhaler");
await page.getByRole("button", { name: "Save changes" }).click();
expect(patchBody).toMatchObject({
  medical_notes: "Carries inhaler",
  reason: "Admin profile update",
});
```

**Step 4: Run failing E2E test**

Run:

```bash
cd frontend
pnpm e2e -- --grep "renders the student profile"
```

Expected: FAIL because the UI is not tabbed and new fields are not rendered yet.

### Task 4: Implement Frontend API Types And Tabbed Page

**Files:**
- Modify: `frontend/lib/api/v2/students.ts`
- Replace/modify: `frontend/app/(admin)/admin/students/[studentId]/page.tsx`

**Step 1: Add frontend API fields**

In `students.ts`, add:

```ts
export interface AdminStudentRecentAttendance {
  session_id?: string | null;
  date?: string | null;
  status: string;
  marked_at?: string | null;
}
```

Extend `AdminStudentDetail`:

```ts
previous_experience?: string | null;
medical_notes?: string | null;
emergency_contact_name?: string | null;
emergency_contact_phone?: string | null;
t_shirt_size?: string | null;
waiver_status?: "signed" | "missing" | "unknown";
waiver_signed_at?: string | null;
waiver_version?: string | null;
recent_attendance: AdminStudentRecentAttendance[];
```

Extend `UpdateAdminStudentRequest` with the new editable fields.

**Step 2: Introduce tab state**

In the page file, add:

```ts
type StudentTab = "overview" | "training" | "sessions" | "billing" | "family";
const STUDENT_TABS = [
  { id: "overview", label: "Overview" },
  { id: "training", label: "Training" },
  { id: "sessions", label: "Sessions" },
  { id: "billing", label: "Billing" },
  { id: "family", label: "Family & Compliance" },
] as const;
```

Use `useState<StudentTab>("overview")`, render a `role="tablist"` with `role="tab"` buttons and selected state.

**Step 3: Replace the panel grid with tab panels**

Render:

- `StudentProfileHeader`
- `StudentProfileTabs`
- one tab panel at a time:
  - Overview: safe basics + warning rows.
  - Training: training/safety editable fields + recent attendance.
  - Sessions: existing `SessionsPanel`.
  - Billing: `CurrentPaymentPanel` + `PaymentHistoryPanel`.
  - Family: `ChangeParentPanel` + waiver/T-shirt/audit summary.

Keep `data-testid` values used by existing tests:

- `admin-student-detail`
- `admin-student-current-payment`
- `admin-student-enrolled-sessions`
- `admin-student-payment-history`

Add new test ids:

- `admin-student-summary-strip`
- `admin-student-training-tab`
- `admin-student-recent-attendance`
- `admin-student-compliance-tab`

**Step 4: Expand edit form component**

Refactor `StudentEditForm` to accept a `mode` prop:

```ts
type StudentEditMode = "overview" | "training" | "family";
```

Use the same mutation and dirty detection, but render only fields for the active tab:

- overview: full name, DOB, level, status, notes;
- training: previous experience, medical notes, emergency contact name/phone;
- family: T-shirt size.

Each save sends only changed fields plus `reason`.

**Step 5: Add header summary helpers**

Add pure helpers:

```ts
function formatPercent(rate: number | null | undefined): string
function deriveAge(dateOfBirth: string | null | undefined): string
function waiverLabel(student: AdminStudentDetail): string
```

Use date-safe guards so invalid/missing dates render `—`.

**Step 6: Run frontend tests**

Run:

```bash
cd frontend
pnpm typecheck
pnpm e2e -- --grep "renders the student profile"
```

Expected: PASS.

**Step 7: Commit frontend tabbed profile**

Run:

```bash
git add frontend/lib/api/v2/students.ts 'frontend/app/(admin)/admin/students/[studentId]/page.tsx' frontend/e2e/specs/admin-students.spec.ts
git commit -m "feat(admin): redesign student profile tabs"
```

### Task 5: Focused Full Verification And Handoff

**Files:**
- Modify: `docs/test-results/active/2026-06-04-student-profile-redesign-options.md`

**Step 1: Run focused backend verification**

Run:

```bash
cd backend
source .venv/bin/activate
pytest v2/tests/application/test_admin_student_edit.py v2/tests/contract/test_admin_directory_mongo_student_repo.py -q
```

Expected: PASS.

**Step 2: Run focused frontend verification**

Run:

```bash
cd frontend
pnpm typecheck
pnpm e2e -- --grep "renders the student profile"
```

Expected: PASS.

**Step 3: Run broader pre-push check**

Run:

```bash
scripts/dev/pre-push-checks.sh
```

Expected: PASS or documented failures unrelated to this branch. If it fails because of this work, fix before pushing.

**Step 4: Update test ledger**

Run:

```bash
scripts/dev/test_result.py log student-profile-redesign-options --agent main --status working --message "Implemented tabbed admin student profile with expanded BFF fields and editable training/family fields."
scripts/dev/test_result.py verify student-profile-redesign-options --message "Record exact commands and PASS/FAIL results."
```

**Step 5: Final commit if ledger changed**

Run:

```bash
git add docs/test-results/active/2026-06-04-student-profile-redesign-options.md
git commit -m "docs: record student profile redesign verification"
```

### Task 6: Push And Open Pull Request

**Files:**
- No code edits unless verification requires fixes.

**Step 1: Check final status**

Run:

```bash
git status --short --branch
git log --oneline --decorate -5
```

Expected: clean worktree on `feat/admin-student-profile-redesign`.

**Step 2: Push branch**

Run:

```bash
git push -u origin feat/admin-student-profile-redesign
```

Expected: branch pushed.

**Step 3: Create PR**

Run:

```bash
gh pr create \
  --title "feat(admin): redesign student profile record" \
  --body "## Summary
- expand admin student profile BFF fields for training, safety, waiver, and attendance context
- redesign admin student detail as a tabbed record with a persistent status summary
- keep session moves, parent changes, and billing edits guarded by existing workflows

## Verification
- [ ] backend focused tests
- [ ] frontend typecheck
- [ ] focused Playwright admin student profile test
- [ ] pre-push checks"
```

Expected: PR URL returned.
