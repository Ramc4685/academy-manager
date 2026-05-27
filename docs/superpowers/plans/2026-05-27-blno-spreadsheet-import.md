# BLNO Spreadsheet Import Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a validated BLNO Badminton Academy data-import path from `/Users/ramc/Downloads/BLno-Badmintion-Training (1).xlsx` that can seed local test data first and later apply the tested dataset to production with explicit operator approval.

**Architecture:** Treat the spreadsheet as source-of-truth and transform it into v2-compatible tenant data with a dry-run validation manifest before any database writes. Do not move local Mongo data to production directly; run the same reviewed importer against production after local validation, backup, and confirmation. Keep legacy `/api/*` untouched and write SaaS/v2-compatible tenant-owned records with explicit `academy_id`.

**Tech Stack:** Python 3.12, FastAPI/MongoDB schema used by `backend/v2`, Motor/PyMongo, Firebase Auth emulator/local mode, `openpyxl` for workbook extraction, existing local stack scripts.

---

## Current Behavior Found

- Workbook `/Users/ramc/Downloads/BLno-Badmintion-Training (1).xlsx` has these source tabs: `Form_Responses`, `Roster`, `Payment_Log`, `Audit_Log`, `Move_Log`, `Attendance_Log`, `Billing_Summary`, `Dues_Followup`, plus dashboard/helper tabs.
- Data profile from the workbook:
  - `Roster`: 47 nonblank child rows, 47 unique students, 43 unique parent emails.
  - Statuses: 44 `Active`, 2 `Dropped`, 1 `Hold`.
  - Billing types: 44 `Standard`, 3 `No Charge`.
  - Sessions: 4 distinct weekly sessions, split 12/12/12/11 students.
  - April 2026: 36 enrolled, $1,825 paid, $245 due.
  - May 2026: 44 enrolled, $2,000 paid, $570 due.
  - `Payment_Log`: 13 explicit May Zelle payment entries totaling $820.
  - `Attendance_Log`: 8 present entries.
  - `Move_Log`: 5 move rows.
- `backend/scripts/import_blno.py` reads Excel but is unsafe for this purpose:
  - It drops many collections.
  - It writes older/legacy fields such as `amount`, `final_amount`, and missing `academy_id` on several docs.
  - It does not create SaaS membership records.
- `backend/scripts/seed_local.py` is safer for the current app:
  - It creates v2-shaped BLNO local data.
  - It seeds `academy_id`, dated sessions, occurrences, waiver acceptances, payments, expenses, and Firebase emulator users.
  - It is hardcoded and may be stale versus the latest spreadsheet.

## Files Likely Affected

- Modify: `backend/scripts/import_blno.py`
  - Replace the old one-shot destructive importer with a guarded workbook importer, or turn it into a thin wrapper around a new importer module.
- Create: `backend/scripts/blno_importer.py`
  - Own workbook parsing, normalization, validation, manifest generation, and v2 Mongo write planning.
- Create: `backend/tests/test_blno_importer.py`
  - Unit-test workbook parsing using small generated workbook fixtures.
- Modify: `backend/scripts/seed_local.py`
  - Keep static fallback seed, but optionally call the workbook importer when `BLNO_XLSX` is provided.
- Create: `docs/runbooks/blno-production-import.md`
  - Operator checklist for backup, dry run, local verification, production apply, and rollback.
- Modify: `test_result.md`
  - Record local seed/import verification and any skipped production checks.

## Proposed Change

### Task 1: Extract BLNO Workbook Parser

**Files:**
- Create: `backend/scripts/blno_importer.py`
- Test: `backend/tests/test_blno_importer.py`

- [ ] **Step 1: Write parser tests for workbook rows**

Create `backend/tests/test_blno_importer.py` with a minimal workbook fixture and tests:

