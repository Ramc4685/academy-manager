from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

DEV_SCRIPTS = Path(__file__).resolve().parents[1]
REPO_ROOT = DEV_SCRIPTS.parents[1]
sys.path.insert(0, str(DEV_SCRIPTS))

import publish_release  # noqa: E402
import release_notes_check  # noqa: E402


def completed(
    args: list[str],
    *,
    returncode: int = 0,
    stdout: str = "",
    stderr: str = "",
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args, returncode, stdout, stderr)


class ReleaseNotesCheckTests(unittest.TestCase):
    def write_note(self, body: str) -> Path:
        temporary = tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False)
        self.addCleanup(Path(temporary.name).unlink, missing_ok=True)
        with temporary:
            temporary.write(body)
        return Path(temporary.name)

    def test_generated_placeholder_is_rejected(self) -> None:
        path = self.write_note(
            """# change

PR: #123

## What changed
Useful description.

## Deploy notes
No migration detected. Confirm no manual env var or manual step is needed before merge.

## Risk / rollback
_Auto-generated stub — author: fill in rollback details._
"""
        )

        problems = release_notes_check.validate_note(path)

        self.assertIn("section not filled in: ## Deploy notes", problems)
        self.assertIn("section not filled in: ## Risk / rollback", problems)

    @patch.object(release_notes_check, "generate_note")
    @patch.object(release_notes_check, "find_existing_note", return_value=None)
    @patch.object(
        release_notes_check, "changed_files", return_value=["backend/v2/main.py"]
    )
    def test_missing_required_note_fails_without_generate_flag(
        self,
        _changed_files,
        _find_existing_note,
        generate_note,
    ) -> None:
        with patch.object(
            sys, "argv", ["release_notes_check.py", "--pr-number", "123"]
        ):
            result = release_notes_check.main()

        self.assertEqual(result, 1)
        generate_note.assert_not_called()

    COMPLETE_NOTE = """# change

PR: {pr}

## What changed
Useful description.

## Deploy notes
None.

## Risk / rollback
Revert the merge commit.
"""

    def note_in_repo(self, pr_line: str) -> str:
        notes_dir = release_notes_check.NOTES_DIR
        temporary = tempfile.NamedTemporaryFile(
            mode="w", suffix=".md", dir=notes_dir, delete=False
        )
        path = Path(temporary.name)
        self.addCleanup(path.unlink, missing_ok=True)
        with temporary:
            temporary.write(self.COMPLETE_NOTE.format(pr=pr_line))
        return str(path.relative_to(release_notes_check.REPO_ROOT))

    def run_main(self, files: list[str]) -> int:
        with (
            patch.object(release_notes_check, "changed_files", return_value=files),
            patch.object(release_notes_check, "find_existing_note", return_value=None),
            patch.object(sys, "argv", ["release_notes_check.py", "--pr-number", "123"]),
        ):
            return release_notes_check.main()

    def test_added_note_with_placeholder_pr_passes(self) -> None:
        note = self.note_in_repo("TBD")
        self.assertEqual(self.run_main(["backend/v2/main.py", note]), 0)

    def test_added_note_without_pr_line_passes(self) -> None:
        note = self.note_in_repo("TBD")
        path = release_notes_check.REPO_ROOT / note
        path.write_text(
            path.read_text(encoding="utf-8").replace("PR: TBD\n", ""),
            encoding="utf-8",
        )
        self.assertEqual(self.run_main(["backend/v2/main.py", note]), 0)

    def test_added_note_for_another_pr_does_not_count(self) -> None:
        note = self.note_in_repo("#999")
        self.assertEqual(self.run_main(["backend/v2/main.py", note]), 1)

    def test_placeholder_note_in_subfolder_does_not_count(self) -> None:
        nested = release_notes_check.NOTES_DIR / "nested-test-dir"
        nested.mkdir(exist_ok=True)
        self.addCleanup(nested.rmdir)
        path = nested / "note.md"
        path.write_text(self.COMPLETE_NOTE.format(pr="TBD"), encoding="utf-8")
        self.addCleanup(path.unlink, missing_ok=True)
        note = str(path.relative_to(release_notes_check.REPO_ROOT))
        self.assertEqual(self.run_main(["backend/v2/main.py", note]), 1)

    def test_placeholder_note_already_on_base_does_not_count(self) -> None:
        note = self.note_in_repo("TBD")
        with patch.object(release_notes_check, "exists_on_base", return_value=True):
            self.assertEqual(self.run_main(["backend/v2/main.py", note]), 1)

    def test_placeholder_note_still_needs_complete_sections(self) -> None:
        note = self.note_in_repo("TBD")
        path = release_notes_check.REPO_ROOT / note
        path.write_text(
            path.read_text(encoding="utf-8").replace("None.", ""),
            encoding="utf-8",
        )
        self.assertEqual(self.run_main(["backend/v2/main.py", note]), 1)


