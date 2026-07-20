#!/usr/bin/env python3
"""Check for or explicitly generate a release-notes entry for a PR.

Used by .github/workflows/release-notes.yml. See the "Release Notes"
section of AGENTS.md for the process this enforces.

Exit codes:
  0 - nothing required, a valid release-notes file already exists, or a stub
      was explicitly generated for local author review.
  1 - required release notes are missing, or an existing file contains
      missing/placeholder content.
"""

from __future__ import annotations

import argparse
import datetime
import os
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
NOTES_DIR = REPO_ROOT / "docs" / "release-notes"
REQUIRED_SECTIONS = ["## What changed", "## Deploy notes", "## Risk / rollback"]
CODE_PREFIXES = ("backend/", "frontend/")
BODY_HEADING_CANDIDATES = ["## What", "## Summary", "## What changed"]
PLACEHOLDER_MARKERS = (
    "auto-generated stub",
    "author: fill in",
    "confirm no manual env var or manual step",
)


def changed_files(base_ref: str) -> list[str]:
    # No --depth here: forcing a shallow fetch on top of an already-full
    # clone (as produced by `actions/checkout` with fetch-depth: 0) breaks
    # merge-base resolution for the `...` diff below.
    subprocess.run(["git", "fetch", "origin", "main"], cwd=REPO_ROOT, check=False)
    diff_spec = f"{base_ref}...HEAD"
    result = subprocess.run(
        ["git", "diff", "--name-only", diff_spec],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        # Fall back to a direct tip-to-tip diff (no merge-base needed) if the
        # clone doesn't have enough history to resolve a common ancestor.
        result = subprocess.run(
            ["git", "diff", "--name-only", base_ref, "HEAD"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
    return [line for line in result.stdout.splitlines() if line.strip()]


def requires_release_notes(files: list[str]) -> bool:
    return any(f.startswith(CODE_PREFIXES) for f in files)


def find_existing_note(pr_number: str) -> Path | None:
    if not NOTES_DIR.is_dir():
        return None
    marker = f"PR: #{pr_number}"
    for path in sorted(NOTES_DIR.glob("*.md")):
        if marker in path.read_text(encoding="utf-8"):
            return path
    return None


def section_body(text: str, heading: str) -> str:
    lines = text.splitlines()
    try:
        start = next(i for i, line in enumerate(lines) if line.strip() == heading)
    except StopIteration:
        return ""
    body_lines = []
    for line in lines[start + 1 :]:
        if line.startswith("## "):
            break
        body_lines.append(line)
    return "\n".join(body_lines).strip()


def validate_note(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    problems = []
    for heading in REQUIRED_SECTIONS:
        if heading not in text:
            problems.append(f"missing section: {heading}")
            continue
        body = section_body(text, heading)
        normalized_body = body.casefold()
        if (
            not body
            or body.startswith("<")
            or any(marker in normalized_body for marker in PLACEHOLDER_MARKERS)
        ):
            problems.append(f"section not filled in: {heading}")
    return problems


def slugify(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return slug[:60].strip("-") or "release"


def extract_what_changed(title: str, body: str) -> str:
    for heading in BODY_HEADING_CANDIDATES:
        excerpt = section_body(body, heading)
        if excerpt:
            return excerpt
    return title


def detect_migrations(files: list[str]) -> list[str]:
    return [
        f
        for f in files
        if "/migrations/" in f and f.endswith(".py") and not f.endswith("__init__.py")
    ]


def generate_note(pr_number: str, title: str, body: str, files: list[str]) -> Path:
    NOTES_DIR.mkdir(parents=True, exist_ok=True)
    date = datetime.date.today().isoformat()
    filename = NOTES_DIR / f"{date}-{slugify(title)}.md"
    # Avoid collisions if multiple PRs land the same slug/day.
    counter = 2
    while filename.exists():
        filename = NOTES_DIR / f"{date}-{slugify(title)}-{counter}.md"
        counter += 1

    migrations = detect_migrations(files)
    if migrations:
        deploy_notes = (
            "Includes migration(s): "
            + ", ".join(migrations)
            + ". Confirm `V2_RUN_MIGRATIONS_ON_BOOT` covers it or run manually — see AGENTS.md."
        )
    else:
        deploy_notes = (
            "No migration detected in the diff. Confirm no manual env var or "
            "manual step is needed before merge."
        )

    content = f"""# {slugify(title)}

PR: #{pr_number}

## What changed
{extract_what_changed(title, body)}

## Deploy notes
{deploy_notes}

## Risk / rollback
_Auto-generated stub — author: fill in what breaks if this is wrong and how
to roll back before merge._ Revert the merge commit if this regresses.
"""
    filename.write_text(content, encoding="utf-8")
    return filename


def set_output(name: str, value: str) -> None:
    output_path = os.environ.get("GITHUB_OUTPUT")
    if not output_path:
        return
    with open(output_path, "a", encoding="utf-8") as fh:
        fh.write(f"{name}={value}\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pr-number", required=True)
    parser.add_argument("--base-ref", default="origin/main")
    parser.add_argument(
        "--generate",
        action="store_true",
        help="Generate a local stub when required notes are missing.",
    )
    args = parser.parse_args()

    title = os.environ.get("PR_TITLE", "")
    body = os.environ.get("PR_BODY", "")

    files = changed_files(args.base_ref)
    existing = find_existing_note(args.pr_number)

    if existing is not None:
        problems = validate_note(existing)
        if problems:
            print(
                f"Release notes file {existing.relative_to(REPO_ROOT)} is incomplete:"
            )
            for problem in problems:
                print(f"  - {problem}")
            set_output("created", "false")
            return 1
        print(f"OK: {existing.relative_to(REPO_ROOT)} is present and complete.")
        set_output("created", "false")
        return 0

    if not requires_release_notes(files):
        print(
            "SKIP: no backend/ or frontend/ changes in this PR; no release notes required."
        )
        set_output("created", "false")
        return 0

    if args.generate:
        path = generate_note(args.pr_number, title, body, files)
        print(
            f"CREATED: {path.relative_to(REPO_ROOT)} "
            "(stub — needs author review before merge)."
        )
        set_output("created", "true")
        set_output("path", str(path.relative_to(REPO_ROOT)))
        return 0

    print(
        "ERROR: this PR changes backend/ or frontend/ but has no complete "
        f"release note containing `PR: #{args.pr_number}`.\n"
        "Generate a starting point locally with:\n"
        f"  python3 scripts/dev/release_notes_check.py --generate "
        f"--pr-number {args.pr_number}\n"
        "Then replace every generated placeholder before pushing."
    )
    set_output("created", "false")
    return 1


if __name__ == "__main__":
    sys.exit(main())