```python
from pathlib import Path

from openpyxl import Workbook

from backend.scripts.blno_importer import load_blno_workbook


def _sample_workbook(path: Path) -> Path:
    wb = Workbook()
    ws = wb.active
    ws.title = "Roster"
    ws.append([
        "Reg Date", "Child Name", "Parent", "Phone", "Email", "Skill", "Price",
        "Session", "Coach", "Status", "Apr-2026 Enr", "Apr-2026 Pay",
        "Apr-2026 Due", "May-2026 Enr", "May-2026 Pay", "May-2026 Due",
        "Apr-2026 Session Override", "May-2026 Session Override", "Billing Type",
    ])
    ws.append([
        None, "Test Student", "Test Parent", "3095551212", "parent@example.com",
        "Beginner", 60, "Thursday 6:00 PM - 6:45 PM Beginner(Coach - Gowtham)",
        "Gowtham", "Active", True, 60, 0, True, 0, 60, None, None, "Standard",
    ])
    wb.create_sheet("Form_Responses").append(["Child Full Name"])
    wb.create_sheet("Payment_Log").append(["Timestamp", "Actor", "Kid", "Month", "Amount", "Method", "Note", "Previous Pay", "New Pay"])
    wb.create_sheet("Audit_Log").append(["Timestamp", "Actor", "Action", "Target", "Scope", "Before", "After", "Meta"])
    wb.create_sheet("Move_Log").append(["Timestamp", "Kid", "Effective Month", "From", "To"])
    wb.create_sheet("Attendance_Log").append(["ATTENDANCE LOG"])
    wb["Attendance_Log"].append([])
    wb["Attendance_Log"].append(["Timestamp", "Date", "Session", "Child", "Status", "Notes"])
    wb.save(path)
    return path


def test_load_blno_workbook_normalizes_roster(tmp_path: Path) -> None:
    parsed = load_blno_workbook(_sample_workbook(tmp_path / "blno.xlsx"))

    assert len(parsed.roster) == 1
    row = parsed.roster[0]
    assert row.child_name == "Test Student"
    assert row.parent_email == "parent@example.com"
    assert row.billing_type == "Standard"
    assert row.months["2026-04"].enrolled is True
    assert row.months["2026-05"].paid_cents == 0
    assert row.months["2026-05"].due_cents == 6000
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
cd backend
source .venv/bin/activate
pytest tests/test_blno_importer.py -q
```

Expected: import fails because `backend.scripts.blno_importer` does not exist.

- [ ] **Step 3: Implement parser dataclasses and workbook reader**

Create `backend/scripts/blno_importer.py`:

```python
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from openpyxl import load_workbook


@dataclass(frozen=True)
class MonthFacts:
    enrolled: bool
    paid_cents: int
    due_cents: int


@dataclass(frozen=True)
class RosterRow:
    child_name: str
    parent_name: str
    parent_phone: str
    parent_email: str
    skill: str
    price_cents: int
    session_name: str
    coach_name: str
    status: str
    billing_type: str
    months: dict[str, MonthFacts] = field(default_factory=dict)


@dataclass(frozen=True)
class ParsedBlnoWorkbook:
    roster: list[RosterRow]
    payment_log: list[dict[str, Any]]
    attendance_log: list[dict[str, Any]]
    move_log: list[dict[str, Any]]
    audit_log: list[dict[str, Any]]


def _money_to_cents(value: Any) -> int:
    if value is None or value == "":
        return 0
    return int(round(float(value) * 100))


def _phone(value: Any) -> str:
    if value is None:
        return ""
    return str(value).replace(".0", "").replace("+", "").replace("-", "").replace(" ", "").replace("(", "").replace(")", "")


def _period_from_header(header: str) -> str:
    dt = datetime.strptime(header.split()[0], "%b-%Y")
    return dt.strftime("%Y-%m")


def _rows(ws: Any, header_row: int) -> list[dict[str, Any]]:
    raw_headers = next(ws.iter_rows(min_row=header_row, max_row=header_row, values_only=True))
    headers = [str(v).strip() if v is not None else None for v in raw_headers]
    out: list[dict[str, Any]] = []
    for raw in ws.iter_rows(min_row=header_row + 1, values_only=True):
        row = {h: v for h, v in zip(headers, raw) if h}
        if any(v not in (None, "") for v in row.values()):
            out.append(row)
    return out


def load_blno_workbook(path: str | Path) -> ParsedBlnoWorkbook:
    wb = load_workbook(Path(path), data_only=True)
    roster_rows: list[RosterRow] = []
    for row in _rows(wb["Roster"], 1):
        child_name = str(row.get("Child Name") or "").strip()
        if not child_name:
            continue
        months: dict[str, MonthFacts] = {}
        for label in ("Apr-2026", "May-2026"):
            months[_period_from_header(label)] = MonthFacts(
                enrolled=row.get(f"{label} Enr") is True,
                paid_cents=_money_to_cents(row.get(f"{label} Pay")),
                due_cents=_money_to_cents(row.get(f"{label} Due")),
            )
        roster_rows.append(
            RosterRow(
                child_name=child_name,
                parent_name=str(row.get("Parent") or "").strip(),
                parent_phone=_phone(row.get("Phone")),
                parent_email=str(row.get("Email") or "").strip().lower(),
                skill=str(row.get("Skill") or "").strip().lower(),
                price_cents=_money_to_cents(row.get("Price")),
                session_name=str(row.get("Session") or "").strip(),
                coach_name=str(row.get("Coach") or "").strip(),
                status=str(row.get("Status") or "Active").strip().lower(),
                billing_type=str(row.get("Billing Type") or "Standard").strip(),
                months=months,
            )
        )
    return ParsedBlnoWorkbook(
        roster=roster_rows,
        payment_log=_rows(wb["Payment_Log"], 1),
        attendance_log=_rows(wb["Attendance_Log"], 3),
        move_log=_rows(wb["Move_Log"], 1),
        audit_log=_rows(wb["Audit_Log"], 1),
    )
```

