#!/usr/bin/env python3
"""Publish one idempotent GitHub Release for a verified production deploy.

The production workflow invokes this only after every changed component has
deployed and the production smoke job has passed. Tags are deterministic for
the deployed commit and are never moved or overwritten.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from release_notes_check import REQUIRED_SECTIONS, section_body, validate_note

REPO_ROOT = Path(__file__).resolve().parents[2]
NOTES_DIR = REPO_ROOT / "docs" / "release-notes"
PRODUCTION_TAG = re.compile(
    r"^deploy-(?:\d{4}-\d{2}-\d{2}-(?:pr-\d+|[0-9a-f]{7,40})|[0-9a-f]{7,40})$"
)
SHA = re.compile(r"^[0-9a-f]{40}$")
REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
PR_MARKER = re.compile(r"^PR:\s+#(\d+)\s*$", re.MULTILINE)
MAX_NOTE_BYTES = 128 * 1024
MAX_RELEASE_BODY_BYTES = 120 * 1024


class ReleaseError(RuntimeError):
    """A condition that makes it unsafe to publish a deployment release."""


@dataclass(frozen=True)
class ProductionRelease:
    tag: str
    published_at: str


@dataclass(frozen=True)
class ReleaseNote:
    path: Path
    title: str
    pr_number: str | None
    sections: dict[str, str]


def run(
    args: list[str],
    *,
    check: bool = True,
    capture_output: bool = True,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        args,
        cwd=REPO_ROOT,
        check=False,
        capture_output=capture_output,
        text=True,
    )
    if check and result.returncode != 0:
        detail = (
            (result.stderr or "").strip()
            or (result.stdout or "").strip()
            or "command failed"
        )
        raise ReleaseError(f"{args[0]} failed: {detail}")
    return result


def git_output(*args: str) -> str:
    return run(["git", *args]).stdout.strip()


def resolve_commit(ref: str) -> str:
    value = git_output("rev-parse", f"{ref}^{{commit}}")
    if not SHA.fullmatch(value):
        raise ReleaseError(f"{ref!r} did not resolve to a full commit SHA")
    return value


def ensure_ancestor(ancestor: str, descendant: str) -> None:
    result = run(
        ["git", "merge-base", "--is-ancestor", ancestor, descendant],
        check=False,
    )
    if result.returncode != 0:
        raise ReleaseError(
            f"previous production release {ancestor} is not an ancestor of {descendant}"
        )


def list_production_releases(repository: str) -> list[ProductionRelease]:
    result = run(
        [
            "gh",
            "api",
            f"repos/{repository}/releases?per_page=100",
        ]
    )
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ReleaseError("GitHub returned invalid release JSON") from exc
    if not isinstance(payload, list):
        raise ReleaseError("GitHub release response was not a list")

    releases = []
    for item in payload:
        tag = item.get("tag_name", "")
        if (
            item.get("draft")
            or item.get("prerelease")
            or not PRODUCTION_TAG.fullmatch(tag)
        ):
            continue
        releases.append(
            ProductionRelease(
                tag=tag,
                published_at=item.get("published_at") or item.get("created_at") or "",
            )
        )
    return sorted(releases, key=lambda release: release.published_at, reverse=True)


def changed_note_paths(previous_tag: str | None, sha: str) -> list[Path]:
    if previous_tag:
        output = git_output(
            "diff",
            "--name-only",
            "--diff-filter=A",
            f"{previous_tag}..{sha}",
            "--",
            "docs/release-notes",
        )
    else:
        output = git_output(
            "ls-tree",
            "-r",
            "--name-only",
            sha,
            "--",
            "docs/release-notes",
        )

    paths = []
    for raw_path in output.splitlines():
        relative = PurePosixPath(raw_path)
        if (
            relative.parent != PurePosixPath("docs/release-notes")
            or relative.suffix != ".md"
        ):
            raise ReleaseError(f"unexpected release-note path in git range: {raw_path}")
        path = REPO_ROOT.joinpath(*relative.parts)
        if not path.is_file() or path.is_symlink():
            raise ReleaseError(f"release note is not a regular file: {raw_path}")
        if path.stat().st_size > MAX_NOTE_BYTES:
            raise ReleaseError(
                f"release note exceeds {MAX_NOTE_BYTES} bytes: {raw_path}"
            )
        paths.append(path)
    return sorted(set(paths))


def parse_release_note(path: Path) -> ReleaseNote:
    problems = validate_note(path)
    if problems:
        joined = "; ".join(problems)
        raise ReleaseError(
            f"incomplete release note {path.relative_to(REPO_ROOT)}: {joined}"
        )

    text = path.read_text(encoding="utf-8")
    title_line = next(
        (
            line.removeprefix("# ").strip()
            for line in text.splitlines()
            if line.startswith("# ")
        ),
        "",
    )
    if not title_line or len(title_line) > 200:
        raise ReleaseError(f"invalid release-note title: {path.relative_to(REPO_ROOT)}")
    pr_match = PR_MARKER.search(text)
    return ReleaseNote(
        path=path,
        title=title_line,
        pr_number=pr_match.group(1) if pr_match else None,
        sections={
            heading: section_body(text, heading) for heading in REQUIRED_SECTIONS
        },
    )


def production_tag(commit_date: str, sha: str) -> str:
    try:
        normalized_date = dt.date.fromisoformat(commit_date).isoformat()
    except ValueError as exc:
        raise ReleaseError(f"invalid commit date: {commit_date!r}") from exc
    if not SHA.fullmatch(sha):
        raise ReleaseError("release target must be a full lowercase commit SHA")
    return f"deploy-{normalized_date}-{sha[:12]}"


def build_release_body(
    *,
    notes: list[ReleaseNote],
    repository: str,
    sha: str,
    deployment_run_url: str,
    previous_tag: str | None,
    commit_summaries: list[str],
) -> str:
    lines = [
        f"Commit: [`{sha[:12]}`](https://github.com/{repository}/commit/{sha})  ",
        f"Deployment: [successful production run]({deployment_run_url})  ",
        f"Previous production release: `{previous_tag or 'none'}`",
        "",
        "## Included changes",
    ]

    if notes:
        for note in notes:
            pr_link = (
                f" ([PR #{note.pr_number}](https://github.com/{repository}/pull/{note.pr_number}))"
                if note.pr_number
                else ""
            )
            lines.extend(
                [
                    "",
                    f"### {note.title}{pr_link}",
                    note.sections["## What changed"],
                ]
            )
    else:
        lines.extend(["", *[f"- {summary}" for summary in commit_summaries]])

    for heading in ("## Deploy notes", "## Risk / rollback"):
        lines.extend(["", heading])
        if notes:
            for note in notes:
                label = f"PR #{note.pr_number}" if note.pr_number else note.title
                lines.extend(["", f"### {label}", note.sections[heading]])
        else:
            fallback = (
                "No repository release-note file was added in this deployment range."
                if heading == "## Deploy notes"
                else "Use the deployment commit and workflow run above for investigation and rollback."
            )
            lines.extend(["", fallback])

    body = "\n".join(lines).strip() + "\n"
    if len(body.encode("utf-8")) > MAX_RELEASE_BODY_BYTES:
        raise ReleaseError(f"release body exceeds {MAX_RELEASE_BODY_BYTES} bytes")
    return body


def release_exists(tag: str) -> bool:
    result = run(["gh", "release", "view", tag, "--json", "tagName"], check=False)
    return result.returncode == 0


def publish(tag: str, sha: str, title: str, body: str) -> None:
    existing_tag = run(
        ["git", "rev-parse", "-q", "--verify", f"refs/tags/{tag}^{{commit}}"],
        check=False,
    )
    if existing_tag.returncode == 0:
        tagged_sha = existing_tag.stdout.strip()
        if tagged_sha != sha:
            raise ReleaseError(
                f"refusing to move existing tag {tag} from {tagged_sha} to {sha}"
            )
        if release_exists(tag):
            print(f"SKIP: {tag} already publishes {sha}.")
            return

    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            prefix="academy-release-",
            suffix=".md",
            delete=False,
        ) as notes_file:
            notes_file.write(body)
            temporary_path = Path(notes_file.name)
        run(
            [
                "gh",
                "release",
                "create",
                tag,
                "--target",
                sha,
                "--title",
                title,
                "--notes-file",
                str(temporary_path),
                "--latest",
            ],
            capture_output=False,
        )
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", default=os.environ.get("GITHUB_REPOSITORY", ""))
    parser.add_argument("--sha", default=os.environ.get("GITHUB_SHA", ""))
    parser.add_argument(
        "--deployment-run-url",
        default=os.environ.get("DEPLOYMENT_RUN_URL", ""),
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    try:
        if not REPOSITORY.fullmatch(args.repository):
            raise ReleaseError("repository must have the form owner/name")
        sha = resolve_commit(args.sha or "HEAD")
        if args.sha and args.sha != sha:
            raise ReleaseError("GITHUB_SHA must be the exact checked-out commit")
        if resolve_commit("HEAD") != sha:
            raise ReleaseError("checked-out HEAD does not match the deployed commit")
        if not args.deployment_run_url.startswith(
            f"https://github.com/{args.repository}/actions/runs/"
        ):
            raise ReleaseError("deployment run URL does not match this repository")

        releases = list_production_releases(args.repository)
        for release in releases:
            if resolve_commit(release.tag) == sha:
                print(f"SKIP: {release.tag} already records deployed commit {sha}.")
                return 0

        previous = releases[0] if releases else None
        if previous:
            ensure_ancestor(resolve_commit(previous.tag), sha)

        note_paths = changed_note_paths(previous.tag if previous else None, sha)
        notes = [parse_release_note(path) for path in note_paths]
        commit_range = f"{previous.tag}..{sha}" if previous else sha
        summaries = [
            line
            for line in git_output(
                "log", "--format=%s", "--max-count=50", commit_range
            ).splitlines()
            if line
        ]
        commit_date = git_output("show", "-s", "--format=%cs", sha)
        tag = production_tag(commit_date, sha)
        title = f"Production deployment — {commit_date}"
        body = build_release_body(
            notes=notes,
            repository=args.repository,
            sha=sha,
            deployment_run_url=args.deployment_run_url,
            previous_tag=previous.tag if previous else None,
            commit_summaries=summaries,
        )

        if args.dry_run:
            print(f"DRY RUN: {tag}\nTITLE: {title}\n\n{body}")
            return 0
        publish(tag, sha, title, body)
        return 0
    except ReleaseError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
