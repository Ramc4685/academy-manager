#!/usr/bin/env python3
"""Manage per-task test result ledgers without editing one shared conflict file."""

from __future__ import annotations

import argparse
import re
import shutil
from datetime import datetime
from pathlib import Path


ACTIVE_DIR = Path("docs/test-results/active")
ARCHIVE_DIR = Path("docs/test-results/archive")
INDEX_FILE = Path("test_result.md")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Create and update per-task test result ledgers."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    start_parser = subparsers.add_parser("start", help="Start a new active task ledger.")
    start_parser.add_argument("title", help="Human-readable task title.")
    start_parser.add_argument("--problem", required=True, help="Problem statement or task goal.")
    start_parser.add_argument(
        "--files",
        nargs="*",
        default=[],
        help="Files expected to change or already changed.",
    )
    start_parser.set_defaults(func=start)

    log_parser = subparsers.add_parser("log", help="Append a task status entry.")
    log_parser.add_argument("slug", help="Task slug, for example prod-defects.")
    log_parser.add_argument("--agent", required=True, help="Agent name, usually main/testing/user.")
    log_parser.add_argument("--status", required=True, help="Status such as working, blocked, or NA.")
    log_parser.add_argument("--message", required=True, help="Status message to append.")
    log_parser.set_defaults(func=log)

    verify_parser = subparsers.add_parser("verify", help="Append verification evidence.")
    verify_parser.add_argument("slug", help="Task slug, for example prod-defects.")
    verify_parser.add_argument("--message", required=True, help="Verification command/result.")
    verify_parser.set_defaults(func=verify)

    close_parser = subparsers.add_parser("close", help="Move an active task ledger to archive.")
    close_parser.add_argument("slug", help="Task slug, for example prod-defects.")
    close_parser.set_defaults(func=close)

    args = parser.parse_args()
    ensure_dirs()
    return args.func(args)


def start(args: argparse.Namespace) -> int:
    slug = slugify(args.title)
    task_path = ACTIVE_DIR / f"{today()}-{slug}.md"
    if task_path.exists():
        print(f"Active test result already exists: {task_path}")
        update_index()
        return 0

    changed_files = "\n".join(f"- `{path}`" for path in args.files) or "- None recorded yet."
    task_path.write_text(
        "\n".join(
            [
                f"# {args.title}",
                "",
                "## Current State",
                "",
                "Status: active",
                "",
                "## Problem",
                "",
                args.problem,
                "",
                "## Changed Files",
                "",
                changed_files,
                "",
                "## Log",
                "",
                f"- {timestamp()} main/NA: Task ledger created.",
                "",
                "## Verification",
                "",
                "- No verification recorded yet.",
                "",
                "## Reusable Lessons",
                "",
                "- None recorded yet.",
                "",
            ]
        )
    )
    update_index()
    print(f"Created active test result: {task_path}")
    return 0


def log(args: argparse.Namespace) -> int:
    task_path = find_active(args.slug)
    append_line(
        task_path,
        "## Log",
        f"- {timestamp()} {args.agent}/{args.status}: {args.message}",
    )
    update_index()
    print(f"Updated log: {task_path}")
    return 0


def verify(args: argparse.Namespace) -> int:
    task_path = find_active(args.slug)
    append_line(task_path, "## Verification", f"- {timestamp()}: {args.message}")
    update_index()
    print(f"Updated verification: {task_path}")
    return 0


def close(args: argparse.Namespace) -> int:
    task_path = find_active(args.slug)
    destination = unique_path(ARCHIVE_DIR / task_path.name)
    shutil.move(str(task_path), destination)
    update_index()
    print(f"Archived test result: {destination}")
    return 0


def update_index() -> None:
    active_files = sorted(ACTIVE_DIR.glob("*.md"))
    if active_files:
        active_section = "\n".join(
            f"- [{path.stem}]({path.as_posix()})" for path in active_files
        )
    else:
        active_section = "No active test result files."

    INDEX_FILE.write_text(
        "\n".join(
            [
                "# Test Result Index",
                "",
                "This file is intentionally small to avoid merge conflicts.",
                "Use the per-task ledgers under `docs/test-results/active/` for current handoffs.",
                "",
                "## Active Test Result Files",
                "",
                active_section,
                "",
                "## Required Workflow",
                "",
                "- Start a task: `scripts/dev/test_result.py start \"task title\" --problem \"...\"`",
                "- Add status: `scripts/dev/test_result.py log <slug> --agent main --status working --message \"...\"`",
                "- Add verification: `scripts/dev/test_result.py verify <slug> --message \"...\"`",
                "- Close a task: `scripts/dev/test_result.py close <slug>`",
                "- Do not manually edit large shared status blocks in this file.",
                "",
                "## Learning Loop",
                "",
                "- Keep task-specific evidence in the relevant active ledger.",
                "- Promote reusable lessons to `docs/agent/testing-verification.md` or `docs/agent/feedback-loop.md`.",
                "- Archive completed task ledgers with the `close` command.",
                "",
            ]
        )
    )


def append_line(path: Path, section: str, line: str) -> None:
    text = path.read_text()
    if section not in text:
        text = f"{text.rstrip()}\n\n{section}\n\n"

    section_start = text.index(section)
    next_section = text.find("\n## ", section_start + len(section))
    if next_section == -1:
        updated = f"{text.rstrip()}\n{line}\n"
    else:
        updated = f"{text[:next_section].rstrip()}\n{line}\n{text[next_section:].lstrip()}"
    path.write_text(updated)


def find_active(slug: str) -> Path:
    normalized = slugify(slug)
    matches = sorted(ACTIVE_DIR.glob(f"*-{normalized}.md"))
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise SystemExit(f"No active test result found for slug: {normalized}")
    raise SystemExit(f"Multiple active test results found for slug: {normalized}")


def ensure_dirs() -> None:
    ACTIVE_DIR.mkdir(parents=True, exist_ok=True)
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "task"


def today() -> str:
    return datetime.now().date().isoformat()


def timestamp() -> str:
    return datetime.now().replace(microsecond=0).isoformat()


def unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    for counter in range(2, 1000):
        candidate = path.with_name(f"{path.stem}-{counter}{path.suffix}")
        if not candidate.exists():
            return candidate
    raise SystemExit(f"Could not find an available archive path for {path}")


if __name__ == "__main__":
    raise SystemExit(main())