- [ ] **Step 4: Run parser tests**

Run:

```bash
cd backend
source .venv/bin/activate
pytest tests/test_blno_importer.py -q
```

Expected: `1 passed`.

### Task 2: Add Validation and Manifest Output

**Files:**
- Modify: `backend/scripts/blno_importer.py`
- Test: `backend/tests/test_blno_importer.py`

- [ ] **Step 1: Add validation test**

Append this test:

```python
from backend.scripts.blno_importer import validate_blno_workbook


def test_validate_blno_workbook_reports_summary(tmp_path: Path) -> None:
    parsed = load_blno_workbook(_sample_workbook(tmp_path / "blno.xlsx"))

    manifest = validate_blno_workbook(parsed)

    assert manifest["students"] == 1
    assert manifest["parents"] == 1
    assert manifest["sessions"] == 1
    assert manifest["errors"] == []
```

- [ ] **Step 2: Implement validation**

Add to `backend/scripts/blno_importer.py`:

```python
def validate_blno_workbook(parsed: ParsedBlnoWorkbook) -> dict[str, Any]:
    errors: list[str] = []
    parent_emails = set()
    sessions = set()
    students = set()
    for row in parsed.roster:
        key = row.child_name.strip().lower()
        if key in students:
            errors.append(f"duplicate student name: {row.child_name}")
        students.add(key)
        if not row.parent_email:
            errors.append(f"missing parent email for {row.child_name}")
        else:
            parent_emails.add(row.parent_email)
        if not row.session_name:
            errors.append(f"missing session for {row.child_name}")
        else:
            sessions.add(row.session_name)
        if row.billing_type not in {"Standard", "No Charge", "NoCharge", "Waived"}:
            errors.append(f"unsupported billing type for {row.child_name}: {row.billing_type}")
    return {
        "students": len(students),
        "parents": len(parent_emails),
        "sessions": len(sessions),
        "payments_in_payment_log": len(parsed.payment_log),
        "attendance_entries": len(parsed.attendance_log),
        "move_log_entries": len(parsed.move_log),
        "errors": errors,
    }
```

- [ ] **Step 3: Run validation tests**

Run:

```bash
cd backend
source .venv/bin/activate
pytest tests/test_blno_importer.py -q
```

Expected: `2 passed`.

### Task 3: Build Local Apply Mode

**Files:**
- Modify: `backend/scripts/blno_importer.py`
- Modify: `backend/scripts/import_blno.py`
- Test: `backend/tests/test_blno_importer.py`

- [ ] **Step 1: Define local-only safety config**

In `backend/scripts/blno_importer.py`, add:

```python
LOCAL_MONGO_HOSTS = {"127.0.0.1", "localhost", "::1", "mongo"}


def assert_local_mongo_url(mongo_url: str) -> None:
    from urllib.parse import urlparse

    parsed = urlparse(mongo_url)
    host = (parsed.hostname or "").lower()
    if host not in LOCAL_MONGO_HOSTS:
        raise SystemExit(f"Refusing local import against non-local Mongo host: {host}")
```