class PublishReleaseTests(unittest.TestCase):
    SHA = "a" * 40

    @patch.object(publish_release, "run")
    def test_pr_number_falls_back_to_squash_subject(self, run_mock) -> None:
        path = publish_release.NOTES_DIR / "2026-11-15-x.md"
        run_mock.return_value = completed([], stdout="chore: faster gate (#1180)\n")
        self.assertEqual(publish_release.pr_from_commit_subject(path), "1180")
        run_mock.return_value = completed([], stdout="")
        self.assertIsNone(publish_release.pr_from_commit_subject(path))

    def test_production_tag_is_deterministic_and_sha_bearing(self) -> None:
        self.assertEqual(
            publish_release.production_tag("2026-07-20", self.SHA),
            "deploy-2026-07-20-aaaaaaaaaaaa",
        )

    def test_release_body_preserves_multiline_shell_metacharacters(self) -> None:
        note = publish_release.ReleaseNote(
            path=Path("note.md"),
            title="Safe `title` $(literal)",
            pr_number="308",
            sections={
                "## What changed": "Line one\n`$(not-executed)` & <tag>",
                "## Deploy notes": "No migration.",
                "## Risk / rollback": "Revert the merge commit.",
            },
        )

        body = publish_release.build_release_body(
            notes=[note],
            repository="Ramc4685/academy-manager",
            sha=self.SHA,
            deployment_run_url=(
                "https://github.com/Ramc4685/academy-manager/actions/runs/123"
            ),
            previous_tag="deploy-2026-07-19-bbbbbbbbbbbb",
            commit_summaries=[],
        )

        self.assertIn("`$(not-executed)` & <tag>", body)
        self.assertIn("[PR #308]", body)

    @patch.object(publish_release, "run")
    def test_publish_refuses_to_move_existing_tag(self, run_mock) -> None:
        run_mock.return_value = completed(
            ["git"],
            stdout="b" * 40 + "\n",
        )

        with self.assertRaisesRegex(publish_release.ReleaseError, "refusing to move"):
            publish_release.publish(
                "deploy-2026-07-20-aaaaaaaaaaaa",
                self.SHA,
                "title",
                "body",
            )

    @patch.object(publish_release, "release_exists", return_value=True)
    @patch.object(publish_release, "run")
    def test_publish_is_idempotent_for_matching_tag_and_release(
        self,
        run_mock,
        _release_exists,
    ) -> None:
        run_mock.return_value = completed(["git"], stdout=self.SHA + "\n")

        publish_release.publish(
            "deploy-2026-07-20-aaaaaaaaaaaa",
            self.SHA,
            "title",
            "body",
        )

        self.assertEqual(run_mock.call_count, 1)

    @patch.object(publish_release, "run")
    def test_non_ancestor_baseline_fails_closed(self, run_mock) -> None:
        run_mock.return_value = completed(["git"], returncode=1)

        with self.assertRaisesRegex(publish_release.ReleaseError, "not an ancestor"):
            publish_release.ensure_ancestor("b" * 40, self.SHA)

    @patch.object(publish_release, "run")
    def test_only_expected_production_release_tags_are_baselines(
        self, run_mock
    ) -> None:
        run_mock.return_value = completed(
            ["gh"],
            stdout=json.dumps(
                [
                    {
                        "tag_name": "deploy-2026-07-20-aaaaaaaaaaaa",
                        "published_at": "2026-07-20T12:00:00Z",
                        "draft": False,
                        "prerelease": False,
                    },
                    {
                        "tag_name": "v9.9.9",
                        "published_at": "2026-07-21T12:00:00Z",
                        "draft": False,
                        "prerelease": False,
                    },
                ]
            ),
        )

        releases = publish_release.list_production_releases("Ramc4685/academy-manager")

        self.assertEqual(
            [release.tag for release in releases], ["deploy-2026-07-20-aaaaaaaaaaaa"]
        )


