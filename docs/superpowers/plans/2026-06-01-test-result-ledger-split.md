# Test Result Ledger Split Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the conflict-prone global `test_result.md` ledger with a stable router and automated per-task test result files.

**Architecture:** `test_result.md` becomes a small index that points agents to active task ledgers. `scripts/dev/test_result.py` owns creation, append logging, lesson promotion prompts, and closing/archiving so agents do not manually edit shared global status blocks.

**Tech Stack:** Python 3 stdlib CLI, Markdown task files, stdlib `unittest` coverage.

---

### Task 1: Add CLI Test Coverage

**Files:**
- Create: `tests/test_test_result_cli.py`

- [ ] **Step 1: Write failing tests for start, log, verify, and close**

```python
import importlib.util
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "dev" / "test_result.py"


def load_module():
    spec = importlib.util.spec_from_file_location("test_result_cli", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class TestResultCliTests(unittest.TestCase):
    def run_cli(self, cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SCRIPT), *args],
            cwd=cwd,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_start_creates_active_task_file_and_router_index(self) -> None:
        with TemporaryDirectory() as tmp:
            cwd = Path(tmp)
            result = self.run_cli(
                cwd,
                "start",
                "prod defects",
                "--problem",
                "Sessions are not showing.",
                "--files",
                "backend/v2/composition/admin.py",
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            active_files = list((cwd / "docs/test-results/active").glob("*prod-defects.md"))
            self.assertEqual(len(active_files), 1)
            task_text = active_files[0].read_text()
            self.assertIn("# prod defects", task_text)
            self.assertIn("Sessions are not showing.", task_text)
            self.assertIn("backend/v2/composition/admin.py", task_text)
            index_text = (cwd / "test_result.md").read_text()
            self.assertIn("Test Result Index", index_text)
            self.assertIn("docs/test-results/active/", index_text)

    def test_log_and_verify_append_timestamped_entries(self) -> None:
        with TemporaryDirectory() as tmp:
            cwd = Path(tmp)
            self.run_cli(cwd, "start", "prod defects", "--problem", "Bug")

            log_result = self.run_cli(
                cwd,
                "log",
                "prod-defects",
                "--agent",
                "main",
                "--status",
                "working",
                "--message",
                "Focused tests passed.",
            )
            verify_result = self.run_cli(
                cwd,
                "verify",
                "prod-defects",
                "--message",
                "pytest v2/tests/interface/test_admin_sessions.py -q passed.",
            )

            self.assertEqual(log_result.returncode, 0, log_result.stderr)
            self.assertEqual(verify_result.returncode, 0, verify_result.stderr)
            task_text = next((cwd / "docs/test-results/active").glob("*prod-defects.md")).read_text()
            self.assertIn("main", task_text)
            self.assertIn("Focused tests passed.", task_text)
            self.assertIn("pytest v2/tests/interface/test_admin_sessions.py -q passed.", task_text)

    def test_close_moves_active_file_to_archive_and_updates_index(self) -> None:
        with TemporaryDirectory() as tmp:
            cwd = Path(tmp)
            self.run_cli(cwd, "start", "prod defects", "--problem", "Bug")

            close_result = self.run_cli(cwd, "close", "prod-defects")

            self.assertEqual(close_result.returncode, 0, close_result.stderr)
            self.assertEqual(list((cwd / "docs/test-results/active").glob("*prod-defects.md")), [])
            archived_files = list((cwd / "docs/test-results/archive").glob("*prod-defects.md"))
            self.assertEqual(len(archived_files), 1)
            self.assertIn("No active test result files.", (cwd / "test_result.md").read_text())

    def test_slug_normalization_is_stable(self) -> None:
        module = load_module()
        self.assertEqual(module.slugify("  Prod Defects: Session Visibility!  "), "prod-defects-session-visibility")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests/test_test_result_cli.py`

Expected: FAIL because `scripts/dev/test_result.py` does not exist.

### Task 2: Implement the CLI

**Files:**
- Create: `scripts/dev/test_result.py`

- [ ] **Step 1: Add minimal CLI implementation**

Implement subcommands:
- `start <title> --problem <text> [--files <path> ...]`
- `log <slug> --agent <name> --status <text> --message <text>`
- `verify <slug> --message <text>`
- `close <slug>`

- [ ] **Step 2: Run focused tests**

Run: `python3 -m unittest tests/test_test_result_cli.py`

Expected: PASS.

### Task 3: Convert the Ledger Into Router + Archive

**Files:**
- Modify: `test_result.md`
- Create: `docs/test-results/README.md`
- Create: `docs/test-results/archive/2026-06-01-pre-split-test-result.md`

- [ ] **Step 1: Preserve old ledger**

Copy the current `test_result.md` body into `docs/test-results/archive/2026-06-01-pre-split-test-result.md`.

- [ ] **Step 2: Replace `test_result.md` with a compact router**

The router must instruct agents to use `scripts/dev/test_result.py` and point to active task files.

### Task 4: Update Agent Workflow Docs

**Files:**
- Modify: `AGENTS.md`
- Modify: `docs/agent/feedback-loop.md`
- Modify: `docs/agent/testing-verification.md`

- [ ] **Step 1: Update read-first and handoff instructions**

Require reading `test_result.md` plus the relevant active file under `docs/test-results/active/`.

- [ ] **Step 2: Tell agents not to manually edit shared global status blocks**

Require `scripts/dev/test_result.py` for start/log/verify/close updates.

### Task 5: Verify

**Files:**
- No new files.

- [ ] **Step 1: Run CLI tests**

Run: `python3 -m unittest tests/test_test_result_cli.py`

Expected: PASS.

- [ ] **Step 2: Run syntax check**

Run: `python3 -m py_compile scripts/dev/test_result.py tests/test_test_result_cli.py`

Expected: PASS.

- [ ] **Step 3: Run whitespace check**

Run: `git diff --check`

Expected: PASS.