- [ ] **Step 2: Replace old importer entrypoint with CLI guard**

In `backend/scripts/import_blno.py`, replace current logic with:

```python
from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path

from backend.scripts.blno_importer import (
    assert_local_mongo_url,
    load_blno_workbook,
    validate_blno_workbook,
)


async def main() -> None:
    parser = argparse.ArgumentParser(description="Import BLNO workbook into local/prod Mongo after validation.")
    parser.add_argument("--xlsx", default=os.environ.get("BLNO_XLSX", "/tmp/blno.xlsx"))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--apply-local", action="store_true")
    args = parser.parse_args()

    parsed = load_blno_workbook(Path(args.xlsx))
    manifest = validate_blno_workbook(parsed)
    print(json.dumps(manifest, indent=2, default=str))
    if manifest["errors"]:
        raise SystemExit("Workbook validation failed")
    if args.dry_run:
        return
    if args.apply_local:
        mongo_url = os.environ.get("MONGO_URL", "mongodb://127.0.0.1:27017")
        assert_local_mongo_url(mongo_url)
        raise SystemExit("apply-local writer not implemented until Task 4")
    raise SystemExit("Pass --dry-run or --apply-local")


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 3: Run dry-run against real workbook**

Run:

```bash
cd /Users/ramc/Documents/Code/academy-manager
source backend/.venv/bin/activate
BLNO_XLSX="/Users/ramc/Downloads/BLno-Badmintion-Training (1).xlsx" \
python backend/scripts/import_blno.py --dry-run
```

Expected manifest:

```json
{
  "students": 47,
  "parents": 43,
  "sessions": 4,
  "payments_in_payment_log": 13,
  "attendance_entries": 8,
  "move_log_entries": 5,
  "errors": []
}
```

### Task 4: Implement v2-Compatible Mongo Writer

**Files:**
- Modify: `backend/scripts/blno_importer.py`
- Modify: `backend/scripts/import_blno.py`
- Test: `backend/tests/test_blno_importer.py`

- [ ] **Step 1: Add deterministic IDs and idempotent import marker**

Use stable IDs so local/prod runs are predictable:

```python
import hashlib


def stable_id(prefix: str, *parts: str) -> str:
    raw = "|".join(part.strip().lower() for part in parts)
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:20]
    return f"{prefix}{digest}"