class WorkflowPolicyTests(unittest.TestCase):
    @staticmethod
    def smoke_gate(
        *,
        event: str,
        backend_changed: bool,
        frontend_changed: bool,
        backend_result: str,
        frontend_result: str,
    ) -> bool:
        manual = event == "workflow_dispatch"
        return (
            (backend_changed or frontend_changed or manual)
            and (backend_result == "success" or (not backend_changed and not manual))
            and (frontend_result == "success" or (not frontend_changed and not manual))
        )

    def test_release_notes_workflow_is_read_only_and_non_mutating(self) -> None:
        workflow = (REPO_ROOT / ".github/workflows/release-notes.yml").read_text()
        self.assertIn("contents: read", workflow)
        self.assertIn("persist-credentials: false", workflow)
        self.assertNotIn("contents: write", workflow)
        self.assertNotIn("git push", workflow)
        self.assertNotIn("actions/github-script", workflow)
        self.assertNotIn("synchronize, reopened, edited", workflow)

    def test_release_publication_requires_complete_changed_component_deploys(
        self,
    ) -> None:
        workflow = (REPO_ROOT / ".github/workflows/production.yml").read_text()
        self.assertIn("needs: [changes, deploy-backend, deploy-frontend]", workflow)
        self.assertIn("needs.deploy-backend.result == 'success'", workflow)
        self.assertIn("needs.deploy-frontend.result == 'success'", workflow)
        self.assertIn("needs.smoke.result == 'success'", workflow)
        self.assertIn(
            "actions/checkout@d23441a48e516b6c34aea4fa41551a30e30af803 # v6",
            workflow,
        )
        self.assertIn("contents: write", workflow)
        self.assertNotIn("pull-requests: write", workflow)

    def test_smoke_gate_event_and_component_matrix(self) -> None:
        cases = [
            ("push", True, False, "success", "skipped", True),
            ("push", False, True, "skipped", "success", True),
            ("push", True, True, "success", "success", True),
            ("push", True, True, "failure", "success", False),
            ("push", True, True, "success", "failure", False),
            ("push", False, False, "skipped", "skipped", False),
            ("workflow_dispatch", False, False, "success", "success", True),
            ("workflow_dispatch", False, False, "success", "skipped", False),
        ]
        for (
            event,
            backend,
            frontend,
            backend_result,
            frontend_result,
            expected,
        ) in cases:
            with self.subTest(
                event=event,
                backend=backend,
                frontend=frontend,
                backend_result=backend_result,
                frontend_result=frontend_result,
            ):
                self.assertEqual(
                    self.smoke_gate(
                        event=event,
                        backend_changed=backend,
                        frontend_changed=frontend,
                        backend_result=backend_result,
                        frontend_result=frontend_result,
                    ),
                    expected,
                )


if __name__ == "__main__":
    unittest.main()