```

- [ ] **Step 2: Write tenant-owned documents**

Writer must create or upsert:

```text
academies
academy_settings
academy_memberships
users
platform_roles for admin only
sessions
session_occurrences for past completed instances
coach_rates
payout_rules
waiver_versions or waiver_templates
waiver_acceptances
students
enrollments
payments
attendance
move_log
expenses
```

Use these BLNO constants:

```python
ACADEMY_ID = "acad_blno_badminton"
ACADEMY_SLUG = "blno-badminton"
ACADEMY_NAME = "BLNO Badminton Academy"
ACADEMY_TZ = "America/Chicago"
OWNER_EMAIL = "ramchand4685@gmail.com"
COACH_PASSWORD = "Coach@12345"
PARENT_PASSWORD = "Parent@12345"
ADMIN_PASSWORD = "Admin@12345"
```

- [ ] **Step 3: Make destructive behavior explicit**

For local apply, allow wiping only BLNO-owned local docs:

```python
BLNO_TENANT_COLLECTIONS = [
    "academies", "academy_settings", "academy_memberships", "users", "sessions",
    "session_occurrences", "coach_rates", "payout_rules", "waiver_versions",
    "waiver_acceptances", "students", "enrollments", "payments", "attendance",
    "move_log", "expenses",
]
```

Delete with `{"academy_id": ACADEMY_ID}` where possible. For global `users`, delete only seed-created BLNO users by email domain/list and the owner user only when running local with an explicit `--reset-local-users` flag.

- [ ] **Step 4: Verify local import**

Run:

```bash
cd /Users/ramc/Documents/Code/academy-manager
source backend/.venv/bin/activate
BLNO_XLSX="/Users/ramc/Downloads/BLno-Badmintion-Training (1).xlsx" \
MONGO_URL="mongodb://127.0.0.1:27017" \
DB_NAME="academy_manager_local" \
FIREBASE_AUTH_ENABLED=true \
FIREBASE_AUTH_EMULATOR_HOST="127.0.0.1:9101" \
python backend/scripts/import_blno.py --apply-local
```

Expected output includes:

```text
students=47 parents=43 sessions=4 payments>=80 attendance=8 errors=0
```

### Task 5: Browser and API Verification

**Files:**
- Modify: `test_result.md`

- [ ] **Step 1: Verify app health**

Run:

```bash
curl -fsS http://127.0.0.1:8002/api/health
curl -fsS http://127.0.0.1:8002/api/v2/healthz
curl -fsS http://localhost:3001/api/v2/healthz
```

Expected:

```text
{"ok":true,"service":"academy-manager-api"}
{"status":"ok"}
{"status":"ok"}
```

- [ ] **Step 2: Login smoke**

Use:

```text
Admin: ramchand4685@gmail.com / Admin@12345
Coach: gowtham@blno.academy / Coach@12345
Coach: kishore@blno.academy / Coach@12345
Parent: manojedward.btech@gmail.com / Parent@12345
Parent: monaa1384@gmail.com / Parent@12345
```

Verify:

```text
Admin can see 47 students, 4 sessions, Apr/May dues, and payment rows.
Coach can see assigned sessions and attendance.
Parent can see their own children only.
```

- [ ] **Step 3: Update `test_result.md`**

Add an `agent_communication` entry with:

```text
BLNO workbook import tested locally. Source workbook: /Users/ramc/Downloads/BLno-Badmintion-Training (1).xlsx. Verified admin/coach/parent smoke, roster counts, session counts, payments, dues, attendance, and tenant isolation. Production import not run.
```

### Task 6: Production Import Runbook

**Files:**
- Create: `docs/runbooks/blno-production-import.md`

- [ ] **Step 1: Write production checklist**

Create:

```markdown
# BLNO Production Import Runbook

## Preconditions

- Local import from the same workbook has passed.
- User has reviewed local data in the UI.
- Production deploy is on the reviewed importer commit.
- MongoDB Atlas backup/snapshot is complete.
- Firebase production account creation plan is approved.

## Dry Run

Run production dry-run only:

```bash
BLNO_XLSX="/secure/path/BLno-Badmintion-Training.xlsx" \
MONGO_URL="$PROD_MONGO_URL" \
DB_NAME="academy_manager" \
python backend/scripts/import_blno.py --dry-run
```

Expected: same manifest as local validation, with `errors: []`.

## Apply

Do not run apply without explicit operator approval in the active thread.
Do not use local Mongo export/import as the production migration method.
Run the reviewed importer against production once, with production credentials supplied by environment.

## Post-Import Verification

- Admin login works.
- BLNO tenant resolves by approved domain/subdomain.
- Student count is 47.
- Parent count is 43.
- Session count is 4 active templates or the expected materialized dated sessions.
- April and May billing totals match the final approved manifest.
- Parent access is tenant-scoped.
- No real emails are sent during import.

## Rollback

Restore the MongoDB snapshot taken before import. Disable imported Firebase users if needed.
```

## Risks

- Spreadsheet totals do not perfectly agree across tabs: profile shows May roster paid sum $2,000 and due $570, while `Billing_Summary` shows collected $1,930 and outstanding $720. This must be reconciled before production apply.
- Existing `Payment_Log` has only 13 May payment events, while roster columns encode broader Apr/May payment state. The plan should use roster columns for invoice/payment state and keep `Payment_Log` as audit/source notes unless the user confirms otherwise.
- Production Firebase user creation and passwords must not be hardcoded for real parents unless the operator explicitly approves the onboarding approach.
- Production import must not drop global collections. It must target only the BLNO tenant and run after backup.
- The current local app is running on alternate ports because Docker Desktop owns the standard backend/Firebase ports.

## Verification Steps

- Parser unit tests: `pytest tests/test_blno_importer.py -q`.
- Real workbook dry-run manifest: `python backend/scripts/import_blno.py --dry-run`.
- Local apply against `academy_manager_local`.
- Backend focused smoke: health endpoints and admin/parent/coach API/UI checks.
- Production: dry run, backup confirmation, explicit approval, apply, post-import counts, and login smoke.

